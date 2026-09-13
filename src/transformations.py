"""
transformations.py

Builds the final star schema from cleaned intermediate tables:
  dim_users, fact_events, dim_sessions, fact_transactions, fact_errors

Also contains the fully-documented synthetic error generator (the one deliberately
synthetic piece of this project — see docs/data_dictionary.md for justification).

Usage:
    python src/transformations.py --input data/processed --output data/processed/star_schema

All randomness is seeded (random_state=42) for reproducibility.
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

RNG = np.random.default_rng(seed=42)

DEVICE_WEIGHTS = {"Mobile": 0.58, "Desktop": 0.35, "Tablet": 0.07}
APP_VERSION_WEIGHTS = {"3.4.0": 0.10, "3.4.1": 0.10, "3.5.0": 0.20, "3.5.2": 0.25, "3.6.0": 0.35}

ERROR_TYPES = [
    "PaymentGatewayTimeout",
    "SessionExpired",
    "APIError5xx",
    "NetworkTimeout",
    "NullPointerException",
    "AuthenticationFailure",
    "OutOfMemory",
]
# Base probabilities (non-checkout-adjacent errors). Renormalized at use.
ERROR_TYPE_BASE_WEIGHTS = [0.10, 0.15, 0.15, 0.20, 0.15, 0.15, 0.10]


def map_customers_to_users(transactions: pd.DataFrame, user_id_pool: np.ndarray) -> pd.DataFrame:
    """
    Deterministically remap Olist customer_unique_id onto the cosmetics-shop user_id pool
    so a transaction can be joined to an events/session history. Uses a stable hash of
    customer_unique_id modulo the size of the user pool -> reproducible, not random per run.
    """
    transactions = transactions.copy()
    hashed_index = transactions["customer_unique_id"].apply(
        lambda x: abs(hash(x)) % len(user_id_pool)
    )
    transactions["user_id"] = user_id_pool[hashed_index]
    return transactions


def assign_session_attributes(events: pd.DataFrame) -> pd.DataFrame:
    """
    Assign a device_type and application_version once per session_id (constant within a
    session, since the raw clickstream doesn't include these fields). Weighted sampling
    per docs/data_dictionary.md.
    """
    sessions = events["session_id"].unique()
    device_choices = RNG.choice(
        list(DEVICE_WEIGHTS.keys()), size=len(sessions), p=list(DEVICE_WEIGHTS.values())
    )
    version_choices = RNG.choice(
        list(APP_VERSION_WEIGHTS.keys()), size=len(sessions), p=list(APP_VERSION_WEIGHTS.values())
    )
    session_attrs = pd.DataFrame(
        {"session_id": sessions, "device_type": device_choices, "application_version": version_choices}
    )
    return events.merge(session_attrs, on="session_id", how="left")


def insert_login_events(events: pd.DataFrame) -> pd.DataFrame:
    """Insert a synthetic 'Login' event at the start of each session (see data_dictionary.md)."""
    session_starts = (
        events.groupby("session_id")
        .agg(user_id=("user_id", "first"), event_timestamp=("event_timestamp", "min"),
             device_type=("device_type", "first"), application_version=("application_version", "first"))
        .reset_index()
    )
    session_starts["event_timestamp"] = session_starts["event_timestamp"] - pd.Timedelta(seconds=5)
    session_starts["event_type"] = "Login"
    login_events = session_starts[
        ["user_id", "session_id", "event_type", "event_timestamp", "device_type", "application_version"]
    ]
    return pd.concat([login_events, events], ignore_index=True).sort_values("event_timestamp")


def build_dim_sessions(events: pd.DataFrame) -> pd.DataFrame:
    agg = (
        events.groupby("session_id")
        .agg(
            user_id=("user_id", "first"),
            session_start=("event_timestamp", "min"),
            session_end=("event_timestamp", "max"),
            event_count=("event_type", "count"),
            device_type=("device_type", "first"),
        )
        .reset_index()
    )
    agg["session_duration_sec"] = (agg["session_end"] - agg["session_start"]).dt.total_seconds()
    converted_sessions = set(events.loc[events["event_type"] == "Checkout", "session_id"])
    agg["converted"] = agg["session_id"].isin(converted_sessions)
    return agg


def build_dim_users(events: pd.DataFrame, transactions: pd.DataFrame, region_pool: pd.Series) -> pd.DataFrame:
    user_ids = events["user_id"].unique()

    registration = events.groupby("user_id")["event_timestamp"].min().rename("registration_date")
    device_mode = events.groupby("user_id")["device_type"].agg(lambda s: s.value_counts().idxmax()).rename("device_type")

    regions = pd.Series(
        RNG.choice(region_pool.values, size=len(user_ids), replace=True),
        index=user_ids,
        name="region",
    )

    dim_users = pd.DataFrame(index=user_ids)
    dim_users.index.name = "user_id"
    dim_users = dim_users.join(registration).join(device_mode).join(regions).reset_index()

    # Customer segment from lifetime spend (only on completed transactions)
    spend = (
        transactions.loc[transactions["transaction_status"] == "Completed"]
        .groupby("user_id")["transaction_amount"]
        .sum()
    )
    dim_users = dim_users.merge(spend.rename("lifetime_spend"), on="user_id", how="left")
    dim_users["lifetime_spend"] = dim_users["lifetime_spend"].fillna(0)

    def segment(spend_value, p80, p50):
        if spend_value == 0:
            return "Non-Purchaser"
        elif spend_value >= p80:
            return "High Value"
        elif spend_value >= p50:
            return "Mid Value"
        return "Low Value"

    nonzero = dim_users.loc[dim_users["lifetime_spend"] > 0, "lifetime_spend"]
    p80, p50 = (nonzero.quantile(0.8), nonzero.quantile(0.5)) if len(nonzero) else (0, 0)
    dim_users["customer_segment"] = dim_users["lifetime_spend"].apply(segment, args=(p80, p50))

    return dim_users.drop(columns=["lifetime_spend"])


def generate_synthetic_errors(
    dim_sessions: pd.DataFrame, n_errors: int = None
) -> pd.DataFrame:
    """
    Generates the synthetic fact_errors table.

    Documented probabilities (see docs/data_dictionary.md for narrative rationale):
      - error volume: ~3% of sessions produce at least one error
      - error is 2x more likely to be sampled from a session that did NOT convert
        (errors correlated with drop-off, not random)
      - device_type skewed Mobile (65%) vs Desktop (28%) vs Tablet (7%)
      - application_version skewed toward newest release 3.6.0 (45%) to simulate a
        realistic "new release regression" narrative
      - error_type: PaymentGatewayTimeout upweighted 2x for sessions that DID convert
        (errors right around successful payment are realistic - e.g. duplicate-charge
        timeouts) while still occurring more often in non-converting sessions overall
    """
    n_sessions = len(dim_sessions)
    if n_errors is None:
        n_errors = max(1, int(n_sessions * 0.03)) if n_sessions > 0 else 0

    # Weight sessions: non-converted sessions 2x more likely to be sampled
    weights = np.where(dim_sessions["converted"], 1.0, 2.0)
    weights = weights / weights.sum()
    sampled_sessions = dim_sessions.sample(n=n_errors, replace=True, weights=weights, random_state=42)

    device_weights_err = {"Mobile": 0.65, "Desktop": 0.28, "Tablet": 0.07}
    devices = RNG.choice(list(device_weights_err.keys()), size=n_errors, p=list(device_weights_err.values()))

    version_weights_err = {"3.4.0": 0.05, "3.4.1": 0.08, "3.5.0": 0.17, "3.5.2": 0.25, "3.6.0": 0.45}
    versions = RNG.choice(list(version_weights_err.keys()), size=n_errors, p=list(version_weights_err.values()))

    error_types = []
    for converted in sampled_sessions["converted"].values:
        weights_local = np.array(ERROR_TYPE_BASE_WEIGHTS, dtype=float)
        if converted:
            idx = ERROR_TYPES.index("PaymentGatewayTimeout")
            weights_local[idx] *= 2
        weights_local = weights_local / weights_local.sum()
        error_types.append(RNG.choice(ERROR_TYPES, p=weights_local))

    # Timestamp: within or shortly after the session window
    offsets_sec = RNG.integers(low=-5, high=120, size=n_errors)
    error_timestamps = sampled_sessions["session_end"].values + pd.to_timedelta(offsets_sec, unit="s")

    fact_errors = pd.DataFrame(
        {
            "error_id": [f"ERR-{i:07d}" for i in range(n_errors)],
            "user_id": sampled_sessions["user_id"].values,
            "error_type": error_types,
            "error_timestamp": error_timestamps,
            "device_type": devices,
            "application_version": versions,
        }
    )
    return fact_errors


def run(input_dir: str, output_dir: str) -> None:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    events = pd.read_parquet(input_path / "events_clean.parquet")
    transactions = pd.read_parquet(input_path / "transactions_clean.parquet")

    logger.info("Assigning session-level device/app-version attributes...")
    events = assign_session_attributes(events)

    logger.info("Inserting synthetic Login events...")
    events = insert_login_events(events)

    logger.info("Mapping Olist customers onto the app user_id pool...")
    user_id_pool = events["user_id"].unique()
    transactions = map_customers_to_users(transactions, user_id_pool)

    logger.info("Building dim_sessions...")
    dim_sessions = build_dim_sessions(events)

    logger.info("Building dim_users...")
    region_pool = transactions["region"].dropna()
    dim_users = build_dim_users(events, transactions, region_pool)

    logger.info("Generating synthetic fact_errors...")
    fact_errors = generate_synthetic_errors(dim_sessions)

    # Add event_id surrogate key
    events = events.reset_index(drop=True)
    events["event_id"] = [f"EVT-{i:08d}" for i in range(len(events))]

    fact_events = events[
        ["event_id", "user_id", "session_id", "event_type", "event_timestamp",
         "device_type", "application_version"]
    ]
    fact_transactions = transactions[
        ["transaction_id", "user_id", "transaction_date", "transaction_amount",
         "payment_method", "transaction_status"]
    ]

    tables = {
        "dim_users": dim_users,
        "fact_events": fact_events,
        "dim_sessions": dim_sessions,
        "fact_transactions": fact_transactions,
        "fact_errors": fact_errors,
    }

    for name, df in tables.items():
        table_dir = output_path / name
        table_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(table_dir / f"{name}.parquet", index=False)
        logger.info(f"Wrote {name}: {len(df):,} rows -> {table_dir}")

    logger.info("transformations.py complete. Star schema written to " + str(output_path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the star schema from cleaned data.")
    parser.add_argument("--input", required=True, help="Path to cleaned intermediate parquet files")
    parser.add_argument("--output", required=True, help="Path to write the star schema")
    args = parser.parse_args()
    run(args.input, args.output)

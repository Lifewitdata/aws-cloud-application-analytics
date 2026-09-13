"""
data_cleaning.py

Cleans the raw source files (cosmetics-shop events, Olist orders/payments/customers)
into standardized intermediate DataFrames ready for validation and transformation.

Usage:
    python src/data_cleaning.py --input data/raw --output data/processed

Design notes:
- Every cleaning step is a small, named function so it's testable and so the logic is
  legible to someone reviewing this as a portfolio piece.
- No step silently drops rows without logging how many/why — see `_log_drop`.
"""

import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _log_drop(df_before: pd.DataFrame, df_after: pd.DataFrame, reason: str) -> None:
    dropped = len(df_before) - len(df_after)
    if dropped:
        pct = dropped / len(df_before) * 100
        logger.info(f"Dropped {dropped} rows ({pct:.2f}%) — reason: {reason}")


# ---------------------------------------------------------------------------
# Events (cosmetics-shop clickstream)
# ---------------------------------------------------------------------------

EVENT_TYPE_MAP = {
    "view": "Product View",
    "cart": "Add to Cart",
    "remove_from_cart": "Remove from Cart",
    "purchase": "Checkout",
}


def clean_events(raw_path: Path) -> pd.DataFrame:
    """Load and clean one or more raw event CSVs (cosmetics-shop format)."""
    files = sorted(Path(raw_path).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No event CSVs found in {raw_path}")

    frames = []
    for f in files:
        logger.info(f"Reading events file: {f.name}")
        df = pd.read_csv(
            f,
            usecols=["event_time", "event_type", "user_id", "user_session"],
            dtype={"user_id": "Int64"},
        )
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    before = df.copy()

    # Parse timestamp
    df["event_timestamp"] = pd.to_datetime(df["event_time"], utc=True, errors="coerce")

    # Drop rows with unparseable timestamps or missing keys
    df = df.dropna(subset=["event_timestamp", "user_id", "user_session"])
    _log_drop(before, df, "missing event_timestamp / user_id / user_session")

    # Standardize event_type to app taxonomy
    df["event_type"] = df["event_type"].map(EVENT_TYPE_MAP)
    before2 = df.copy()
    df = df.dropna(subset=["event_type"])
    _log_drop(before2, df, "unrecognized raw event_type")

    df = df.rename(columns={"user_session": "session_id"})
    df["user_id"] = df["user_id"].astype("int64")

    # Deduplicate exact duplicate events (same user, session, type, timestamp)
    before3 = len(df)
    df = df.drop_duplicates(subset=["user_id", "session_id", "event_type", "event_timestamp"])
    if before3 - len(df):
        logger.info(f"Dropped {before3 - len(df)} exact duplicate events")

    return df[["user_id", "session_id", "event_type", "event_timestamp"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Transactions (Olist orders + payments)
# ---------------------------------------------------------------------------

ORDER_STATUS_MAP = {
    "delivered": "Completed",
    "shipped": "Completed",
    "invoiced": "Completed",
    "approved": "Pending",
    "processing": "Pending",
    "created": "Pending",
    "canceled": "Failed",
    "unavailable": "Failed",
}


def clean_transactions(raw_path: Path) -> pd.DataFrame:
    """Load and clean Olist orders + payments + customers into one transactions table."""
    orders = pd.read_csv(
        Path(raw_path) / "olist_orders_dataset.csv",
        usecols=["order_id", "customer_id", "order_purchase_timestamp", "order_status"],
    )
    payments = pd.read_csv(
        Path(raw_path) / "olist_order_payments_dataset.csv",
        usecols=["order_id", "payment_type", "payment_value"],
    )
    customers = pd.read_csv(
        Path(raw_path) / "olist_customers_dataset.csv",
        usecols=["customer_id", "customer_unique_id", "customer_state"],
    )

    before = len(orders)
    orders = orders.dropna(subset=["order_id", "customer_id", "order_purchase_timestamp"])
    logger.info(f"Dropped {before - len(orders)} orders with missing key fields")

    # Aggregate payments (an order can have multiple installments)
    payments_agg = (
        payments.groupby("order_id")
        .agg(transaction_amount=("payment_value", "sum"), payment_method=("payment_type", "first"))
        .reset_index()
    )

    df = orders.merge(payments_agg, on="order_id", how="left").merge(
        customers, on="customer_id", how="left"
    )

    before2 = len(df)
    df = df.dropna(subset=["transaction_amount"])
    _log_drop(pd.DataFrame(index=range(before2)), pd.DataFrame(index=range(len(df))), "orders with no matching payment")

    df["transaction_date"] = pd.to_datetime(df["order_purchase_timestamp"], errors="coerce")
    df["transaction_status"] = df["order_status"].map(ORDER_STATUS_MAP).fillna("Pending")
    df = df.rename(
        columns={
            "order_id": "transaction_id",
            "customer_unique_id": "customer_unique_id",
            "customer_state": "region",
        }
    )

    # Basic sanity filter: no negative or absurd amounts
    before3 = len(df)
    df = df[(df["transaction_amount"] > 0) & (df["transaction_amount"] < 50000)]
    _log_drop(pd.DataFrame(index=range(before3)), pd.DataFrame(index=range(len(df))), "non-positive or implausible transaction_amount")

    return df[
        ["transaction_id", "customer_id", "customer_unique_id", "region",
         "transaction_date", "transaction_amount", "payment_method", "transaction_status"]
    ].reset_index(drop=True)


def run(input_dir: str, output_dir: str) -> None:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    events = clean_events(input_path / "events")
    logger.info(f"Cleaned events: {len(events):,} rows")
    events.to_parquet(output_path / "events_clean.parquet", index=False)

    transactions = clean_transactions(input_path / "transactions")
    logger.info(f"Cleaned transactions: {len(transactions):,} rows")
    transactions.to_parquet(output_path / "transactions_clean.parquet", index=False)

    logger.info("data_cleaning.py complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean raw application data sources.")
    parser.add_argument("--input", required=True, help="Path to data/raw")
    parser.add_argument("--output", required=True, help="Path to write cleaned intermediate files")
    args = parser.parse_args()
    run(args.input, args.output)

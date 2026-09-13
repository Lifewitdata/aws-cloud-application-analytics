"""
data_validation.py

Validates cleaned intermediate tables against expected schema and business rules,
producing a data-quality report. Fails loudly (raises) on critical issues; logs and
continues on warnings.

Usage:
    python src/data_validation.py --input data/processed
"""

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    table: str
    checks: list = field(default_factory=list)  # list of dicts: {check, status, detail}

    def add(self, check: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"check": check, "status": "PASS" if passed else "FAIL", "detail": detail})

    def has_failures(self) -> bool:
        return any(c["status"] == "FAIL" for c in self.checks)


EXPECTED_SCHEMAS = {
    "events_clean": {
        "columns": ["user_id", "session_id", "event_type", "event_timestamp"],
        "dtypes": {"user_id": "int64", "event_type": "object"},
        "allowed_values": {
            "event_type": {"Product View", "Add to Cart", "Remove from Cart", "Checkout"}
        },
    },
    "transactions_clean": {
        "columns": [
            "transaction_id", "customer_id", "customer_unique_id", "region",
            "transaction_date", "transaction_amount", "payment_method", "transaction_status",
        ],
        "dtypes": {"transaction_amount": "float64"},
        "allowed_values": {
            "transaction_status": {"Completed", "Pending", "Failed"}
        },
    },
}


def validate_schema(df: pd.DataFrame, table_name: str, result: ValidationResult) -> None:
    expected = EXPECTED_SCHEMAS[table_name]

    missing_cols = set(expected["columns"]) - set(df.columns)
    result.add("required_columns_present", len(missing_cols) == 0, f"missing: {missing_cols}" if missing_cols else "")

    for col, expected_values in expected.get("allowed_values", {}).items():
        if col in df.columns:
            actual_values = set(df[col].dropna().unique())
            unexpected = actual_values - expected_values
            result.add(
                f"allowed_values[{col}]",
                len(unexpected) == 0,
                f"unexpected values: {unexpected}" if unexpected else "",
            )


def validate_business_rules(df: pd.DataFrame, table_name: str, result: ValidationResult) -> None:
    # Nulls in primary/foreign keys
    key_cols = {
        "events_clean": ["user_id", "session_id", "event_type", "event_timestamp"],
        "transactions_clean": ["transaction_id", "customer_unique_id", "transaction_amount"],
    }.get(table_name, [])
    for col in key_cols:
        if col in df.columns:
            null_count = df[col].isna().sum()
            result.add(f"no_nulls[{col}]", null_count == 0, f"{null_count} nulls found")

    # Duplicate primary keys
    pk = {"transactions_clean": "transaction_id"}.get(table_name)
    if pk and pk in df.columns:
        dupes = df[pk].duplicated().sum()
        result.add(f"unique_pk[{pk}]", dupes == 0, f"{dupes} duplicate {pk} values")

    # Timestamp sanity (no future dates, no dates before a reasonable floor)
    ts_col = {"events_clean": "event_timestamp", "transactions_clean": "transaction_date"}.get(table_name)
    if ts_col and ts_col in df.columns:
        now = pd.Timestamp.now(tz="UTC")
        future = (pd.to_datetime(df[ts_col], utc=True, errors="coerce") > now).sum()
        result.add(f"no_future_dates[{ts_col}]", future == 0, f"{future} rows with future {ts_col}")

    # Transaction amount sanity
    if table_name == "transactions_clean" and "transaction_amount" in df.columns:
        negative = (df["transaction_amount"] <= 0).sum()
        result.add("positive_transaction_amount", negative == 0, f"{negative} non-positive amounts")


def run(input_dir: str) -> dict:
    input_path = Path(input_dir)
    report = {}

    for table_name in EXPECTED_SCHEMAS:
        file_path = input_path / f"{table_name}.parquet"
        if not file_path.exists():
            logger.warning(f"Skipping {table_name}: file not found at {file_path}")
            continue

        df = pd.read_parquet(file_path)
        result = ValidationResult(table=table_name)
        validate_schema(df, table_name, result)
        validate_business_rules(df, table_name, result)

        report[table_name] = result.checks
        status = "FAILED" if result.has_failures() else "PASSED"
        logger.info(f"Validation for {table_name}: {status} ({len(result.checks)} checks run)")

        if result.has_failures():
            for c in result.checks:
                if c["status"] == "FAIL":
                    logger.warning(f"  [{table_name}] {c['check']}: {c['detail']}")

    report_path = input_path / "data_quality_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Data quality report written to {report_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate cleaned data against schema and business rules.")
    parser.add_argument("--input", required=True, help="Path to data/processed (cleaned intermediate files)")
    args = parser.parse_args()
    run(args.input)

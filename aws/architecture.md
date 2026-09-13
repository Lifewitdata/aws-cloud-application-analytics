# AWS Architecture

## Diagram

```
                         ┌────────────────────────────────────────────────────────┐
                         │                     Data Sources                        │
                         │  Kaggle CSVs (users/events, transactions) + synthetic    │
                         │  error generator (local Python)                          │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  aws s3 cp / boto3 upload
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  Amazon S3 — RAW ZONE                                    │
                         │  s3://app-analytics-<env>/raw/{users,events,             │
                         │       transactions,errors}/                              │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  scheduled / on-demand crawl
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  AWS Glue Crawler → AWS Glue Data Catalog                │
                         │  Infers schema-on-read for the raw CSV/JSON               │
                         │  Creates database: app_analytics_raw                       │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  queried by / drives
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  Python / Pandas — Cleaning & Validation                  │
                         │  (src/data_cleaning.py, data_validation.py,               │
                         │   transformations.py) — runs locally or as a               │
                         │   Glue Python Shell / AWS Lambda job                        │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  writes Parquet, partitioned by date
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  Amazon S3 — PROCESSED ZONE                               │
                         │  s3://app-analytics-<env>/processed/{dim_users,           │
                         │       fact_events,dim_sessions,fact_transactions,          │
                         │       fact_errors}/year=YYYY/month=MM/                      │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  second Glue Crawler run
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  AWS Glue Data Catalog — database: app_analytics_processed │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  SELECT ... via Presto engine
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  Amazon Athena — SQL Analytics                            │
                         │  sql/data_quality_checks.sql, data_exploration.sql,        │
                         │  business_analysis.sql                                      │
                         └───────────────────────┬────────────────────────────────┘
                                                  │  ODBC / query-result export
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  Power BI Desktop — Dashboard                             │
                         │  Star-schema model, DAX measures, 4-page report            │
                         └───────────────────────┬────────────────────────────────┘
                                                  │
                                                  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │  Business Insights & Recommendations (docs/insights.md)  │
                         └────────────────────────────────────────────────────────┘
```

## Why each service was chosen

| Service | Role | Why this over alternatives |
|---|---|---|
| **Amazon S3** | Durable, cheap object storage for raw + processed data, split into zones (raw / processed) | Standard data-lake pattern; decouples storage from compute; versioning + lifecycle rules for cost control |
| **AWS Glue Crawler + Data Catalog** | Automatic schema inference and a central metastore | Avoids manually defining Athena table DDL for every schema change; the catalog is also reusable by other tools (Redshift Spectrum, EMR) if the project grows |
| **Python / Pandas** | Cleaning, validation, transformation logic | Transparent, testable, and the standard tool in a Data Analyst's kit; small-to-medium data volumes here don't need Spark |
| **Parquet** | Storage format for the processed zone | Columnar, compressed, and partition-pruned by Athena — dramatically cheaper/faster to query than CSV at scale |
| **Amazon Athena** | Serverless SQL query engine directly on S3 | No cluster to manage, pay-per-query, and it's the natural on-ramp from "files in S3" to "SQL tables" for a portfolio project |
| **Power BI** | Business-facing dashboard | Widely used in industry, connects to Athena via ODBC, and DAX measures demonstrate BI-specific skills beyond SQL |

## Partitioning strategy

Processed data is partitioned by `year`/`month` (and `day` for `fact_events`, the highest
volume table) to let Athena skip irrelevant files — this is called out explicitly in
`sql/data_exploration.sql` with `WHERE year = ... AND month = ...` predicates so it's clear
the query is partition-pruned.

## IAM / Security notes

- A dedicated IAM role `GlueAppAnalyticsRole` is used for the Glue crawler with
  least-privilege S3 read/write scoped to the project bucket only (not `s3:*`).
- Athena queries run under a workgroup with query-result location scoped to a dedicated
  `s3://app-analytics-<env>/athena-results/` prefix, separate from raw/processed data.
- No credentials are stored in code; all access is via IAM roles / the AWS CLI's default
  credential chain. See `aws_setup_guide.md` for exact policy JSON.

## Cost control

- S3 lifecycle rule moves raw CSVs to S3 Standard-IA after 30 days.
- Athena workgroup has a per-query data-scanned limit configured to avoid runaway costs
  from an accidental `SELECT *` over unpartitioned data.
- All of this is free-tier-friendly for a portfolio project at the data volumes described
  here (single-digit GB).

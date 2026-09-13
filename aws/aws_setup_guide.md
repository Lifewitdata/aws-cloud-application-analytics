# AWS Setup Guide

Step-by-step instructions to stand up the AWS side of this project. Uses AWS CLI
commands (also doable in the console — console equivalents are noted).

Prerequisites: an AWS account, AWS CLI installed and configured (`aws configure`), and
an IAM user/role with permission to create S3, Glue, Athena, and IAM resources.

---

## Step 1 — Create the S3 buckets (raw + processed + athena results)

```bash
export BUCKET=app-analytics-yourname-demo   # must be globally unique
export REGION=us-east-1

aws s3 mb s3://$BUCKET --region $REGION

# Logical "zones" via prefixes (no separate buckets needed)
aws s3api put-object --bucket $BUCKET --key raw/users/
aws s3api put-object --bucket $BUCKET --key raw/events/
aws s3api put-object --bucket $BUCKET --key raw/transactions/
aws s3api put-object --bucket $BUCKET --key raw/errors/
aws s3api put-object --bucket $BUCKET --key processed/
aws s3api put-object --bucket $BUCKET --key athena-results/
```

Console equivalent: S3 → Create bucket → enable "Block all public access" (default) →
create the same prefixes by uploading empty folders.

## Step 2 — Upload raw data

```bash
aws s3 cp data/raw/2019-Nov.csv s3://$BUCKET/raw/events/2019-Nov.csv
aws s3 cp data/raw/olist_orders_dataset.csv s3://$BUCKET/raw/transactions/
aws s3 cp data/raw/olist_order_payments_dataset.csv s3://$BUCKET/raw/transactions/
aws s3 cp data/raw/olist_customers_dataset.csv s3://$BUCKET/raw/transactions/
aws s3 cp data/raw/app_errors_synthetic.csv s3://$BUCKET/raw/errors/
```

## Step 3 — Create the IAM role for Glue

Save as `glue-trust-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "glue.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
```

Save as `glue-s3-policy.json` (scoped to this bucket only):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::app-analytics-yourname-demo",
      "arn:aws:s3:::app-analytics-yourname-demo/*"
    ]
  }]
}
```

```bash
aws iam create-role --role-name GlueAppAnalyticsRole \
  --assume-role-policy-document file://glue-trust-policy.json

aws iam put-role-policy --role-name GlueAppAnalyticsRole \
  --policy-name GlueS3Access --policy-document file://glue-s3-policy.json

aws iam attach-role-policy --role-name GlueAppAnalyticsRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole
```

## Step 4 — Create Glue databases

```bash
aws glue create-database --database-input '{"Name":"app_analytics_raw"}'
aws glue create-database --database-input '{"Name":"app_analytics_processed"}'
```

## Step 5 — Create and run the raw-zone Glue Crawler

```bash
aws glue create-crawler \
  --name app-analytics-raw-crawler \
  --role GlueAppAnalyticsRole \
  --database-name app_analytics_raw \
  --targets '{"S3Targets":[{"Path":"s3://'"$BUCKET"'/raw/"}]}'

aws glue start-crawler --name app-analytics-raw-crawler
```

Console equivalent: Glue → Crawlers → Create crawler → point at `s3://<bucket>/raw/` →
choose the `GlueAppAnalyticsRole` → target database `app_analytics_raw` → Run.

Check status:
```bash
aws glue get-crawler --name app-analytics-raw-crawler --query 'Crawler.State'
```

## Step 6 — Run the local cleaning pipeline

```bash
pip install -r requirements.txt
python src/data_cleaning.py --input data/raw --output data/processed
python src/data_validation.py --input data/processed
python src/transformations.py --input data/processed --output data/processed/star_schema
```

This writes partitioned Parquet to `data/processed/star_schema/{table}/year=YYYY/month=MM/`.

## Step 7 — Upload processed Parquet to S3

```bash
aws s3 sync data/processed/star_schema s3://$BUCKET/processed/
```

## Step 8 — Crawl the processed zone

```bash
aws glue create-crawler \
  --name app-analytics-processed-crawler \
  --role GlueAppAnalyticsRole \
  --database-name app_analytics_processed \
  --targets '{"S3Targets":[{"Path":"s3://'"$BUCKET"'/processed/"}]}'

aws glue start-crawler --name app-analytics-processed-crawler
```

## Step 9 — Set up Athena

```bash
aws athena create-work-group --name app-analytics-wg \
  --configuration "ResultConfiguration={OutputLocation=s3://$BUCKET/athena-results/},EnforceWorkGroupConfiguration=true"
```

Console equivalent: Athena → Workgroups → Create → set query result location to
`s3://<bucket>/athena-results/`. Then Athena → Query editor → select database
`app_analytics_processed` → run the scripts in `sql/`, in order:
1. `sql/data_quality_checks.sql`
2. `sql/data_exploration.sql`
3. `sql/business_analysis.sql`

## Step 10 — Connect Power BI

Power BI Desktop → Get Data → **Amazon Athena** connector (requires the Athena ODBC
driver, free download from AWS) → enter the workgroup's query result S3 location and your
AWS region → authenticate with an IAM access key scoped to Athena read-only + the
`athena-results` prefix → select the tables under `app_analytics_processed`.

Alternative (no ODBC driver needed): export each query in `sql/business_analysis.sql` as
CSV from the Athena console ("Download results") and import those CSVs directly into
Power BI — fully sufficient for a portfolio demo.

## Teardown (avoid ongoing charges)

```bash
aws glue delete-crawler --name app-analytics-raw-crawler
aws glue delete-crawler --name app-analytics-processed-crawler
aws glue delete-database --name app_analytics_raw
aws glue delete-database --name app_analytics_processed
aws athena delete-work-group --work-group app-analytics-wg --recursive-delete-option
aws s3 rb s3://$BUCKET --force
aws iam delete-role-policy --role-name GlueAppAnalyticsRole --policy-name GlueS3Access
aws iam detach-role-policy --role-name GlueAppAnalyticsRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole
aws iam delete-role --role-name GlueAppAnalyticsRole
```

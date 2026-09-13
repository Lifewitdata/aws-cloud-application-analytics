-- ============================================================================
-- data_exploration.sql
-- Run SECOND, after quality checks pass. Database: app_analytics_processed
-- General profiling to understand shape/scale of the data before business analysis.
-- ============================================================================

-- 1. Date range covered by each fact table
SELECT MIN(event_timestamp) AS first_event, MAX(event_timestamp) AS last_event
FROM fact_events;

SELECT MIN(transaction_date) AS first_txn, MAX(transaction_date) AS last_txn
FROM fact_transactions;

SELECT MIN(error_timestamp) AS first_error, MAX(error_timestamp) AS last_error
FROM fact_errors;

-- 2. Distinct counts (cardinality check)
SELECT
    COUNT(DISTINCT user_id)    AS distinct_users,
    COUNT(DISTINCT session_id) AS distinct_sessions
FROM fact_events;

-- 3. Event type distribution (raw counts)
SELECT event_type, COUNT(*) AS events, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM fact_events
GROUP BY event_type
ORDER BY events DESC;

-- 4. Device type distribution across events
SELECT device_type, COUNT(*) AS events, COUNT(DISTINCT user_id) AS users
FROM fact_events
GROUP BY device_type
ORDER BY events DESC;

-- 5. Application version distribution
SELECT application_version, COUNT(*) AS events
FROM fact_events
GROUP BY application_version
ORDER BY application_version;

-- 6. Transaction status breakdown
SELECT transaction_status, COUNT(*) AS transactions, SUM(transaction_amount) AS total_amount
FROM fact_transactions
GROUP BY transaction_status
ORDER BY transactions DESC;

-- 7. Payment method mix
SELECT payment_method, COUNT(*) AS transactions, SUM(transaction_amount) AS total_amount,
       ROUND(AVG(transaction_amount), 2) AS avg_amount
FROM fact_transactions
WHERE transaction_status = 'Completed'
GROUP BY payment_method
ORDER BY total_amount DESC;

-- 8. Customer segment distribution
SELECT customer_segment, COUNT(*) AS users
FROM dim_users
GROUP BY customer_segment
ORDER BY users DESC;

-- 9. Region distribution
SELECT region, COUNT(*) AS users
FROM dim_users
GROUP BY region
ORDER BY users DESC
LIMIT 15;

-- 10. Error type distribution
SELECT error_type, COUNT(*) AS errors, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM fact_errors
GROUP BY error_type
ORDER BY errors DESC;

-- 11. Session duration distribution (basic stats)
SELECT
    ROUND(AVG(session_duration_sec), 1)                                  AS avg_duration_sec,
    APPROX_PERCENTILE(session_duration_sec, 0.5)                          AS median_duration_sec,
    APPROX_PERCENTILE(session_duration_sec, 0.9)                          AS p90_duration_sec,
    ROUND(AVG(event_count), 1)                                            AS avg_events_per_session
FROM dim_sessions;

-- ============================================================================
-- data_quality_checks.sql
-- Run FIRST, before analysis. Database: app_analytics_processed (Amazon Athena / Presto)
-- Mirrors the checks in src/data_validation.py, run again post-load as a safety net.
-- ============================================================================

-- 1. Row counts per table (sanity check nothing failed to load)
SELECT 'dim_users' AS table_name, COUNT(*) AS row_count FROM dim_users
UNION ALL
SELECT 'fact_events', COUNT(*) FROM fact_events
UNION ALL
SELECT 'dim_sessions', COUNT(*) FROM dim_sessions
UNION ALL
SELECT 'fact_transactions', COUNT(*) FROM fact_transactions
UNION ALL
SELECT 'fact_errors', COUNT(*) FROM fact_errors;

-- 2. Null checks on key columns
SELECT
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE user_id IS NULL) AS null_user_id,
    COUNT(*) FILTER (WHERE session_id IS NULL) AS null_session_id,
    COUNT(*) FILTER (WHERE event_type IS NULL) AS null_event_type,
    COUNT(*) FILTER (WHERE event_timestamp IS NULL) AS null_event_timestamp
FROM fact_events;

SELECT
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE transaction_amount IS NULL) AS null_amount,
    COUNT(*) FILTER (WHERE transaction_amount <= 0) AS non_positive_amount
FROM fact_transactions;

-- 3. Duplicate primary key check
SELECT transaction_id, COUNT(*) AS occurrences
FROM fact_transactions
GROUP BY transaction_id
HAVING COUNT(*) > 1;

SELECT event_id, COUNT(*) AS occurrences
FROM fact_events
GROUP BY event_id
HAVING COUNT(*) > 1;

-- 4. Referential integrity: events referencing a user not in dim_users
SELECT COUNT(*) AS orphaned_events
FROM fact_events e
LEFT JOIN dim_users u ON e.user_id = u.user_id
WHERE u.user_id IS NULL;

-- 5. Referential integrity: transactions referencing a user not in dim_users
SELECT COUNT(*) AS orphaned_transactions
FROM fact_transactions t
LEFT JOIN dim_users u ON t.user_id = u.user_id
WHERE u.user_id IS NULL;

-- 6. Referential integrity: errors referencing a user not in dim_users
SELECT COUNT(*) AS orphaned_errors
FROM fact_errors er
LEFT JOIN dim_users u ON er.user_id = u.user_id
WHERE u.user_id IS NULL;

-- 7. Events referencing a session not in dim_sessions
SELECT COUNT(*) AS orphaned_event_sessions
FROM fact_events e
LEFT JOIN dim_sessions s ON e.session_id = s.session_id
WHERE s.session_id IS NULL;

-- 8. Value-set / domain checks
SELECT DISTINCT event_type FROM fact_events;                 -- expect exactly: Login, Product View, Add to Cart, Remove from Cart, Checkout
SELECT DISTINCT transaction_status FROM fact_transactions;   -- expect exactly: Completed, Pending, Failed
SELECT DISTINCT device_type FROM fact_events;                 -- expect exactly: Mobile, Desktop, Tablet
SELECT DISTINCT customer_segment FROM dim_users;               -- expect exactly: High Value, Mid Value, Low Value, Non-Purchaser

-- 9. Timestamp range sanity (no future dates, no implausibly old dates)
SELECT MIN(event_timestamp) AS earliest_event, MAX(event_timestamp) AS latest_event
FROM fact_events
WHERE event_timestamp > CURRENT_TIMESTAMP OR event_timestamp < DATE '2015-01-01';

-- 10. Cross-table consistency: every converted session should have >= 1 'Checkout' event
SELECT COUNT(*) AS mismatched_conversion_flags
FROM dim_sessions s
WHERE s.converted = TRUE
  AND NOT EXISTS (
      SELECT 1 FROM fact_events e
      WHERE e.session_id = s.session_id AND e.event_type = 'Checkout'
  );

-- ============================================================================
-- business_analysis.sql
-- Run THIRD. Database: app_analytics_processed
-- Each query is named to match docs/business_questions.md and
-- powerbi/dashboard_documentation.md so results trace directly to a dashboard visual.
-- ============================================================================

-- =========================================================
-- Q1_event_type_distribution
-- How do users interact with the application (event mix)?
-- =========================================================
SELECT
    event_type,
    COUNT(*) AS event_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM fact_events
GROUP BY event_type
ORDER BY event_count DESC;


-- =========================================================
-- Q2_daily_event_trend
-- Which features are used most frequently, and how does usage trend?
-- =========================================================
SELECT
    DATE(event_timestamp) AS event_date,
    event_type,
    COUNT(*) AS event_count
FROM fact_events
GROUP BY DATE(event_timestamp), event_type
ORDER BY event_date, event_type;


-- =========================================================
-- Q3_dau_wau_mau
-- Daily / Weekly / Monthly Active Users
-- =========================================================
WITH daily AS (
    SELECT DATE(event_timestamp) AS activity_date, user_id
    FROM fact_events
),
dau AS (
    SELECT activity_date, COUNT(DISTINCT user_id) AS dau
    FROM daily
    GROUP BY activity_date
),
wau AS (
    SELECT activity_date,
           COUNT(DISTINCT user_id) FILTER (WHERE TRUE) AS wau  -- placeholder, replaced by window below
    FROM daily
    GROUP BY activity_date
)
-- DAU per day, plus rolling 7-day and 30-day active-user counts computed with a self-join
-- (Presto does not support DISTINCT COUNT in a window frame directly)
SELECT
    d.activity_date,
    d.dau,
    (SELECT COUNT(DISTINCT user_id) FROM daily x
       WHERE x.activity_date BETWEEN d.activity_date - INTERVAL '6' DAY AND d.activity_date) AS wau_trailing_7d,
    (SELECT COUNT(DISTINCT user_id) FROM daily x
       WHERE x.activity_date BETWEEN d.activity_date - INTERVAL '29' DAY AND d.activity_date) AS mau_trailing_30d
FROM dau d
ORDER BY d.activity_date;


-- =========================================================
-- Q4_conversion_funnel
-- Where do users drop off (View -> Cart -> Checkout -> Payment)?
-- Built at the SESSION grain to avoid double-counting repeat views within one session.
-- =========================================================
WITH session_flags AS (
    SELECT
        session_id,
        MAX(CASE WHEN event_type = 'Product View' THEN 1 ELSE 0 END)  AS reached_view,
        MAX(CASE WHEN event_type = 'Add to Cart'  THEN 1 ELSE 0 END)  AS reached_cart,
        MAX(CASE WHEN event_type = 'Checkout'     THEN 1 ELSE 0 END)  AS reached_checkout
    FROM fact_events
    GROUP BY session_id
),
payment_flags AS (
    SELECT s.session_id, MAX(CASE WHEN t.transaction_status = 'Completed' THEN 1 ELSE 0 END) AS reached_payment
    FROM dim_sessions s
    LEFT JOIN fact_transactions t ON s.user_id = t.user_id
        AND t.transaction_date BETWEEN s.session_start AND s.session_end + INTERVAL '1' DAY
    GROUP BY s.session_id
)
SELECT
    SUM(f.reached_view)     AS stage_1_product_view,
    SUM(f.reached_cart)     AS stage_2_add_to_cart,
    SUM(f.reached_checkout) AS stage_3_checkout,
    SUM(COALESCE(p.reached_payment, 0)) AS stage_4_payment
FROM session_flags f
LEFT JOIN payment_flags p ON f.session_id = p.session_id;


-- =========================================================
-- Q5_errors_by_device_version
-- Which devices / app versions generate the most errors?
-- =========================================================
SELECT
    device_type,
    application_version,
    COUNT(*) AS error_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total_errors
FROM fact_errors
GROUP BY device_type, application_version
ORDER BY error_count DESC;


-- =========================================================
-- Q6_engagement_vs_transaction
-- How does engagement relate to whether/how much a user transacts?
-- =========================================================
WITH user_engagement AS (
    SELECT
        u.user_id,
        COUNT(DISTINCT s.session_id) AS session_count,
        ROUND(AVG(s.event_count), 1) AS avg_events_per_session
    FROM dim_users u
    LEFT JOIN dim_sessions s ON u.user_id = s.user_id
    GROUP BY u.user_id
),
user_spend AS (
    SELECT user_id, SUM(transaction_amount) AS lifetime_spend
    FROM fact_transactions
    WHERE transaction_status = 'Completed'
    GROUP BY user_id
)
SELECT
    e.user_id,
    e.session_count,
    e.avg_events_per_session,
    COALESCE(s.lifetime_spend, 0) AS lifetime_spend
FROM user_engagement e
LEFT JOIN user_spend s ON e.user_id = s.user_id;


-- =========================================================
-- Q7_revenue_by_segment_region
-- Which customer segments / regions generate the most revenue?
-- =========================================================
SELECT
    u.customer_segment,
    u.region,
    COUNT(DISTINCT u.user_id) AS users,
    SUM(t.transaction_amount) AS total_revenue,
    ROUND(SUM(t.transaction_amount) / COUNT(DISTINCT u.user_id), 2) AS revenue_per_user
FROM dim_users u
JOIN fact_transactions t ON u.user_id = t.user_id
WHERE t.transaction_status = 'Completed'
GROUP BY u.customer_segment, u.region
ORDER BY total_revenue DESC;


-- =========================================================
-- Q8_error_rate_vs_conversion
-- How does app performance (errors) affect conversion / revenue?
-- =========================================================
WITH daily_sessions AS (
    SELECT DATE(session_start) AS activity_date,
           COUNT(*) AS total_sessions,
           SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS converted_sessions
    FROM dim_sessions
    GROUP BY DATE(session_start)
),
daily_errors AS (
    SELECT DATE(error_timestamp) AS activity_date, COUNT(*) AS error_count
    FROM fact_errors
    GROUP BY DATE(error_timestamp)
),
daily_events AS (
    SELECT DATE(event_timestamp) AS activity_date, COUNT(DISTINCT session_id) AS active_sessions
    FROM fact_events
    GROUP BY DATE(event_timestamp)
)
SELECT
    s.activity_date,
    s.total_sessions,
    ROUND(100.0 * s.converted_sessions / NULLIF(s.total_sessions, 0), 2) AS conversion_rate_pct,
    COALESCE(er.error_count, 0) AS error_count,
    ROUND(100.0 * COALESCE(er.error_count, 0) / NULLIF(ev.active_sessions, 0), 2) AS error_rate_pct
FROM daily_sessions s
LEFT JOIN daily_errors er ON s.activity_date = er.activity_date
LEFT JOIN daily_events ev ON s.activity_date = ev.activity_date
ORDER BY s.activity_date;


-- =========================================================
-- Q9_aov_repeat_rate
-- Average order value and repeat purchase rate
-- =========================================================
WITH per_user_orders AS (
    SELECT user_id, COUNT(*) AS order_count, SUM(transaction_amount) AS total_spend
    FROM fact_transactions
    WHERE transaction_status = 'Completed'
    GROUP BY user_id
)
SELECT
    ROUND(AVG(total_spend / order_count), 2) AS avg_order_value,
    ROUND(100.0 * SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS repeat_purchase_rate_pct,
    COUNT(*) AS total_purchasing_users
FROM per_user_orders;


-- =========================================================
-- Q10_payment_method_mix
-- Payment method mix by count, revenue, and average value
-- =========================================================
SELECT
    payment_method,
    COUNT(*) AS transactions,
    SUM(transaction_amount) AS total_revenue,
    ROUND(AVG(transaction_amount), 2) AS avg_value,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_transactions
FROM fact_transactions
WHERE transaction_status = 'Completed'
GROUP BY payment_method
ORDER BY total_revenue DESC;

# Business Questions → SQL → Dashboard Mapping

Each question below maps to a named query in `sql/business_analysis.sql` and a specific
visual in the Power BI report (`powerbi/dashboard_documentation.md`).

| # | Business Question | SQL Query | Dashboard Visual |
|---|---|---|---|
| 1 | How do users interact with the application (event mix)? | `Q1_event_type_distribution` | Donut chart — event type share |
| 2 | Which features/events are used most frequently, and how does usage trend over time? | `Q2_daily_event_trend` | Line chart — daily event volume by type |
| 3 | How many Daily / Weekly / Monthly Active Users does the app have? | `Q3_dau_wau_mau` | KPI cards + trend line — DAU/WAU/MAU |
| 4 | Where do users drop off in the funnel (View → Cart → Checkout → Payment)? | `Q4_conversion_funnel` | Funnel chart |
| 5 | Which devices / app versions generate the most errors? | `Q5_errors_by_device_version` | Stacked bar — errors by device × version |
| 6 | How does engagement (sessions, events per user) relate to whether a user transacts? | `Q6_engagement_vs_transaction` | Scatter plot — events/session vs. spend |
| 7 | Which customer segments / regions generate the most revenue? | `Q7_revenue_by_segment_region` | Bar chart + map — revenue by segment/region |
| 8 | How does app performance (error rate) affect conversion / revenue? | `Q8_error_rate_vs_conversion` | Combo chart — error rate vs. conversion rate over time |
| — | Supporting: average order value, repeat purchase rate, payment method mix | `Q9_aov_repeat_rate`, `Q10_payment_method_mix` | KPI cards / pie chart |

## Notes on interpretation

- **DAU/WAU/MAU (Q3):** computed from `fact_events`, distinct `user_id` per day/7-day
  window/30-day window. This is the standard product-analytics definition of "active."
- **Funnel (Q4):** built on `dim_sessions` + `fact_events`, using session-level flags for
  whether each session reached each funnel stage — this avoids double counting users who
  view a product multiple times without proceeding further.
- **Engagement vs. transaction (Q6):** deliberately correlational, not causal — the
  write-up in `docs/insights.md` should state this explicitly rather than implying
  engagement *causes* spend.
- **Error rate vs. conversion (Q8):** this is the headline "so what" chart of the project —
  it's the one most likely to be discussed in an interview, so the underlying SQL should
  be the most carefully validated (cross-check counts against `data_quality_checks.sql`).

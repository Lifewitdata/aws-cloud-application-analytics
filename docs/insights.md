# Business Insights & Recommendations

> Template — fill in the `[ ]` placeholders with the actual numbers your Athena queries
> and Power BI dashboard produce once you run the pipeline end-to-end. Keep every claim
> tied to a specific query name from `sql/business_analysis.sql` so the insight is
> auditable.

## 1. User Engagement

- **Finding:** DAU averaged **[ ]** users over the analysis period, with WAU/DAU stickiness
  ratio of **[ ]%** (source: `Q3_dau_wau_mau`).
- **So what:** [ interpretation — e.g., is engagement seasonal, growing, flat? ]
- **Recommendation:** [ e.g., target re-engagement campaigns on days where DAU dips below X ]

## 2. Feature Usage

- **Finding:** **[event_type]** accounts for **[ ]%** of all events; **[event_type]** is
  the least-used major feature (source: `Q1_event_type_distribution`, `Q2_daily_event_trend`).
- **Recommendation:** [ ]

## 3. Conversion Funnel

- **Finding:** Of sessions that reach "Product View," only **[ ]%** reach "Add to Cart,"
  and only **[ ]%** of those reach "Payment" — the largest single drop-off is between
  **[stage]** and **[stage]** (source: `Q4_conversion_funnel`).
- **Recommendation:** [ e.g., investigate friction at checkout / simplify cart-to-checkout UX ]

## 4. Errors & Platform Reliability

- **Finding:** **[device_type]** on app version **[X.X.X]** accounts for **[ ]%** of all
  errors, disproportionate to its **[ ]%** share of sessions (source: `Q5_errors_by_device_version`).
- **Recommendation:** [ e.g., prioritize a hotfix for that version/device combination ]

## 5. Engagement → Revenue Link

- **Finding:** Users with **[ ]+ events per session on average** show **[ ]x** higher
  average transaction value than low-engagement users (source: `Q6_engagement_vs_transaction`).
- **Caveat:** correlation, not causation — high-intent users may naturally browse more
  AND spend more, independent of any causal engagement effect.
- **Recommendation:** [ ]

## 6. Revenue by Segment & Region

- **Finding:** The **[segment]** segment contributes **[ ]%** of revenue from only **[ ]%**
  of users; **[region]** is the top-revenue region (source: `Q7_revenue_by_segment_region`).
- **Recommendation:** [ e.g., double down on retention for High Value segment ]

## 7. Errors vs. Business Outcomes

- **Finding:** On days where the error rate exceeded **[ ]%**, checkout conversion dropped
  by **[ ]** percentage points relative to low-error days (source: `Q8_error_rate_vs_conversion`).
- **Recommendation:** [ tie engineering reliability work directly to a revenue estimate ]

## 8. Summary of Top 3 Recommendations

1. [ ]
2. [ ]
3. [ ]

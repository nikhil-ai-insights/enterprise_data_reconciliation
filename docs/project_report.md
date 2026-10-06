# Enterprise Data Reconciliation Project Report

## 1. Executive Summary
This project solves a FinTech financial-audit reconciliation problem using three independent data systems: historical customer records in SQLite, 100,000 raw server logs, and daily EUR/USD exchange rates. The final pipeline extracts valid transactions, removes ERROR records, selects the latest Active customer state, forward-fills missing market rates, calculates USD revenue, validates the result, and produces CFO-oriented summaries.

The completed run retained **94,902 valid transactions** from **100,000 raw logs** after filtering **5,098 ERROR records**. The final reconciled table also contains 94,902 rows with zero duplicate rows.

## 2. Business Problem
The source systems are intentionally messy. Customer history contains multiple records per user; transactions are embedded inside log text; and exchange-rate data contains missing market dates. A naive join can lose valid records or attach stale customer states.

## 3. Objectives
1. Retrieve each user's latest record and keep only latest Active users.
2. Parse Date, User ID, Product ID and Euro Value from raw logs with Regex.
3. Remove ERROR log rows without manually editing the source data.
4. Forward-fill missing exchange rates before reconciliation.
5. Calculate USD revenue without dropping valid transaction rows.
6. Produce monthly revenue and Top-5 customer summaries.
7. Validate completeness, uniqueness and consistency.
8. Meet the efficiency requirement for 100,000 rows.

## 4. Data Sources
### 4.1 Enterprise database
The SQLite `users` table contains **47,464 historical records** covering **25,000 unique users**. A window-function query selects the latest chronological row per `user_id`; filtering to `Active` yields **14,183 latest Active users**.

### 4.2 Server logs
`server_logs.txt` contains **100,000 transaction records**. Each valid record stores transaction Date, User ID, Product ID and Euro Value in an unstructured text payload. **5,098** rows are labeled ERROR and are filtered out.

### 4.3 Exchange-rate file
The daily exchange-rate file covers **365 dates in 2023**. It contains **104** missing source EUR/USD values. The pipeline sorts by Date and applies forward-fill, leaving **0** missing rates. The actual missing source values occur on **52 Fridays and 52 Saturdays**.

## 5. Methodology
### 5.1 Advanced SQL
The customer history is ranked with:

```sql
ROW_NUMBER() OVER (
    PARTITION BY user_id
    ORDER BY datetime(updated_at) DESC, rowid DESC
)
```

Rows with `rn = 1` represent each user's most recent state, after which only `Active` records are selected.

### 5.2 Regex and Unstructured Data
The raw log file is loaded as a Pandas `Series`. The implementation:
- filters ERROR rows with vectorized string matching,
- extracts the timestamp from the log prefix,
- extracts `u`, `item_code`, and `eur_val` from the payload,
- converts dates and numeric amounts to proper types,
- validates all required fields.

The parser uses vectorized Pandas string operations and does not use `iterrows()` or a Pandas row-wise loop.

### 5.3 Temporal Reconciliation
Exchange rates are sorted chronologically and missing values are forward-filled. Transactions are then left-joined by exact calendar date. This preserves transaction rows even where the original exchange-rate table had missing values.

### 5.4 Customer Reconciliation
Transactions are left-joined to the latest Active-user table. The `Active_User_Match` indicator distinguishes transaction rows that reconcile to the latest Active customer dimension from rows whose latest customer state is not Active.

### 5.5 Revenue Calculation
For each valid transaction:

```text
USD_Revenue = Euro_Value × EUR_to_USD_Filled
```

## 6. Results
### 6.1 Reconciliation summary
| Metric | Result |
|---|---:|
| Raw log rows | 100,000 |
| ERROR rows filtered | 5,098 |
| Valid parsed transactions | 94,902 |
| Latest Active users | 14,183 |
| Transactions matched to latest Active users | 53,899 |
| Transactions without latest Active match | 41,003 |
| Transactions with exchange rate | 94,902 |
| Transactions without exchange rate | 0 |
| Final reconciled rows | 94,902 |
| Duplicate final rows | 0 |
| Total EUR value | €237,775,609.55 |
| Total USD revenue | $261,241,851.63 |
| Weekend-dated valid transactions retained | 27,243 |

### 6.2 Top 5 Most Valuable Customers
| Rank | User ID | Customer | USD Revenue |
|---:|---|---|---:|
| 1 | U-06582 | User_U-06582 | $40,050.99 |
| 2 | U-23313 | User_U-23313 | $39,555.81 |
| 3 | U-03805 | User_U-03805 | $39,529.95 |
| 4 | U-20018 | User_U-20018 | $38,649.97 |
| 5 | U-06489 | User_U-06489 | $38,629.14 |

### 6.3 Monthly Revenue
The complete monthly revenue breakdown is stored in `outputs/monthly_usd_revenue.csv` and visualized in the CFO dashboard. All twelve months of 2023 reconcile to the overall USD revenue total.

## 7. Data Quality Validation
All final checks passed:
- unique latest Active user IDs: PASS
- missing exchange rates after forward-fill: 0
- missing Date values: 0
- missing User IDs: 0
- missing Product IDs: 0
- missing Euro values: 0
- missing USD revenue: 0
- duplicate final rows: 0

## 8. Performance
A direct benchmark of the vectorized server-log parser on the supplied **100,000-record** file completed in **0.7193 seconds**, substantially below the project's 2-minute efficiency requirement.

## 9. Dashboard
The CFO dashboard contains:
1. Total USD Revenue by Month.
2. Top 5 Most Valuable Customers.

The project stores both standalone chart PNGs and the combined `cfo_dashboard.png`.

## 10. Deliverables
- `src/run_pipeline.py` — complete Python pipeline
- `sql/enterprise_reconciliation.sql` — SQL implementation and audit queries
- `docs/complete_solution.ipynb` — completed notebook
- `outputs/final_reconciled_transactions.csv` — final transaction-level reconciliation
- `outputs/monthly_usd_revenue.csv` — monthly revenue
- `outputs/top5_customers.csv` — Top-5 customers
- `outputs/reconciliation_summary.csv` — reconciliation metrics
- `outputs/data_quality_summary.csv` — validation results
- `outputs/cfo_dashboard.png` — CFO dashboard
- `README.md` — execution and project documentation

## 11. Conclusion
The completed solution reconciles the supplied enterprise datasets without silently dropping valid transactions, handles historical customer versions correctly, fills exchange-rate gaps, and produces a validated financial view suitable for audit and CFO review.

from __future__ import annotations

import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "outputs"
DB_PATH = DATA_DIR / "enterprise_database.db"
RATES_PATH = DATA_DIR / "daily_exchange_rates.csv"
LOG_PATH = DATA_DIR / "server_logs.txt"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Project requirements call for four fields embedded in raw log text.
DATE_RE = r"\[([^\]]+)\]"
USER_RE = r'''(?:""u""|["']u["'])\s*:\s*(?:""|["'])([^"']+)(?:""|["'])'''
PRODUCT_RE = r'''(?:""item_code""|["']item_code["'])\s*:\s*(?:""|["'])([^"']+)(?:""|["'])'''
EURO_RE = r'''(?:""eur_val""|["']eur_val["'])\s*:\s*(-?\d+(?:\.\d+)?)'''


def extract_active_users(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Use a SQL window function to keep only each user's latest Active status."""
    query = """
    WITH ranked_users AS (
        SELECT
            user_id,
            name,
            status,
            updated_at,
            ROW_NUMBER() OVER (
                PARTITION BY user_id
                ORDER BY datetime(updated_at) DESC, rowid DESC
            ) AS rn
        FROM users
    )
    SELECT user_id, name, status, updated_at
    FROM ranked_users
    WHERE rn = 1 AND status = 'Active'
    ORDER BY user_id;
    """
    with sqlite3.connect(db_path) as conn:
        active = pd.read_sql_query(query, conn)
    active["updated_at"] = pd.to_datetime(active["updated_at"], errors="coerce")
    active["user_id"] = active["user_id"].astype("string")
    return active


def prepare_exchange_rates(rates_path: Path = RATES_PATH) -> pd.DataFrame:
    """Sort daily EUR/USD rates and forward-fill missing source values."""
    rates = pd.read_csv(rates_path)
    required = {"Date", "EUR_to_USD"}
    missing = required.difference(rates.columns)
    if missing:
        raise ValueError(f"Exchange-rate file missing columns: {sorted(missing)}")
    rates["Date"] = pd.to_datetime(rates["Date"], errors="coerce").dt.normalize()
    rates["EUR_to_USD"] = pd.to_numeric(rates["EUR_to_USD"], errors="coerce")
    rates = rates.sort_values("Date", kind="stable").reset_index(drop=True)
    if rates["Date"].isna().any() or rates["Date"].duplicated().any():
        raise ValueError("Exchange-rate dates must be valid and unique.")
    rates["EUR_to_USD_Filled"] = rates["EUR_to_USD"].ffill()
    if rates["EUR_to_USD_Filled"].isna().any():
        raise ValueError("Leading missing exchange rate(s) prevent safe forward-fill.")
    return rates


def parse_server_logs(log_path: Path = LOG_PATH) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Vectorized parsing of one raw log record per line; returns transactions and audit counts."""
    if not log_path.exists():
        raise FileNotFoundError(
            f"Missing required input: {log_path}. The starter notebook specifies a 100,000-row server_logs.txt file."
        )
    raw_text = log_path.read_text(encoding="utf-8", errors="replace")
    raw = pd.Series(raw_text.splitlines(), name="raw_log", dtype="string")
    # The first row is the source-file header, not a transaction record.
    if raw.size and raw.iloc[0].strip().lower() == "raw_server_log":
        raw = raw.iloc[1:].reset_index(drop=True)
    total_rows = int(raw.size)
    error_mask = raw.str.contains(r"\bERROR\b", case=False, na=False, regex=True)
    clean = raw.loc[~error_mask]

    parsed = pd.DataFrame({
        "Date": clean.str.extract(DATE_RE, expand=False),
        "User_ID": clean.str.extract(USER_RE, expand=False),
        "Product_ID": clean.str.extract(PRODUCT_RE, expand=False),
        "Euro_Value": clean.str.extract(EURO_RE, expand=False),
    })
    parsed["Date"] = pd.to_datetime(parsed["Date"], errors="coerce").dt.normalize()
    parsed["Euro_Value"] = pd.to_numeric(parsed["Euro_Value"], errors="coerce")
    parseable_mask = parsed.notna().all(axis=1) & parsed["Euro_Value"].ge(0)
    transactions = parsed.loc[parseable_mask].copy().reset_index(drop=True)
    transactions["User_ID"] = transactions["User_ID"].astype("string")
    transactions["Product_ID"] = transactions["Product_ID"].astype("string")

    audit = pd.DataFrame({
        "metric": [
            "raw_log_rows",
            "error_rows_filtered",
            "non_error_rows",
            "fully_parsed_valid_transactions",
            "non_error_unparseable_or_invalid_rows",
        ],
        "value": [
            total_rows,
            int(error_mask.sum()),
            int(clean.size),
            int(transactions.shape[0]),
            int(clean.size - transactions.shape[0]),
        ],
    })
    return transactions, audit


def reconcile(active_users: pd.DataFrame, transactions: pd.DataFrame, rates: pd.DataFrame):
    """Reconcile transactions to time-series rates and latest Active customer records."""
    tx = transactions.copy()
    rate_join = rates[["Date", "EUR_to_USD_Filled"]].copy()
    merged = tx.merge(rate_join, on="Date", how="left", validate="many_to_one")
    merged = merged.merge(
        active_users[["user_id", "name", "status"]],
        left_on="User_ID",
        right_on="user_id",
        how="left",
        validate="many_to_one",
    )
    merged["USD_Revenue"] = merged["Euro_Value"] * merged["EUR_to_USD_Filled"]
    merged["Month"] = merged["Date"].dt.to_period("M").astype("string")
    merged["Active_User_Match"] = merged["user_id"].notna()

    monthly = (
        merged.groupby("Month", as_index=False, dropna=False)["USD_Revenue"]
        .sum(min_count=1)
        .sort_values("Month")
        .reset_index(drop=True)
    )
    matched = merged.loc[merged["Active_User_Match"]].copy()
    top5 = (
        matched.groupby(["User_ID", "name"], as_index=False)["USD_Revenue"]
        .sum(min_count=1)
        .sort_values("USD_Revenue", ascending=False)
        .head(5)
        .reset_index(drop=True)
    )

    summary = pd.DataFrame({
        "metric": [
            "valid_parsed_transactions",
            "transactions_with_exchange_rate",
            "transactions_without_exchange_rate",
            "transactions_matched_to_latest_active_user",
            "transactions_without_latest_active_user_match",
            "final_reconciled_rows",
            "duplicate_final_rows",
        ],
        "value": [
            len(merged),
            int(merged["EUR_to_USD_Filled"].notna().sum()),
            int(merged["EUR_to_USD_Filled"].isna().sum()),
            int(merged["Active_User_Match"].sum()),
            int((~merged["Active_User_Match"]).sum()),
            len(merged),
            int(merged.duplicated().sum()),
        ],
    })
    return merged, monthly, top5, summary


def make_dashboard(monthly: pd.DataFrame, top5: pd.DataFrame, path: Path = OUT_DIR / "cfo_dashboard.png") -> None:
    """Build two standalone charts and combine them side-by-side into the requested dashboard."""
    monthly_path = OUT_DIR / "monthly_usd_revenue_chart.png"
    top5_path = OUT_DIR / "top5_customers_chart.png"

    fig1, ax1 = plt.subplots(figsize=(9, 5.5))
    ax1.bar(monthly["Month"], monthly["USD_Revenue"])
    ax1.set_title("Total USD Revenue by Month")
    ax1.set_xlabel("Month")
    ax1.set_ylabel("USD Revenue")
    ax1.tick_params(axis="x", rotation=45)
    fig1.tight_layout()
    fig1.savefig(monthly_path, dpi=180, bbox_inches="tight")
    plt.close(fig1)

    fig2, ax2 = plt.subplots(figsize=(9, 5.5))
    ax2.barh(top5["User_ID"].astype(str).iloc[::-1], top5["USD_Revenue"].iloc[::-1])
    ax2.set_title("Top 5 Most Valuable Customers")
    ax2.set_xlabel("USD Spend")
    ax2.set_ylabel("Customer")
    fig2.tight_layout()
    fig2.savefig(top5_path, dpi=180, bbox_inches="tight")
    plt.close(fig2)

    left = Image.open(monthly_path).convert("RGB")
    right = Image.open(top5_path).convert("RGB")
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width, height), "white")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width, 0))
    canvas.save(path)


def main() -> None:
    active_users = extract_active_users()
    active_users.to_csv(OUT_DIR / "active_users.csv", index=False)

    rates = prepare_exchange_rates()
    rates.to_csv(OUT_DIR / "exchange_rates_filled.csv", index=False)

    transactions, log_audit = parse_server_logs()
    transactions.to_csv(OUT_DIR / "extracted_transactions.csv", index=False)
    log_audit.to_csv(OUT_DIR / "transaction_parsing_audit.csv", index=False)

    df_final, monthly, top5, reconciliation = reconcile(active_users, transactions, rates)
    df_final.to_csv(OUT_DIR / "final_reconciled_transactions.csv", index=False)
    monthly.to_csv(OUT_DIR / "monthly_usd_revenue.csv", index=False)
    top5.to_csv(OUT_DIR / "top5_customers.csv", index=False)
    reconciliation.to_csv(OUT_DIR / "reconciliation_summary.csv", index=False)

    quality = pd.DataFrame({
        "check": [
            "active_user_id_unique",
            "exchange_rate_missing_after_ffill",
            "final_missing_date",
            "final_missing_user_id",
            "final_missing_product_id",
            "final_missing_euro_value",
            "final_missing_usd_revenue",
            "final_duplicate_rows",
        ],
        "result": [
            bool(active_users["user_id"].is_unique),
            int(rates["EUR_to_USD_Filled"].isna().sum()),
            int(df_final["Date"].isna().sum()),
            int(df_final["User_ID"].isna().sum()),
            int(df_final["Product_ID"].isna().sum()),
            int(df_final["Euro_Value"].isna().sum()),
            int(df_final["USD_Revenue"].isna().sum()),
            int(df_final.duplicated().sum()),
        ],
    })
    quality.to_csv(OUT_DIR / "data_quality_summary.csv", index=False)
    make_dashboard(monthly, top5)

    print("Project pipeline completed successfully")
    print(f"Latest Active users: {len(active_users):,}")
    print(f"Valid transactions: {len(transactions):,}")
    print(f"Final rows: {len(df_final):,}")


if __name__ == "__main__":
    main()

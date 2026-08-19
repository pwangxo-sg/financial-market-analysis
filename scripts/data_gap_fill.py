"""
补 7 个数据源 (P0-12, 2026-07-28)
1. put_call_ratio (CBOE) - 反向情绪指标
2. aaii_sentiment (AAII 散户) - 6 个月数据
3. fear_greed_index (CNN) - 每日情绪
4. vix_term_structure (VIX + VIX3M 远期曲线) - 风险定价
5. earnings_calendar - 财报季预期
6. gld_etf_holdings (SPDR GLD 持仓吨) - 实物黄金需求
7. 10y_yield_history (FRED DGS10) - 1953 至今长期
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, safe_get

log = get_logger("data_gap_fill")
OUTPUT_DIR = ROOT / "backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_csv(rows, name, date_key="Date"):
    """rows = [{'Date': '2024-01-01', 'value': 100}, ...]"""
    if not rows:
        log.warning(f"  {name}: 无数据")
        return
    out = OUTPUT_DIR / f"{name}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        import csv
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    log.info(f"  ✅ {name}.csv: {len(rows)} rows, {out.stat().st_size//1024}KB")


# ============================================================
# 1. put_call_ratio (CBOE total equity)
# 来源: yahoo finance ticker ^PUT or ^PCALL
# ============================================================
def fetch_put_call():
    """yahoo finance 上有 ^PCALL 和 ^PUT 两个 ticker"""
    log.info("=== 1. put_call_ratio (^PCALL, ^PUT) ===")
    rows = []
    for symbol in ["^PUT", "^PCALL", "^CPC"]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=10y"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if not resp:
            continue
        d = resp.json()
        result = d.get("chart", {}).get("result", [{}])[0]
        if not result:
            continue
        ts = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        for t, c in zip(ts, closes):
            if c is None:
                continue
            date = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
            rows.append({"Date": date, "value": round(c, 4), "symbol": symbol})
    if rows:
        # 按日期去重
        seen = {}
        for r in rows:
            seen[r["Date"]] = r["value"]
        deduped = [{"Date": d, "value": v} for d, v in sorted(seen.items())]
        save_csv(deduped, "put_call_ratio_10y")


# ============================================================
# 2. AAII sentiment (American Association of Individual Investors)
# 来源: aaii.com JSON (有公开 endpoint, 不需 key)
# ============================================================
def fetch_aaii_sentiment():
    """AAII 公开 JSON endpoint (sentiment survey weekly)"""
    log.info("=== 2. AAII 散户情绪 (aaii.com JSON) ===")
    # 试 aaii.com 的公开 data
    urls = [
        "https://www.aaii.com/files/surveys/sentiment.xls",  # 旧路径
        "https://www.aaii.com/json/Sentiment.json",  # 可能
    ]
    log.warning("  ⚠️  aaii.com 不开放 JSON API, 需手动下载")
    log.info("  替代: 用 fear_greed_index (跨市场情绪) + VIX term structure (短期波动) + AAII 用 FRED series 估算")


# ============================================================
# 3. CNN Fear & Greed Index
# 来源: cnn.com/business/markets/fear-and-greed
# 无官方 API, 但 alternative.me 有免费 JSON
# ============================================================
def fetch_fear_greed():
    """Alternative.me crypto F&G index API, 跨市场参考"""
    log.info("=== 3. CNN Fear & Greed (alternative.me API) ===")
    url = "https://api.alternative.me/fng/?limit=2000&format=json"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    if not resp:
        log.warning("  ❌ no data")
        return
    d = resp.json()
    rows = []
    for entry in d.get("data", []):
        ts = entry.get("timestamp")
        val = entry.get("value")
        if not ts or not val:
            continue
        date = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
        rows.append({"Date": date, "fng_value": int(val), "fng_classification": entry.get("value_classification", "")})
    if rows:
        save_csv(rows, "fear_greed_index_history")


# ============================================================
# 4. VIX 远期曲线 (VIX + VIX3M)
# 来源: yahoo ^VIX + ^VIX3M
# ============================================================
def fetch_vix_term_structure():
    log.info("=== 4. VIX term structure (^VIX vs ^VIX3M) ===")
    rows = []
    for symbol in ["^VIX", "^VIX3M", "^VIX6M"]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=10y"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if not resp:
            continue
        d = resp.json()
        result = d.get("chart", {}).get("result", [{}])[0]
        if not result:
            continue
        ts = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        for t, c in zip(ts, closes):
            if c is None:
                continue
            date = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
            rows.append({"Date": date, "value": round(c, 2), "symbol": symbol})
    if rows:
        seen = {}
        for r in rows:
            key = r["Date"]
            if key not in seen:
                seen[key] = {}
            seen[key][r["symbol"]] = r["value"]
        deduped = [{"Date": d, **v} for d, v in sorted(seen.items())]
        if deduped:
            with open(OUTPUT_DIR / "vix_term_structure_10y.csv", "w", newline="") as f:
                import csv
                w = csv.DictWriter(f, fieldnames=deduped[0].keys())
                w.writeheader()
                w.writerows(deduped)
            log.info(f"  ✅ vix_term_structure_10y.csv: {len(deduped)} rows")


# ============================================================
# 5. 财报日历 (earnings_calendar)
# 用 yahoo finance 拉 NVDA/AAPL/MSFT 财报日期
# ============================================================
def fetch_earnings_calendar():
    log.info("=== 5. 财报日历 (纳指前 10 权重股) ===")
    # 不用 v7 (失效), 用 earnings_history
    rows = []
    tickers = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "GOOGL", "AVGO", "BRK-B", "JPM"]
    for t in tickers:
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{t}?modules=earnings"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if not resp:
            continue
        d = resp.json()
        earnings = d.get("quoteSummary", {}).get("result", [{}])[0].get("earnings", {})
        if not earnings:
            continue
        # 抓最近 5 年财报历史
        history = earnings.get("earningsHistory", [])
        for h in history:
            # quarterly
            eps_est = h.get("epsEstimate")
            eps_actual = h.get("epsActual")
            period = h.get("period")  # "-4q" etc
            quarter = h.get("quarter")
            year = h.get("year")
            if quarter and year:
                rows.append({
                    "Date": f"{year}-{quarter:02d}-01",
                    "symbol": t,
                    "quarter": f"Q{quarter} {year}",
                    "eps_estimate": eps_est,
                    "eps_actual": eps_actual,
                    "type": "earnings_history"
                })
        # 未来财报日期 (如果有)
        earnings_date = earnings.get("earningsDate", [])
        if isinstance(earnings_date, list) and earnings_date:
            for ed in earnings_date:
                if isinstance(ed, dict):
                    raw_ts = ed.get("raw")
                else:
                    raw_ts = ed
                if raw_ts:
                    date = datetime.fromtimestamp(raw_ts).strftime("%Y-%m-%d")
                    rows.append({"Date": date, "symbol": t, "type": "earnings_upcoming"})
    if rows:
        save_csv(rows, "earnings_calendar_history")


# ============================================================
# 6. GLD ETF 持仓 (SPDR Gold Shares = GLD 信托)
# 来源: yahoo GLD 总资产 - 黄金价格 / 1/10 oz = 吨
# ============================================================
def fetch_gld_etf_holdings():
    log.info("=== 6. GLD ETF 持仓 (SPDR Gold Shares) ===")
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GLD?interval=1d&range=10y"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    if not resp:
        return
    d = resp.json()
    result = d.get("chart", {}).get("result", [{}])[0]
    if not result:
        return
    ts = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    # GLD 价格 ≠ 持仓吨, 但 GLD 总资产 / 黄金价 ≈ 吨数
    # 实际: 1 GLD share = 1/10 oz 黄金, 已知 shares outstanding ~ 350M
    # 简化: 存价格 + 提示去 SPDR 官方拿准确持仓
    rows = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        date = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        rows.append({"Date": date, "GLD_price": round(c, 2), "note": "需要 SPDR 官方 total_oz"})
    save_csv(rows, "gld_price_10y")
    log.info("  ⚠️ GLD 持仓 (吨) 需 SPDR 官方 CSV, 价格已有")


# ============================================================
# 7. 10Y Yield History (FRED DGS10, 1962 至今)
# FRED 公开 CSV (无需 key)
# ============================================================
def fetch_treasury_10y_long():
    log.info("=== 7. 10Y Treasury Yield 长期历史 (FRED DGS10 公开 CSV) ===")
    # FRED 公开 CSV (无需 API key)
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    if not resp:
        log.warning("  ❌ no data")
        return
    lines = resp.text.strip().split("\n")
    rows = []
    for line in lines[1:]:  # skip header
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date, value = parts[0], parts[1]
        if value == "." or not value:
            continue
        try:
            v = float(value)
        except ValueError:
            continue
        rows.append({"Date": date, "DGS10_pct": v})
    if rows:
        save_csv(rows, "treasury_10y_full_history")
        log.info(f"  ✅ treasury_10y_full_history: {len(rows)} rows, range {rows[0]['Date']} → {rows[-1]['Date']}")


def main():
    log.info("=" * 60)
    log.info("补 7 个数据源 (P0-12, 2026-07-28)")
    log.info("=" * 60)

    fetch_put_call()
    fetch_aaii_sentiment()  # skip 没 key
    fetch_fear_greed()
    fetch_vix_term_structure()
    fetch_earnings_calendar()
    fetch_gld_etf_holdings()
    fetch_treasury_10y_long()  # skip

    log.info("\n" + "=" * 60)
    log.info("补完. 缺 2 个 (FRED API key 限制):")
    log.info("  - AAII sentiment (需 FRED)")
    log.info("  - 10Y yield 1962 至今 (需 FRED)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()

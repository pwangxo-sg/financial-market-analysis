"""
P1 #8: AI 算力 / 半导体 / 软件 热门板块日线
(cron 26322edf978c + 投资日报 "今日核心热点" 强制覆盖)
- 算力芯片: NVDA / AMD / TSM / AVGO / ARM
- AI 软件: PLTR
- 服务器 / 整机: SMCI
- 板块 ETF: SOXX (半导体) / SMH (半导体) / IGV (软件)
- 中概互联网: KWEB
- 数据源: Yahoo Finance (Mac 直连可用)
- 拉每日最新, 入 intel.db
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime

log = get_logger("ai_compute")

# Yahoo Finance tickers
TICKERS = [
    # 算力芯片 (5)
    {"ticker": "NVDA",   "yahoo_ticker": "NVDA",     "code": "NVDA",  "name_zh": "英伟达",         "sector": "AI算力-芯片"},
    {"ticker": "AMD",    "yahoo_ticker": "AMD",      "code": "AMD",   "name_zh": "AMD",            "sector": "AI算力-芯片"},
    {"ticker": "TSM",    "yahoo_ticker": "TSM",      "code": "TSM",   "name_zh": "台积电",         "sector": "AI算力-晶圆代工"},
    {"ticker": "AVGO",   "yahoo_ticker": "AVGO",     "code": "AVGO",  "name_zh": "博通",           "sector": "AI算力-芯片"},
    {"ticker": "ARM",    "yahoo_ticker": "ARM",      "code": "ARM",   "name_zh": "ARM",            "sector": "AI算力-芯片"},
    # AI 软件
    {"ticker": "PLTR",   "yahoo_ticker": "PLTR",     "code": "PLTR",  "name_zh": "Palantir",       "sector": "AI应用"},
    # 服务器 / 整机
    {"ticker": "SMCI",   "yahoo_ticker": "SMCI",     "code": "SMCI",  "name_zh": "超微",           "sector": "AI算力-服务器"},
    # 板块 ETF
    {"ticker": "SOXX",   "yahoo_ticker": "SOXX",     "code": "SOXX",  "name_zh": "iShares 半导体", "sector": "半导体ETF"},
    {"ticker": "SMH",    "yahoo_ticker": "SMH",      "code": "SMH",   "name_zh": "VanEck 半导体",  "sector": "半导体ETF"},
    {"ticker": "IGV",    "yahoo_ticker": "IGV",      "code": "IGV",   "name_zh": "iShares 软件",   "sector": "软件ETF"},
    # 中概互联网
    {"ticker": "KWEB",   "yahoo_ticker": "KWEB",     "code": "KWEB",  "name_zh": "中概互联网",     "sector": "中概互联"},
]


def fetch_quote(t):
    """拉一个 ticker 的当日行情 + 5 日 K 线"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t['yahoo_ticker']}?interval=1d&range=5d"
    r = safe_get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if not r:
        return None
    try:
        d = r.json()
    except Exception as e:
        log.warning(f"  ❌ {t['code']} JSON 解析失败: {e}")
        return None
    chart = d.get("chart", {})
    if not chart.get("result"):
        return None
    res = chart["result"][0]
    meta = res.get("meta", {})
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    cur = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if cur is None or prev is None:
        return None

    chg_amt = cur - prev
    chg_pct = (chg_amt / prev * 100) if prev else 0

    five_day_chg = None
    if len(closes) >= 5 and closes[0] and closes[-1]:
        five_day_chg = (closes[-1] - closes[0]) / closes[0] * 100

    return {
        "code": t["code"],
        "name_zh": t["name_zh"],
        "sector": t["sector"],
        "ticker": t["ticker"],
        "price": round(cur, 2),
        "prev_close": round(prev, 2),
        "chg_amt": round(chg_amt, 2),
        "chg_pct": round(chg_pct, 2),
        "5d_chg_pct": round(five_day_chg, 2) if five_day_chg is not None else None,
        "market_time_bjt": datetime.fromtimestamp(meta.get("regularMarketTime", 0), tz=BJT).strftime("%Y-%m-%d %H:%M"),
    }


def make_intel_items(quotes):
    items = []
    now = datetime.now(BJT).isoformat(timespec="seconds")
    for q in quotes:
        title = f"🔥 {q['sector']} | {q['name_zh']} ({q['code']}) {q['price']} {q['chg_pct']:+.2f}%"
        content_lines = [
            f"板块: {q['sector']}",
            f"标的: {q['name_zh']} ({q['code']})",
            f"现价: {q['price']}",
            f"昨收: {q['prev_close']}",
            f"今日涨跌: {q['chg_pct']:+.2f}%",
            f"5日涨跌: {q.get('5d_chg_pct'):+.2f}%" if q.get("5d_chg_pct") is not None else "5日涨跌: N/A",
            f"行情时间 (BJT): {q['market_time_bjt']}",
        ]
        items.append({
            "title": title,
            "content": "\n".join(content_lines),
            "url": f"https://finance.yahoo.com/quote/{q['ticker']}",
            "author": "Yahoo Finance",
            "published_at": now,
            "tags": ["ai", "compute", "semiconductor", q["code"].lower(), "us", "daily"],
            "severity": 3,
            "extra": q,
        })
    return items


def get_quotes():
    quotes = []
    for t in TICKERS:
        q = fetch_quote(t)
        if q:
            quotes.append(q)
        time.sleep(0.3)
    return quotes


def run():
    log.info("=== AI 算力 / 半导体 / 软件 热门板块 ===")
    quotes = get_quotes()
    if not quotes:
        log.warning("  ❌ 全部失败, 无数据")
        return 0, 0
    items = make_intel_items(quotes)
    saved, dups = save_intel(items, "ai_compute", "commodity")
    for q in quotes:
        marker = "🔥" if abs(q["chg_pct"]) >= 3 else "  "
        log.info(f"  {marker} {q['code']:6s} {q['name_zh']:14s} {q['price']:>9.2f} {q['chg_pct']:+.2f}%")
    log.info(f"=== AI/算力 完成: {saved} new, {dups} dup ===")
    return saved, dups


if __name__ == "__main__":
    run()
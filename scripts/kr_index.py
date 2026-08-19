"""
P1 #7: 韩国指数日线 (补全日报"亚太市场"板块)
- KOSPI 综合指数 ^KS11
- KOSDAQ 创业板 ^KQ11
- 数据源: Yahoo Finance (Mac 直连可用)
- 拉每日最新, 入 intel.db
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime

log = get_logger("kr_index")

# Yahoo Finance tickers
INDICES = [
    {
        "ticker": "^KS11",
        "yahoo_ticker": "%5EKS11",
        "code": "KS11",
        "name_zh": "韩国综合指数 (KOSPI)",
        "name_en": "KOSPI Composite Index",
    },
    {
        "ticker": "^KQ11",
        "yahoo_ticker": "%5EKQ11",
        "code": "KQ11",
        "name_zh": "韩国创业板 (KOSDAQ)",
        "name_en": "KOSDAQ Composite Index",
    },
]


def fetch_index(idx):
    """拉一个指数的当日行情 + 5 日 K 线"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{idx['yahoo_ticker']}?interval=1d&range=5d"
    r = safe_get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if not r:
        return None
    try:
        d = r.json()
    except Exception as e:
        log.warning(f"  ❌ {idx['code']} JSON 解析失败: {e}")
        return None
    chart = d.get("chart", {})
    if not chart.get("result"):
        err = chart.get("error", {})
        log.warning(f"  ❌ {idx['code']} 无数据: {err.get('description', '?')[:80] if err else '?'}")
        return None
    res = chart["result"][0]
    meta = res.get("meta", {})
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    cur = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    day_high = meta.get("regularMarketDayHigh")
    day_low = meta.get("regularMarketDayLow")
    currency = meta.get("currency", "KRW")
    market_time = meta.get("regularMarketTime")

    if cur is None or prev is None:
        log.warning(f"  ❌ {idx['code']} 缺关键字段 cur={cur} prev={prev}")
        return None

    chg_amt = cur - prev
    chg_pct = (chg_amt / prev * 100) if prev else 0

    five_day_chg = None
    if len(closes) >= 5 and closes[0] and closes[-1]:
        five_day_chg = (closes[-1] - closes[0]) / closes[0] * 100

    if market_time:
        mkt_dt = datetime.fromtimestamp(market_time, tz=BJT)
        mkt_str = mkt_dt.strftime("%Y-%m-%d %H:%M")
    else:
        mkt_str = datetime.now(BJT).strftime("%Y-%m-%d %H:%M")

    return {
        "code": idx["code"],
        "name_zh": idx["name_zh"],
        "name_en": idx["name_en"],
        "ticker": idx["ticker"],
        "currency": currency,
        "price": round(cur, 2),
        "prev_close": round(prev, 2),
        "chg_amt": round(chg_amt, 2),
        "chg_pct": round(chg_pct, 2),
        "day_high": round(day_high, 2) if day_high else None,
        "day_low": round(day_low, 2) if day_low else None,
        "5d_chg_pct": round(five_day_chg, 2) if five_day_chg is not None else None,
        "market_time_bjt": mkt_str,
    }


def make_intel_items(quotes):
    """把 quotes 列表转为 save_intel 格式"""
    items = []
    now = datetime.now(BJT).isoformat(timespec="seconds")
    for q in quotes:
        title = f"🇰🇷 {q['name_zh']} ({q['code']}) {q['price']} {q['chg_amt']:+} ({q['chg_pct']:+.2f}%)"
        content_lines = [
            f"指数: {q['name_zh']} ({q['code']})",
            f"现价: {q['price']} {q['currency']}",
            f"昨收: {q['prev_close']}",
            f"涨跌: {q['chg_amt']:+} ({q['chg_pct']:+.2f}%)",
            f"日内高/低: {q.get('day_high')} / {q.get('day_low')}",
            f"5 日涨跌: {q.get('5d_chg_pct'):+.2f}%" if q.get("5d_chg_pct") is not None else "5 日涨跌: N/A",
            f"行情时间 (BJT): {q['market_time_bjt']}",
        ]
        items.append({
            "title": title,
            "content": "\n".join(content_lines),
            "url": f"https://finance.yahoo.com/quote/{q['ticker']}",
            "author": "Yahoo Finance",
            "published_at": now,
            "tags": ["kr", "index", q["code"].lower(), "asia", "daily"],
            "severity": 3,
            "extra": q,
        })
    return items


def get_kr_quotes():
    """直接返回 dict 列表"""
    quotes = []
    for idx in INDICES:
        q = fetch_index(idx)
        if q:
            quotes.append(q)
        time.sleep(0.5)
    return quotes


def run():
    log.info("=== KR 指数 ===")
    quotes = get_kr_quotes()
    if not quotes:
        log.warning("  ❌ 全部失败, 无数据")
        return 0, 0
    items = make_intel_items(quotes)
    saved, dups = save_intel(items, "kr_index", "commodity")
    for q in quotes:
        log.info(f"  ✅ {q['code']:8s} {q['price']:>10} {q['chg_pct']:+.2f}%")
    log.info(f"=== KR 完成: {saved} new, {dups} dup ===")
    return saved, dups


if __name__ == "__main__":
    run()
"""
P0-6: EIA 能源库存 + 黄金 ETF (GLD) 持仓
- EIA 周度原油/天然气库存 (影响油价)
- GLD 持仓 (SPDR Gold Trust, 黄金市场情绪)
- CFTC COT 持仓 (如果可获取)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
import json
import re
from datetime import datetime, timedelta

log = get_logger("eia_commodity")

# EIA 公开 API (无 key 也能用部分端点)
EIA_PETROLEUM = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/?frequency=weekly&data[0]=value&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=5&api_key="

# SPDR Gold Trust (GLD) 持仓数据
# 公开来源: Yahoo Finance / ETF.com
# Yahoo Finance GLD historical holdings 实际难, 用价格代替
GLD_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GLD?interval=1d&range=5d"

# CFTC COT 报告 (公开页) - Legacy + Financial Futures
CFTC_COT_URLS = [
    "https://www.cftc.gov/dea/newcot/deafut.txt",     # Futures-Only (Legacy)
    "https://www.cftc.gov/dea/newcot/FinFutWk.txt",  # Financial Futures (TFF)
]


def fetch_eia_petroleum():
    """EIA 原油库存 (Yahoo 兜底)"""
    # 没有 EIA API key 时用 Yahoo Finance 兜底
    # 用 CL=F (WTI Crude Futures) 作为代理
    items = []
    for symbol, label in [("CL=F", "WTI原油"), ("NG=F", "天然气")]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if not resp:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        result = data.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        ts = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if not ts or not closes:
            continue
        latest_close = closes[-1]
        prev_close = closes[-2] if len(closes) > 1 else latest_close
        change_pct = (latest_close - prev_close) / prev_close * 100 if prev_close else 0
        pub_iso = datetime.fromtimestamp(ts[-1], BJT).isoformat(timespec="seconds")
        items.append({
            "title": f"{label} ${latest_close:.2f} ({change_pct:+.2f}%)",
            "content": f"近期价格: {closes}",
            "url": f"https://finance.yahoo.com/quote/{symbol}",
            "author": "Yahoo Finance",
            "published_at": pub_iso,
            "tags": ["commodity", "energy", label],
            "severity": 3,
            "extra": {
                "symbol": symbol,
                "label": label,
                "latest": latest_close,
                "prev": prev_close,
                "change_pct": round(change_pct, 3),
            },
        })
    return items


def fetch_gld_holdings():
    """SPDR Gold Trust 价格 + 估算持仓"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GLD?interval=1d&range=10d"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    if not resp:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    result = data.get("chart", {}).get("result", [{}])[0]
    ts = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    volumes = result.get("indicators", {}).get("quote", [{}])[0].get("volume", [])
    if not ts or not closes:
        return []
    items = []
    for i in range(len(ts)):
        if i == 0:
            continue
        c = closes[i]
        p = closes[i-1]
        chg = (c - p) / p * 100 if (p is not None and c is not None and p) else 0
        v = volumes[i] if i < len(volumes) else 0
        pub_iso = datetime.fromtimestamp(ts[i], BJT).isoformat(timespec="seconds")
        items.append({
            "title": f"GLD ${c:.2f} ({chg:+.2f}%) Vol={v}",
            "content": f"SPDR Gold Trust daily price/volume",
            "url": "https://finance.yahoo.com/quote/GLD",
            "author": "Yahoo Finance",
            "published_at": pub_iso,
            "tags": ["commodity", "gold", "etf_holding", "gld"],
            "severity": 2,
            "extra": {
                "symbol": "GLD",
                "close": c,
                "prev_close": p,
                "change_pct": round(chg, 3),
                "volume": v,
            },
        })
    return items


def fetch_cftc_cot():
    """CFTC COT 报告 (commitments of traders)"""
    # CSV: 1行 = header, 之后每行 = 一个市场 + 1周数据
    # 列: Market, Date, ...
    items = []
    for url in CFTC_COT_URLS:
        resp = safe_get(url, timeout=30)
        if not resp:
            continue
        text = resp.text
        lines = text.splitlines()
        if not lines:
            continue
        # 简单解析: 第一行是 header
        header = lines[0] if lines else ""
        url_kind = "futures_legacy" if "deafut" in url else "financial_futures"
        # 找几个重要市场 (gold, oil, bonds, sp500, bitcoin)
        keywords = ["GOLD", "CRUDE", "NAT GAS", "TREASURY", "BITCOIN", "S&P", "NASDAQ", "DOLLAR", "EURO", "CORN", "WHEAT", "SOYBEAN", "COPPER"]
        for line in lines[1:200]:  # 头 200 行
            upper = line.upper()
            matched = [k for k in keywords if k in upper]
            if not matched:
                continue
            items.append({
                "title": f"📊 COT {','.join(matched)} [{url_kind}]",
                "content": line[:1000],
                "url": url,
                "author": "CFTC",
                "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
                "tags": ["cot", "cftc", "positioning", "commodity"] + [m.lower() for m in matched],
                "severity": 3,
                "extra": {
                    "url_kind": url_kind,
                    "matched_markets": matched,
                },
            })
    return items[:20]  # 限制条目


def run():
    log.info("=== EIA / GLD / COT 抓取 ===")
    total = 0; dups = 0
    try:
        items = fetch_eia_petroleum()
        s, d = save_intel(items, "eia_oil_proxy", "commodity")
        total += s; dups += d
        log.info(f"  ✅ 能源价格: +{s} new")
    except Exception as e:
        log.warning(f"  ❌ 能源: {e}")
    try:
        items = fetch_gld_holdings()
        s, d = save_intel(items, "gld_holdings", "commodity")
        total += s; dups += d
        log.info(f"  ✅ GLD: +{s} new")
    except Exception as e:
        log.warning(f"  ❌ GLD: {e}")
    try:
        items = fetch_cftc_cot()
        s, d = save_intel(items, "cftc_cot", "commodity")
        total += s; dups += d
        log.info(f"  ✅ CFTC COT: +{s} new")
    except Exception as e:
        log.warning(f"  ❌ CFTC: {e}")
    log.info(f"=== 商品完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

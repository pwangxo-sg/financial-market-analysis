"""
P1 #6: 加密 5 大币种日价 (补全日报"市场全貌"板块)
- BTC / ETH / SOL / BNB / XRP
- 数据源: CoinGecko simple price API (免费, 无需 auth, 无需 VPN)
- 拉每日价格 + 24h 变化, 入 intel.db
"""
import sys
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime

log = get_logger("crypto")

# 5 币配置
COINS = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum"},
    {"id": "solana", "symbol": "SOL", "name": "Solana"},
    {"id": "binancecoin", "symbol": "BNB", "name": "BNB"},
    {"id": "ripple", "symbol": "XRP", "name": "XRP"},
]

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def fetch_crypto_quotes():
    """一次拉 5 币"""
    ids = ",".join(c["id"] for c in COINS)
    url = f"{COINGECKO_URL}?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
    r = safe_get(url, timeout=15)
    if not r:
        return []
    try:
        d = r.json()
    except Exception as e:
        log.warning(f"  ❌ JSON 解析失败: {e}")
        return []
    quotes = []
    for c in COINS:
        v = d.get(c["id"])
        if not v or "usd" not in v:
            log.warning(f"  ❌ {c['symbol']} 无数据")
            continue
        price = v["usd"]
        chg_24h = v.get("usd_24h_change", 0)
        mcap = v.get("usd_market_cap", 0)
        quotes.append({
            "symbol": c["symbol"],
            "name": c["name"],
            "id": c["id"],
            "price_usd": round(price, 4) if price < 100 else round(price, 2),
            "chg_24h_pct": round(chg_24h, 2),
            "market_cap_usd": mcap,
        })
    return quotes


def make_intel_items(quotes):
    """转 save_intel 格式"""
    items = []
    now = datetime.now(BJT).isoformat(timespec="seconds")
    for q in quotes:
        title = f"🪙 {q['symbol']} (${q['price_usd']:,.2f}) 24h {q['chg_24h_pct']:+.2f}%"
        content_lines = [
            f"币种: {q['name']} ({q['symbol']})",
            f"现价 USD: ${q['price_usd']:,.2f}",
            f"24h 涨跌: {q['chg_24h_pct']:+.2f}%",
            f"市值 USD: ${q['market_cap_usd']:,.0f}" if q['market_cap_usd'] else "市值 USD: N/A",
        ]
        items.append({
            "title": title,
            "content": "\n".join(content_lines),
            "url": f"https://www.coingecko.com/en/coins/{q['id']}",
            "author": "CoinGecko",
            "published_at": now,
            "tags": ["crypto", q["symbol"].lower(), "daily", "usd"],
            "severity": 2,
            "extra": q,
        })
    return items


def get_crypto_quotes():
    """直接返回 dict 列表 (给 evaluate_today 等用)"""
    return fetch_crypto_quotes()


def run():
    log.info("=== Crypto 5 币 ===")
    quotes = fetch_crypto_quotes()
    if not quotes:
        log.warning("  ❌ 全部失败, 无数据")
        return 0, 0
    items = make_intel_items(quotes)
    saved, dups = save_intel(items, "crypto", "commodity")
    for q in quotes:
        log.info(f"  ✅ {q['symbol']:5s} ${q['price_usd']:>12,.2f} {q['chg_24h_pct']:+.2f}%")
    log.info(f"=== Crypto 完成: {saved} new, {dups} dup ===")
    return saved, dups


if __name__ == "__main__":
    run()

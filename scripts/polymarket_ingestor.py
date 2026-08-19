"""
P1-1: Polymarket 押注赔率
- 实时群体预测: 押注赔率 = "市场认为 X 事件发生的概率"
- 例如: "美联储 7 月降息 75%" 这种事件, Polymarket 赔率 = 75%
- 比新闻快得多, 是真正的"群体智慧"
- 公开 API 无需 auth
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get
from datetime import datetime
from urllib.parse import urlencode

log = get_logger("polymarket")

API_BASE = "https://gamma-api.polymarket.com"

# 关注的关键词 (筛选金融/经济/地缘相关)
FINANCE_KEYWORDS = [
    "fed", "fomc", "rate", "interest", "inflation", "cpi", "pce", "recession",
    "gdp", "unemployment", "jobs", "payroll", "powell", "treasury",
    "btc", "bitcoin", "eth", "ethereum", "crypto", "stablecoin",
    "trump", "biden", "tariff", "trade war", "sanction",
    "russia", "ukraine", "china", "taiwan", "iran", "israel", "middle east",
    "oil", "opec", "wti", "brent", "barrel", "crude",
    "recession", "depression", "bank", "jpmorgan", "goldman", "blackrock",
    "gold", "silver", "platinum",
    "election", "vote", "president", "congress", "senate",
    "nvidia", "ai", "openai", "anthropic", "tesla", "apple", "microsoft",
]


def fetch_active_markets(limit=100, offset=0):
    """拉活跃市场"""
    url = f"{API_BASE}/markets?active=true&closed=false&limit={limit}&offset={offset}"
    resp = safe_get(url, timeout=20)
    if not resp:
        return []
    try:
        return resp.json()
    except Exception as e:
        log.warning(f"json parse failed: {e}")
        return []


def fetch_by_tag(tag_slug, limit=50):
    """按 tag 拉市场"""
    url = f"{API_BASE}/markets?active=true&closed=false&tag_slug={tag_slug}&limit={limit}"
    resp = safe_get(url, timeout=20)
    if not resp:
        return []
    try:
        return resp.json()
    except Exception as e:
        return []


def is_finance_related(market):
    """判断是否金融/经济/地缘相关"""
    text = (
        market.get("question", "") + " " +
        market.get("description", "") + " " +
        market.get("groupItemTitle", "")
    ).lower()
    for kw in FINANCE_KEYWORDS:
        if kw in text:
            return True, kw
    return False, None


def parse_outcome_prices(prices_str):
    """解析 outcomePrices 字符串 → list of float"""
    try:
        prices = json.loads(prices_str)
        return [float(p) for p in prices]
    except Exception:
        return []


def market_to_intel(market, matched_kw):
    """把 Polymarket 市场转成 intel 格式"""
    question = market.get("question", "")
    if not question:
        return None
    prices = parse_outcome_prices(market.get("outcomePrices", "[]"))
    outcomes = json.loads(market.get("outcomes", "[]")) if market.get("outcomes") else []
    if not prices or not outcomes:
        return None
    # 主概率 (Yes)
    yes_price = prices[0] if prices else 0
    # 交易量
    vol_24h = float(market.get("volume24hr", 0) or 0)
    vol_total = float(market.get("volumeNum", 0) or 0)
    liquidity = float(market.get("liquidityNum", 0) or 0)
    # 截止日期
    end_date = market.get("endDate", "")[:10]
    # 价格摘要
    price_summary = " | ".join([f"{o}: {p:.1%}" for o, p in zip(outcomes, prices)])
    content = (
        f"赔率: {price_summary} | "
        f"截止: {end_date} | "
        f"24h量: ${vol_24h:,.0f} | "
        f"总量: ${vol_total:,.0f} | "
        f"流动性: ${liquidity:,.0f} | "
        f"关键词: {matched_kw}"
    )
    # 严重度 = 流动性 + 概率偏离 0.5
    deviation = abs(yes_price - 0.5)
    severity = min(5, max(1, int(2 + deviation * 6 + (liquidity / 50000))))
    return {
        "title": f"📊 [{yes_price*100:.0f}%] {question[:100]}",
        "content": content,
        "url": f"https://polymarket.com/event/{market.get('slug', '')}" if market.get("slug") else "",
        "author": "Polymarket",
        "published_at": market.get("updatedAt", "") or datetime.now().isoformat(timespec="seconds"),
        "tags": ["polymarket", "prediction_market", "sentiment"] + ([f"kw:{matched_kw}"] if matched_kw else []),
        "severity": severity,
        "extra": {
            "market_id": market.get("id"),
            "yes_price": yes_price,
            "all_prices": prices,
            "outcomes": outcomes,
            "volume_24h": vol_24h,
            "volume_total": vol_total,
            "liquidity": liquidity,
            "end_date": end_date,
            "matched_keyword": matched_kw,
        },
    }


def run():
    log.info("=" * 60)
    log.info("📊 Polymarket 押注赔率")
    log.info("=" * 60)
    total = 0
    dups = 0
    all_items = []
    seen_ids = set()

    # 1. 通用拉取 (前 200 个活跃市场)
    log.info("\n--- 拉取活跃市场 (200 个) ---")
    for offset in [0, 100]:
        markets = fetch_active_markets(limit=100, offset=offset)
        log.info(f"  收到 {len(markets)} 个市场")
        for m in markets:
            mid = m.get("id")
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            related, kw = is_finance_related(m)
            if not related:
                continue
            intel = market_to_intel(m, kw)
            if intel:
                all_items.append(intel)
        time.sleep(0.5)  # rate limit

    # 2. 按 tag 拉 (经济/金融/加密/政治)
    log.info("\n--- 按 tag 拉 (economics/crypto/politics/world) ---")
    for tag in ["economics", "crypto", "world", "politics", "finance"]:
        try:
            markets = fetch_by_tag(tag, limit=30)
            log.info(f"  tag={tag}: {len(markets)} 个市场")
            for m in markets:
                mid = m.get("id")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                related, kw = is_finance_related(m)
                if not related:
                    continue
                intel = market_to_intel(m, kw or tag)
                if intel:
                    all_items.append(intel)
        except Exception as e:
            log.warning(f"  tag={tag} failed: {e}")

    log.info(f"\n--- 共筛出 {len(all_items)} 个金融相关市场 ---")
    if all_items:
        saved, dups = save_intel(all_items, "polymarket", "sentiment")
        total += saved
        log.info(f"  ✅ polymarket: +{total} new, {dups} dup")

    log.info(f"=== Polymarket 完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    import time
    run()

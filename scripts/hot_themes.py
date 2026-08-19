"""
P1 #9: 全球热点投资方向扫描
(每次 cron 26322edf978c 必入 "今日核心热点" 板块)

数据源:
1. Yahoo Finance RSS (主) — https://finance.yahoo.com/news/rssindex
2. Investing.com Stock Market News (辅) — https://www.investing.com/rss/news_25.rss

输出: intel.db 标记 source='hot_themes', tags=['ai','semiconductor','energy','healthcare',...]

Cron 报告用法:
sqlite3 ~/.dsh/market_intel/db/intel.db "SELECT title, content FROM intel WHERE source='hot_themes' AND published_at >= datetime('now', '-1 day') ORDER BY published_at DESC LIMIT 15"
"""
import sys
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime

log = get_logger("hot_themes")

# 主题标签识别关键词
SECTOR_KEYWORDS = {
    "ai": ["AI", "artificial intelligence", "GPT", "LLM", "ChatGPT", "machine learning", "neural", "agentic"],
    "semiconductor": ["chip", "semiconductor", "Nvidia", "AMD", "TSMC", "TSM", "Intel", "ARM", "HBM", "foundry", "wafer", "SMH", "SOXX", "ASML", "SK Hynix", "Micron", "Marvell", "Broadcom", "AVGO", "Qualcomm"],
    "energy": ["oil", "crude", "OPEC", "natural gas", "Brent", "WTI", "energy", "petroleum", "refiner"],
    "gold": ["gold", "bullion", "GLD", "goldman", "precious metal", "silver"],
    "biotech": ["FDA", "pharma", "biotech", "drug", "clinical trial", "vaccine", "Eli Lilly", "LLY", "Pfizer", "Merck", "AbbVie", "Regeneron"],
    "ev": ["EV", "electric vehicle", "Tesla", "BYD", "battery", "NIO", "Li Auto", "XPeng", "充电桩"],
    "finance": ["Fed", "rate", "yield", "Treasury", "bond", "FOMC", "Powell", "rate cut", "rate hike", "CPI", "inflation", "jobs", "unemployment"],
    "geopolitics": ["Russia", "China", "Iran", "Israel", "Ukraine", "Taiwan", "tariff", "sanction", "war", "Trump"],
    "crypto": ["Bitcoin", "BTC", "Ethereum", "ETH", "crypto", "blockchain"],
    "china": ["China", "Beijing", "Shanghai", "Hong Kong", "HSI", "Alibaba", "BABA", "Tencent", "Baidu", "PDD"],
}

FEEDS = [
    {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
        "limit": 20,
    },
    {
        "name": "Investing.com",
        "url": "https://www.investing.com/rss/news_25.rss",
        "limit": 10,
    },
]


def classify(title):
    """根据标题给文章打 sector tag"""
    tags = []
    title_lower = title.lower()
    for sector, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                tags.append(sector)
                break
    return tags or ["other"]


def parse_rss(content, source_name, limit):
    """解析 RSS XML 返回 item 列表"""
    items = []
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub = item.findtext("pubDate", "")
            desc = item.findtext("description", "")
            # strip HTML from description
            desc = re.sub(r"<[^>]+>", "", desc).strip()
            if not title:
                continue
            items.append({
                "title": title.strip(),
                "link": link.strip(),
                "pubDate": pub,
                "description": desc[:300],
                "source_name": source_name,
            })
    except ET.ParseError as e:
        log.warning(f"  ❌ {source_name} RSS parse error: {e}")
    return items


def make_intel_items(articles):
    """转 save_intel 格式"""
    now = datetime.now(BJT).isoformat(timespec="seconds")
    items = []
    for a in articles:
        tags = classify(a["title"])
        # 强 sector 标签
        if "semiconductor" in tags and "ai" in tags:
            severity = 4  # 半导体+AI = 双重高优
        elif "ai" in tags or "semiconductor" in tags:
            severity = 3
        else:
            severity = 2
        title_with_tag = f"📰 [{','.join(tags[:3])}] {a['title'][:100]}"
        content = f"来源: {a['source_name']}\n发布时间: {a['pubDate']}\n\n{a['description']}"
        items.append({
            "title": title_with_tag,
            "content": content,
            "url": a["link"],
            "author": a["source_name"],
            "published_at": now,
            "tags": tags + ["hot", "news"],
            "severity": severity,
            "extra": {"sectors": tags, "raw_title": a["title"]},
        })
    return items


def run():
    log.info("=== 全球热点投资方向扫描 ===")
    all_articles = []
    for feed in FEEDS:
        r = safe_get(feed["url"], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if not r:
            log.warning(f"  ❌ {feed['name']} 抓取失败")
            continue
        items = parse_rss(r.text, feed["name"], feed["limit"])
        log.info(f"  ✅ {feed['name']}: {len(items)} 条")
        all_articles.extend(items)
        time.sleep(0.5)
    if not all_articles:
        log.warning("  ❌ 全部失败, 无数据")
        return 0, 0
    items = make_intel_items(all_articles)
    saved, dups = save_intel(items, "hot_themes", "news")
    # 按 sector 统计
    from collections import Counter
    sector_count = Counter()
    for a in all_articles:
        for t in classify(a["title"]):
            sector_count[t] += 1
    log.info(f"=== 热点扫描完成: {saved} new, {dups} dup ===")
    log.info("  板块热度 TOP:")
    for sector, n in sector_count.most_common(5):
        log.info(f"    {sector}: {n} 条")
    return saved, dups


if __name__ == "__main__":
    run()
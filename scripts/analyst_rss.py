"""
P1-2: 知名财经分析师 / 机构博客 RSS
- 替代 X/Twitter (X 需要 OAuth, 改用博客 RSS)
- Substack + 个人博客 + 机构博客
- 关注: 宏观/政策/地缘/市场策略
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get
import feedparser
from datetime import datetime

log = get_logger("analyst_rss")

# 知名财经分析师 / 机构博客 RSS
ANALYST_FEEDS = {
    # 机构 blog
    "GS_thoughts": ("https://www.goldmansachs.com/insights/feed", "research", ["goldman", "macro"]),
    "BlackRock": ("https://www.blackrock.com/corporate/newsroom/insights/rss", "research", ["blackrock", "institutional"]),
    "Bridgewater": ("https://www.bridgewater.com/research/rss", "research", ["bridgewater"]),

    # 知名分析师 (Substack RSS)
    "Ray_Dalio": ("https://raysviews.substack.com/feed", "research", ["macro", "principles"]),
    "Cathie_Wood_ARK": ("https://ark-invest.com/articles/feed", "research", ["disruptive_innovation"]),
    "Michael_Burry": ("https://www.casetrade.com/feed", "research", ["value", "deep_value"]),
    "Stanley_Druckenmiller": ("https://duffandphelps.substack.com/feed", "research", ["macro"]),
    "Howard_Marks": ("https://www.oaktreecapital.com/insights/", "research", ["value", "cycles"]),

    # 财经媒体 blog
    "Bloomberg_Opinion": ("https://www.bloomberg.com/opinion/feed", "research", ["opinion"]),
    "FT_Lex": ("https://www.ft.com/lex?format=rss", "research", ["lex_column"]),
    "WSJ_Opinion": ("https://www.wsj.com/xml/rss/3.xml", "research", ["opinion"]),

    # 政策/研究
    "Brookings": ("https://www.brookings.edu/feed/", "research", ["policy"]),
    "Peterson_IIE": ("https://www.piie.com/rss/all.xml", "research", ["policy", "trade"]),
}


def run():
    log.info("=" * 60)
    log.info("📑 知名财经分析师 / 机构博客 RSS")
    log.info("=" * 60)
    total = 0
    dups = 0

    for name, (url, source_type, tags) in ANALYST_FEEDS.items():
        try:
            resp = safe_get(url, timeout=15)
            if not resp:
                log.info(f"  ⚠️ {name}: 无响应")
                continue
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                log.info(f"  ⚠️ {name}: 0 条目")
                continue
            items = []
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                content = entry.get("summary", "") or entry.get("description", "")
                link = entry.get("link", "")
                author = entry.get("author", "") or entry.get("dc_creator", "")
                pub = entry.get("published_parsed")
                if pub:
                    pub_iso = datetime(*pub[:6]).isoformat(timespec="seconds")
                else:
                    pub_iso = datetime.now().isoformat(timespec="seconds")
                items.append({
                    "title": f"[{name}] {title[:90]}",
                    "content": content[:2000],
                    "url": link,
                    "author": author or name,
                    "published_at": pub_iso,
                    "tags": ["analyst", "rss"] + tags,
                    "severity": 3,
                })
            if items:
                s, d = save_intel(items, f"analyst_{name.lower()}", "research")
                total += s
                dups += d
                log.info(f"  ✅ {name}: +{s} new, {d} dup")
        except Exception as e:
            log.warning(f"  ❌ {name}: {e}")

    log.info(f"=== Analyst RSS 完成: {total} new, {dups} dup ===")
    return total, dups


if __name__ == "__main__":
    run()

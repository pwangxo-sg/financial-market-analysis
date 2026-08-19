"""
P1-2 v2: 知名财经分析师 / 媒体 RSS (修正版)
- 用可靠的 RSS 源 (跳过 Substack 死镜像)
- 替代 X/Twitter 大 V
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get
import feedparser
from datetime import datetime, timezone

log = get_logger("analyst_rss_v2")

# 可靠 RSS 源 (2026-06 实际测试可用)
FEEDS = {
    # 财经媒体 (有 RSS)
    "CNBC_Top": ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "news", ["cnbc"]),
    "CNBC_Economy": ("https://www.cnbc.com/id/20910258/device/rss/rss.html", "news", ["cnbc", "economy"]),
    "FT_Markets": ("https://www.ft.com/markets?format=rss", "news", ["ft", "markets"]),
    "FT_World": ("https://www.ft.com/world?format=rss", "news", ["ft", "world"]),
    "FT_Lex": ("https://www.ft.com/lex?format=rss", "research", ["ft", "lex_column"]),
    "BBC_Business": ("https://feeds.bbci.co.uk/news/business/rss.xml", "news", ["bbc"]),
    "BBC_World": ("https://feeds.bbci.co.uk/news/world/rss.xml", "news", ["bbc", "world"]),

    # 政策/研究机构 (博客 RSS)
    "IMF_News": ("https://www.imf.org/en/news/news?format=rss", "research", ["imf", "policy"]),
    "WorldBank": ("https://www.worldbank.org/en/news/all?format=rss", "research", ["worldbank", "policy"]),
    "BIS_Speeches": ("https://www.bis.org/cbspeeches/rss.htm", "research", ["bis", "central_bank"]),
    "ECB_Speeches": ("https://www.ecb.europa.eu/rss/speeches.html", "research", ["ecb", "central_bank"]),

    # 财经 blog
    "Calculated_Risk": ("https://calculatedrisk.substack.com/feed", "research", ["macro", "us_economy"]),
    "Mises_Institute": ("https://mises.org/feed", "research", ["austrian_economics"]),
    "Project_Syndicate": ("https://www.project-syndicate.org/rss", "research", ["opinion", "macro"]),
    "Brookings": ("https://www.brookings.edu/feed/", "research", ["policy"]),
}


def run():
    log.info("=" * 60)
    log.info("📑 P1-2 v2: 财经媒体 / 机构博客 RSS (修正版)")
    log.info("=" * 60)
    total = 0
    dups = 0
    for name, (url, source_type, tags) in FEEDS.items():
        try:
            resp = safe_get(url, timeout=12)
            if not resp:
                log.info(f"  ⚠️ {name}: 无响应")
                continue
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                log.info(f"  ⚠️ {name}: 0 条目")
                continue
            items = []
            for entry in feed.entries[:8]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                content = entry.get("summary", "") or entry.get("description", "")
                link = entry.get("link", "")
                author = entry.get("author", "") or entry.get("dc_creator", "")
                pub = entry.get("published_parsed")
                if pub:
                    try:
                        pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                        pub_iso = pub_dt.isoformat(timespec="seconds")
                    except (TypeError, ValueError):
                        pub_iso = datetime.now().isoformat(timespec="seconds")
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
                s, d = save_intel(items, f"analyst_{name.lower()}", source_type)
                total += s
                dups += d
                log.info(f"  ✅ {name}: +{s} new, {d} dup")
        except Exception as e:
            log.warning(f"  ❌ {name}: {e}")
    log.info(f"=== Analyst RSS v2 完成: {total} new, {dups} dup ===")
    return total, dups


if __name__ == "__main__":
    run()

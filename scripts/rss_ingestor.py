"""
P0-1: RSS 抓取 — 财经新闻 + 监管 + 机构
覆盖：
  新闻: Reuters/Bloomberg/AP/FT/CNBC/财新/华尔街见闻
  监管: Fed/SEC/ECB/美财政部/BIS/中国央行
  机构: BlackRock/Goldman/JPMorgan/Morgan Stanley/Bridgewater
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
import feedparser
from datetime import datetime

log = get_logger("rss_ingestor")

# RSS 源清单
FEEDS = {
    # ============== 财经新闻 ==============
    "reuters_business": ("https://feeds.reuters.com/reuters/businessNews", "news", ["global", "macro"]),
    "reuters_markets":  ("https://feeds.reuters.com/reuters/financialmarkets", "news", ["markets"]),
    "reuters_world":    ("https://feeds.reuters.com/Reuters/worldNews", "news", ["global", "geopol"]),
    "bloomberg_markets":("https://feeds.bloomberg.com/markets/news.rss", "news", ["markets"]),
    "bloomberg_econ":   ("https://feeds.bloomberg.com/economics/news.rss", "news", ["macro"]),
    "ap_business":      ("https://feeds.apnews.com/rss/apf-business", "news", ["business"]),
    "ft_world":         ("https://www.ft.com/world?format=rss", "news", ["global"]),
    "ft_markets":       ("https://www.ft.com/markets?format=rss", "news", ["markets"]),
    "cnbc_top":         ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "news", ["markets"]),
    "cnbc_economy":     ("https://www.cnbc.com/id/20910258/device/rss/rss.html", "news", ["macro"]),

    # ============== 监管 ==============
    "fed_press":        ("https://www.federalreserve.gov/feeds/press_all.xml", "regulator", ["fed", "us"]),
    "fed_speeches":     ("https://www.federalreserve.gov/feeds/speeches.xml", "regulator", ["fed", "us"]),
    "sec_press":        ("https://www.sec.gov/news/pressreleases.rss", "regulator", ["sec", "us"]),
    "ecb_press":        ("https://www.ecb.europa.eu/rss/press.html", "regulator", ["ecb", "eu"]),
    "us_treasury":      ("https://home.treasury.gov/news/press-releases/feed", "regulator", ["us_treasury"]),
    "bis_news":         ("https://www.bis.org/doclist/bis_fsi.rss", "regulator", ["bis", "global"]),

    # ============== 投行/资管 ==============
    "blackrock":        ("https://www.blackrock.com/corporate/newsroom/insights/rss", "research", ["blackrock", "institutional"]),
    "goldman_insights": ("https://www.goldmansachs.com/insights/rss", "research", ["goldman", "institutional"]),
    "jpm_insights":     ("https://www.jpmorgan.com/insights/rss", "research", ["jpm", "institutional"]),
    "ms_insights":      ("https://www.morganstanley.com/ideas/rss", "research", ["morgan_stanley", "institutional"]),
}


def parse_published(entry):
    """统一解析发布时间"""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=BJT).isoformat(timespec="seconds")
        except Exception:
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime(*entry.updated_parsed[:6], tzinfo=BJT).isoformat(timespec="seconds")
        except Exception:
            pass
    return ""


def fetch_one(source_key, url, source_type, tags):
    """抓取单个 RSS"""
    resp = safe_get(url, timeout=12)
    if not resp:
        return 0, 0
    try:
        feed = feedparser.parse(resp.content)
    except Exception as e:
        log.warning(f"parse {source_key} failed: {e}")
        return 0, 0

    items = []
    for entry in feed.entries[:20]:  # 每个源最新 20 条
        title = entry.get("title", "").strip()
        if not title:
            continue
        content = ""
        if entry.get("summary"):
            content = entry.summary
        elif entry.get("description"):
            content = entry.description
        link = entry.get("link", "")
        author = entry.get("author", "") or entry.get("dc_creator", "")
        published = parse_published(entry)
        items.append({
            "title": title,
            "content": content[:3000],
            "url": link,
            "author": author,
            "published_at": published,
            "tags": tags,
            "severity": 3 if source_type == "regulator" else 2,
        })
    saved, dups = save_intel(items, source_key, source_type)
    return saved, dups


def run():
    log.info(f"=== RSS ingestor: {len(FEEDS)} feeds ===")
    total_saved = 0
    total_dups = 0
    ok_count = 0
    fail_count = 0
    for key, (url, source_type, tags) in FEEDS.items():
        try:
            saved, dups = fetch_one(key, url, source_type, tags)
            total_saved += saved
            total_dups += dups
            if saved > 0:
                ok_count += 1
                log.info(f"  ✅ {key}: +{saved} new, {dups} dup")
            else:
                log.info(f"  ⏭️  {key}: 0 new, {dups} dup")
        except Exception as e:
            fail_count += 1
            log.warning(f"  ❌ {key}: {e}")
    log.info(f"=== Done: {ok_count} ok, {fail_count} fail, {total_saved} new, {total_dups} dup ===")
    return total_saved, total_dups


if __name__ == "__main__":
    run()

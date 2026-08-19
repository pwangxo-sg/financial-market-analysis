"""
P0-5: Reddit 情绪监控
- r/wallstreetbets, r/stocks, r/investing, r/options, r/China_Investments
- 抓取热门帖 + 情绪标签（看涨/看跌/中性）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
import re
from datetime import datetime

log = get_logger("reddit_sentiment")

# 关注标的关键词
WATCH_TICKERS = {
    "012752": ["nasdaq", "qqq", "ndx", "tech", "ai"],
    "022653": ["gold", "gld", "黄金"],
    "025857": ["grid", "electric", "utilities"],
    "020274": ["chem", "chemical", "化工"],
    "宏观": ["fed", "rate", "inflation", "recession", "fomc", "cpi", "pce"],
}

# 情绪词 (英文)
BULL_WORDS = ["buy", "calls", "moon", "long", "bullish", "rally", "breakout", "🚀", "💎", "🔥", "ATH", "green", "up", "rise", "higher", "beat", "strong"]
BEAR_WORDS = ["sell", "puts", "crash", "short", "bearish", "dump", "tank", "drill", "red", "down", "fall", "drop", "miss", "weak", "recession", "fear"]


def score_sentiment(text):
    """简单情绪打分 (-1 到 +1)"""
    if not text:
        return 0
    text_l = text.lower()
    bull = sum(1 for w in BULL_WORDS if w.lower() in text_l)
    bear = sum(1 for w in BEAR_WORDS if w.lower() in text_l)
    total = bull + bear
    if total == 0:
        return 0
    return (bull - bear) / total


def fetch_subreddit(subreddit, sort="hot", limit=25, time_filter="day"):
    """抓取单 subreddit 热门 - 用 RSS (反爬更宽松)"""
    if sort == "top":
        url = f"https://www.reddit.com/r/{subreddit}/top/.rss?t={time_filter}&limit={limit}"
    elif sort == "new":
        url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={limit}"
    else:
        url = f"https://www.reddit.com/r/{subreddit}/hot/.rss?limit={limit}"

    resp = safe_get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; MarketIntelBot/1.0)"},
        timeout=15,
    )
    if not resp:
        return []
    try:
        import feedparser
        feed = feedparser.parse(resp.content)
    except Exception as e:
        log.warning(f"reddit {subreddit} rss fail: {e}")
        return []

    items = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        # RSS 不带 selftext, content 是 summary
        from _lib import BJT
        full_text = (title + " " + (entry.get("summary", "") or "")).lower()
        matched = []
        for code, kws in WATCH_TICKERS.items():
            for kw in kws:
                if kw.lower() in full_text:
                    matched.append(code)
                    break
        # num_comments RSS 不一定有, 用 0
        num_comments = 0
        score = 0
        upvote_ratio = 0.5
        link = entry.get("link", "")
        url = link
        author = entry.get("author", "").replace("/u/", "") if entry.get("author") else ""
        # 解析发布时间
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            from datetime import datetime as _dt
            pub_iso = _dt(*published_parsed[:6], tzinfo=BJT).isoformat(timespec="seconds")
        else:
            pub_iso = datetime.now(BJT).isoformat(timespec="seconds")
        # 情绪打分
        content = entry.get("summary", "") or entry.get("description", "")
        sentiment = score_sentiment(title + " " + content[:500])
        # 严重度 (无具体分数, 默认 2)
        heat = 2
        tags = ["reddit", f"sub:{subreddit}"]
        if matched:
            tags.append("watched")
            tags.extend([f"code:{c}" for c in matched])
        title_full = title
        if matched:
            title_full = f"📊 [{','.join(matched)}] {title}"
        items.append({
            "title": title_full,
            "content": content[:1500],
            "url": url,
            "author": f"u/{author}" if author else "",
            "published_at": pub_iso,
            "tags": tags,
            "severity": heat,
            "extra": {
                "subreddit": subreddit,
                "matched_tickers": matched,
                "sentiment": round(sentiment, 3),
                "source": "rss",
            },
        })
    return items


def run():
    log.info("=== Reddit 情绪抓取 ===")
    total = 0
    dups = 0
    subs = [
        ("wallstreetbets", "hot"),
        ("stocks", "top"),
        ("investing", "top"),
        ("options", "hot"),
    ]
    for sub, sort in subs:
        try:
            items = fetch_subreddit(sub, sort=sort, limit=15)
            s, d = save_intel(items, f"reddit_{sub}", "sentiment")
            total += s; dups += d
            log.info(f"  ✅ r/{sub}: +{s} new (扫描 {len(items)})")
        except Exception as e:
            log.warning(f"  ❌ r/{sub}: {e}")
    log.info(f"=== Reddit 完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

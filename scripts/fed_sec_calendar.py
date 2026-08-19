"""
P0-3: 美联储 + SEC EDGAR
- FOMC 日历
- 美联储讲话日程
- SEC 8-K 重大事项 (公开 API: EDGAR full-text search)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
import json
from datetime import datetime, timedelta

log = get_logger("fed_sec_calendar")

# FOMC 下次会议 (动态从美联储网页取)
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# SEC EDGAR 8-K (实时重要事件)
SEC_8K_API = "https://efts.sec.gov/LATEST/search-index?q=%22formType%3D8-K%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K"


def fetch_fomc_calendar():
    """抓取 FOMC 日历"""
    resp = safe_get(FOMC_CALENDAR_URL, timeout=15)
    if not resp:
        return []
    text = resp.text
    items = []
    # 简单文本匹配 (美联储 HTML 有结构)
    import re
    # 抓取日期模式
    date_patterns = re.findall(
        r"(\w+ \d{1,2}(?:-\d{1,2})?,?\s*\d{4})",
        text
    )
    # 关联"Statement"/"Press Conference"/"SEP"
    for m in re.finditer(
        r"<div[^>]*class=\"fomc-meeting[^\"]*\"[^>]*>(.*?)</div>",
        text, re.DOTALL | re.IGNORECASE,
    ):
        chunk = m.group(1)
        date_m = re.search(r"(\w+ \d{1,2}(?:-\d{1,2})?,?\s*\d{4})", chunk)
        if not date_m:
            continue
        text_clean = re.sub(r"<[^>]+>", " ", chunk)
        text_clean = re.sub(r"\s+", " ", text_clean).strip()
        if not text_clean:
            continue
        items.append({
            "title": f"FOMC Meeting: {date_m.group(1)}",
            "content": text_clean[:500],
            "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "author": "Federal Reserve",
            "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "tags": ["fed", "fomc", "calendar", "us"],
            "severity": 4,
        })
    if not items:
        # fallback: 把整页简化
        items.append({
            "title": "FOMC Calendar (full text)",
            "content": "见美联储官方日历: " + FOMC_CALENDAR_URL,
            "url": FOMC_CALENDAR_URL,
            "author": "Federal Reserve",
            "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "tags": ["fed", "fomc", "calendar", "us"],
            "severity": 3,
        })
    return items[:10]


def fetch_sec_recent_8k(days=1, limit=30):
    """SEC 近期 8-K"""
    end = datetime.now()
    start = end - timedelta(days=days)
    url = (
        "https://efts.sec.gov/LATEST/search-index"
        f"?q=%22formType%3D8-K%22"
        f"&dateRange=custom"
        f"&startdt={start.strftime('%Y-%m-%d')}"
        f"&enddt={end.strftime('%Y-%m-%d')}"
        f"&forms=8-K"
    )
    resp = safe_get(url, headers={"User-Agent": "MarketIntel research@example.com"}, timeout=15)
    if not resp:
        return []

    try:
        data = resp.json()
    except Exception:
        return []

    items = []
    hits = data.get("hits", {}).get("hits", [])
    for h in hits[:limit]:
        src = h.get("_source", {})
        display = src.get("display_names", [""])[0] if src.get("display_names") else ""
        form = src.get("form", "8-K")
        period = src.get("file_date", "")
        cik = h.get("_id", "").split(":")[0] if ":" in h.get("_id", "") else ""
        adsh = src.get("adsh", "")
        url_doc = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=40" if cik else ""

        # 解析正文
        title = f"8-K {display} ({form})"
        content_parts = [f"CIK: {cik}", f"File: {adsh}"]
        items.append({
            "title": title,
            "content": " | ".join(content_parts),
            "url": url_doc,
            "author": "SEC EDGAR",
            "published_at": period,
            "tags": ["sec", "8k", "us", "filing"],
            "severity": 3,
            "extra": {
                "cik": cik,
                "adsh": adsh,
                "display_name": display,
                "form": form,
            },
        })
    return items


def run():
    log.info("=== Fed + SEC 抓取 ===")
    total = 0
    dups = 0

    # FOMC 日历
    try:
        items = fetch_fomc_calendar()
        s, d = save_intel(items, "fed_calendar", "regulator")
        total += s; dups += d
        log.info(f"  ✅ FOMC: +{s} new, {d} dup")
    except Exception as e:
        log.warning(f"  ❌ FOMC: {e}")

    # SEC 8-K
    try:
        items = fetch_sec_recent_8k(days=1, limit=30)
        s, d = save_intel(items, "sec_8k", "regulator")
        total += s; dups += d
        log.info(f"  ✅ SEC 8-K: +{s} new, {d} dup")
    except Exception as e:
        log.warning(f"  ❌ SEC 8-K: {e}")

    log.info(f"=== Fed/SEC 完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

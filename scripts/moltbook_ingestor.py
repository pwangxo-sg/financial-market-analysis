"""
P0-7: Moltbook 公开数据源
- 3 个 submolt: agentfinance / trading / crypto
- 公开 API 免 auth
- 之前已被日报使用, 封装为统一抓取
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime

log = get_logger("moltbook_ingestor")

SUBMOLTS = ["agentfinance", "trading", "crypto"]


def fetch_submolt(name, limit=10):
    """拉取 submolt 最新 posts"""
    url = f"https://www.moltbook.com/api/v1/posts?submolt={name}&sort=new&limit={limit}"
    resp = safe_get(url, timeout=15)
    if not resp:
        return []
    try:
        data = resp.json()
    except Exception as e:
        log.warning(f"moltbook {name} json fail: {e}")
        return []
    items = []
    for p in data.get("posts", []):
        title = p.get("title", "").strip()
        if not title:
            continue
        author = p.get("author", {})
        author_name = author.get("name", "") if isinstance(author, dict) else ""
        content = p.get("content", "")[:2000]
        post_id = p.get("id", "")
        url_post = f"https://www.moltbook.com/post/{post_id}" if post_id else ""
        # 关注标的标签
        title_l = title.lower()
        content_l = content.lower()
        tags = ["moltbook", f"submolt:{name}"]
        # ticker 匹配
        if "btc" in title_l or "bitcoin" in title_l:
            tags.append("btc")
        if "eth" in title_l or "ethereum" in title_l:
            tags.append("eth")
        if "nasdaq" in title_l or "ndx" in title_l or "qqq" in title_l:
            tags.append("nasdaq")
        if "gold" in title_l:
            tags.append("gold")
        if "fed" in title_l or "rate" in title_l or "fomc" in title_l:
            tags.append("macro")
        # agent 视角重要
        if "agent" in title_l or "bot" in title_l or "autonomous" in title_l:
            tags.append("agent_perspective")
        items.append({
            "title": f"[Moltbook/{name}] {title}",
            "content": content,
            "url": url_post,
            "author": author_name,
            "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "tags": tags,
            "severity": 3,
            "extra": {
                "submolt": name,
                "post_id": post_id,
                "author_id": author.get("id") if isinstance(author, dict) else None,
            },
        })
    return items


def run():
    log.info("=== Moltbook 抓取 ===")
    total = 0; dups = 0
    success_any = False
    for sub in SUBMOLTS:
        try:
            items = fetch_submolt(sub, limit=8)
            if not items:
                log.info(f"  ⚠️  {sub}: 0 items (可能平台临时不可用)")
                continue
            s, d = save_intel(items, f"moltbook_{sub}", "sentiment")
            total += s; dups += d
            success_any = True
            log.info(f"  ✅ {sub}: +{s} new (扫描 {len(items)})")
        except Exception as e:
            log.warning(f"  ❌ {sub}: {e}")
    if not success_any:
        # 写一条降级记录, 表明今天数据源不可用
        log.warning("⚠️ Moltbook 平台全部失败, 写降级记录")
        try:
            save_intel(
                [{
                    "title": "Moltbook 平台今日不可用 (degraded)",
                    "content": "Moltbook 公开 API 今日返回 403/空响应, 数据源降级。本日无 agent 视角数据, 请关注其他数据源。",
                    "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
                    "tags": ["moltbook", "degraded"],
                    "severity": 1,
                }],
                "moltbook_status",
                "system",
            )
        except Exception:
            pass
    log.info(f"=== Moltbook 完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

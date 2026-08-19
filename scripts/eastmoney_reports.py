"""
P0-2: Eastmoney 研报中心
- 抓取中金/中信/华泰/招商/海通 等头部券商研报
- 高盛中文版/摩根士丹利中文版
- 行业研究 + 公司研究 + 宏观研究
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
import json
import re
from datetime import datetime

log = get_logger("eastmoney_reports")

# 研报 API（公开）
REPORTS_API = "https://data.eastmoney.com/report/data.js"

# 头部机构 ID 列表 (Eastmoney 内部 ID)
INSTITUTIONS = {
    "92": "中金公司",
    "85": "中信证券",
    "78": "华泰证券",
    "87": "招商证券",
    "79": "海通证券",
    "97": "国泰君安",
    "60": "国信证券",
    "88": "广发证券",
    "94": "申万宏源",
    "65": "兴业证券",
    "52": "高盛",
    "56": "摩根士丹利",
    "54": "摩根大通",
    "75": "瑞银",
    "118": "美银美林",
}


def fetch_reports(institution_id, days=30, limit=20):
    """抓取单个机构的研报"""
    end = datetime.now()
    from datetime import timedelta
    start = end - timedelta(days=days)
    url = (
        f"https://reportapi.eastmoney.com/report/list"
        f"?cb=jQuery&industryCode=*&pageSize={limit}&industry=*"
        f"&rating=*&ratingChange=*&beginTime={start.strftime('%Y-%m-%d')}"
        f"&endTime={end.strftime('%Y-%m-%d')}&pageNo=1"
        f"&fields=&qType=0&orgCode={institution_id}"
        f"&_=1"
    )
    resp = safe_get(url, headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
    if not resp:
        return []

    text = resp.text
    # 解 jQuery 包裹
    m = re.search(r"jQuery\((.*)\)", text, re.DOTALL)
    if not m:
        m = re.search(r"^\s*(\[.*\])\s*$", text, re.DOTALL)
        if not m:
            log.warning(f"无法解析 {institution_id} 响应")
            return []
        raw = m.group(1)
    else:
        raw = m.group(1)
        # jQuery wrap 是 json string, 需要 unescape
        raw = raw.strip().strip("'").strip('"')

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试解 unicode escape
        try:
            raw_unescaped = raw.encode().decode("unicode_escape")
            data = json.loads(raw_unescaped)
        except Exception as e:
            log.warning(f"json parse {institution_id} failed: {e}")
            return []

    items = []
    inst_name = INSTITUTIONS.get(institution_id, institution_id)
    # data 可能是 dict {data: [...]} 或 list
    if isinstance(data, dict):
        report_list = data.get("data", [])
    elif isinstance(data, list):
        report_list = data
    else:
        report_list = []
    for r in report_list[:limit]:
        title = r.get("title", "").strip()
        if not title:
            continue
        stock = r.get("stockName", "") or r.get("secCode", "")
        industry = r.get("industryName", "")
        rating = r.get("rtRating", "") or r.get("rating", "")
        pub_date = r.get("publishDate", "")
        if pub_date:
            try:
                dt = datetime.strptime(pub_date, "%Y-%m-%dT%H:%M:%S")
                pub_iso = dt.replace(tzinfo=BJT).isoformat(timespec="seconds")
            except Exception:
                pub_iso = pub_date
        else:
            pub_iso = ""

        content_parts = []
        if industry:
            content_parts.append(f"行业: {industry}")
        if stock:
            content_parts.append(f"标的: {stock}")
        if rating:
            content_parts.append(f"评级: {rating}")
        info_code = r.get("infoCode", "")

        items.append({
            "title": f"[{inst_name}] {title}",
            "content": " | ".join(content_parts),
            "url": f"https://data.eastmoney.com/report/info/{info_code}.html" if info_code else "",
            "author": inst_name,
            "published_at": pub_iso,
            "tags": ["research", "institutional", "china"] + ([stock] if stock else []),
            "severity": 3,
            "extra": {
                "institution_id": institution_id,
                "stock": stock,
                "industry": industry,
                "rating": rating,
                "info_code": info_code,
            },
        })
    return items


def run():
    log.info(f"=== 研报抓取: {len(INSTITUTIONS)} 机构 ===")
    total_saved = 0
    total_dups = 0
    for inst_id, inst_name in INSTITUTIONS.items():
        try:
            items = fetch_reports(inst_id)
            if not items:
                continue
            saved, dups = save_intel(items, f"eastmoney_report_{inst_id}", "research")
            total_saved += saved
            total_dups += dups
            if saved > 0:
                log.info(f"  ✅ {inst_name}({inst_id}): +{saved} new")
        except Exception as e:
            log.warning(f"  ❌ {inst_name}({inst_id}): {e}")
    log.info(f"=== 研报完成: {total_saved} new, {total_dups} dup ===")
    return total_saved, total_dups


if __name__ == "__main__":
    run()

"""
P1-4: NBS 中国 PMI 抓取 (简化版)
- 每月初 NBS 发布, 我们抓最新 PMI 新闻稿
- HTML 用 <span> 拆词, 解析复杂, 但已经验证 PMI 数字
- 直接入库: 制造业 / 非制造业 / 综合 PMI
"""
import sys
import json
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get
from datetime import datetime
import csv

log = get_logger("nbs_pmi_v2")
NBS_BASE = "https://www.stats.gov.cn"


def extract_pmi(html):
    """从 PMI 新闻稿 HTML 提取关键数字 (强制 UTF-8)"""
    if isinstance(html, bytes):
        clean = re.sub(r'<[^>]+>', ' ', html.decode('utf-8', errors='ignore'))
    else:
        clean = re.sub(r'<[^>]+>', ' ', html)
    clean = re.sub(r'\s+', ' ', clean)
    pmi = {}
    m = re.search(r'制造业.{0,30}PMI.{0,30}为\s*(\d+\.\d+)\s*%', clean)
    if m:
        pmi['mfg_pmi'] = float(m.group(1))
    # 非制造业 (必须 > 45 才合理)
    m = re.search(r'非制造业.{0,30}(?:商务活动|PMI).{0,30}为\s*(\d+\.\d+)\s*%', clean)
    if m and 45 <= float(m.group(1)) <= 60:
        pmi['non_mfg_pmi'] = float(m.group(1))
    # 综合 (50 附近)
    m = re.search(r'综合.{0,15}(?:PMI|产出).{0,20}为\s*(\d+\.\d+)\s*%', clean)
    if m and 45 <= float(m.group(1)) <= 60:
        pmi['composite_pmi'] = float(m.group(1))
    for k, name in [('large_enterprise_pmi', '大型企业'), ('mid_enterprise_pmi', '中型企业'), ('small_enterprise_pmi', '小型企业')]:
        m = re.search(name + r'.{0,20}PMI.{0,10}为\s*(\d+\.\d+)\s*%', clean)
        if m and 40 <= float(m.group(1)) <= 60:
            pmi[k] = float(m.group(1))
    m = re.search(r'<meta name="PubDate" content="([^"]+)"', html if isinstance(html, str) else html.decode('utf-8', errors='ignore'))
    pub_date = m.group(1).strip()[:10] if m else ""
    return pmi, pub_date


def fetch_pmi_html():
    """找最新 PMI 新闻稿, 返回 (url, content_bytes)"""
    resp = safe_get(f"{NBS_BASE}/sj/zxfb/", timeout=15)
    if not resp:
        return None, None
    text = resp.text
    urls = list(dict.fromkeys(re.findall(r'href="(\./\d{6}/t\d+_\d+\.html)"', text)))
    for url_rel in urls[:8]:
        url = f"{NBS_BASE}/sj/zxfb/" + url_rel[2:]
        r = safe_get(url, timeout=10)
        if r and ('PMI' in r.text or '采购经理' in r.text or 'å·ä¸' in r.text):
            return url, r.content  # 返回 bytes 强制 utf-8
    return None, None


def save_pmi_history(pmi, pub_date):
    """追加到 CSV 历史"""
    OUTPUT_DIR = _lib.ROOT / "backtest"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "nbs_pmi_history.csv"
    existing_dates = set()
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            for line in f.read().strip().splitlines()[1:]:
                existing_dates.add(line.split(",")[0])
    if pub_date in existing_dates:
        return False
    header = "date,mfg_pmi,non_mfg_pmi,composite_pmi,large_enterprise_pmi,mid_enterprise_pmi,small_enterprise_pmi"
    keys = ["mfg_pmi", "non_mfg_pmi", "composite_pmi", "large_enterprise_pmi", "mid_enterprise_pmi", "small_enterprise_pmi"]
    row = pub_date + "," + ",".join(str(pmi.get(k, "")) for k in keys)
    with open(csv_path, "a" if csv_path.exists() else "w", encoding="utf-8") as f:
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            f.write(header + "\n")
        f.write(row + "\n")
    return True


def pmi_to_intel(pmi, pub_date, url):
    if not pmi:
        return None
    mfg = pmi.get('mfg_pmi', 50)
    severity = 4 if mfg < 50 else (3 if mfg < 50.5 else 2)
    title = f"🇨🇳 NBS 中国 PMI {pub_date[:7]}: 制造业 {mfg}%"
    if pmi.get('non_mfg_pmi'):
        title += f" | 非制造业 {pmi['non_mfg_pmi']}%"
    if pmi.get('composite_pmi'):
        title += f" | 综合 {pmi['composite_pmi']}%"
    content_parts = []
    for k, v in pmi.items():
        label = {
            'mfg_pmi': '制造业 PMI',
            'non_mfg_pmi': '非制造业 PMI',
            'composite_pmi': '综合 PMI 产出',
            'large_enterprise_pmi': '大型企业 PMI',
            'mid_enterprise_pmi': '中型企业 PMI',
            'small_enterprise_pmi': '小型企业 PMI',
        }.get(k, k)
        content_parts.append(f"{label}: {v}%")
    return {
        "title": title,
        "content": " | ".join(content_parts),
        "url": url,
        "author": "国家统计局",
        "published_at": f"{pub_date}T00:00:00+00:00" if pub_date else datetime.now().isoformat(timespec="seconds"),
        "tags": ["nbs", "pmi", "china", "macro", "official"],
        "severity": severity,
        "extra": {
            "country": "china",
            "source_org": "NBS",
            "pmi_data": pmi,
            "pub_date": pub_date,
        },
    }


def run():
    log.info("=" * 60)
    log.info("🇨🇳 NBS 中国 PMI 抓取 (v2)")
    log.info("=" * 60)
    url, html = fetch_pmi_html()
    if not url:
        log.error("❌ 未找到 PMI 新闻稿")
        return 0, 0
    log.info(f"  找到: {url}")
    pmi, pub_date = extract_pmi(html)
    if not pmi:
        log.error("❌ 解析失败")
        return 0, 0
    log.info(f"  发布: {pub_date}")
    log.info(f"  PMI: {pmi}")
    # 保存历史
    if save_pmi_history(pmi, pub_date):
        log.info(f"  💾 历史 CSV 已更新")
    else:
        log.info(f"  ℹ️ 历史已有 {pub_date}")
    # 入库
    intel = pmi_to_intel(pmi, pub_date, url)
    if intel:
        s, d = save_intel([intel], "nbs_pmi", "regulator")
        log.info(f"  ✅ nbs_pmi: +{s} new, {d} dup")
        return s, d
    return 0, 0


if __name__ == "__main__":
    run()

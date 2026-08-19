"""
P1-4: NBS 中国 PMI 实时抓取
- 每月初 NBS 在 https://www.stats.gov.cn/sj/zxfb/ 发布 PMI 数据
- 自动抓最新 PMI 新闻稿, 解析制造业/非制造业 PMI 数字
- 给 GRID_PMI_01 / CHEM_CNPMI_01 规则用
"""
import sys
import json
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get
from datetime import datetime, timedelta

log = get_logger("nbs_pmi")

# NBS 每月初发布上月 PMI
NBS_ZXFB_INDEX = "https://www.stats.gov.cn/sj/zxfb/"
NBS_BASE = "https://www.stats.gov.cn"


def get_latest_pmi_url():
    """找最新 PMI 新闻稿 URL"""
    resp = safe_get(NBS_ZXFB_INDEX, timeout=15)
    if not resp:
        return None
    text = resp.text
    # 找最近 2 个月发布的新闻稿 (PMI 通常 5/31 5月底发, 5月初 4月)
    urls = re.findall(r'href="(\./\d{6}/t\d+_\d+\.html)"', text)
    # 去重
    urls = list(dict.fromkeys(urls))
    if not urls:
        return None
    # 试前 10 个找 PMI 关键词
    for url_rel in urls[:10]:
        url = NBS_BASE + "/sj/zxfb/" + url_rel[2:]  # 去掉 "./"
        try:
            r = safe_get(url, timeout=10)
            if not r:
                continue
            if 'PMI' in r.text or '采购经理' in r.text or '制造业' in r.text[:5000]:
                return url
        except Exception:
            continue
    return None


def parse_pmi_content(url):
    """解析 PMI 新闻稿内容"""
    resp = safe_get(url, timeout=15)
    if not resp:
        return None
    text = resp.text
    # 标题
    title_m = re.search(r'<title>(.*?)</title>', text, re.DOTALL)
    title = title_m.group(1).strip() if title_m else ""
    # 发布日期
    date_m = re.search(r'<meta name="PubDate" content="([^"]+)"', text)
    pub_date = date_m.group(1).strip() if date_m else ""
    # 关键: 先 strip HTML 标签 (因为 PMI 关键词被 <span> 拆开)
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    clean_text = re.sub(r'\s+', ' ', clean_text)
    # 提取 PMI 关键数字
    pmi_data = {}
    # 制造业 PMI 主数字
    mfg_m = re.search(r'制造业.*?PMI.*?为\s*(\d+\.\d+)\s*%', clean_text)
    if not mfg_m:
        mfg_m = re.search(r'制造业.*?采购经理指数.*?(\d+\.\d+)\s*%', clean_text)
    if mfg_m:
        pmi_data['mfg_pmi'] = float(mfg_m.group(1))
    # 非制造业 PMI
    non_mfg_m = re.search(r'非制造业.*?(?:商务活动|PMI).*?(\d+\.\d+)\s*%', clean_text)
    if non_mfg_m:
        pmi_data['non_mfg_pmi'] = float(non_mfg_m.group(1))
    # 综合 PMI 产出
    comp_m = re.search(r'综合.*?(?:PMI|产出)指数.*?(\d+\.\d+)\s*%', clean_text)
    if comp_m:
        pmi_data['composite_pmi'] = float(comp_m.group(1))
    # 大型企业 PMI
    large_m = re.search(r'大型企业.*?PMI.*?为\s*(\d+\.\d+)\s*%', clean_text)
    if large_m:
        pmi_data['large_enterprise_pmi'] = float(large_m.group(1))
    # 中型企业 PMI
    mid_m = re.search(r'中型企业.*?PMI.*?为\s*(\d+\.\d+)\s*%', clean_text)
    if mid_m:
        pmi_data['mid_enterprise_pmi'] = float(mid_m.group(1))
    # 小型企业 PMI
    small_m = re.search(r'小型企业.*?PMI.*?为\s*(\d+\.\d+)\s*%', clean_text)
    if small_m:
        pmi_data['small_enterprise_pmi'] = float(small_m.group(1))
    # 建筑业 PMI
    constr_m = re.search(r'建筑业.*?(?:商务活动|PMI).*?(\d+\.\d+)\s*%', clean_text)
    if constr_m:
        pmi_data['construction_pmi'] = float(constr_m.group(1))
    # 服务业 PMI
    serv_m = re.search(r'服务业.*?(?:商务活动|PMI).*?(\d+\.\d+)\s*%', clean_text)
    if serv_m:
        pmi_data['services_pmi'] = float(serv_m.group(1))
    return {
        "url": url,
        "title": title[:200],
        "pub_date": pub_date,
        "pmi_data": pmi_data,
    }


def save_pmi_history(parsed):
    """保存 PMI 历史数据到 CSV (用于回测)"""
    if not parsed or not parsed.get("pmi_data"):
        return
    OUTPUT_DIR = _lib.ROOT / "backtest"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "nbs_pmi_history.csv"
    # 读已有
    existing = []
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            existing = f.read().strip().splitlines()
    # 新行
    date_str = parsed["pub_date"][:10] if parsed["pub_date"] else datetime.now().strftime("%Y-%m-%d")
    new_row = f"{date_str}," + ",".join(str(parsed["pmi_data"].get(k, "")) for k in ["mfg_pmi", "non_mfg_pmi", "composite_pmi", "construction_pmi", "services_pmi"])
    # 检查是否重复
    if not existing or existing[-1].split(",")[0] != date_str:
        # 加 header 如果是新的
        if not existing:
            header = "date,mfg_pmi,non_mfg_pmi,composite_pmi,construction_pmi,services_pmi"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(header + "\n" + new_row + "\n")
        else:
            with open(csv_path, "a", encoding="utf-8") as f:
                f.write(new_row + "\n")
        log.info(f"  💾 PMI 历史已更新: {csv_path}")
    else:
        log.info(f"  ℹ️ PMI {date_str} 已在历史中, 跳过")


def pmi_to_intel(parsed):
    """转 intel 格式"""
    if not parsed or not parsed.get("pmi_data"):
        return None
    pmi = parsed["pmi_data"]
    # 严重度: PMI < 50 = 经济收缩, 高
    mfg = pmi.get('mfg_pmi', 50)
    severity = 4 if mfg < 50 else (3 if mfg < 50.5 else 2)
    title_parts = [f"PMI {mfg}%"]
    if pmi.get('non_mfg_pmi'):
        title_parts.append(f"非制造业 {pmi['non_mfg_pmi']}%")
    if pmi.get('composite_pmi'):
        title_parts.append(f"综合 {pmi['composite_pmi']}%")
    title = f"🇨🇳 NBS 中国 PMI {parsed['pub_date'][:7]}: " + " | ".join(title_parts)
    # 内容
    content_parts = [f"发布: {parsed['pub_date']}"]
    for k, v in pmi.items():
        content_parts.append(f"{k}: {v}%")
    content = " | ".join(content_parts)
    return {
        "title": title,
        "content": content[:2000],
        "url": parsed["url"],
        "author": "国家统计局",
        "published_at": parsed["pub_date"] or datetime.now().isoformat(timespec="seconds"),
        "tags": ["nbs", "pmi", "china", "macro", "official"],
        "severity": severity,
        "extra": {
            "country": "china",
            "source_org": "NBS",
            "pmi_data": pmi,
            "pub_date": parsed["pub_date"],
        },
    }


def run():
    log.info("=" * 60)
    log.info("🇨🇳 NBS 中国 PMI 抓取")
    log.info("=" * 60)
    # 找最新 PMI 新闻稿
    url = get_latest_pmi_url()
    if not url:
        log.error("❌ 未找到 PMI 新闻稿")
        return 0, 0
    log.info(f"  找到: {url}")
    # 解析
    parsed = parse_pmi_content(url)
    if not parsed or not parsed.get("pmi_data"):
        log.error("❌ 解析失败")
        return 0, 0
    pmi = parsed["pmi_data"]
    log.info(f"  标题: {parsed['title']}")
    log.info(f"  发布: {parsed['pub_date']}")
    log.info(f"  PMI 数据: {pmi}")
    # 保存历史
    save_pmi_history(parsed)
    # 入库
    intel = pmi_to_intel(parsed)
    if intel:
        s, d = save_intel([intel], "nbs_pmi", "regulator")
        log.info(f"  ✅ nbs_pmi: +{s} new, {d} dup")
        log.info(f"=== NBS PMI 完成: {s} new ===")
        return s, d
    return 0, 0


if __name__ == "__main__":
    run()

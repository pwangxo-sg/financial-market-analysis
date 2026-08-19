"""
P1-4: FRED 公开经济数据
- PMI / CPI / 失业率 / GDP 等核心宏观指标
- 用 FRED 公开 CSV 端点
- 给规则引擎用 (GRID_PMI_01, CHEM_CNPMI_01 等需要)
"""
import sys
import json
import csv
import io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, ROOT
from datetime import datetime

log = get_logger("fred_indicators")
OUTPUT_DIR = ROOT / "backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# FRED 公开 CSV 端点 (无需 API key)
# 格式: https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES}
FRED_SERIES = {
    # 美国 ISM PMI
    "MANEMPICNSA": {"name": "ISM Manufacturing PMI", "country": "us", "frequency": "monthly", "category": "pmi"},
    "NMFBAI": {"name": "ISM Non-Manufacturing PMI (Business Activity)", "country": "us", "frequency": "monthly", "category": "pmi"},
    # CPI
    "CPIAUCSL": {"name": "CPI (All Urban Consumers)", "country": "us", "frequency": "monthly", "category": "inflation"},
    "CPILFESL": {"name": "Core CPI (Less Food & Energy)", "country": "us", "frequency": "monthly", "category": "inflation"},
    # 就业
    "UNRATE": {"name": "Unemployment Rate", "country": "us", "frequency": "monthly", "category": "employment"},
    "PAYEMS": {"name": "Non-Farm Payrolls", "country": "us", "frequency": "monthly", "category": "employment"},
    # 利率
    "FEDFUNDS": {"name": "Effective Federal Funds Rate", "country": "us", "frequency": "monthly", "category": "rates"},
    "DGS10": {"name": "10-Year Treasury Constant Maturity", "country": "us", "frequency": "daily", "category": "rates"},
    "DGS2": {"name": "2-Year Treasury Constant Maturity", "country": "us", "frequency": "daily", "category": "rates"},
    # 通胀预期
    "T10YIE": {"name": "10-Year Breakeven Inflation Rate", "country": "us", "frequency": "daily", "category": "inflation_expectation"},
    # 美元
    "DTWEXBGS": {"name": "Trade Weighted U.S. Dollar Index (Broad)", "country": "us", "frequency": "daily", "category": "fx"},
    # 油价 (WTI)
    "DCOILWTICO": {"name": "WTI Crude Oil Price", "country": "us", "frequency": "daily", "category": "commodity"},
}


def fetch_fred_csv(series_id):
    """FRED 公开 CSV"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = safe_get(url, timeout=20)
    if not resp:
        return None
    return resp.text


def parse_fred_csv(text, series_id, meta):
    """解析 FRED CSV, 返回最新 12 行 + 保存全量"""
    if not text:
        return None
    # 保存全量
    csv_path = OUTPUT_DIR / f"fred_{series_id.lower()}.csv"
    csv_path.write_text(text, encoding="utf-8")
    # 解析最新
    try:
        lines = text.strip().splitlines()
        if len(lines) < 2:
            return None
        # 第一行 header: DATE, SERIES_ID
        # 找最新非空值
        latest = None
        for line in reversed(lines[1:]):
            parts = line.split(",")
            if len(parts) < 2:
                continue
            date, val = parts[0].strip(), parts[1].strip()
            if val and val != "." and val != "":
                try:
                    float(val)
                    latest = (date, float(val))
                    break
                except ValueError:
                    continue
        if not latest:
            return None
        # 历史数据点
        history = []
        for line in lines[1:][-12:]:  # 最近 12 期
            parts = line.split(",")
            if len(parts) < 2:
                continue
            date, val = parts[0].strip(), parts[1].strip()
            if val and val != "." and val != "":
                try:
                    history.append({"date": date, "value": float(val)})
                except ValueError:
                    continue
        return {
            "series_id": series_id,
            "name": meta["name"],
            "country": meta["country"],
            "category": meta["category"],
            "frequency": meta["frequency"],
            "latest": latest,
            "history": history,
        }
    except Exception as e:
        log.warning(f"parse {series_id} failed: {e}")
        return None


def data_to_intel(parsed):
    """转 intel 格式"""
    if not parsed:
        return None
    date, val = parsed["latest"]
    hist_summary = ", ".join([f"{h['date']}: {h['value']}" for h in parsed["history"][-6:]])
    return {
        "title": f"📈 {parsed['name']} ({parsed['country'].upper()}) {date}: {val}",
        "content": (
            f"最新: {val} | "
            f"频率: {parsed['frequency']} | "
            f"类别: {parsed['category']} | "
            f"历史: {hist_summary}"
        ),
        "url": f"https://fred.stlouisfed.org/series/{parsed['series_id']}",
        "author": "FRED",
        "published_at": f"{date}T00:00:00+00:00",
        "tags": ["fred", "macro", parsed["category"], parsed["country"]],
        "severity": 4 if parsed["category"] in ("pmi", "rates") else 2,
        "extra": {
            "series_id": parsed["series_id"],
            "country": parsed["country"],
            "category": parsed["category"],
            "frequency": parsed["frequency"],
            "latest_date": date,
            "latest_value": val,
        },
    }


def run():
    log.info("=" * 60)
    log.info("📈 FRED 公开经济数据 (12 个核心指标)")
    log.info("=" * 60)
    total = 0
    dups = 0

    # 检测 HTML 反爬: 如果返回 <html 而非 CSV, 跳过
    for sid, meta in FRED_SERIES.items():
        try:
            text = fetch_fred_csv(sid)
            # 检查是否是 HTML 反爬
            if text and ("<html" in text[:100] or "<body" in text[:200] or "<script" in text[:300]):
                log.info(f"  ⚠️ {sid} ({meta['name'][:25]}): HTML 反爬, 跳过")
                continue
            parsed = parse_fred_csv(text, sid, meta)
            if not parsed:
                log.info(f"  ⚠️ {sid}: 无数据")
                continue
            intel = data_to_intel(parsed)
            if intel:
                s, d = save_intel([intel], f"fred_{sid.lower()}", "regulator")
                total += s
                dups += d
                log.info(f"  ✅ {sid} ({meta['name'][:30]}): {parsed['latest'][0]} = {parsed['latest'][1]}")
        except Exception as e:
            log.warning(f"  ❌ {sid}: {e}")

    log.info(f"=== FRED 完成: {total} new, {dups} dup ===")
    return total, dups


if __name__ == "__main__":
    run()

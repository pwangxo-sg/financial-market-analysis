"""
P0-8: Treasury Daily Yield Curve
- 名义利率: 1Mo-30Yr (CSV)
- 实际利率 (TIPS): 5Y/10Y/30Y
- 拉每日最新, 存到 DB + 给规则引擎用
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime, timedelta
import csv
import io

log = get_logger("treasury_ingestor")

# Treasury Daily Yield Curve (名义)
TREASURY_NOMINAL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/all/{yyyymm}?"
    "type=daily_treasury_yield_curve"
    "&field_tdr_date_value_month={yyyymm}&page&_format=csv"
)

# Treasury Daily Real Yield Curve (TIPS, 实际利率)
TREASURY_REAL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/all/{yyyymm}?"
    "type=daily_treasury_real_yield_curve"
    "&field_tdr_date_value_month={yyyymm}&page&_format=csv"
)


def fetch_treasury(curve_type="nominal"):
    """拉 Treasury 数据"""
    if curve_type == "nominal":
        url = TREASURY_NOMINAL_URL
    else:
        url = TREASURY_REAL_URL

    yyyymm = datetime.now().strftime("%Y%m")
    url = url.format(yyyymm=yyyymm)

    resp = safe_get(url, timeout=20)
    if not resp:
        return []
    text = resp.text
    # 解析 CSV
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    # 最新一天
    latest = rows[0]
    log.info(f"  Treasury {curve_type} 最新: {latest.get('Date')}")

    items = []
    date_str = latest.get("Date", "")
    # 命名映射
    if curve_type == "nominal":
        # 标准列: Date,"1 Mo","1.5 Month",..."30 Yr"
        items.append({
            "title": f"🇺🇸 Treasury Nominal Yield Curve {date_str}",
            "content": json.dumps(latest, ensure_ascii=False)[:2000],
            "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates",
            "author": "U.S. Treasury",
            "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "tags": ["treasury", "yield_curve", "us", "nominal", "daily"],
            "severity": 3,
            "extra": {"curve_type": "nominal", "raw": latest},
        })
    else:
        # TIPS 实际利率
        items.append({
            "title": f"🇺🇸 Treasury TIPS Real Yield Curve {date_str}",
            "content": json.dumps(latest, ensure_ascii=False)[:2000],
            "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/real-yield-curve",
            "author": "U.S. Treasury",
            "published_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "tags": ["treasury", "yield_curve", "us", "real", "tips", "daily"],
            "severity": 3,
            "extra": {"curve_type": "real", "raw": latest},
        })
    return items


def get_treasury_latest(curve_type="nominal"):
    """直接返回最新 Treasury dict (给 evaluate_today 用)"""
    items = fetch_treasury(curve_type)
    if not items:
        return None
    return items[0].get("extra", {}).get("raw", {})


def run():
    import json
    log.info("=== Treasury Yield Curve ===")
    total = 0; dups = 0
    for ctype in ["nominal", "real"]:
        try:
            items = fetch_treasury(ctype)
            s, d = save_intel(items, f"treasury_{ctype}", "regulator")
            total += s; dups += d
            log.info(f"  ✅ {ctype}: +{s} new")
        except Exception as e:
            log.warning(f"  ❌ {ctype}: {e}")
    log.info(f"=== Treasury 完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

"""
P0-9: Treasury 历史 CSV 拉取 (5-10 年)
- 用于回测: 每天利率水平 → 规则触发 → 后续 N 天标的表现
- 输出: parquet/csv, 可直接 pandas 读
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime, timedelta
import csv
import io

log = get_logger("treasury_history")
OUTPUT_DIR = ROOT / "backtest" / "treasury_history"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_month(yyyymm, curve_type="nominal"):
    """拉单月 Treasury 数据"""
    base = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"
    if curve_type == "real":
        url = f"{base}/all/{yyyymm}?type=daily_treasury_real_yield_curve&field_tdr_date_value_month={yyyymm}&page&_format=csv"
    else:
        url = f"{base}/all/{yyyymm}?type=daily_treasury_yield_curve&field_tdr_date_value_month={yyyymm}&page&_format=csv"

    import requests
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception as e:
        log.warning(f"fetch {yyyymm} {curve_type} failed: {e}")
        return []

    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader)


def fetch_history(years=5, curve_type="nominal"):
    """拉过去 N 年"""
    log.info(f"=== 拉 {years} 年 Treasury {curve_type} 数据 ===")
    end = datetime.now()
    months = []
    for i in range(years * 12):
        m = end - timedelta(days=30 * i)
        months.append(m.strftime("%Y%m"))

    all_rows = []
    for yyyymm in months:
        rows = fetch_month(yyyymm, curve_type)
        if rows:
            all_rows.extend(rows)
            log.info(f"  ✅ {yyyymm}: {len(rows)} 天")
        else:
            log.info(f"  ⚠️ {yyyymm}: 0 天 (可能旧数据被归档)")
    log.info(f"=== 总计 {len(all_rows)} 天 ===")
    return all_rows


def save_csv(rows, filename):
    """保存为 CSV"""
    if not rows:
        return
    output_path = OUTPUT_DIR / filename
    keys = rows[0].keys()
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    log.info(f"💾 保存 {output_path} ({len(rows)} 行)")


def main():
    # 名义利率
    nominal = fetch_history(years=5, curve_type="nominal")
    save_csv(nominal, "treasury_nominal_5y.csv")

    # 实际利率 (TIPS)
    real = fetch_history(years=5, curve_type="real")
    save_csv(real, "treasury_real_5y.csv")

    log.info("\n=== 数据示例 (最新 3 行 nominal) ===")
    if nominal:
        for r in nominal[:3]:
            log.info(f"  {r}")


if __name__ == "__main__":
    main()

"""拉 Yahoo 中国指数 CSV (替代 Sina 旧数据)"""
import sys
import json
import csv
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, safe_get

log = get_logger("yahoo_cn_index")
OUTPUT_DIR = ROOT / "backtest"

# Yahoo 中国指数代码
CN_INDICES = {
    "000300.SS": "沪深300",
    "000905.SS": "中证500",
    "000688.SS": "科创50",
    "000015.SS": "红利指数",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300（上交所）",
}


def fetch(sym, range_str="2y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range={range_str}"
    resp = safe_get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if not resp:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    result = data.get("chart", {}).get("result", [{}])[0]
    if not result:
        return []
    ts = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    if not ts or not closes:
        return []
    rows = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        rows.append({"date": d, "close": round(c, 4)})
    return rows


def main():
    log.info("=" * 60)
    log.info("🇨🇳 拉 Yahoo 中国指数 2 年日线 (替代 Sina 旧数据)")
    log.info("=" * 60)
    for sym, name in CN_INDICES.items():
        try:
            rows = fetch(sym, "2y")
            if not rows:
                log.info(f"  ❌ {sym} ({name}): 无数据")
                continue
            csv_name = sym.replace(".", "_") + ".csv"
            csv_path = OUTPUT_DIR / csv_name
            with open(csv_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["date", "close"])
                w.writeheader()
                w.writerows(rows)
            log.info(f"  ✅ {sym} ({name}): {len(rows)} 天 ({rows[0]['date']} → {rows[-1]['date']}) → {csv_path}")
        except Exception as e:
            log.warning(f"  ❌ {sym} ({name}): {e}")
        import time
        time.sleep(1)


if __name__ == "__main__":
    main()

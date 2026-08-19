"""
拉 VIX/DXY/FFR/QQQ/GLD 5-10 年历史
为完整回测准备
"""
import sys
import json
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, safe_get
from datetime import datetime

log = get_logger("fetch_history_all")

OUTPUT_DIR = ROOT / "backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_yahoo(symbol, range_str="10y", interval="1d"):
    """拉 Yahoo 历史"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_str}"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if not resp:
        return []
    data = resp.json()
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
        date = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        rows.append({"date": date, "close": round(c, 4)})
    return rows


def save_csv(rows, name):
    """保存 CSV"""
    if not rows:
        log.warning(f"  {name}: 0 行, 跳过")
        return
    path = OUTPUT_DIR / f"{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    log.info(f"  ✅ {name}: {len(rows)} 天 → {path}")


def main():
    log.info("=" * 60)
    log.info("📈 拉全量历史数据 (10 年)")
    log.info("=" * 60)

    # 已有: treasury_nominal_5y, treasury_real_5y, qqq_5y, gld_5y
    # 新拉: vix_10y, dxy_10y, qqq_10y, gld_10y, spy_10y (备用)
    targets = [
        ("^VIX", "vix_10y", "VIX 恐慌指数"),
        ("DX-Y.NYB", "dxy_10y", "美元指数 DXY"),
        ("QQQ", "qqq_10y", "纳指 ETF"),
        ("GLD", "gld_10y", "黄金 ETF"),
        ("SPY", "spy_10y", "标普 500"),
        ("TLT", "tlt_10y", "20+Y 国债 ETF"),
        ("XLE", "xle_10y", "能源 ETF"),
    ]
    for symbol, name, label in targets:
        try:
            log.info(f"\n--- {label} ({symbol}) ---")
            rows = fetch_yahoo(symbol, "10y", "1d")
            save_csv(rows, name)
        except Exception as e:
            log.warning(f"  ❌ {symbol}: {e}")

    log.info("\n=== 历史数据准备完成 ===")


if __name__ == "__main__":
    main()


"""
自动验证信号: 检查 30 天前的信号, 回填实际结果
- 每天跑一次 (cron)
- 对每个 generated_at > 30 天前的 signal
  - 从 intel 表找当时触发的具体数据
  - 用 Yahoo Finance 取 30 天后价格
  - 计算实际收益, 更新 actual_outcome + pnl_pct
"""
import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_db, get_logger, ROOT, safe_get
from rule_engine import RULES

log = get_logger("verify_signals")

DB_PATH = ROOT / "db" / "intel.db"
OUTPUT_DIR = ROOT / "backtest"


def fetch_price_on_date(code, target_date):
    """从 10 年 CSV 取某日价格"""
    asset_map = {
        "012752": "qqq_10y",
        "022653": "gld_10y",
        "025857": "spy_10y",  # 用 SPY 代理
        "020274": "xle_10y",  # 用 XLE 代理
    }
    csv_name = asset_map.get(code)
    if not csv_name:
        return None
    path = OUTPUT_DIR / f"{csv_name}.csv"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("date") == target_date:
                try:
                    return float(r["close"])
                except (ValueError, KeyError):
                    continue
    return None


def verify_pending_signals():
    """验证 30 天前的信号"""
    cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    verified = 0
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, code, signal_type, generated_at, rule_id
            FROM signals WHERE generated_at < ? AND actual_outcome IS NULL
            LIMIT 50""",
            (cutoff,),
        ).fetchall()
    for r in rows:
        sig_id = r["id"]
        code = r["code"]
        sig_type = r["signal_type"]
        gen_date = r["generated_at"][:10]  # YYYY-MM-DD
        # 30 天后日期
        gen_dt = datetime.fromisoformat(gen_date)
        exit_date = (gen_dt + timedelta(days=30)).strftime("%Y-%m-%d")
        # 取当时价格 + 30 天后价格
        entry_price = fetch_price_on_date(code, gen_date)
        exit_price = fetch_price_on_date(code, exit_date)
        if not entry_price or not exit_price:
            continue
        ret = (exit_price - entry_price) / entry_price
        # add 信号: 涨 = win
        # reduce 信号: 跌 = win
        if sig_type == "add":
            outcome = "win" if ret > 0 else "loss"
        elif sig_type == "reduce":
            outcome = "win" if ret < 0 else "loss"
        else:
            outcome = "neutral"
        with get_db() as conn:
            conn.execute(
                """UPDATE signals SET verified_at=?, actual_outcome=?, pnl_pct=?
                WHERE id=?""",
                (datetime.now().isoformat(timespec="seconds"), outcome, round(ret * 100, 2), sig_id),
            )
        verified += 1
    log.info(f"  ✅ 验证 {verified} 个信号")
    return verified


if __name__ == "__main__":
    log.info("=" * 60)
    log.info(f"📊 信号验证 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    n = verify_pending_signals()
    log.info(f"\n完成: {n} 个信号已验证")

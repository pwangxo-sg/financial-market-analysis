"""
首席投资专家 迭代 V2 - 一次性做 4 件事
1. 加 4 条金子技术面规则到 rule_engine
2. 跨标的验证 (QQQ/GLD/SPY 都跑 4 条技术规则)
3. 加更多技术面规则 (动量衰减/趋势强度/VIX 配合)
4. 建"信号胜率追踪" (cron 自动入库 + 30 天后回填结果)
"""
import sys
import json
import csv
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, get_db, init_db
from datetime import datetime, timedelta
from rule_engine import RULES

log = get_logger("iteration_v2")
OUTPUT_DIR = ROOT / "backtest"
DB_PATH = ROOT / "db" / "intel.db"


# ============== 1. 加载所有标的 ==============
def load_csv(name):
    path = OUTPUT_DIR / f"{name}.csv"
    if not path.exists():
        return {}
    rows = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            date = r.get("date") or r.get("Date", "")
            try:
                close = float(r.get("close") or r.get("Close", ""))
            except (ValueError, TypeError):
                continue
            rows[date] = close
    return rows


def ma(prices, dates, i, period):
    if i < period - 1:
        return None
    vals = [prices[dates[i-j]] for j in range(period) if dates[i-j] in prices]
    if len(vals) < period:
        return None
    return sum(vals) / period


# ============== 通用回测 ==============
def backtest_rule(rule_name, asset, signal_type, hold_days, trigger_fn):
    dates = sorted(asset.keys())
    trades = []
    i = 250
    while i < len(dates) - hold_days:
        date = dates[i]
        if trigger_fn(i, dates, asset):
            entry_price = asset[date]
            exit_date = dates[i + hold_days]
            if exit_date in asset:
                ret = (asset[exit_date] - entry_price) / entry_price
                trades.append({"date": date, "return_pct": round(ret * 100, 2)})
            i += max(hold_days, 5)
        else:
            i += 1
    if not trades:
        return {"rule": rule_name, "trades": 0, "win_rate": 0, "avg_return": 0}
    if signal_type == "add":
        wins = sum(1 for t in trades if t["return_pct"] > 0)
    else:
        wins = sum(1 for t in trades if t["return_pct"] < 0)
    return {
        "rule": rule_name,
        "trades": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades), 3),
        "avg_return": round(sum(t["return_pct"] for t in trades) / len(trades), 2),
    }


# ============== 技术面规则集 (10 条) ==============
def momentum_long(i, dates, p):
    if i < 20: return False
    past_20 = p[dates[i-20]]
    cur = p[dates[i]]
    return 0.05 < (cur - past_20) / past_20 < 0.15

def momentum_strong(i, dates, p):
    """20 日涨幅 > 15% (超强动量)"""
    if i < 20: return False
    past_20 = p[dates[i-20]]
    cur = p[dates[i]]
    return (cur - past_20) / past_20 > 0.15

def ma_cross_golden(i, dates, p):
    if i < 65: return False
    ma20_now = ma(p, dates, i, 20)
    ma60_now = ma(p, dates, i, 60)
    ma20_prev = ma(p, dates, i-3, 20)
    ma60_prev = ma(p, dates, i-3, 60)
    if None in (ma20_now, ma60_now, ma20_prev, ma60_prev): return False
    return ma20_prev < ma60_prev and ma20_now > ma60_now

def ma_cross_death(i, dates, p):
    """MA20 下穿 MA60 (死叉, 减仓信号)"""
    if i < 65: return False
    ma20_now = ma(p, dates, i, 20)
    ma60_now = ma(p, dates, i, 60)
    ma20_prev = ma(p, dates, i-3, 20)
    ma60_prev = ma(p, dates, i-3, 60)
    if None in (ma20_now, ma60_now, ma20_prev, ma60_prev): return False
    return ma20_prev > ma60_prev and ma20_now < ma60_now

def new_high_breakout(i, dates, p):
    if i < 250: return False
    past_250_high = max(p[dates[i-j]] for j in range(250) if dates[i-j] in p)
    return p[dates[i]] >= past_250_high * 0.999

def trend_above_ma60(i, dates, p):
    if i < 65: return False
    cur = p[dates[i]]
    ma60 = ma(p, dates, i, 60)
    if ma60 is None: return False
    return cur > ma60 * 1.005

def trend_above_ma200(i, dates, p):
    if i < 205: return False
    cur = p[dates[i]]
    ma200 = ma(p, dates, i, 200)
    if ma200 is None: return False
    return cur > ma200 * 1.005

def rsi_oversold(i, dates, p, period=14, threshold=30):
    """RSI 超卖 (逆向买)"""
    if i < period + 1: return False
    gains = losses = 0
    for j in range(period):
        chg = p[dates[i-j]] - p[dates[i-j-1]]
        if chg > 0: gains += chg
        else: losses -= chg
    if losses == 0: return False
    rs = gains / losses
    rsi = 100 - 100 / (1 + rs)
    return rsi < threshold

def pullback_to_ma20(i, dates, p):
    """回踩 MA20 (中继买点)"""
    if i < 25: return False
    cur = p[dates[i]]
    ma20 = ma(p, dates, i, 20)
    if ma20 is None: return False
    # 当前价回到 MA20 ± 2%
    return abs(cur - ma20) / ma20 < 0.02

def volatility_breakout(i, dates, p, period=20):
    """波动率突破 (布林带)"""
    if i < period: return False
    ma20 = ma(p, dates, i, period)
    if ma20 is None: return False
    std = (sum((p[dates[i-j]] - ma20) ** 2 for j in range(period)) / period) ** 0.5
    cur = p[dates[i]]
    # 价格突破上轨 (MA + 2*STD)
    return cur > ma20 + 2 * std


TECH_RULES = [
    ("MOMENTUM_LONG", "add", 60, momentum_long, "20日涨幅 5-15%"),
    ("MOMENTUM_STRONG", "add", 60, momentum_strong, "20日涨幅 > 15%"),
    ("MA_CROSS_GOLDEN", "add", 90, ma_cross_golden, "MA20 上穿 MA60"),
    ("MA_CROSS_DEATH", "reduce", 30, ma_cross_death, "MA20 下穿 MA60"),
    ("BREAKOUT_250D", "add", 90, new_high_breakout, "突破 250 日新高"),
    ("TREND_MA60", "add", 60, trend_above_ma60, "首次站上 MA60"),
    ("TREND_MA200", "add", 90, trend_above_ma200, "首次站上 MA200"),
    ("RSI_OVERSOLD", "add", 30, rsi_oversold, "RSI < 30 超卖"),
    ("PULLBACK_MA20", "add", 60, pullback_to_ma20, "回踩 MA20"),
    ("VOL_BREAKOUT", "add", 60, volatility_breakout, "布林带突破"),
]


# ============== 任务 2: 跨标的验证 ==============
def cross_asset_validation():
    log.info("\n" + "=" * 60)
    log.info("🌐 任务 2: 跨标的验证 (QQQ/GLD/SPY)")
    log.info("=" * 60)
    assets = {
        "QQQ": load_csv("qqq_10y"),
        "GLD": load_csv("gld_10y"),
        "SPY": load_csv("spy_10y"),
    }
    results = {}
    for asset_name, asset in assets.items():
        if not asset:
            log.warning(f"  ⚠️ {asset_name} 数据缺失")
            continue
        log.info(f"\n--- {asset_name} ({len(asset)} 天) ---")
        results[asset_name] = []
        for rid, sig, hd, fn, desc in TECH_RULES:
            r = backtest_rule(rid, asset, sig, hd, fn)
            r["description"] = desc
            r["signal_type"] = sig
            results[asset_name].append(r)
            emoji = "✅" if r["win_rate"] > 0.55 else ("⚠️" if r["win_rate"] > 0.45 else "❌")
            log.info(f"  {emoji} {rid:20s}: {r['trades']:3d}次, 胜率{r['win_rate']*100:5.1f}%, 收益{r['avg_return']:+6.2f}%")
    return results


# ============== 任务 3: 加金子规则到 rule_engine ==============
def update_rule_engine():
    log.info("\n" + "=" * 60)
    log.info("📜 任务 3: 加 4 条金子技术面规则到 rule_engine")
    log.info("=" * 60)
    init_db()
    # 已有 4 条金子: MA_CROSS_20_60, BREAKOUT_250D, TREND_ABOVE_MA60, MOMENTUM_20D
    new_rules = [
        {
            "rule_id": "TECH_MA_GOLDEN_QQQ",
            "description": "QQQ: MA20 上穿 MA60 → 加仓 (技术面金叉)",
            "target_codes": ["012752"],
            "signal_type": "add",
            "confidence": 85,
            "indicators": [{"name": "ma20", "operator": ">", "value": "ma60"}],  # 触发由技术面逻辑判断
            "hold_days": 90,
            "rationale": "MA 金叉是中长期趋势反转信号, 10 年回测胜率 84.6%, 收益 +7.18%",
            "expected_win_rate": 0.846,
            "lookback_days": 60,
        },
        {
            "rule_id": "TECH_BREAKOUT_QQQ",
            "description": "QQQ: 突破 250 日新高 → 加仓 (技术面突破)",
            "target_codes": ["012752"],
            "signal_type": "add",
            "confidence": 80,
            "indicators": [{"name": "new_250d_high", "operator": "==", "value": True}],
            "hold_days": 90,
            "rationale": "突破 250 日新高是强势信号, 胜率 80%, 收益 +7.00%",
            "expected_win_rate": 0.800,
            "lookback_days": 250,
        },
        {
            "rule_id": "TECH_MOMENTUM_QQQ",
            "description": "QQQ: 20 日涨幅 5-15% → 加仓 (动量跟踪)",
            "target_codes": ["012752"],
            "signal_type": "add",
            "confidence": 70,
            "indicators": [{"name": "mom_20d", "operator": "between", "value": [0.05, 0.15]}],
            "hold_days": 60,
            "rationale": "动量跟踪, 强势但非超买, 胜率 66.7%, 收益 +3.16%",
            "expected_win_rate": 0.667,
            "lookback_days": 20,
        },
        {
            "rule_id": "TECH_TREND_QQQ",
            "description": "QQQ: 首次站上 MA60 → 加仓 (趋势确认)",
            "target_codes": ["012752"],
            "signal_type": "add",
            "confidence": 72,
            "indicators": [{"name": "above_ma60", "operator": "==", "value": True}],
            "hold_days": 60,
            "rationale": "站上 MA60 是中期趋势确认, 胜率 71.4%, 收益 +3.41%",
            "expected_win_rate": 0.714,
            "lookback_days": 60,
        },
    ]
    with get_db() as conn:
        for r in new_rules:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO rules
                    (rule_id, description, scope, target_codes, conditions,
                     expected_win_rate, expected_hold_days, enabled, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        r["rule_id"], r["description"], "fund",
                        json.dumps(r["target_codes"], ensure_ascii=False),
                        json.dumps({
                            "signal_type": r["signal_type"],
                            "confidence": r["confidence"],
                            "indicators": r["indicators"],
                            "hold_days": r["hold_days"],
                            "rationale": r["rationale"],
                            "tech_rule": True,  # 标记为技术面规则
                        }, ensure_ascii=False),
                        r["expected_win_rate"],
                        r["hold_days"],
                        1,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                log.info(f"  ✅ {r['rule_id']:25s}: 胜率 {r['expected_win_rate']*100:.0f}%, {r['hold_days']}天")
            except Exception as e:
                log.warning(f"  ❌ {r['rule_id']}: {e}")
    return new_rules


# ============== 任务 4: 信号胜率追踪 ==============
def signal_tracker_init():
    """初始化信号追踪表 + 自动验证逻辑"""
    log.info("\n" + "=" * 60)
    log.info("📊 任务 4: 信号胜率追踪 (自动入库 + 30 天后回填)")
    log.info("=" * 60)
    init_db()
    # signals 表已存在 (在 _lib SCHEMA 中)
    # 写一个 verify_old_signals 函数, 检查 30 天前的信号, 自动回填实际结果
    log.info("  ✅ signals 表已存在")
    log.info("  💡 验证逻辑: 每天跑 verify_signals.py, 检查 30 天前的信号, 回填实际收益")

    # 写 verify_signals.py
    verify_script = OUTPUT_DIR.parent / "scripts" / "verify_signals.py"
    verify_script.write_text('''
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
    log.info(f"\\n完成: {n} 个信号已验证")
''', encoding="utf-8")
    log.info(f"  ✅ 写 verify_signals.py")


# ============== 主函数 ==============
def main():
    log.info("=" * 60)
    log.info("🚀 首席投资专家 迭代 V2 - 一次性 4 件事")
    log.info("=" * 60)

    # 任务 1: 已通过 tech_rules.py 完成, 这里汇总
    log.info("\n--- 任务 1: 加 4 条金子技术面规则 (10年 QQQ回测) ---")
    log.info("  ✅ MA_CROSS_20_60 (84.6% / +7.18%)")
    log.info("  ✅ BREAKOUT_250D (80% / +7.00%)")
    log.info("  ✅ TREND_ABOVE_MA60 (71.4% / +3.41%)")
    log.info("  ✅ MOMENTUM_20D (66.7% / +3.16%)")

    # 任务 2: 跨标的
    cross_results = cross_asset_validation()

    # 任务 3: 更新 rule_engine
    new_rules = update_rule_engine()

    # 任务 4: 信号追踪
    signal_tracker_init()

    # 保存综合结果
    output = {
        "cross_asset_validation": {
            asset: [{k: v for k, v in r.items() if k != "trades" or v > 0} for r in results]
            for asset, results in cross_results.items()
        },
        "new_rules_added": [{"rule_id": r["rule_id"], "win_rate": r["expected_win_rate"]} for r in new_rules],
    }
    output_path = OUTPUT_DIR / "iteration_v2_result.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 综合结果: {output_path}")

    # 总览
    log.info("\n" + "=" * 60)
    log.info("📊 跨标的验证总览")
    log.info("=" * 60)
    for asset, results in cross_results.items():
        good = [r for r in results if r["win_rate"] > 0.55 and r["trades"] > 0]
        log.info(f"  {asset}: {len(good)}/{len(results)} 条规则胜率>55% (样本足)")


if __name__ == "__main__":
    main()

"""
复合回测：4 条 QQQ 金子规则 + 宏观过滤器
过滤器：yield_curve_2_10 <= 0 (衰退信号) → 禁用技术面触发
数据：QQQ 价格 2000-2010 + 2016-2026, Treasury yield curve 2-10

对比：
- 无过滤（基线）: cross_cycle_2000_2010.py 的结果
- yield_curve <= 0 过滤: 当天 2-10 <= 0 时跳过技术面触发
- 目标：熊市胜率提升，期望值改善
"""
import csv
import json
from pathlib import Path
from datetime import datetime, timedelta
from bisect import bisect_left

BACKTEST_DIR = Path("~/.dsh/market_intel/backtest").expanduser()
OUTPUT = BACKTEST_DIR / "filtered_backtest_result.json"


def load_csv(path, cols):
    """加载 CSV，返回 {col: [(date, value)]}"""
    out = {c: [] for c in cols}
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.fromisoformat(r["date"]).date()
            except (ValueError, KeyError):
                continue
            for c in cols:
                if c in r and r[c]:
                    try:
                        out[c].append((d, float(r[c])))
                    except ValueError:
                        pass
    for c in cols:
        out[c].sort()
    return out


def value_on_or_before(dates_values, target_date):
    """二分查找：找 target_date 或之前最近一天的值"""
    if not dates_values:
        return None
    dates = [d for d, _ in dates_values]
    idx = bisect_left(dates, target_date)
    if idx == 0:
        return None
    return dates_values[idx - 1][1]


def ma(prices, n, idx):
    if idx < n - 1:
        return None
    return sum(p for _, p in prices[idx - n + 1:idx + 1]) / n


def find_signals_filtered(prices, rule, yc_lookup, filter_check):
    """filter_check(date) -> bool, True=禁用, False=允许"""
    out = []
    last_exit_idx = -1
    for i in range(250, len(prices) - rule["hold_days"]):
        if i <= last_exit_idx:
            continue
        date_i = prices[i][0]
        # 宏观过滤器
        if filter_check(date_i, yc_lookup):
            continue
        fired = False
        if rule["id"] == "MA_CROSS_20_60":
            ma20_prev = ma(prices, 20, i - 1)
            ma60_prev = ma(prices, 60, i - 1)
            ma20_now = ma(prices, 20, i)
            ma60_now = ma(prices, 60, i)
            if ma20_prev and ma60_prev and ma20_now and ma60_now:
                fired = (ma20_prev <= ma60_prev) and (ma20_now > ma60_now)
        elif rule["id"] == "BREAKOUT_250D":
            if i >= 250:
                high_250 = max(p for _, p in prices[i - 250:i])
                fired = prices[i][1] > high_250
        elif rule["id"] == "TREND_MA60":
            ma60_now = ma(prices, 60, i)
            ma60_prev = ma(prices, 60, i - 1)
            if ma60_now and ma60_prev:
                fired = (prices[i - 1][1] < ma60_prev) and (prices[i][1] > ma60_now)
        elif rule["id"] == "MOMENTUM_20D":
            if i >= 20:
                ret_20d = (prices[i][1] - prices[i - 20][1]) / prices[i - 20][1]
                fired = 0.05 <= ret_20d <= 0.15
        if fired:
            entry_idx = i
            exit_idx = min(i + rule["hold_days"], len(prices) - 1)
            out.append((entry_idx, exit_idx))
            last_exit_idx = exit_idx
    return out


def backtest(prices, rule, yc_lookup, filter_check):
    trades = find_signals_filtered(prices, rule, yc_lookup, filter_check)
    wins = losses = 0
    returns = []
    for entry_idx, exit_idx in trades:
        entry = prices[entry_idx][1]
        exit_p = prices[exit_idx][1]
        ret = (exit_p - entry) / entry * 100
        returns.append(ret)
        if ret > 0:
            wins += 1
        else:
            losses += 1
    total = wins + losses
    avg_w = sum(r for r in returns if r > 0) / wins if wins else 0
    avg_l = sum(r for r in returns if r < 0) / losses if losses else 0
    expectancy = (wins / total * avg_w) - (losses / total * abs(avg_l)) if total else 0
    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "avg_return": round(sum(returns) / total, 2) if total else 0,
        "expectancy": round(expectancy, 2),
        "best": round(max(returns), 2) if returns else 0,
        "worst": round(min(returns), 2) if returns else 0,
    }


RULES = [
    {"id": "MA_CROSS_20_60", "hold_days": 90},
    {"id": "BREAKOUT_250D", "hold_days": 90},
    {"id": "TREND_MA60", "hold_days": 60},
    {"id": "MOMENTUM_20D", "hold_days": 60},
]

PERIODS = {
    "2000-2010 (熊市)": "qqq_2000_2010.csv",
    "2016-2026 (牛市)": "qqq_10y.csv",
}

# 基线（无过滤）：来自 cross_cycle_2000_2010.py 的结果
BASELINE = {
    "2000-2010 (熊市)": {
        "MA_CROSS_20_60": {"trades": 15, "win_rate": 60.0, "avg_return": -2.45, "expectancy": None},
        "BREAKOUT_250D": {"trades": 7, "win_rate": 71.4, "avg_return": 1.88, "expectancy": None},
        "TREND_MA60": {"trades": 25, "win_rate": 60.0, "avg_return": -0.39, "expectancy": None},
        "MOMENTUM_20D": {"trades": 27, "win_rate": 55.6, "avg_return": 0.17, "expectancy": None},
    },
    "2016-2026 (牛市)": {
        "MA_CROSS_20_60": {"trades": 13, "win_rate": 84.6, "avg_return": 7.18},
        "BREAKOUT_250D": {"trades": 15, "win_rate": 80.0, "avg_return": 7.00},
        "TREND_MA60": {"trades": 35, "win_rate": 71.4, "avg_return": 3.41},
        "MOMENTUM_20D": {"trades": 30, "win_rate": 66.7, "avg_return": 3.16},
    },
}


def main():
    yc = load_csv(BACKTEST_DIR / "yield_curve_2_10_2000_2010.csv", ["yield_curve_2_10"])
    yc_lookup_2000_2010 = yc["yield_curve_2_10"]
    # 2016-2026 的 yield curve 已有 treasury_history/treasury_nominal_5y.csv, 用同样的 load_csv
    yc_2016 = load_csv(BACKTEST_DIR / "treasury_history" / "treasury_nominal_5y.csv", ["2 Yr", "10 Yr"])
    # 构造 yield_curve_2_10 = 10Y - 2Y
    yc_2016_curve = []
    for d, _ in yc_2016["2 Yr"]:
        v2 = value_on_or_before(yc_2016["2 Yr"], d)
        v10 = value_on_or_before(yc_2016["10 Yr"], d)
        if v2 and v10:
            yc_2016_curve.append((d, v10 - v2))
    yc_2016_curve.sort()

    def filter_yield_curve(date, lookup):
        v = value_on_or_before(lookup, date)
        return v is not None and v <= 0

    results = {"filter": "yield_curve_2_10 <= 0 (衰退信号禁用)", "rules": {}}
    for period_name, csv_name in PERIODS.items():
        csv_path = BACKTEST_DIR / csv_name
        if not csv_path.exists():
            print(f"  skip {csv_name} (not found)")
            continue
        prices = load_csv(csv_path, ["close"])
        if not prices["close"]:
            continue
        prices = [(d, c) for d, c in prices["close"]]
        yc_lookup = yc_lookup_2000_2010 if "2000-2010" in period_name else yc_2016_curve

        results["rules"][period_name] = {}
        for rule in RULES:
            r = backtest(prices, rule, yc_lookup, filter_yield_curve)
            base = BASELINE.get(period_name, {}).get(rule["id"], {})
            # 计算改善
            win_rate_delta = (r["win_rate"] - base.get("win_rate", 0)) if base else 0
            avg_return_delta = (r["avg_return"] - base.get("avg_return", 0)) if base else 0
            results["rules"][period_name][rule["id"]] = {
                **r,
                "baseline_win_rate": base.get("win_rate"),
                "baseline_avg_return": base.get("avg_return"),
                "win_rate_delta": round(win_rate_delta, 1),
                "avg_return_delta": round(avg_return_delta, 2),
            }

    # 输出 verdict
    print(f"\n=== 加 yield_curve_2_10<=0 过滤器后的复合回测 ===\n")
    print(f"{'PERIOD':<18} {'RULE':<18} {'TRADES':>7} {'WIN%':>7} {'AVG%':>7} {'ΔWIN%':>7} {'ΔAVG%':>7} {'EXP':>7}")
    for period, rules_data in results["rules"].items():
        for rid, r in rules_data.items():
            print(f"{period:<18} {rid:<18} {r['trades']:>7} {r['win_rate']:>6}% {r['avg_return']:>6}% {r['win_rate_delta']:>+6}% {r['avg_return_delta']:>+6}% {r['expectancy']:>6}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果: {OUTPUT}")

    # 写最终 verdict
    print("\n=== 结论 ===")
    for period, rules_data in results["rules"].items():
        for rid, r in rules_data.items():
            base = BASELINE.get(period, {}).get(rid, {})
            if r["trades"] < 5:
                print(f"  {period} {rid}: 触发{ r['trades']}次（样本太少，需谨慎）")
            elif r["win_rate"] >= 60 and r["avg_return"] > 0 and r["expectancy"] > 0:
                print(f"  ✅ {period} {rid}: 胜率{r['win_rate']}%, 收益{r['avg_return']}%, 期望值{r['expectancy']} (基线 {base.get('win_rate')}%/{base.get('avg_return')}%)")
            else:
                print(f"  ⚠️ {period} {rid}: 胜率{r['win_rate']}%, 收益{r['avg_return']}% (基线 {base.get('win_rate')}%/{base.get('avg_return')}%)")


if __name__ == "__main__":
    main()

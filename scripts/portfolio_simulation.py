"""
模拟回测: 假设按当前模型建议调整, 看 1 年收益情况
- 数据: QQQ/GLD/SPY/XLE 5 年日线 (用 SPY 代理电网, XLE 代理化工)
- 初始: 50 万人民币, 4 只基金各 1 万 (现状 8% 仓位)
- 策略: 按今日建议分 4 周调仓到目标权重
- 评估: 累计收益, 最大回撤, 夏普, 胜率
- 对比: vs 不调仓 / vs 一次调到位 / vs 纳指单独 / vs 50/50
"""
import sys
import json
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime, timedelta

log = get_logger("backtest_portfolio")
OUTPUT_DIR = ROOT / "backtest"

# 目标组合权重
TARGET_WEIGHTS = {
    "qqq_10y": 0.25,  # 纳指
    "gld_10y": 0.25,  # 黄金
    "spy_10y": 0.15,  # 电网 (代理)
    "xle_10y": 0.10,  # 化工 (代理)
}
# 初始持仓 (现状)
INITIAL_HOLDINGS = {
    "qqq_10y": 10000,
    "gld_10y": 10000,
    "spy_10y": 10000,
    "xle_10y": 10000,
}
TOTAL_CAPITAL = 500000
# 现金假设 46 万, 累计投入 4 万
INITIAL_CASH = TOTAL_CAPITAL - sum(INITIAL_HOLDINGS.values())  # 460000


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


def rebalance_dates(dates, weeks=4):
    """从起点往后, 找到 4 个再平衡日期 (按周)"""
    if not dates:
        return []
    return [dates[min(i * 5, len(dates) - 1)] for i in range(weeks)]  # 简化: 5 个交易日 = 1 周


def simulate_scenario(name, asset_data, scenario_type, period_days=252):
    """
    模拟 1 个场景
    scenario_type: "no_rebalance" / "lump_sum" / "gradual_4w"
    """
    dates = sorted(asset_data[list(asset_data.keys())[0]].keys())
    if len(dates) < period_days:
        period_days = len(dates)
    sim_dates = dates[-period_days:]  # 取最近 1 年
    sim_dates_set = set(sim_dates)

    # 加载所有资产在模拟期间的价格
    prices = {name: {d: asset_data[name].get(d, 0) for d in sim_dates} for name in asset_data}

    # 起点: 假设我们在 sim_dates[0] 有初始持仓
    # 初始份额 = 金额 / 价格
    initial_shares = {}
    initial_value = 0
    for name in INITIAL_HOLDINGS:
        if name in prices and sim_dates[0] in prices[name] and prices[name][sim_dates[0]] > 0:
            shares = INITIAL_HOLDINGS[name] / prices[name][sim_dates[0]]
            initial_shares[name] = shares
            initial_value += INITIAL_HOLDINGS[name]
    initial_cash = INITIAL_CASH

    # 再平衡日期 (按周, 4 周)
    rebal_dates = set()
    if sim_dates:
        if scenario_type == "lump_sum":
            rebal_dates.add(sim_dates[0])  # 第 1 天一次调
        elif scenario_type == "gradual_4w":
            for i in range(4):
                idx = min((i + 1) * 5, len(sim_dates) - 1)
                rebal_dates.add(sim_dates[idx])

    # 模拟每日组合价值
    portfolio_values = []
    daily_rets = []
    last_value = initial_value + initial_cash
    shares = dict(initial_shares)
    cash = initial_cash

    for date in sim_dates:
        # 计算当日价值
        value = cash
        for name, sh in shares.items():
            if prices[name].get(date, 0) > 0:
                value += sh * prices[name][date]
        portfolio_values.append({"date": date, "value": value, "cash": cash})

        # 再平衡
        if date in rebal_dates and value > 0:
            target_values = {n: value * w for n, w in TARGET_WEIGHTS.items()}
            new_shares = {}
            new_cash = 0
            for name in TARGET_WEIGHTS:
                if name in prices and prices[name].get(date, 0) > 0:
                    sh = target_values[name] / prices[name][date]
                    new_shares[name] = sh
            # 剩余当现金
            new_cash = value - sum(target_values.values())
            shares = new_shares
            cash = new_cash

        # 日收益
        if last_value > 0:
            daily_rets.append((value - last_value) / last_value)
        last_value = value

    return {
        "scenario": name,
        "scenario_type": scenario_type,
        "initial_value": initial_value + initial_cash,
        "final_value": portfolio_values[-1]["value"] if portfolio_values else 0,
        "return_pct": ((portfolio_values[-1]["value"] - last_value) / last_value * 100) if portfolio_values and last_value else 0,
        "max_drawdown": compute_max_drawdown([p["value"] for p in portfolio_values]),
        "sharpe": compute_sharpe(daily_rets),
        "daily_values": portfolio_values,
    }


def compute_max_drawdown(values):
    if not values:
        return 0
    peak = values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd * 100


def compute_sharpe(daily_rets, risk_free=0.02):
    """年化夏普 (假设无风险 2%)"""
    if not daily_rets or len(daily_rets) < 2:
        return 0
    import statistics
    avg = sum(daily_rets) / len(daily_rets) * 252  # 年化收益
    std = statistics.stdev(daily_rets) * (252 ** 0.5)  # 年化波动
    if std == 0:
        return 0
    return (avg - risk_free) / std


def simulate_benchmarks(asset_data, period_days=252):
    """基准: 1) 100% QQQ 2) 50/50 QQQ+GLD 3) 不动"""
    dates = sorted(asset_data[list(asset_data.keys())[0]].keys())
    sim_dates = dates[-period_days:]
    results = {}
    # 1) 100% QQQ
    if "qqq_10y" in asset_data:
        p0 = asset_data["qqq_10y"].get(sim_dates[0], 0)
        p1 = asset_data["qqq_10y"].get(sim_dates[-1], 0)
        if p0 > 0:
            results["100% QQQ"] = (p1 - p0) / p0 * 100
    # 2) 50/50 QQQ+GLD
    if "qqq_10y" in asset_data and "gld_10y" in asset_data:
        q0 = asset_data["qqq_10y"].get(sim_dates[0], 0)
        q1 = asset_data["qqq_10y"].get(sim_dates[-1], 0)
        g0 = asset_data["gld_10y"].get(sim_dates[0], 0)
        g1 = asset_data["gld_10y"].get(sim_dates[-1], 0)
        if q0 > 0 and g0 > 0:
            qqq_ret = (q1 - q0) / q0
            gld_ret = (g1 - g0) / g0
            results["50% QQQ + 50% GLD"] = (qqq_ret + gld_ret) / 2 * 100
    # 3) 不动 (当前 4 万分布, 96% 现金)
    # 假设现金也按 0% 收益 (实际短债 2%, 简化)
    initial = 500000
    # 8% 仓位: 实际按持仓的 1 年收益, 92% 现金按 0%
    holdings_ret = 0
    for n, amt in INITIAL_HOLDINGS.items():
        if n in asset_data and asset_data[n].get(sim_dates[0], 0) > 0:
            ret = (asset_data[n].get(sim_dates[-1], 0) - asset_data[n].get(sim_dates[0], 0)) / asset_data[n].get(sim_dates[0], 0)
            holdings_ret += ret * (amt / 500000) * 100
    results["不动 (8% 持仓 + 92% 现金 0%)"] = holdings_ret
    return results


def main():
    log.info("=" * 60)
    log.info("🧪 模拟回测: 50万组合 1 年调整 vs 不调整")
    log.info("=" * 60)

    asset_data = {
        "qqq_10y": load_csv("qqq_10y"),
        "gld_10y": load_csv("gld_10y"),
        "spy_10y": load_csv("spy_10y"),
        "xle_10y": load_csv("xle_10y"),
    }
    if not all(asset_data.values()):
        log.error("❌ 数据缺失")
        return

    period = 252  # 1 年
    log.info(f"\n回测窗口: 过去 {period} 天 (1 年)")
    log.info(f"初始: 50 万 (4 万已投 + 46 万现金)")

    # 3 个场景
    scenarios = [
        ("场景A: 不调仓 (8% 持仓)", "no_rebalance"),
        ("场景B: 一次调到位 (Day 1)", "lump_sum"),
        ("场景C: 分4周调 (推荐)", "gradual_4w"),
    ]
    results = {}
    for name, s in scenarios:
        log.info(f"\n--- {name} ---")
        r = simulate_scenario(name, asset_data, s, period_days=period)
        results[name] = r
        log.info(f"  初始: ¥{r['initial_value']:,.0f}")
        log.info(f"  最终: ¥{r['final_value']:,.0f}")
        ret = (r['final_value'] - r['initial_value']) / r['initial_value'] * 100
        log.info(f"  收益: {ret:+.2f}%")
        log.info(f"  最大回撤: {r['max_drawdown']:.2f}%")
        log.info(f"  年化夏普: {r['sharpe']:.2f}")

    # 基准对比
    log.info("\n--- 基准对比 (同期 1 年) ---")
    bench = simulate_benchmarks(asset_data, period)
    for k, v in bench.items():
        log.info(f"  {k}: {v:+.2f}%")

    # 综合结果
    log.info("\n" + "=" * 60)
    log.info("📊 综合对比")
    log.info("=" * 60)
    for name, r in results.items():
        ret = (r['final_value'] - r['initial_value']) / r['initial_value'] * 100
        log.info(f"  {name:30s}: 收益 {ret:+6.2f}% | 回撤 {r['max_drawdown']:5.2f}% | 夏普 {r['sharpe']:5.2f}")
    for k, v in bench.items():
        log.info(f"  [基准] {k:30s}: 收益 {v:+6.2f}%")

    # 保存
    output = {
        "scenarios": {k: {k2: v2 for k2, v2 in v.items() if k2 != "daily_values"} for k, v in results.items()},
        "benchmarks": bench,
        "period_days": period,
        "target_weights": TARGET_WEIGHTS,
        "initial_holdings": INITIAL_HOLDINGS,
    }
    output_path = OUTPUT_DIR / "portfolio_simulation.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 综合结果: {output_path}")


if __name__ == "__main__":
    main()

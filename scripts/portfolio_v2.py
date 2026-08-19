"""
10 标的 50 万组合新设计
- 用 9 个有数据的代理指数/ETF 做回测
- 4 周分批加仓
- 输出综合方案
"""
import sys
import json
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime, timedelta

log = get_logger("portfolio_v2")
OUTPUT_DIR = ROOT / "backtest"

# 10 标的 50 万目标组合 (基于持仓之外机会扫描)
NEW_PORTFOLIO = {
    "012752_纳指":   {"name": "纳指QDII",     "proxy": "qqq_10y",  "weight": 0.15, "scenario": "buy_dip",  "weekly_amt": 0},
    "022653_黄金":   {"name": "黄金ETF",     "proxy": "gld_10y",  "weight": 0.15, "scenario": "add_aggressive", "weekly_amt": 0},
    "510300_沪深300": {"name": "沪深300",     "proxy": "sh000905", "weight": 0.10, "scenario": "slow_add",  "weekly_amt": 0},  # 代理
    "513500_标普500": {"name": "标普500",     "proxy": "spy_10y",  "weight": 0.10, "scenario": "slow_add",  "weekly_amt": 0},
    "512890_红利低波": {"name": "红利低波",   "proxy": "sh000015", "weight": 0.10, "scenario": "defensive", "weekly_amt": 0},  # 防御
    "159813_半导体":  {"name": "半导体芯片",  "proxy": "sh000688", "weight": 0.08, "scenario": "buy_dip",  "weekly_amt": 0},  # 科创50代理
    "159819_创新药":  {"name": "创新药/AI",  "proxy": "sz399006", "weight": 0.05, "scenario": "buy_dip",  "weekly_amt": 0},  # 创业板代理
    "512810_军工":   {"name": "军工ETF",     "proxy": "sh000959", "weight": 0.04, "scenario": "add_aggressive", "weekly_amt": 0},  # 中证军工
    "020274_化工":   {"name": "化工ETF",     "proxy": "xle_10y",  "weight": 0.03, "scenario": "buy_dip",  "weekly_amt": 0},  # XLE 代理
    "现金/短债":     {"name": "现金/短债",    "proxy": None,       "weight": 0.20, "scenario": "buffer",    "weekly_amt": 0},
}

# 现状持仓 (Patrick 当前)
CURRENT_HOLDINGS = {
    "012752_纳指": 10000,  # 已持 1 万
    "022653_黄金": 10000,
    "025857_电网": 10000,  # 旧组合, 改造为新组合时可能减仓
    "020274_化工": 10000,
}
TOTAL_CAPITAL = 500000


def load_csv(name):
    """加载 CSV, 兼容 'date' 或 'day' 列"""
    path = OUTPUT_DIR / f"{name}.csv"
    if not path.exists():
        return {}
    rows = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            date = r.get("date") or r.get("day", "")
            try:
                close = float(r.get("close") or r.get("Close", ""))
            except (ValueError, KeyError):
                continue
            rows[date] = close
    return rows


def compute_weekly_plan():
    """4 周分批加仓计划 (基于 scenario)"""
    # 已有持仓
    # 计算每周应加仓金额
    # 现状: 4 万已投 (1 万/只)
    # 目标: 50 万 * 权重
    for code, info in NEW_PORTFOLIO.items():
        if info["proxy"] is None:
            continue  # 现金
        target = TOTAL_CAPITAL * info["weight"]
        current = CURRENT_HOLDINGS.get(code, 0)
        delta = target - current
        if delta <= 0:
            info["weekly_amt"] = 0
            info["weeks_to_complete"] = 0
            continue
        # 按 scenario 决定节奏
        if info["scenario"] == "buy_dip":
            info["weeks_to_complete"] = 2  # 2 周完成
            info["weekly_amt"] = delta / 2
        elif info["scenario"] == "add_aggressive":
            info["weeks_to_complete"] = 2
            info["weekly_amt"] = delta / 2
        elif info["scenario"] == "slow_add":
            info["weeks_to_complete"] = 4
            info["weekly_amt"] = delta / 4
        elif info["scenario"] == "defensive":
            info["weeks_to_complete"] = 4
            info["weekly_amt"] = delta / 4
        else:
            info["weeks_to_complete"] = 4
            info["weekly_amt"] = delta / 4
    return NEW_PORTFOLIO


def simulate_v2_combined(period_days=500):
    """10 标的 50 万组合 1 年回测"""
    log.info(f"模拟窗口: 过去 {period_days} 天")
    # 加载所有代理数据
    proxies = {}
    for code, info in NEW_PORTFOLIO.items():
        if info["proxy"] is None:
            continue
        proxies[code] = load_csv(info["proxy"])
        if not proxies[code]:
            log.warning(f"  ⚠️ {code} ({info['proxy']}) 数据缺失")

    # 用最新源 (Sina 500 天) 作为基准日期
    # Yahoo 5 年数据 ≥ Sina 500 天, 截取 Sina 的 500 天范围
    sina_keys = ["sh000905", "sh000688", "sh000015", "sh000959", "sz399006"]
    sina_dates = set()
    for code, info in NEW_PORTFOLIO.items():
        if info["proxy"] in sina_keys and code in proxies:
            sina_dates.update(proxies[code].keys())
    # Yahoo 标的: 也加载同期 (用 Sina 范围对齐)
    common_dates = sorted(sina_dates)
    if not common_dates:
        log.error("❌ Sina 数据为空")
        return None
    # 截取最后 N 天
    if len(common_dates) > period_days:
        common_dates = common_dates[-period_days:]
    log.info(f"  共同日期: {common_dates[0]} → {common_dates[-1]} ({len(common_dates)} 天)")

    # 假设在 common_dates[0] 起点, 各标的目标权重 (50万 * weight)
    # 4 周分批加仓 (20 个交易日)
    rebal_dates = set()
    for i in [5, 10, 15, 20]:
        if i < len(common_dates):
            rebal_dates.add(common_dates[i])

    # 初始: 已持仓部分用真实金额, 其余现金
    # 已持仓标的: 假设初始 value = current_holdings
    initial_value = 0
    for code, info in NEW_PORTFOLIO.items():
        if code in CURRENT_HOLDINGS and code in proxies:
            # 假设初始价格 = 区间最早收盘
            p0 = proxies[code].get(common_dates[0], 0)
            if p0 > 0:
                # 已持仓价值 = current_holdings 金额
                initial_value += CURRENT_HOLDINGS[code]
    initial_cash = TOTAL_CAPITAL - initial_value
    # 假设初始 shares = current_holdings / p0
    shares = {}
    for code, info in NEW_PORTFOLIO.items():
        if code in CURRENT_HOLDINGS and code in proxies:
            p0 = proxies[code].get(common_dates[0], 0)
            if p0 > 0:
                shares[code] = CURRENT_HOLDINGS[code] / p0
    cash = initial_cash

    # 模拟每日
    portfolio_values = []
    daily_rets = []
    last_value = initial_value + cash

    for date in common_dates:
        # 计算当日价值
        value = cash
        for code, sh in shares.items():
            p = proxies[code].get(date, 0)
            if p > 0:
                value += sh * p
        portfolio_values.append({"date": date, "value": value})

        # 4 周分批调仓
        if date in rebal_dates and value > 0:
            for code, info in NEW_PORTFOLIO.items():
                if info["proxy"] is None or code not in proxies:
                    continue
                target_value = value * info["weight"]
                p = proxies[code].get(date, 0)
                if p > 0 and target_value > 0:
                    new_shares = target_value / p
                    shares[code] = new_shares
            # 剩余当现金
            target_total = sum(value * info["weight"] for code, info in NEW_PORTFOLIO.items() if info["weight"] > 0)
            cash = value - target_total + value * NEW_PORTFOLIO["现金/短债"]["weight"]
            # 简化: 实际剩余 = value - sum(target_values) + 现金部分
            cash = value * NEW_PORTFOLIO["现金/短债"]["weight"]

        # 日收益
        if last_value > 0:
            daily_rets.append((value - last_value) / last_value)
        last_value = value

    final_value = portfolio_values[-1]["value"] if portfolio_values else 0
    initial_total = initial_value + initial_cash
    return_pct = (final_value - initial_total) / initial_total * 100
    max_dd = compute_max_drawdown([p["value"] for p in portfolio_values])
    sharpe = compute_sharpe(daily_rets)
    return {
        "initial_value": initial_total,
        "final_value": final_value,
        "return_pct": round(return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "period_days": len(common_dates),
        "daily_values": portfolio_values[-30:],  # 最近 30 天
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
    if not daily_rets or len(daily_rets) < 2:
        return 0
    import statistics
    avg = sum(daily_rets) / len(daily_rets) * 252
    std = statistics.stdev(daily_rets) * (252 ** 0.5)
    if std == 0:
        return 0
    return (avg - risk_free) / std


def main():
    log.info("=" * 60)
    log.info("💼 10 标的 50 万组合新设计")
    log.info("=" * 60)

    # 1. 加仓计划
    log.info("\n--- 加仓计划 ---")
    compute_weekly_plan()
    for code, info in NEW_PORTFOLIO.items():
        target = TOTAL_CAPITAL * info["weight"]
        current = CURRENT_HOLDINGS.get(code, 0)
        delta = target - current
        weeks = info.get("weeks_to_complete", 0)
        weekly = info.get("weekly_amt", 0)
        if info["proxy"] is None:
            # 现金/短债
            log.info(f"  💰 {info['name']:10s} 目标¥{target:>8,.0f} ({info['weight']*100:4.1f}%) 应急 + 加仓子弹")
            continue
        emoji = "✅" if current > 0 else "🆕"
        log.info(f"  {emoji} {info['name']:10s} 目标¥{target:>8,.0f} ({info['weight']*100:4.1f}%) "
                 f"已持¥{current:>6,.0f} 加¥{max(0,delta):>7,.0f} "
                 f"周数:{weeks} 每周¥{weekly:>7,.0f} ({info['scenario']})")

    # 2. 回测
    log.info("\n--- 模拟回测 (10 标的组合) ---")
    result = simulate_v2_combined(period_days=500)
    if result:
        log.info(f"  初始: ¥{result['initial_value']:,.0f}")
        log.info(f"  最终: ¥{result['final_value']:,.0f}")
        log.info(f"  收益: {result['return_pct']:+.2f}%")
        log.info(f"  最大回撤: {result['max_drawdown_pct']:.2f}%")
        log.info(f"  年化夏普: {result['sharpe']:.2f}")
        log.info(f"  周期: {result['period_days']} 天 ({result['period_days']//252} 年)")

    # 3. 对比 4 标的原组合 (之前回测的)
    log.info("\n--- 对比: 原 4 标的组合 (3 个月窗口) ---")
    # 注: 之前 portfolio_simulation 用 252 天 1 年, 这里用 252 天可比
    log.info("  原 4 标的 (不调): +2.55% / 回撤 0.61% / 夏普 0.45")
    log.info("  原 4 标的 (分 4 周): +21.68% / 回撤 7.27% / 夏普 1.66")

    # 4. 详细保存
    output = {
        "new_portfolio": {code: {k: v for k, v in info.items() if k != "proxy"} for code, info in NEW_PORTFOLIO.items()},
        "simulation": result,
    }
    output_path = OUTPUT_DIR / "portfolio_v2.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info(f"\n💾 综合结果: {output_path}")


if __name__ == "__main__":
    main()

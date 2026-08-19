"""
简化版 10 标的组合回测 (用 Yahoo 美股 5 年真实数据)
- 5 个有数据的标的: QQQ/GLD/SPY/XLE/沪深300
- 其他 A 股 ETF 用 1 个代表指数或仅作方案不参与回测
- 修复回撤 bug
"""
import sys
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
import statistics

log = get_logger("portfolio_v2_simple")
OUTPUT_DIR = ROOT / "backtest"


def load(name):
    p = OUTPUT_DIR / f"{name}.csv"
    if not p.exists():
        return {}
    rows = {}
    with open(p, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = r.get("date") or r.get("day", "")
            try:
                c = float(r.get("close") or r.get("Close", ""))
                rows[d] = c
            except (ValueError, KeyError):
                continue
    return rows


# 5 个有数据的标的 (用 Yahoo 沪深 300 替代 A 股 ETF)
DATA = {
    "QQQ": load("qqq_10y"),
    "GLD": load("gld_10y"),
    "SPY": load("spy_10y"),
    "XLE": load("xle_10y"),
    "HS300": load("000300_SS"),  # 沪深 300
}

# 找共同日期
common = sorted(set.intersection(*[set(d.keys()) for d in DATA.values()]))
common = common[-252:]  # 1 年窗口
log.info(f"回测窗口: {common[0]} → {common[-1]} ({len(common)} 天)")

# 初始组合
INITIAL_HOLDINGS = {
    "QQQ": 10000, "GLD": 10000, "SPY": 10000, "XLE": 10000, "HS300": 0,
}

# 三个场景
SCENARIOS = [
    ("A: 维持现状 (8% 持仓)", "none", {
        "QQQ": 0.10, "GLD": 0.10, "SPY": 0.10, "XLE": 0.10, "HS300": 0.00,
    }),
    ("B: 4 标的 50/25/15/10", "rebalance_4w", {
        "QQQ": 0.25, "GLD": 0.25, "XLE": 0.10, "HS300": 0.15,
    }),
    ("C: 5 标的 加沪深300 (推荐)", "rebalance_4w", {
        "QQQ": 0.20, "GLD": 0.20, "SPY": 0.20, "XLE": 0.10, "HS300": 0.10,
    }),
]


def simulate(scenario_name, scenario_type, target_w, period=252):
    """单个场景模拟"""
    # 起点: 起点日期
    init_date = common[0]
    initial_value = 500000
    initial_total = 0
    # 已持仓 = current holding
    shares = {}
    for sym, amt in INITIAL_HOLDINGS.items():
        p = DATA[sym].get(init_date, 0)
        if p > 0 and amt > 0:
            shares[sym] = amt / p
            initial_total += amt
    cash = initial_value - initial_total  # 46 万现金

    # 调仓日期 (5, 10, 15, 20 交易日)
    rebal = set()
    if scenario_type == "rebalance_4w":
        for i in [5, 10, 15, 20]:
            if i < len(common):
                rebal.add(common[i])

    # 模拟每日
    values = []
    rets = []
    last_v = initial_value
    for date in common:
        # 计算当日价值
        v = cash
        for sym, sh in shares.items():
            p = DATA[sym].get(date, 0)
            if p > 0:
                v += sh * p
        values.append(v)
        # 调仓
        if date in rebal and v > 0:
            for sym, w in target_w.items():
                p = DATA[sym].get(date, 0)
                if p > 0:
                    target_val = v * w
                    shares[sym] = target_val / p
            # 现金 = 总 - 股票合计
            stock_total = sum(v * w for w in target_w.values())
            cash = v - stock_total
        if last_v > 0:
            rets.append((v - last_v) / last_v)
        last_v = v
    final = values[-1] if values else 0
    ret = (final - initial_value) / initial_value * 100
    # 最大回撤
    peak = values[0] if values else 0
    max_dd = 0
    for v in values:
        if v > peak: peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd: max_dd = dd
    max_dd_pct = max_dd * 100
    # 夏普
    sharpe = 0
    if len(rets) > 1:
        avg = sum(rets) / len(rets) * 252
        std = statistics.stdev(rets) * (252 ** 0.5)
        if std > 0:
            sharpe = (avg - 0.02) / std
    return {
        "scenario": scenario_name,
        "scenario_type": scenario_type,
        "initial": initial_value,
        "final": round(final, 2),
        "return_pct": round(ret, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": round(sharpe, 2),
    }


# 跑全部场景
log.info("=" * 60)
log.info("💼 简化 10 标的组合 (1 年窗口, 真实数据)")
log.info("=" * 60)
for name, stype, tw in SCENARIOS:
    log.info(f"\n--- {name} ---")
    r = simulate(name, stype, tw)
    log.info(f"  初始 ¥{r['initial']:,.0f} → 最终 ¥{r['final']:,.0f}")
    log.info(f"  收益 {r['return_pct']:+.2f}% | 回撤 {r['max_drawdown_pct']:.2f}% | 夏普 {r['sharpe']:.2f}")

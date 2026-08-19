"""
跨周期回测：4 条 QQQ 金子规则在 2000-2010 熊市周期 + 3 标的 (QQQ/SPY/GLD) 表现
目的：验证 2016-2026 牛市胜率是否在熊市也成立
数据：~/.dsh/market_intel/backtest/{ticker}_2000_2010.csv
"""
import csv
import json
from pathlib import Path
from datetime import datetime, timedelta

BACKTEST_DIR = Path("~/.dsh/market_intel/backtest").expanduser()
OUTPUT = BACKTEST_DIR / "cross_cycle_2000_2010.json"


def load_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((datetime.fromisoformat(r["date"]), float(r["close"])))
    return rows


def ma(prices, n, idx):
    if idx < n - 1:
        return None
    return sum(p for _, p in prices[idx - n + 1:idx + 1]) / n


def find_signals(prices, rule):
    """返回 [(entry_idx, exit_idx), ...] 触发位置"""
    out = []
    last_exit_idx = -1
    for i in range(250, len(prices) - rule["hold_days"]):  # MA200 需 250 历史
        if i <= last_exit_idx:
            continue  # 持仓期不重复
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


def backtest(prices, rule):
    trades = find_signals(prices, rule)
    wins = 0
    losses = 0
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
    return {
        "rule": rule["id"],
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "avg_return": round(sum(returns) / total, 2) if total else 0,
        "best": round(max(returns), 2) if returns else 0,
        "worst": round(min(returns), 2) if returns else 0,
        "expectancy": round(
            (wins / total * (sum(r for r in returns if r > 0) / wins if wins else 0))
            - (losses / total * (abs(sum(r for r in returns if r < 0)) / losses if losses else 0)),
            2,
        ) if total else 0,
        "sample_grade": (
            "✅" if total >= 30 else
            "⚠️" if total >= 10 else
            "❌"
        ),
    }


RULES = [
    {"id": "MA_CROSS_20_60", "hold_days": 90},
    {"id": "BREAKOUT_250D", "hold_days": 90},
    {"id": "TREND_MA60", "hold_days": 60},
    {"id": "MOMENTUM_20D", "hold_days": 60},
]

# 对比：2016-2026 牛市已有数据
BULL_2016_2026 = {
    "QQQ": {
        "MA_CROSS_20_60": {"trades": 13, "win_rate": 84.6, "avg_return": 7.18},
        "BREAKOUT_250D": {"trades": 15, "win_rate": 80.0, "avg_return": 7.00},
        "TREND_MA60": {"trades": 35, "win_rate": 71.4, "avg_return": 3.41},
        "MOMENTUM_20D": {"trades": 30, "win_rate": 66.7, "avg_return": 3.16},
    }
}


def main():
    tickers = ["qqq", "spy", "gld"]
    results = {"cycle": "2000-2010 (dot-com bust + 2008 GFC)", "rules": {}}

    for ticker in tickers:
        path = BACKTEST_DIR / f"{ticker}_2000_2010.csv"
        if not path.exists():
            continue
        prices = load_csv(path)
        results["rules"][ticker] = {}
        for rule in RULES:
            r = backtest(prices, rule)
            results["rules"][ticker][rule["id"]] = r

    # 跨周期对比
    results["comparison"] = {}
    for rule in RULES:
        rid = rule["id"]
        bull = BULL_2016_2026["QQQ"].get(rid, {})
        bear_qqq = results["rules"].get("qqq", {}).get(rid, {})
        results["comparison"][rid] = {
            "bull_2016_2026_QQQ": {
                "win_rate": bull.get("win_rate"),
                "avg_return": bull.get("avg_return"),
                "trades": bull.get("trades"),
            },
            "bear_2000_2010_QQQ": {
                "win_rate": bear_qqq.get("win_rate"),
                "avg_return": bear_qqq.get("avg_return"),
                "trades": bear_qqq.get("trades"),
            },
            "verdict": (
                "✅ 跨周期稳健" if (bear_qqq.get("win_rate", 0) or 0) >= 55 else
                "⚠️ 牛市有效，熊市失效 (过拟合)" if (bear_qqq.get("win_rate", 0) or 0) < 50 and (bull.get("win_rate", 0) or 0) >= 60 else
                "❌ 全周期不可用"
            ),
        }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # 打印
    print(f"=== 跨周期回测 (2000-2010 熊市 vs 2016-2026 牛市) ===\n")
    print(f"{'TICKER':<6} {'RULE':<18} {'TRADES':>7} {'WIN%':>7} {'AVG%':>7} {'SAMPLE':>8} {'VERDICT'}")
    for ticker in tickers:
        if ticker not in results["rules"]:
            continue
        for rid, r in results["rules"][ticker].items():
            v = ""
            if ticker == "qqq":
                c = results["comparison"].get(rid, {})
                v = c.get("verdict", "")
            print(f"{ticker.upper():<6} {rid:<18} {r['trades']:>7} {r['win_rate']:>6}% {r['avg_return']:>6}% {r['sample_grade']:>8} {v}")
    print(f"\n结论写入: {OUTPUT}")


if __name__ == "__main__":
    main()

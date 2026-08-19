"""
测试多个候选过滤器，找出真正改善熊市表现的过滤器

候选：
1. VIX > 30 (恐慌)
2. VIX > 35 (极度恐慌)
3. QQQ < MA200 (市场已破位)
4. QQQ < MA200 OR VIX > 35 (组合)
"""
import csv
import json
from pathlib import Path
from datetime import datetime
from bisect import bisect_left

BACKTEST_DIR = Path("~/.dsh/market_intel/backtest").expanduser()
OUTPUT = BACKTEST_DIR / "filter_comparison.json"


def load_csv(path, date_col, val_col):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.fromisoformat(r[date_col]).date()
                v = float(r[val_col])
                out.append((d, v))
            except (ValueError, KeyError):
                continue
    out.sort()
    return out


def load_vix_yahoo(ticker, p1, p2):
    import urllib.request, json as j
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d&events=history"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = j.loads(resp.read())
    r = data["chart"]["result"][0]
    ts = r["timestamp"]
    closes = r["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, closes):
        if c is None: continue
        d = datetime.fromtimestamp(t).date()
        out.append((d, c))
    return out


def value_on_or_before(dates_values, target_date):
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


def find_signals_filtered(prices, rule, filter_check):
    out = []
    last_exit_idx = -1
    for i in range(250, len(prices) - rule["hold_days"]):
        if i <= last_exit_idx:
            continue
        date_i = prices[i][0]
        if filter_check(date_i, i, prices):
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
            out.append((i, min(i + rule["hold_days"], len(prices) - 1)))
            last_exit_idx = out[-1][1]
    return out


def backtest(prices, rule, filter_check):
    trades = find_signals_filtered(prices, rule, filter_check)
    wins = losses = 0
    returns = []
    for ei, xi in trades:
        ret = (prices[xi][1] - prices[ei][1]) / prices[ei][1] * 100
        returns.append(ret)
        if ret > 0: wins += 1
        else: losses += 1
    total = wins + losses
    if total == 0:
        return {"trades": 0, "win_rate": 0, "avg_return": 0, "expectancy": 0}
    avg_w = sum(r for r in returns if r > 0) / wins if wins else 0
    avg_l = sum(r for r in returns if r < 0) / losses if losses else 0
    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1),
        "avg_return": round(sum(returns) / total, 2),
        "expectancy": round((wins/total*avg_w) - (losses/total*abs(avg_l)), 2),
    }


RULES = [
    {"id": "MA_CROSS_20_60", "hold_days": 90},
    {"id": "BREAKOUT_250D", "hold_days": 90},
    {"id": "TREND_MA60", "hold_days": 60},
    {"id": "MOMENTUM_20D", "hold_days": 60},
]

# 基线
BASELINE_QQQ_2000_2010 = {
    "MA_CROSS_20_60": {"trades": 15, "win_rate": 60.0, "avg_return": -2.45, "expectancy": 0},
    "BREAKOUT_250D":   {"trades": 7,  "win_rate": 71.4, "avg_return": 1.88, "expectancy": 0},
    "TREND_MA60":      {"trades": 25, "win_rate": 60.0, "avg_return": -0.39, "expectancy": 0},
    "MOMENTUM_20D":    {"trades": 27, "win_rate": 55.6, "avg_return": 0.17, "expectancy": 0},
}
BASELINE_QQQ_2016_2026 = {
    "MA_CROSS_20_60": {"trades": 13, "win_rate": 84.6, "avg_return": 7.18, "expectancy": 0},
    "BREAKOUT_250D":   {"trades": 15, "win_rate": 80.0, "avg_return": 7.00, "expectancy": 0},
    "TREND_MA60":      {"trades": 35, "win_rate": 71.4, "avg_return": 3.41, "expectancy": 0},
    "MOMENTUM_20D":    {"trades": 30, "win_rate": 66.7, "avg_return": 3.16, "expectancy": 0},
}


def main():
    print("拉 VIX 2000-2010...")
    vix_2000_2010 = load_vix_yahoo("^VIX", 946684800, 1262304000)
    with open('~/.dsh/market_intel/backtest/vix_2000_2010.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'close'])
        for d, v in vix_2000_2010:
            w.writerow([d.isoformat(), v])
    print(f"  {len(vix_2000_2010)} rows")

    # 2016-2026 VIX 已有
    vix_2016_2026 = load_csv(BACKTEST_DIR / "vix_10y.csv", "date", "close")
    print(f"  2016-2026 VIX: {len(vix_2016_2026)} rows")

    # QQQ 价格
    qqq_2000_2010 = load_csv(BACKTEST_DIR / "qqq_2000_2010.csv", "date", "close")
    qqq_2016_2026 = load_csv(BACKTEST_DIR / "qqq_10y.csv", "date", "close")
    print(f"  QQQ 2000-2010: {len(qqq_2000_2010)} rows, 2016-2026: {len(qqq_2016_2026)} rows")

    # 候选过滤器
    def make_filter_vix(threshold, vix_data):
        def f(date, idx, prices):
            v = value_on_or_before(vix_data, date)
            return v is not None and v > threshold
        return f

    def make_filter_ma200_below(prices):
        def f(date, idx, _):
            m200 = ma(prices, 200, idx)
            return m200 is not None and prices[idx][1] < m200
        return f

    def make_filter_vix_or_ma200(vix_data, threshold, prices):
        def f(date, idx, _):
            v = value_on_or_before(vix_data, date)
            if v is not None and v > threshold: return True
            m200 = ma(prices, 200, idx)
            if m200 is not None and prices[idx][1] < m200: return True
            return False
        return f

    filters = {
        "no_filter": lambda d, i, p: False,
        "vix>30":    make_filter_vix(30, vix_2000_2010),  # placeholder
        "vix>35":    make_filter_vix(35, vix_2000_2010),
        "qqq<ma200": make_filter_ma200_below(qqq_2000_2010),
    }
    # 修正 vix>30 (用闭包)
    filters["vix>30"] = make_filter_vix(30, vix_2000_2010)
    filters["vix_or_ma200"] = make_filter_vix_or_ma200(vix_2000_2010, 35, qqq_2000_2010)

    periods = {
        "2000-2010 (熊市)": (qqq_2000_2010, BASELINE_QQQ_2000_2010),
        "2016-2026 (牛市)": (qqq_2016_2026, BASELINE_QQQ_2016_2026),
    }

    # 修正过滤器（vix data 按 period 用）
    vix_by_period = {
        "2000-2010 (熊市)": vix_2000_2010,
        "2016-2026 (牛市)": vix_2016_2026,
    }
    filters_by_period = {
        period: {
            "no_filter": lambda d, i, p: False,
            "vix>30": make_filter_vix(30, vix_by_period[period]),
            "vix>35": make_filter_vix(35, vix_by_period[period]),
            "qqq<ma200": make_filter_ma200_below(prices),
            "vix>35 OR qqq<ma200": make_filter_vix_or_ma200(vix_by_period[period], 35, prices),
        }
        for period, (prices, _) in periods.items()
    }

    print(f"\n=== 多过滤器对比 ===\n")
    print(f"{'PERIOD':<18} {'FILTER':<18} {'RULE':<18} {'TRADES':>7} {'WIN%':>7} {'AVG%':>7} {'EXP':>7} {'VERDICT'}")
    results = {"filters": {}}
    for period, (prices, baseline) in periods.items():
        results["filters"][period] = {}
        for fname, fcheck in filters_by_period[period].items():
            results["filters"][period][fname] = {}
            for rule in RULES:
                r = backtest(prices, rule, fcheck)
                base = baseline.get(rule["id"], {})
                # 比较基线
                win_improved = r["win_rate"] > base.get("win_rate", 0)
                ret_improved = r["avg_return"] > base.get("avg_return", 0)
                exp_pos = r["expectancy"] > 0
                verdict = "✅" if (win_improved and ret_improved and exp_pos) else ("⚠️" if exp_pos else "❌")
                results["filters"][period][fname][rule["id"]] = {
                    **r,
                    "baseline_win_rate": base.get("win_rate"),
                    "baseline_avg_return": base.get("avg_return"),
                    "win_improved": win_improved,
                    "ret_improved": ret_improved,
                    "exp_pos": exp_pos,
                }
                print(f"{period:<18} {fname:<18} {rule['id']:<18} {r['trades']:>7} {r['win_rate']:>6}% {r['avg_return']:>6}% {r['expectancy']:>6} {verdict}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果: {OUTPUT}")


if __name__ == "__main__":
    main()

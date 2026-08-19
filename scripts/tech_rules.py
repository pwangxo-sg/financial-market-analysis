"""
技术面规则扩展
- 动量跟踪 (Momentum)
- 突破新高 (Breakout)
- 趋势跟踪 (MA Cross)
- 波动率收缩突破 (Squeeze)
样本量充足, 适合用 QQQ 10 年数据回测
"""
import sys
import json
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime, timedelta

log = get_logger("tech_rules")
OUTPUT_DIR = ROOT / "backtest"


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
    """计算 i 处 period 日均线"""
    if i < period - 1:
        return None
    vals = [prices[dates[i-j]] for j in range(period) if dates[i-j] in prices]
    if len(vals) < period:
        return None
    return sum(vals) / period


def backtest_tech_rule(name, asset, signal_type, hold_days, trigger_fn):
    """
    通用技术面规则回测
    trigger_fn(date_idx, dates, prices, indicator_dict) -> bool
    """
    dates = sorted(asset.keys())
    trades = []
    i = 250  # skip 前 250 天 (用于 MA250)
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
        return {"rule": name, "trades": 0, "win_rate": 0, "avg_return": 0}

    if signal_type == "add":
        wins = sum(1 for t in trades if t["return_pct"] > 0)
    else:
        wins = sum(1 for t in trades if t["return_pct"] < 0)
    return {
        "rule": name,
        "signal_type": signal_type,
        "trades": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades), 3),
        "avg_return": round(sum(t["return_pct"] for t in trades) / len(trades), 2),
    }


# ============== 规则 1: 动量跟踪 (20 日 +5%-15%) ==============
def momentum_long(i, dates, prices):
    """20 日涨幅 5%-15% (强势但非超买)"""
    if i < 20:
        return False
    past_20 = prices[dates[i-20]]
    current = prices[dates[i]]
    pct = (current - past_20) / past_20
    return 0.05 < pct < 0.15


# ============== 规则 2: MA20 上穿 MA60 (金叉) ==============
def ma_cross_golden(i, dates, prices):
    """MA20 上穿 MA60"""
    if i < 65:
        return False
    ma20_now = ma(prices, dates, i, 20)
    ma60_now = ma(prices, dates, i, 60)
    ma20_prev = ma(prices, dates, i-3, 20)
    ma60_prev = ma(prices, dates, i-3, 60)
    if None in (ma20_now, ma60_now, ma20_prev, ma60_prev):
        return False
    return ma20_prev < ma60_prev and ma20_now > ma60_now


# ============== 规则 3: 250 日新高突破 ==============
def new_high_breakout(i, dates, prices):
    """突破 250 日新高"""
    if i < 250:
        return False
    past_250_high = max(prices[dates[i-j]] for j in range(250) if dates[i-j] in prices)
    current = prices[dates[i]]
    return current >= past_250_high * 0.999  # 99.9% 算新高


# ============== 规则 4: VIX 突降 (恐慌缓解) ==============
def vix_spike_relief(i, dates, prices):
    """VIX 5 日内降 > 30% (恐慌缓解, 反向买)"""
    # 注: 需要 vix 数据
    return False  # 这里跳过, 单独跑


# ============== 规则 5: 60 日趋势 (价格在 MA60 上) ==============
def trend_above_ma60(i, dates, prices):
    """首次站上 MA60 (回踩后)"""
    if i < 65:
        return False
    current = prices[dates[i]]
    ma60 = ma(prices, dates, i, 60)
    if ma60 is None:
        return False
    # 当前价 > MA60
    return current > ma60 * 1.005  # 略高于 MA60


def main():
    log.info("=" * 60)
    log.info("🧪 技术面规则扩展回测 (10 年 QQQ)")
    log.info("=" * 60)

    qqq = load_csv("qqq_10y")
    log.info(f"  QQQ: {len(qqq)} 天")

    rules = [
        ("MOMENTUM_20D", "add", 60, momentum_long, "20日涨幅 5-15% (动量)"),
        ("MA_CROSS_20_60", "add", 90, ma_cross_golden, "MA20 上穿 MA60 (金叉)"),
        ("BREAKOUT_250D", "add", 90, new_high_breakout, "突破 250 日新高"),
        ("TREND_ABOVE_MA60", "add", 60, trend_above_ma60, "首次站上 MA60"),
    ]

    results = []
    for rid, sig, hd, fn, desc in rules:
        r = backtest_tech_rule(rid, qqq, sig, hd, fn)
        r["description"] = desc
        results.append(r)
        log.info(f"  {r['rule']:20s}: 触发{r['trades']:3d}次 | 胜率{r['win_rate']*100:5.1f}% | 收益{r['avg_return']:+6.2f}%  ({desc})")

    log.info("\n" + "=" * 60)
    log.info("📊 总结 (按胜率排序)")
    log.info("=" * 60)
    for r in sorted(results, key=lambda x: -x["win_rate"]):
        emoji = "✅" if r["win_rate"] > 0.55 else ("⚠️" if r["win_rate"] > 0.45 else "❌")
        log.info(f"  {emoji} {r['rule']:20s}: {r['trades']}次触发, 胜率{r['win_rate']*100:.1f}%, 收益{r['avg_return']:+.2f}%")

    output_path = OUTPUT_DIR / "tech_rules_result.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 结果: {output_path}")


if __name__ == "__main__":
    main()

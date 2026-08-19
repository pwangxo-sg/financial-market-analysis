"""
简化回测 demo
- 数据: QQQ 5 年 daily (Yahoo) + Treasury 5 年 TIPS
- 规则: GOLD_REAL_01 实际利率 < 0.5% → 加仓
- 跑回测, 计算胜率
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, safe_get
from datetime import datetime, timedelta
import csv

log = get_logger("backtest_demo")
OUTPUT_DIR = ROOT / "backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_yahoo_history(symbol, range_str="5y", interval="1d"):
    """拉 Yahoo 历史数据"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_str}"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    if not resp:
        return None
    data = resp.json()
    result = data.get("chart", {}).get("result", [{}])[0]
    if not result:
        return None
    ts = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    if not ts or not closes:
        return None
    # 转 dict by date
    from datetime import datetime as _dt
    rows = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        date = _dt.fromtimestamp(t).strftime("%Y-%m-%d")
        rows.append({"date": date, "close": c})
    return rows


def load_treasury_real(csv_path):
    """读 Treasury TIPS CSV"""
    from datetime import datetime as _dt
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            date_str = r.get("Date", "")
            try:
                d = _dt.strptime(date_str, "%m/%d/%Y")
                iso = d.strftime("%Y-%m-%d")
            except Exception:
                continue
            # TIPS CSV 列名是 "10 YR" (大写) — 兼容
            real_10y = r.get("10 YR", "") or r.get("10 Yr", "")
            if real_10y and real_10y != "":
                try:
                    rows.append({"date": iso, "us10y_real": float(real_10y)})
                except ValueError:
                    continue
    return rows


def backtest_rule(rule_id, asset_data, indicator_data, rule_threshold, hold_days=30, label=""):
    """
    简化回测: 当指标满足阈值时, 记录"加仓", hold_days 天后看结果
    返回胜率 + 平均收益
    """
    # 合并数据
    asset_dict = {r["date"]: r["close"] for r in asset_data}
    ind_dict = {r["date"]: r.get("us10y_real", 0) for r in indicator_data}
    dates = sorted(set(asset_dict.keys()) & set(ind_dict.keys()))
    if not dates:
        return None

    log.info(f"  {label} 回测: {len(dates)} 天共同数据")

    trades = []
    i = 0
    while i < len(dates) - hold_days:
        date = dates[i]
        indicator = ind_dict[date]
        if indicator is None:
            i += 1
            continue
        # 检查规则: 实际利率 < 0.5%
        triggered = indicator < rule_threshold
        if triggered:
            entry_date = date
            entry_price = asset_dict[date]
            # 找 hold_days 天后
            if i + hold_days < len(dates):
                exit_date = dates[i + hold_days]
                exit_price = asset_dict[exit_date]
                ret = (exit_price - entry_price) / entry_price
                trades.append({
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "indicator": round(indicator, 3),
                })
            i += hold_days  # 触发后跳过 hold_days 防重叠
        else:
            i += 1

    if not trades:
        return {"rule": rule_id, "trades": 0, "win_rate": 0, "avg_return": 0, "label": label}

    wins = sum(1 for t in trades if t["return_pct"] > 0)
    win_rate = wins / len(trades)
    avg_return = sum(t["return_pct"] for t in trades) / len(trades)

    return {
        "rule": rule_id,
        "label": label,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate": round(win_rate, 3),
        "avg_return_pct": round(avg_return, 2),
        "trades_detail": trades[:10],  # 前 10 个样本
    }


def main():
    from datetime import datetime as _dt
    log.info("=" * 60)
    log.info("🧪 简化回测 demo")
    log.info("=" * 60)

    # 1. 拉 QQQ 5 年 daily
    log.info("\n--- 拉 QQQ 5 年历史 ---")
    qqq = fetch_yahoo_history("QQQ", "5y", "1d")
    if not qqq:
        log.error("QQQ 拉取失败")
        return
    log.info(f"  ✅ QQQ: {len(qqq)} 天 ({qqq[-1]['date']} → {qqq[0]['date']})")
    # 保存
    csv_path = OUTPUT_DIR / "qqq_5y.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "close"])
        w.writeheader()
        w.writerows(qqq)

    # 2. 拉 GLD 5 年
    log.info("\n--- 拉 GLD 5 年历史 ---")
    gld = fetch_yahoo_history("GLD", "5y", "1d")
    if gld:
        log.info(f"  ✅ GLD: {len(gld)} 天")
        with open(OUTPUT_DIR / "gld_5y.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "close"])
            w.writeheader()
            w.writerows(gld)
    else:
        gld = []

    # 3. 加载 Treasury TIPS 5 年
    log.info("\n--- 加载 Treasury TIPS 5 年 ---")
    tips_path = ROOT / "backtest" / "treasury_history" / "treasury_real_5y.csv"
    tips = load_treasury_real(tips_path)
    if not tips:
        log.error(f"TIPS 加载失败: {tips_path}")
        return
    log.info(f"  ✅ TIPS: {len(tips)} 天 ({tips[-1]['date']} → {tips[0]['date']})")

    # 4. 多个规则回测
    log.info("\n--- 多规则回测 ---")
    backtest_results = {}

    # 规则列表: (rule_id, 标的, 指标, 阈值, 持仓天数, 方向, 标签)
    rules_to_test = [
        ("GOLD_REAL_01", gld, tips, "us10y_real", 0.5, 90, "below", "黄金: 实际利率<0.5% → 加仓 90天"),
        ("GOLD_DXY_01", gld, None, None, None, None, None, "黄金: DXY>106 + 实际>2% → 减仓 (无 DXY 历史)"),  # DXY 暂无历史, 跳过
        ("NDX_RATE_01", qqq, None, None, None, None, None, "纳指: 10Y>4.5% + VIX>25 → 减仓 (无 VIX 历史)"),  # VIX 暂无历史
        ("NDX_PULLBACK_01", qqq, qqq, "close", 0, 5, "drawdown_5pct_1w", "纳指: 1周跌>5% + VIX<30 → 加仓 60天"),
    ]

    # 简化: 跑 GLD 2 条 + QQQ 1 条 pullback
    if gld and tips:
        for threshold, hold, label in [(0.5, 90, "GLD 实际利率<0.5% 90天"), (0.0, 90, "GLD 实际利率<0% 90天"), (1.0, 90, "GLD 实际利率<1.0% 90天")]:
            r = backtest_rule(f"GLD_REAL<{threshold}", gld, tips, rule_threshold=threshold, hold_days=hold, label=label)
            if r:
                backtest_results[f"GLD_REAL<{threshold}"] = r
                log.info(f"  {label}: 触发{r['trades']}次, 胜率{r['win_rate']*100:.0f}%, 平均收益{r['avg_return_pct']:+.2f}%")

    # QQQ pullback (5天跌>5% → 60天)
    if qqq:
        # 简化实现: 5天滚动最低/最高
        trades = []
        for i in range(60, len(qqq) - 60):
            entry_date = qqq[i]["date"]
            entry_price = qqq[i]["close"]
            past_5d = qqq[i-5:i]
            if not past_5d:
                continue
            max_5d = max(r["close"] for r in past_5d)
            drop_pct = (entry_price - max_5d) / max_5d
            if drop_pct < -0.05:  # 跌超过 5%
                # 60天后看
                exit_price = qqq[i+60]["close"]
                ret = (exit_price - entry_price) / entry_price
                trades.append({"date": entry_date, "drop_pct": round(drop_pct*100, 2), "return_pct": round(ret*100, 2)})
        if trades:
            wins = sum(1 for t in trades if t["return_pct"] > 0)
            wr = wins / len(trades)
            avg = sum(t["return_pct"] for t in trades) / len(trades)
            log.info(f"\n  QQQ 5天跌>5% → 60天后: 触发{len(trades)}次, 胜率{wr*100:.0f}%, 平均收益{avg:+.2f}%")
            backtest_results["QQX_5D_DROP_5PCT"] = {
                "trades": len(trades), "wins": wins, "win_rate": round(wr, 3), "avg_return_pct": round(avg, 2),
                "trades_detail": trades[:10],
            }

    # 5. 保存回测结果
    output_json = OUTPUT_DIR / "backtest_demo_result.json"
    output_json.write_text(json.dumps(backtest_results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 结果保存: {output_json}")

    log.info("\n" + "=" * 60)
    log.info("📊 总结:")
    log.info("=" * 60)
    for rid, r in backtest_results.items():
        log.info(f"  {rid:30s}: 触发{r['trades']:3d}次 | 胜率{r['win_rate']*100:5.1f}% | 平均收益{r['avg_return_pct']:+6.2f}%")


if __name__ == "__main__":
    main()

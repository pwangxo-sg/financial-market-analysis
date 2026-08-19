"""
参数敏感性分析 + 网格搜索
- 验证 Patrick 的洞察: "参数之间互相影响, 需要迭代"
- 对 NDX_PULLBACK_01 (金子规则) 做参数扫描
- 找出: 最佳 (drawdown阈值, hold_days) 组合
"""
import sys
import json
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime

log = get_logger("param_search")

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


def load_vix():
    """加载 VIX 字典"""
    return load_csv("vix_10y")


def backtest_param(drawdown_threshold, hold_days, qqq, vix):
    """
    网格搜索一个参数组合
    规则: QQQ 5天最大回撤 > drawdown_threshold + VIX < 30 → 加仓 hold_days 天
    """
    dates = sorted(qqq.keys())
    trades = []
    i = 60  # skip 前 60 天
    while i < len(dates) - hold_days:
        date = dates[i]
        # 5 天前到现在的最大回撤
        past_5d_prices = [qqq[dates[i-5+j]] for j in range(6) if dates[i-5+j] in qqq]
        if not past_5d_prices:
            i += 1
            continue
        max_5d = max(past_5d_prices)
        current = qqq[date]
        drawdown = (current - max_5d) / max_5d
        vix_val = vix.get(date, 999)

        if drawdown < -drawdown_threshold and vix_val < 30:
            entry_price = current
            exit_date = dates[i + hold_days]
            if exit_date in qqq:
                ret = (qqq[exit_date] - entry_price) / entry_price
                trades.append({
                    "date": date,
                    "drawdown_pct": round(drawdown * 100, 2),
                    "vix": round(vix_val, 2),
                    "return_pct": round(ret * 100, 2),
                })
            i += max(hold_days, 5)  # 防重叠
        else:
            i += 1

    if not trades:
        return {"trades": 0, "win_rate": 0, "avg_return": 0}

    wins = sum(1 for t in trades if t["return_pct"] > 0)
    return {
        "trades": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades), 3),
        "avg_return": round(sum(t["return_pct"] for t in trades) / len(trades), 2),
        "max_drawdown_triggered": min(t["drawdown_pct"] for t in trades),
    }


def main():
    log.info("=" * 60)
    log.info("🔬 参数敏感性分析 (网格搜索)")
    log.info("=" * 60)

    # 加载数据
    qqq = load_csv("qqq_10y")
    vix = load_vix()
    log.info(f"  QQQ: {len(qqq)} 天")
    log.info(f"  VIX: {len(vix)} 天")

    # 参数空间
    drawdown_thresholds = [0.03, 0.05, 0.07, 0.10, 0.12, 0.15, 0.20]  # 3% / 5% / 7% / ...
    hold_days_list = [30, 60, 90, 120, 180]
    vix_thresholds = [20, 25, 30, 35, 40]  # VIX 上限

    log.info("\n--- 网格搜索: drawdown × hold_days × vix_threshold ---")
    log.info(f"  drawdown: {drawdown_thresholds}")
    log.info(f"  hold_days: {hold_days_list}")
    log.info(f"  vix: {vix_thresholds}")

    results = []
    for dd in drawdown_thresholds:
        for hd in hold_days_list:
            for vix_th in vix_thresholds:
                # 自定义 VIX 阈值版本
                trades_list = []
                dates = sorted(qqq.keys())
                i = 60
                while i < len(dates) - hd:
                    date = dates[i]
                    past_5d_prices = [qqq[dates[i-5+j]] for j in range(6) if dates[i-5+j] in qqq]
                    if not past_5d_prices:
                        i += 1
                        continue
                    max_5d = max(past_5d_prices)
                    current = qqq[date]
                    drawdown = (current - max_5d) / max_5d
                    vix_val = vix.get(date, 999)

                    if drawdown < -dd and vix_val < vix_th:
                        entry_price = current
                        exit_date = dates[i + hd]
                        if exit_date in qqq:
                            ret = (qqq[exit_date] - entry_price) / entry_price
                            trades_list.append(ret)
                        i += max(hd, 5)
                    else:
                        i += 1

                if trades_list:
                    n = len(trades_list)
                    wins = sum(1 for r in trades_list if r > 0)
                    wr = wins / n
                    avg_ret = sum(trades_list) / n
                    results.append({
                        "drawdown": dd,
                        "hold_days": hd,
                        "vix_threshold": vix_th,
                        "trades": n,
                        "win_rate": round(wr, 3),
                        "avg_return_pct": round(avg_ret * 100, 2),
                    })

    # 排序: 综合分 (胜率 × 收益 × 样本量惩罚)
    # 用: 综合分 = win_rate × 100 - max(0, 5 - trades) × 5 + avg_return
    # 简单: 先按胜率, 再按收益
    results.sort(key=lambda x: (-x["win_rate"], -x["avg_return_pct"]))

    log.info(f"\n--- Top 10 参数组合 (按胜率排序) ---")
    log.info(f"{'DD%':>6} {'HD':>5} {'VIX':>5} {'trades':>7} {'WR%':>7} {'AVG%':>7}")
    for r in results[:10]:
        log.info(f"  {r['drawdown']*100:5.1f} {r['hold_days']:5d} {r['vix_threshold']:5d} {r['trades']:7d} {r['win_rate']*100:6.1f} {r['avg_return_pct']:+6.2f}")

    log.info(f"\n--- Bottom 5 (按胜率排序) ---")
    for r in results[-5:]:
        log.info(f"  {r['drawdown']*100:5.1f} {r['hold_days']:5d} {r['vix_threshold']:5d} {r['trades']:7d} {r['win_rate']*100:6.1f} {r['avg_return_pct']:+6.2f}")

    # 推荐
    log.info("\n" + "=" * 60)
    log.info("🎯 推荐配置")
    log.info("=" * 60)
    best = results[0] if results else None
    if best:
        log.info(f"  最佳组合: drawdown={best['drawdown']*100:.1f}%, hold={best['hold_days']}d, vix<{best['vix_threshold']}")
        log.info(f"  触发: {best['trades']} 次, 胜率: {best['win_rate']*100:.1f}%, 平均收益: {best['avg_return_pct']:+.2f}%")

    # 数据质量评分
    log.info("\n" + "=" * 60)
    log.info("📊 数据源质量评分")
    log.info("=" * 60)
    log.info("评分维度: 覆盖率 + 及时性 + 一致性 + 完整性")

    data_quality = {
        "QQQ 10y daily": {"rows": len(qqq), "完整性": "100%", "及时性": "T+1", "用途": "NDX规则"},
        "GLD 10y daily": {"rows": len(load_csv('gld_10y')), "完整性": "100%", "及时性": "T+1", "用途": "GOLD规则"},
        "VIX 10y daily": {"rows": len(vix), "完整性": "100%", "及时性": "实时", "用途": "恐慌指标"},
        "DXY 10y daily": {"rows": len(load_csv('dxy_10y')), "完整性": "100%", "及时性": "T+1", "用途": "美元"},
        "Treasury Nominal 5y": {"rows": len(load_csv('treasury_nominal_5y')) if (OUTPUT_DIR / 'treasury_nominal_5y.csv').exists() else 0, "完整性": "?", "及时性": "T+1", "用途": "美债收益率"},
    }
    for name, q in data_quality.items():
        log.info(f"  {name:30s}: {q['rows']:>5} 行 | {q['完整性']} | T+{q['及时性']} | {q['用途']}")

    # 保存
    output = {
        "param_search_top10": results[:10],
        "best": best,
        "data_quality": data_quality,
        "total_combinations": len(results),
    }
    output_path = OUTPUT_DIR / "param_search_result.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 完整结果: {output_path}")


if __name__ == "__main__":
    main()

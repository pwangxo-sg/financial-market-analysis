"""
完整规则回测
- 遍历 15 条规则
- 用 10 年日线数据评估实际胜率
- 输出胜率表 + 表现分级
"""
import sys
import json
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime, timedelta

log = get_logger("full_backtest")

OUTPUT_DIR = ROOT / "backtest"

# ============== 加载数据 ==============
def load_csv(name):
    """加载 CSV → dict[date] = close"""
    path = OUTPUT_DIR / f"{name}.csv"
    if not path.exists():
        log.warning(f"  ❌ {name} 不存在")
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


def load_treasury_csv(name, key):
    """加载 Treasury CSV (Date + 列名)"""
    # 兼容两个位置
    paths = [
        ROOT / "backtest" / "treasury_history" / f"{name}.csv",
        ROOT / "backtest" / f"{name}.csv",
    ]
    for path in paths:
        if path.exists():
            rows = {}
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    date = r.get("Date", "")
                    try:
                        d = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
                    except ValueError:
                        continue
                    val = r.get(key, "")
                    try:
                        rows[d] = float(val)
                    except ValueError:
                        continue
            return rows
    return {}


# ============== 通用回测器 ==============
def backtest_single_rule(
    rule_id, signal_type, hold_days,
    entry_dates, asset_dict,
):
    """
    给定一组入场日期 + 标的 close, 跑 hold_days 后出场
    返回: {trades, wins, win_rate, avg_return}
    """
    if not entry_dates:
        return {"rule_id": rule_id, "trades": 0, "win_rate": 0, "avg_return_pct": 0}

    dates_sorted = sorted(asset_dict.keys())
    trades = []
    for entry_date in entry_dates:
        # 找 entry_date 在 dates_sorted 中的索引
        try:
            i = dates_sorted.index(entry_date)
        except ValueError:
            # 找最接近的
            for j, d in enumerate(dates_sorted):
                if d >= entry_date:
                    i = j
                    break
            else:
                continue
        if i + hold_days >= len(dates_sorted):
            continue
        entry_price = asset_dict[entry_date]
        exit_date = dates_sorted[i + hold_days]
        exit_price = asset_dict[exit_date]
        ret = (exit_price - entry_price) / entry_price
        trades.append({"date": entry_date, "return_pct": round(ret * 100, 3)})

    if not trades:
        return {"rule_id": rule_id, "trades": 0, "win_rate": 0, "avg_return_pct": 0}

    if signal_type == "add":
        wins = sum(1 for t in trades if t["return_pct"] > 0)
    elif signal_type == "reduce":
        # 减仓信号: 标的应该跌, 所以"胜"= 跌
        wins = sum(1 for t in trades if t["return_pct"] < 0)
    else:
        wins = 0  # hold 不好评估

    return {
        "rule_id": rule_id,
        "signal_type": signal_type,
        "trades": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades), 3) if trades else 0,
        "avg_return_pct": round(sum(t["return_pct"] for t in trades) / len(trades), 2),
        "sample_returns": trades[:5],
    }


# ============== 规则触发逻辑 ==============
def find_trigger_dates(rule, indicators_dict):
    """
    给定规则, 找出所有触发日期
    indicators_dict: {date: {indicator_name: value}}
    """
    rule_id = rule["rule_id"]
    signal_type = rule["signal_type"]
    indicators = rule["indicators"]
    trigger_dates = []

    for date, inds in sorted(indicators_dict.items()):
        ok = True
        any_data = False
        for cond in indicators:
            name = cond["name"]
            op = cond["operator"]
            target = cond["value"]
            actual = inds.get(name)
            if actual is None:
                # 数据缺失
                continue
            any_data = True
            if op == ">" and not (actual > target):
                ok = False
                break
            elif op == "<" and not (actual < target):
                ok = False
                break
            elif op == ">=" and not (actual >= target):
                ok = False
                break
            elif op == "<=" and not (actual <= target):
                ok = False
                break
        if ok and any_data:
            trigger_dates.append(date)

    # 防重叠: 同规则触发后 skip hold_days
    if rule.get("hold_days"):
        skip = rule["hold_days"]
        filtered = []
        last = None
        for d in sorted(trigger_dates):
            if last is None:
                filtered.append(d)
                last = d
            else:
                last_dt = datetime.strptime(last, "%Y-%m-%d")
                cur_dt = datetime.strptime(d, "%Y-%m-%d")
                if (cur_dt - last_dt).days >= skip:
                    filtered.append(d)
                    last = d
        return filtered
    return trigger_dates


# ============== 标的映射 ==============
ASSET_MAP = {
    "012752": "qqq_10y",  # 纳指
    "022653": "gld_10y",  # 黄金
    "025857": "spy_10y",  # 电网 (用 SPY 代理, 后续用行业 ETF 替换)
    "020274": "xle_10y",  # 化工 (用 XLE 代理)
}


def build_indicators_dict(rules, treasury_nominal, treasury_real, vix, dxy, asset_data, intel_db_count):
    """
    构建 {date: {indicator: value}} 给规则评估用
    """
    # 找公共日期范围
    all_dates = set(treasury_nominal.keys()) & set(treasury_real.keys()) & set(vix.keys()) & set(dxy.keys())
    all_dates &= set(asset_data.get("qqq_10y", {}).keys())

    indicators_dict = {}
    for date in sorted(all_dates):
        inds = {}
        # Treasury
        if date in treasury_nominal:
            inds["us10y"] = treasury_nominal[date]
            inds["us2y"] = treasury_nominal.get(date, 0)  # 需要 us2y 单独
        if date in treasury_real:
            inds["us10y_real"] = treasury_real[date]
        if date in vix:
            inds["vix"] = vix[date]
        if date in dxy:
            inds["dxy"] = dxy[date]
        # 标的涨跌
        if date in asset_data.get("qqq_10y", {}):
            # 5 天涨跌幅
            qqq_dates = sorted(asset_data["qqq_10y"].keys())
            if date in qqq_dates:
                i = qqq_dates.index(date)
                if i >= 5:
                    past_5d = qqq_dates[i-5]
                    if past_5d in asset_data["qqq_10y"]:
                        inds["ndx_1w_pct"] = (asset_data["qqq_10y"][date] - asset_data["qqq_10y"][past_5d]) / asset_data["qqq_10y"][past_5d]
                if i >= 21:  # 1 月 ≈ 21 工作日
                    past_30d = qqq_dates[i-21]
                    if past_30d in asset_data["qqq_10y"]:
                        inds["ndx_1m_pct"] = (asset_data["qqq_10y"][date] - asset_data["qqq_10y"][past_30d]) / asset_data["qqq_10y"][past_30d]
        if date in asset_data.get("xle_10y", {}):
            xle_dates = sorted(asset_data["xle_10y"].keys())
            if date in xle_dates:
                i = xle_dates.index(date)
                if i >= 21:
                    past_30d = xle_dates[i-21]
                    if past_30d in asset_data["xle_10y"]:
                        inds["chem_1m_pct"] = (asset_data["xle_10y"][date] - asset_data["xle_10y"][past_30d]) / asset_data["xle_10y"][past_30d]
        # 地缘事件: 用静态值 (缺历史)
        inds["geopolitical_severity_count_4plus"] = 1  # 平均 < 1, 不太可能触发 GOLD_GEOPOL_01
        # 其他: 静态/缺数据, 跳过
        indicators_dict[date] = inds

    return indicators_dict


def main():
    log.info("=" * 60)
    log.info("📊 完整规则回测 (10 年数据)")
    log.info("=" * 60)

    # 1. 加载所有数据
    log.info("\n--- 加载数据 ---")
    # 用新 backtest_indicators 模块 (接入 6 个新 CSV + 历史真实数据)
    from backtest_indicators import build_full_indicators
    indicators_dict = build_full_indicators()
    log.info(f"  build_full_indicators: {len(indicators_dict)} 天")

    # 兼容老版: build_indicators_dict 仍需 asset_data (实际回测买卖用)
    # ASSET_MAP 键是 csv 文件名 (如 qqq_10y), 老 load_csv() 读本地
    asset_data = {}
    for label, csv_name in ASSET_MAP.items():
        asset_data[csv_name] = load_csv(csv_name)
        log.info(f"  {csv_name}: {len(asset_data[csv_name])} 天")

    # 2. 构建指标字典 - 直接用新 build_full_indicators 输出
    log.info(f"\n--- 公共日期: {len(indicators_dict)} 天 ---")

    # 3. 加载规则
    from rule_engine import RULES
    log.info(f"\n--- 评估 {len(RULES)} 条规则 ---")

    results = []
    for rule in RULES:
        rid = rule["rule_id"]
        signal_type = rule["signal_type"]
        targets = rule["target_codes"]
        hold_days = rule.get("hold_days", 60)

        # 找触发日期
        trigger_dates = find_trigger_dates(rule, indicators_dict)
        if not trigger_dates:
            results.append({
                "rule_id": rid,
                "description": rule["description"][:60],
                "trades": 0,
                "win_rate": 0,
                "avg_return_pct": 0,
                "note": "无触发 / 数据缺失",
                "signal_type": signal_type,
                "expected_wr": rule["expected_win_rate"],
            })
            log.info(f"  ⚠️ {rid:25s}: 0 次触发 (数据缺失或无信号)")
            continue

        # 对每个目标标的回测
        per_target = []
        for target in targets:
            if target not in ASSET_MAP:
                continue
            asset_name = ASSET_MAP[target]
            asset_dict = asset_data[asset_name]
            r = backtest_single_rule(rid, signal_type, hold_days, trigger_dates, asset_dict)
            per_target.append(r)

        if per_target:
            total_trades = sum(r["trades"] for r in per_target)
            total_wins = sum(r["wins"] for r in per_target)
            avg_wr = total_wins / total_trades if total_trades else 0
            avg_ret = sum(r["avg_return_pct"] * r["trades"] for r in per_target) / total_trades if total_trades else 0
            results.append({
                "rule_id": rid,
                "description": rule["description"][:60],
                "signal_type": signal_type,
                "trades": total_trades,
                "wins": total_wins,
                "win_rate": round(avg_wr, 3),
                "avg_return_pct": round(avg_ret, 2),
                "expected_wr": rule["expected_win_rate"],
                "diff_vs_expected": round(avg_wr - rule["expected_win_rate"], 3),
                "hold_days": hold_days,
            })
            log.info(f"  {'✅' if avg_wr > 0.5 else '⚠️' if avg_wr > 0.4 else '❌'} {rid:25s}: 触发{total_trades:3d}次, 胜率{avg_wr*100:5.1f}%, 平均收益{avg_ret:+6.2f}% (预期{rule['expected_win_rate']*100:.0f}%)")

    # 4. 输出汇总
    log.info("\n" + "=" * 60)
    log.info("📊 完整胜率表 (按信号类型分组)")
    log.info("=" * 60)

    for sig in ["add", "reduce", "hold", "observe"]:
        sig_rules = [r for r in results if r["signal_type"] == sig]
        if not sig_rules:
            continue
        log.info(f"\n  {sig.upper()} 信号:")
        for r in sorted(sig_rules, key=lambda x: -x["win_rate"]):
            emoji = "✅" if r["win_rate"] > 0.55 else ("⚠️" if r["win_rate"] > 0.4 else "❌")
            log.info(f"    {emoji} {r['rule_id']:25s} 触发{r['trades']:3d}次 | 胜率{r['win_rate']*100:5.1f}% | 收益{r['avg_return_pct']:+6.2f}% | 预期{r['expected_wr']*100:.0f}%  {r.get('description','')[:40]}")

    # 5. 保存
    output = OUTPUT_DIR / "full_backtest_result.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 完整结果: {output}")

    # 6. 总结
    log.info("\n" + "=" * 60)
    log.info("🎯 关键洞察")
    log.info("=" * 60)
    good = [r for r in results if r["trades"] > 0 and r["win_rate"] > 0.55]
    bad = [r for r in results if r["trades"] > 0 and r["win_rate"] < 0.45]
    no_data = [r for r in results if r["trades"] == 0]
    log.info(f"  ✅ 胜率 > 55%: {len(good)} 条")
    log.info(f"  ❌ 胜率 < 45%: {len(bad)} 条")
    log.info(f"  ⚠️ 数据缺失: {len(no_data)} 条")
    log.info(f"\n  好规则 TOP 3:")
    for r in sorted(good, key=lambda x: -x["win_rate"])[:3]:
        log.info(f"    {r['rule_id']:25s} 胜率 {r['win_rate']*100:.1f}% (触发{r['trades']}次)")


if __name__ == "__main__":
    main()

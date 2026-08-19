"""
50万组合监控 cron
- 每天拉一次持仓 + 目标权重
- 算当前实际权重 vs 目标
- 输出: 偏离度报告 + 再平衡建议
- 投递微信
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT
from datetime import datetime
from evaluate_today import fetch_indicators
from rule_engine import RULES, evaluate_rule
from evaluate_today_v2 import timing_advice, evaluate_v2
from decision_tracker import save_decisions_from_evaluate_v2

log = get_logger("portfolio_monitor")

# ============== 50 万目标组合 ==============
# 目标权重（不变）
TARGET_PORTFOLIO = {
    "012752": {"name": "纳指QDII", "target_pct": 0.25},
    "022653": {"name": "黄金ETF", "target_pct": 0.25},
    "025857": {"name": "电网设备ETF", "target_pct": 0.15},
    "020274": {"name": "化工ETF", "target_pct": 0.10},
    "现金": {"name": "现金/短债", "target_pct": 0.25},
}
TOTAL_CAPITAL = 500000

# 实际持仓 = 从 actual_holdings.json 读（Patrick 手动同步）
# 文件位置: ~/.dsh/market_intel/state/actual_holdings.json
ACTUAL_HOLDINGS_PATH = Path(__file__).parent.parent / "state" / "actual_holdings.json"


def load_actual_holdings():
    """从 actual_holdings.json 读 Patrick 实际持仓（每次他加仓/减仓后手动更新）"""
    if not ACTUAL_HOLDINGS_PATH.exists():
        # 文件不存在 = 全部默认初始状态
        return {
            "012752": 10000, "022653": 10000, "025857": 10000, "020274": 10000,
            "现金": 460000,
        }
    with open(ACTUAL_HOLDINGS_PATH, "r") as f:
        data = json.load(f)
    positions = data.get("positions", {})
    result = {code: info.get("amount", 0) for code, info in positions.items()}
    result["现金"] = data.get("cash_equivalent", 0)
    return result


# Staleness threshold (Patrick 2026-06-24 选 2: 加 staleness 标注, 不强制 update)
STALE_DAYS_THRESHOLD = 3


def get_holdings_staleness():
    """
    检查 actual_holdings.json 的新鲜度.
    返回 dict:
      - days_stale: int (0 = today, 1 = 昨天更新过)
      - last_sync: str (file mtime 字符串)
      - last_sync_with_patrick: str (文件内的 last_sync_with_patrick 字段)
      - source: str (文件内的 source 字段)
      - is_stale: bool (days_stale > STALE_DAYS_THRESHOLD)
      - warning_line: str (用于 CIO 报告头部的 ⚠️ 标注)
    """
    out = {
        "days_stale": 999,
        "last_sync": "文件不存在",
        "last_sync_with_patrick": "未知",
        "source": "未知",
        "is_stale": True,
        "warning_line": "⚠️ 持仓数据缺失 (actual_holdings.json 不存在) - 全部偏离度仅参考",
    }
    if not ACTUAL_HOLDINGS_PATH.exists():
        return out
    try:
        mtime_ts = ACTUAL_HOLDINGS_PATH.stat().st_mtime
        mtime_dt = datetime.fromtimestamp(mtime_ts)
        days_stale = (datetime.now() - mtime_dt).days
        with open(ACTUAL_HOLDINGS_PATH, "r") as f:
            data = json.load(f)
        last_sync_with_patrick = data.get("last_sync_with_patrick", "未知")
        source = data.get("source", "未知")
        is_stale = days_stale > STALE_DAYS_THRESHOLD
        if is_stale:
            warn = f"⚠️ 持仓数据 {days_stale} 天 stale (最后更新 {mtime_dt.strftime('%Y-%m-%d')}, 来自 {last_sync_with_patrick}, source: {source}) - 偏离度仅参考, 加仓/减仓请告知更新"
        elif days_stale == 0:
            warn = f"✅ 持仓数据今日已同步 ({last_sync_with_patrick}, source: {source})"
        else:
            warn = f"🟡 持仓数据 {days_stale} 天前更新 ({mtime_dt.strftime('%Y-%m-%d')}, {last_sync_with_patrick})"
        out.update({
            "days_stale": days_stale,
            "last_sync": mtime_dt.strftime("%Y-%m-%d %H:%M"),
            "last_sync_with_patrick": last_sync_with_patrick,
            "source": source,
            "is_stale": is_stale,
            "warning_line": warn,
        })
        return out
    except Exception as e:
        out["warning_line"] = f"⚠️ 持仓 staleness check 失败: {e}"
        return out


def save_actual_holdings(holdings_dict, source_note=""):
    """写回 actual_holdings.json（Patrick 告诉我加仓/减仓后调用）"""
    import json as _json
    from datetime import datetime
    positions = {k: {"name": TARGET_PORTFOLIO.get(k, {}).get("name", k), "amount": v, "last_update": datetime.now().strftime("%Y-%m-%d")}
                 for k, v in holdings_dict.items() if k != "现金"}
    out = {
        "version": "1.0",
        "last_sync_with_patrick": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source_note or "Patrick 手动同步",
        "positions": positions,
        "cash_equivalent": holdings_dict.get("现金", 0),
        "total_capital": sum(v for v in holdings_dict.values()),
    }
    ACTUAL_HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ACTUAL_HOLDINGS_PATH, "w") as f:
        _json.dump(out, f, indent=2, ensure_ascii=False)
    return out


def estimate_current_value(code, current_amount):
    """根据最近阶段涨幅估算当前价值 (粗略)"""
    # 实际应该用 fundgz 实时估值, 这里简化
    growth_estimates = {
        "012752": 0.0919,  # 近 1 月 +9.19%
        "022653": -0.039,  # 近 1 月 -3.90%
        "025857": 0.0563,  # 近 1 月 +5.63%
        "020274": -0.1391, # 近 1 月 -13.91%
    }
    return current_amount * (1 + growth_estimates.get(code, 0))


def compute_drift():
    """算当前实际权重 vs 目标权重 (基于 actual_holdings.json 中 Patrick 实际持仓)"""
    log.info("=== 50万组合监控 ===")
    actual = load_actual_holdings()  # 从 actual_holdings.json 读真实持仓
    total_estimated = 0
    positions = {}
    for code, info in TARGET_PORTFOLIO.items():
        current_amount = actual.get(code, 0)
        if code == "现金":
            est_value = current_amount
        else:
            est_value = estimate_current_value(code, current_amount)
        positions[code] = {
            "name": info["name"],
            "current_amount": current_amount,
            "current_value": round(est_value, 2),
            "target_pct": info["target_pct"],
            "current_pct": round(est_value / TOTAL_CAPITAL, 4),
            "drift_pct": round(est_value / TOTAL_CAPITAL - info["target_pct"], 4),
            "target_value": round(TOTAL_CAPITAL * info["target_pct"], 2),
            "rebalance_amount": round(TOTAL_CAPITAL * info["target_pct"] - est_value, 2),
        }
        total_estimated += est_value

    log.info(f"总估算价值: {total_estimated:.2f}")
    log.info(f"持仓数据来源: {ACTUAL_HOLDINGS_PATH}")
    return positions


def main():
    log.info("=" * 60)
    log.info(f"📅 组合监控 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    # 0. 持仓数据 staleness 检查 (Patrick 2026-06-24 决策)
    staleness = get_holdings_staleness()
    log.info(f"\n--- 0. 持仓数据新鲜度 (P0 #9 staleness) ---")
    log.info(f"  {staleness['warning_line']}")

    # 1. 拉指标 + 评估
    log.info("\n--- 1. 拉指标 + 评估规则 ---")
    result = evaluate_v2()  # 已包含 fetch_indicators
    summary = result["fund_decisions"]

    # 1.5. (P0 #11) evaluate_v2 已写 decisions, 这里不需要再写
    if result.get("saved_decision_ids"):
        log.info(f"  💾 decisions saved by evaluate_v2: {result['saved_decision_ids']}")

    # 2. 算组合偏离
    log.info("\n--- 2. 算组合偏离 ---")
    positions = compute_drift()

    # 3. 输出
    log.info("\n--- 3. 组合状态 ---")
    for code, p in positions.items():
        emoji = "🟢" if abs(p["drift_pct"]) < 0.05 else ("🟡" if abs(p["drift_pct"]) < 0.15 else "🔴")
        log.info(f"  {emoji} {code} {p['name']:12s}: 当前¥{p['current_value']:>10,.0f} ({p['current_pct']*100:5.1f}%) | 目标{p['target_pct']*100:5.1f}% | 偏离{p['drift_pct']*100:+5.1f}%")

    # 4. 触发建议
    log.info("\n--- 4. 触发建议 ---")
    actions = []
    for code, p in positions.items():
        if abs(p["drift_pct"]) < 0.03:
            continue  # 偏离小
        if code == "现金":
            continue  # 现金不主动调
        if p["drift_pct"] > 0.05:  # 超配 > 5%
            actions.append(f"  🟡 减 {code} ({p['name']}): 当前超配 {p['drift_pct']*100:+.1f}%, 减仓 ¥{abs(p['rebalance_amount']):,.0f}")
        elif p["drift_pct"] < -0.10:  # 低配 > 10%
            actions.append(f"  🟢 加 {code} ({p['name']}): 当前低配 {p['drift_pct']*100:+.1f}%, 加仓 ¥{abs(p['rebalance_amount']):,.0f}")

    if not actions:
        log.info("  ✅ 组合偏离在 ±5% 内, 无需再平衡")
    else:
        for a in actions:
            log.info(a)

    # 5. 微信输出 (短版)
    lines = [f"📅 组合监控 {datetime.now().strftime('%m-%d %H:%M')}\n"]
    # 0.5 持仓 staleness 横幅 (放在报告第一行, Patrick 一眼可见)
    lines.append(staleness["warning_line"])
    lines.append("")
    for code, p in positions.items():
        if code == "现金":
            continue
        emoji = "🟢" if abs(p["drift_pct"]) < 0.05 else "🟡"
        lines.append(f"{emoji} {p['name']:8s} {p['current_pct']*100:5.1f}% → 目标 {p['target_pct']*100:5.1f}% 偏离{p['drift_pct']*100:+.1f}%")
    lines.append("")
    if actions:
        lines.append("⚠️ 触发再平衡 (分批 4 周):")
        for a in actions[:4]:  # 限制 4 条
            if "加" in a and "¥" in a:
                try:
                    amt_str = a.split("¥")[1].replace(",", "").split()[0]
                    weekly_amt = abs(float(amt_str)) / 4
                    lines.append(f"{a} → 每周 ¥{weekly_amt:,.0f}")
                    continue
                except (IndexError, ValueError):
                    pass
            lines.append(a)
    else:
        lines.append("✅ 偏离在 5% 内, 无需再平衡")

    # 模型建议 + 加仓速度
    lines.append("\n🤖 模型建议:")
    add_count = 0
    for code, d in summary.items():
        lines.append(f"  {d['emoji']} {d['final']}")
        if "现在加仓" in d.get("final", ""):
            add_count += 1
    if add_count == 4:
        lines.append("\n💡 4 只都触发, 建议分 4-6 周完成加仓, 不要一次性")

    output = "\n".join(lines)
    log.info("\n" + "=" * 60)
    log.info("📱 微信输出:")
    log.info("=" * 60)
    log.info("\n" + output)

    output_path = "/tmp/portfolio_monitor.txt"
    Path(output_path).write_text(output, encoding="utf-8")
    log.info(f"\n💾 完整输出: {output_path}")

    return output


if __name__ == "__main__":
    main()

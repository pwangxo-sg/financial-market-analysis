"""
月度复盘报告
- 拉过去 30 天的 signals 表
- 计算每条规则的实际胜率
- 与 expected_win_rate 对比
- 标记表现差的规则 (建议降权)
- 输出月度报告
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, get_db
from datetime import datetime, timedelta
from rule_engine import RULES

log = get_logger("monthly_review")


def compute_actual_winrate(days=30):
    """计算过去 N 天规则的实际胜率"""
    from _lib import BJT
    cutoff = (datetime.now(BJT) - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT rule_id, signal_type, COUNT(*) as total,
                      SUM(CASE WHEN actual_outcome = 'win' THEN 1 ELSE 0 END) as wins
               FROM signals
               WHERE generated_at >= ? AND actual_outcome IS NOT NULL
               GROUP BY rule_id, signal_type""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def compare_with_expected(actual):
    """对比实际胜率 vs 规则预期"""
    rule_map = {r["rule_id"]: r for r in RULES}
    report = []
    for r in actual:
        rid = r["rule_id"]
        if rid not in rule_map:
            continue
        rule = rule_map[rid]
        actual_wr = (r["wins"] / r["total"]) if r["total"] > 0 else 0
        expected = rule["expected_win_rate"]
        diff = actual_wr - expected
        status = "✅ 达标" if diff >= -0.05 else ("⚠️ 低于预期" if diff >= -0.15 else "❌ 大幅低于")
        report.append({
            "rule_id": rid,
            "description": rule["description"][:50],
            "trades": r["total"],
            "wins": r["wins"],
            "actual_wr": round(actual_wr, 3),
            "expected_wr": expected,
            "diff": round(diff, 3),
            "status": status,
            "recommendation": "保持" if diff >= -0.05 else ("降权" if diff >= -0.15 else "禁用"),
        })
    return report


def main():
    log.info("=" * 60)
    log.info("📅 月度复盘报告")
    log.info("=" * 60)

    actual = compute_actual_winrate(days=30)
    if not actual:
        log.info("\n⚠️ 过去 30 天没有 signal 验证数据 (模型刚启动, 待积累)")
        log.info("💡 月度复盘需要至少 1 个月运行才能产生有意义数据")
        log.info("\n📋 当前规则库 (15 条):")
        for r in RULES:
            target = "/".join(r["target_codes"])
            log.info(f"  {r['rule_id']:25s} 预期胜率 {r['expected_win_rate']*100:.0f}% ({r['signal_type']:7s}, {target})")
        return

    report = compare_with_expected(actual)
    log.info(f"\n--- 过去 30 天规则表现 ---")
    for r in report:
        log.info(f"  {r['status']:12s} {r['rule_id']:25s}: 实际{r['actual_wr']*100:5.1f}% vs 预期{r['expected_wr']*100:5.1f}% 触发{r['trades']}次 → {r['recommendation']}")

    # 总结
    log.info(f"\n--- 总结 ---")
    disabled = [r for r in report if r["recommendation"] == "禁用"]
    downweight = [r for r in report if r["recommendation"] == "降权"]
    keep = [r for r in report if r["recommendation"] == "保持"]
    log.info(f"  禁用: {len(disabled)} 条")
    log.info(f"  降权: {len(downweight)} 条")
    log.info(f"  保持: {len(keep)} 条")

    output_path = "/tmp/monthly_review.json"
    Path(output_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 完整报告: {output_path}")


if __name__ == "__main__":
    main()

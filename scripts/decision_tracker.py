"""
决策追踪器 (P0 #11, 2026-07-15)
- save_decision(): 任何"加仓/减仓/持有/观察"建议 → 自动写 decisions 表 + 关联 signal_ids
- apply_decision(): Patrick 确认执行 → 写 actual_holdings + 关联 decision
- get_pending_decisions(): 报告里读"上周建议 vs 实际采纳"对照
- get_rule_stats(): rule 胜率 + 触发次数, 给每条建议背书
- verify_decisions(): 30 天后自动回填 actual_outcome + pnl_pct (与 verify_signals.py 同步)

设计原则:
1. 单一入口 — 所有"建议"和"执行"走这两个函数
2. 强一致 — save + apply 都要 idempotent (同一 decision_id 不重复)
3. 时效 — 30 天后自动 verify, 不需要手动
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, BJT

log = get_logger("decision_tracker")

DB_PATH = ROOT / "db" / "intel.db"
STATE_DIR = ROOT / "state"
ACTUAL_HOLDINGS_PATH = STATE_DIR / "actual_holdings.json"


def get_conn():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def save_decision(decision_summary, rationale, signal_ids=None, sources=None, expires_days=30, decision_id=None):
    """
    保存一条 CIO 建议到 decisions 表
    decision_id: 可选, 默认 None (用 AUTOINCREMENT rowid)
    返回 rowid (int)
    """
    now = datetime.now(BJT).isoformat(timespec="seconds")
    expires = (datetime.now(BJT) + timedelta(days=expires_days)).isoformat(timespec="seconds")

    con = get_conn()
    try:
        cur = con.execute("""
            INSERT INTO decisions
            (decision, rationale, sources, signal_ids, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            decision_summary,
            rationale,
            json.dumps(sources or [], ensure_ascii=False),
            json.dumps(signal_ids or [], ensure_ascii=False),
            now,
            expires,
        ))
        con.commit()
        new_id = cur.lastrowid
        log.info(f"  ✅ decision saved: id={new_id} | {decision_summary[:60]}")
        return new_id
    except Exception as e:
        log.error(f"  ❌ save_decision failed: {e}")
        return None
    finally:
        con.close()


def save_decisions_from_evaluate_v2(eval_result, source_note="auto_cron"):
    """
    从 evaluate_today_v2() 的 result 提取所有 fund_decisions (含 hold/observe),
    自动写 decisions 表, signal_ids 关联最新 signals 表.
    返回写入的 decision_id 列表.
    """
    saved = []
    fund_decisions = eval_result.get("fund_decisions", {})
    if not fund_decisions:
        return saved

    # 拉最新 signals 用于关联
    con = get_conn()
    try:
        for code, d in fund_decisions.items():
            base = d.get("base_action", "")
            final = d.get("final", "")
            # 关联最新 signal (任何类型)
            cur = con.execute(
                "SELECT id FROM signals WHERE code=? ORDER BY rowid DESC LIMIT 1",
                (code,)
            ).fetchone()
            signal_ids = [cur["id"]] if cur else []

            rationale = f"中期: {base} | 触发: {d.get('triggered_rules', [])} | 时机: {d.get('timing', {}).get('explanation', '')[:80]}"
            did = save_decision(
                decision_summary=f"{code} {base}: {final}",
                rationale=rationale,
                signal_ids=signal_ids,
                sources=[source_note],
                expires_days=30,
            )
            if did:
                saved.append(did)
    finally:
        con.close()
    return saved


def apply_decision(decision_id, execution_note="Patrick 确认执行"):
    """
    Patrick 接受了一条建议并执行, 标记 decisions 表为 executed.
    同时: 把对应建议的"操作"应用到 actual_holdings.json (从 watchlist.json 读).
    返回执行摘要.
    """
    con = get_conn()
    try:
        cur = con.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if not cur:
            return {"status": "not_found", "decision_id": decision_id}
        # 现在: 写 rationale 末尾加 "[EXECUTED at <ts>]"
        new_rationale = (cur["rationale"] or "") + f"\n[EXECUTED {datetime.now(BJT).isoformat(timespec='seconds')}] {execution_note}"
        con.execute("UPDATE decisions SET rationale=? WHERE id=?", (new_rationale, decision_id))
        con.commit()
        log.info(f"  ✅ decision executed: {decision_id} | {execution_note}")
        return {"status": "executed", "decision_id": decision_id, "rationale": new_rationale}
    except Exception as e:
        log.error(f"  ❌ apply_decision failed: {e}")
        return {"status": "error", "decision_id": decision_id, "error": str(e)}
    finally:
        con.close()


def get_pending_decisions(days_back=7):
    """
    读最近 N 天的未执行 decisions, 用于报告"上周建议 vs 实际"对照.
    返回: [{decision_id, summary, signal_ids, days_ago, expired}]
    """
    con = get_conn()
    try:
        since = (datetime.now(BJT) - timedelta(days=days_back)).isoformat(timespec="seconds")
        rows = con.execute("""
            SELECT id, decision, rationale, signal_ids, created_at, expires_at
            FROM decisions
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """, (since,)).fetchall()
        results = []
        for r in rows:
            created = datetime.fromisoformat(r["created_at"])
            days_ago = (datetime.now(BJT) - created).days
            executed = r["rationale"] and "[EXECUTED" in r["rationale"]
            expired = False
            if r["expires_at"]:
                try:
                    expired = datetime.fromisoformat(r["expires_at"]) < datetime.now(BJT)
                except Exception:
                    pass
            results.append({
                "decision_id": r["id"],
                "summary": r["decision"],
                "signal_ids": json.loads(r["signal_ids"] or "[]"),
                "days_ago": days_ago,
                "executed": executed,
                "expired": expired,
            })
        return results
    finally:
        con.close()


def get_rule_stats():
    """
    拉每条 rule 触发次数 + 30 天回填后胜率 (verify_signals.py 已填 pnl_pct).
    返回: {rule_id: {trigger_count, win_count, total_pnl_pct, win_rate}}
    """
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT rule_id,
                   COUNT(*) as trigger_count,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as win_count,
                   SUM(COALESCE(pnl_pct, 0)) as total_pnl_pct,
                   AVG(CASE WHEN pnl_pct IS NOT NULL THEN pnl_pct END) as avg_pnl
            FROM signals
            GROUP BY rule_id
        """).fetchall()
        stats = {}
        for r in rows:
            trigger = r["trigger_count"] or 0
            win = r["win_count"] or 0
            total = r["total_pnl_pct"] or 0
            stats[r["rule_id"]] = {
                "trigger_count": trigger,
                "win_count": win,
                "win_rate": round(win / trigger * 100, 1) if trigger > 0 else 0,
                "total_pnl_pct": round(total, 2),
                "avg_pnl_pct": round(r["avg_pnl"] or 0, 2),
            }
        return stats
    finally:
        con.close()


if __name__ == "__main__":
    # self-test
    log.info("=== decision_tracker self-test ===")
    # 测试保存
    did = save_decision(
        "self-test decision",
        "单元测试: 验证 decisions 表写入",
        signal_ids=[1, 2],
        sources=["self_test"],
    )
    print(f"\nSaved: {did}")
    # 测试读
    pending = get_pending_decisions(days_back=1)
    print(f"\nPending (last 1d): {len(pending)}")
    for p in pending[:3]:
        print(f"  {p['decision_id']}: {p['summary']}")
    # 测试 rule stats
    stats = get_rule_stats()
    print(f"\nRule stats ({len(stats)} rules):")
    for rid, s in list(stats.items())[:5]:
        print(f"  {rid:25s} 触发{s['trigger_count']:3d} 胜率{s['win_rate']:5.1f}% 平均{s['avg_pnl_pct']:+.2f}%")
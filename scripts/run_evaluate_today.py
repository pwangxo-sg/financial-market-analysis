"""
Run evaluate_today.py + insert signals into DB
================================================
- 跑 evaluate_today.py main()
- 解析 fund_summary 里每只基金的 action (add/reduce/hold/observe)
- 把 triggered_rules + action 组合写入 signals 表
- 每次运行只插入当天的信号（按 generated_at + code 去重）

P0 #2 (6/17 跨日): signals 表 Day 7 of 0，必须补上
- 06-16 16:00 化工ETF CHEM_OIL_01 加仓信号已生成但未 insert signals 表
- 这层 wrapper 保证 evaluate_today.py 跑完后结果一定落库

用法：
    python3 run_evaluate_today.py          # 跑一次并入库
    python3 run_evaluate_today.py --dry    # 只评估不入库
"""
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 加 scripts 路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from _lib import get_db, get_logger, BJT  # noqa: E402
import evaluate_today  # noqa: E402

log = get_logger("run_evaluate_today")

# 代码 → 名称映射（fund_summary 没存 name, 用 holdings 表补全）
DB_PATH = SCRIPT_DIR.parent / "db" / "intel.db"


def _direction_for(action: str) -> str:
    """signal_type → direction 映射"""
    return {
        "add": "long",
        "reduce": "short",
        "hold": "hedge",
        "observe": "long",
    }.get(action, "long")


def _fetch_rules_meta():
    """从 rules 表里拿每条规则的 hold_days / confidence（缺失则用规则引擎默认值）"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT rule_id, target_codes, expected_hold_days FROM rules"
            ).fetchall()
            meta = {}
            for row in rows:
                meta[row["rule_id"]] = {
                    "target_codes": json.loads(row["target_codes"] or "[]"),
                    "hold_days": row["expected_hold_days"] or 60,
                }
            return meta
    except Exception as e:
        log.warning(f"⚠️ rules 表读取失败: {e}")
        return {}


def _signal_exists(conn, code: str, generated_at: str, rule_id: str) -> bool:
    """同 code+date+rule_id 已存在则跳过 (避免每次跑重复 insert)

    P0 #8 修复 (6/19 跨日): 原 dedup 用 full ISO timestamp 区分,
    导致同一天 09:04 vs 16:33 两次 evaluate 都插入新行 (id 1-3 = id 4-6)
    改用 date(generated_at) 跨批次去重, 同日同 code+rule_id 只入一次。
    """
    cur = conn.execute(
        "SELECT id FROM signals "
        "WHERE code=? AND date(generated_at)=date(?) AND rule_id=?",
        (code, generated_at, rule_id),
    )
    return cur.fetchone() is not None


def insert_signals(result: dict) -> dict:
    """
    把 evaluate_today.main() 的 fund_summary 写入 signals 表

    result['fund_summary'][code] 结构：
      {
        'action': 'add'|'reduce'|'hold'|'observe'|'mixed',
        'emoji': '🟢',
        'triggered_count': N,
        'add_score': int,
        'reduce_score': int,
        'hold_score': int,
        'triggered_rules': ['RULE_01', 'RULE_02', ...],
      }
    """
    summary = result.get("fund_summary", {})
    timestamp = result.get("timestamp") or datetime.now(BJT).isoformat(timespec="seconds")
    rules_meta = _fetch_rules_meta()

    inserted = 0
    skipped_duplicate = 0
    skipped_observe = 0

    with get_db() as conn:
        for code, s in summary.items():
            action = s.get("action", "observe")
            triggered_rules = s.get("triggered_rules", [])

            if action == "observe":
                skipped_observe += 1
                log.info(f"  ⚪ {code}: observe, 跳过 (无触发规则)")
                continue

            if not triggered_rules:
                # action 有但没触发的具体规则 (mixed/hold+无规则)
                # 仍写一条 OBSERVE 信号供看板
                if action == "mixed":
                    log.info(f"  🟠 {code}: mixed, 跳过 (无明确信号方向)")
                    skipped_observe += 1
                    continue

            # 主信号 = 第一条触发的规则 (按 evaluate_today 的处理顺序)
            # 若没有 triggered_rules 但 action 非 observe (如 add 来自综合分数), 用个 placeholder
            primary_rule = triggered_rules[0] if triggered_rules else f"AGG_{action.upper()}"

            # 计算 hold_days / confidence
            hold_days_max = 60  # 默认 60 天
            confidence_max = 0
            for rid in triggered_rules:
                meta = rules_meta.get(rid, {})
                hold_days_max = max(hold_days_max, meta.get("hold_days", 60))

            # 综合 confidence: 用 add_score / reduce_score 中较大的一个
            if action == "add":
                confidence = s.get("add_score", 60)
            elif action == "reduce":
                confidence = s.get("reduce_score", 60)
            elif action == "hold":
                confidence = s.get("hold_score", 60)
            else:
                confidence = 50
            confidence = max(0, min(100, int(confidence)))
            # 至少给一个 base (avoid 0)
            if confidence == 0:
                confidence = 55
            confidence_max = confidence

            # expires_at = generated_at + hold_days_max
            try:
                gen_dt = datetime.fromisoformat(timestamp)
                expires_dt = gen_dt + timedelta(days=hold_days_max)
                expires_iso = expires_dt.isoformat(timespec="seconds")
            except Exception:
                expires_iso = None

            # 去重检查
            if _signal_exists(conn, code, timestamp, primary_rule):
                skipped_duplicate += 1
                log.info(f"  ⏭️ {code} ({primary_rule}) 已存在, 跳过")
                continue

            evidence = {
                "action": action,
                "emoji": s.get("emoji", ""),
                "triggered_count": s.get("triggered_count", 0),
                "add_score": s.get("add_score", 0),
                "reduce_score": s.get("reduce_score", 0),
                "hold_score": s.get("hold_score", 0),
                "triggered_rules": triggered_rules,
                "hold_days_max": hold_days_max,
            }
            try:
                conn.execute(
                    """INSERT INTO signals
                       (code, signal_type, direction, confidence, rule_id,
                        evidence, generated_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        code,
                        action,
                        _direction_for(action),
                        confidence_max,
                        primary_rule,
                        json.dumps(evidence, ensure_ascii=False),
                        timestamp,
                        expires_iso,
                    ),
                )
                inserted += 1
                log.info(
                    f"  ✅ {code}: {action.upper()} → signals "
                    f"(rule={primary_rule}, confidence={confidence_max}, "
                    f"expires={expires_iso})"
                )
            except sqlite3.IntegrityError as e:
                log.warning(f"  ⚠️ {code} ({primary_rule}) insert failed: {e}")
                skipped_duplicate += 1

    return {
        "inserted": inserted,
        "skipped_duplicate": skipped_duplicate,
        "skipped_observe": skipped_observe,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="只跑评估，不入库")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(f"📊 今日信号评估 + 入库 - {datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    # 1. 跑评估
    log.info("\n--- 1. 跑 evaluate_today.main() ---")
    try:
        result = evaluate_today.main()
    except Exception as e:
        log.error(f"❌ evaluate_today.main() 失败: {e}", exc_info=True)
        sys.exit(1)

    # 2. 入库
    if args.dry:
        log.info("\n--- 2. (DRY) 跳过入库 ---")
        return result

    log.info("\n--- 2. 插入 signals 表 ---")
    summary = insert_signals(result)

    log.info("\n" + "=" * 60)
    log.info(
        f"📋 入库结果: {summary['inserted']} 新增 | "
        f"{summary['skipped_duplicate']} 重复跳过 | "
        f"{summary['skipped_observe']} observe 跳过"
    )
    log.info("=" * 60)

    # 3. 汇总
    if summary["inserted"] == 0:
        log.warning("⚠️ 今日 0 signals 入库 - 检查是否有 action=observe 或全 mixed")
    return result


if __name__ == "__main__":
    main()
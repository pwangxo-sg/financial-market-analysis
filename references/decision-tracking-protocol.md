---
name: financial-market-analysis
description: 投资建议 → decisions 表 → 30 天回填自动化的完整工作流（save_decision / apply_decision / get_pending_decisions / get_rule_stats），含 schema 铁律 + apply_decision 后续。
---

# Decision Tracking Protocol（投资建议自动回填协议，v1.7.13 P0-11）

## 为什么需要

CIO 报告每天都给"加仓/减仓/持有"建议。但**这些建议从未进回填系统** → 30/90 天后无法回答"哪些建议被采纳 + 实际盈亏 + rule engine 自我进化"。

**v1.7.12 之前**：`signals` 表 92 行（rule engine 自动 INSERT）但 `decisions` 表 0 行（CIO 报告从不写）。

**v1.7.13 落地**：`decision_tracker.py` 强制把每一份报告的方向词 → `decisions` 表 → 30 天后 verify_signals.py 自动回填 actual_outcome + pnl_pct。

## 数据库 schema（已存在）

```sql
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- ⚠️ INTEGER，不是 string
    decision TEXT NOT NULL,                -- 决策摘要, e.g. "012752 add: ✅ 现在加仓"
    rationale TEXT,                        -- 触发规则 + 时机解释
    sources TEXT,                          -- JSON array, e.g. ["evaluate_today_v2"]
    signal_ids TEXT,                       -- JSON array, e.g. [92]
    created_at TEXT NOT NULL,
    expires_at TEXT                        -- 默认 30 天后
);
```

⚠️ **ID 类型坑**：`id` 是 INTEGER PRIMARY KEY AUTOINCREMENT。**不要传 string**（v1.7.13 自测踩过 `datatype mismatch`，已修）。

```python
# ❌ 错误示例
cur.execute("INSERT INTO decisions (id, ...) VALUES (?, ...)", ("D-20260715-001", ...))
#                                                            ^^^^^^^^^^^^^^^^
#                                                          sqlite3 自动拒绝

# ✅ 正确: 不传 id，让 sqlite3 AUTOINCREMENT
cur.execute("INSERT INTO decisions (decision, ...) VALUES (?, ...)", (...,))
new_id = cur.lastrowid  # 返回 int
```

## decision_tracker.py API（已落地）

**位置**: `$MARKET_INTEL_ROOT/scripts/decision_tracker.py`

### save_decision(decision_summary, rationale, signal_ids, sources, expires_days=30)

**写入一条独立决策（手动/单条）**：
```python
from decision_tracker import save_decision
did = save_decision(
    decision_summary="SMH add: 加仓 ¥15,000 (25 股 ≈ $2,094)",
    rationale="NVDA +7.55% / AMD +6.20% = AI 算力 4 龙头单日 +5%~+7.55%, 今日市场主线",
    signal_ids=[92],
    sources=["evaluate_today_v2"],
    expires_days=30,
)
# 返回 int (rowid)
```

### save_decisions_from_evaluate_v2(eval_result, source_note)

**批量从 evaluate_today_v2() 输出提取所有 fund_decisions 写 decisions 表**：
```python
from evaluate_today_v2 import evaluate_v2
from decision_tracker import save_decisions_from_evaluate_v2

result = evaluate_v2()
# 自动写: 4 只基金 (012752/022653/025857/020274) → 4 行 decisions
saved_ids = save_decisions_from_evaluate_v2(result, "evaluate_today_v2")
# 已接入 evaluate_today_v2.py 末尾 (v1.7.13)
```

⚠️ **v1.7.13 改动**：写**所有** fund_decisions（add/reduce/hold/observe 全写），不再过滤 hold/observe。原因：报告里"🔵 持有"也是建议，未来 30 天回填需要这个数据。

### apply_decision(decision_id, execution_note)

**用户 接受建议 + 实际执行 → 标记 decisions 为 [EXECUTED] + 更新 actual_holdings.json**（TODO: 当前只标记 rationale，待加自动同步 actual_holdings）：

```python
from decision_tracker import apply_decision
result = apply_decision(
    decision_id=5,
    execution_note="用户 确认加仓 012752 ¥5,000 @ 3.3594",
)
# 返回 {"status": "executed", "decision_id": 5, "rationale": "...[EXECUTED 2026-...]"}
```

**未来扩展 (P0-2 完整版)**：
```python
def apply_decision(decision_id, execution_note, auto_update_holdings=True):
    """如果 auto_update=True，从 decision_summary 解析 (code, action, amount) 自动写 actual_holdings.json"""
    # 示例: decision="012752 add: 加仓 ¥5,000" → actual_holdings.json '012752': 10000 → 15000
```

### get_pending_decisions(days_back=7)

**读最近 N 天的未执行 decisions，用于报告"上周建议 vs 实际"对照表**：

```python
from decision_tracker import get_pending_decisions
pending = get_pending_decisions(days_back=7)
# 返回 [{decision_id, summary, signal_ids, days_ago, executed, expired}]
```

**报告格式示例**：
```
📌 上周建议回顾 (7-14 / 7-15):
  1. 012752 add (决策 #5) - 7-15 11:30 建议加仓 + 现价 3.36 → 未执行 (今日 +X%)
  2. SMH add (决策 #10) - 7-15 14:30 建议 ¥15K - 渠道待确定 - 未执行
```

### get_rule_stats()

**每条 rule 触发次数 + 已回填胜率 + 平均 PnL**，给 CIO 报告每条建议背书：

```python
from decision_tracker import get_rule_stats
stats = get_rule_stats()
# 返回 {rule_id: {trigger_count, win_count, win_rate, total_pnl_pct, avg_pnl_pct}}
```

**报告格式示例**：
```
012752 add (rule NDX_FED_01, 30 次触发, 胜率 0%, PnL 0%) — ⚠️ 等待 verify
025857 add (rule GRID_AI_01, 30 次触发, 胜率 0%, PnL 0%) — ⚠️ 等待 verify
```

⚠️ **当前 pnl_pct 全 0**：因为 verify_signals.py 还没回填。一旦回填完成（30 天），rule_stats 才有意义。

## verify_signals.py 后续升级 (P0-3)

当前 `verify_signals.py` 只回填 `signals` 表的 pnl_pct。**v1.7.14 待升级**：

1. 关联 `decisions` 表（signal_ids 字段）→ 给每条 decision 写 actual_outcome
2. 对每个 decision：判断 用户 是否采纳（看 actual_holdings.json 的对应变更）
3. 算两个数：
   - **采纳建议的实际收益**：实际成交后的 P&L
   - **拒绝建议的反事实收益**：如果当时按建议操作，30 天后的 P&L
4. 输出"建议采纳率 + 采纳时收益 vs 拒绝时收益 diff" 报告

这才是真正的 "CIO 自我进化" 闭环。

## apply_decision 后续 (P0-2 完整版)

**当前实现**：apply_decision 只标 rationale 末尾 "[EXECUTED ...]"。没有自动改 actual_holdings.json。

**待加**：从 decision_summary 解析 (code, action, amount, price) → 自动调 save_actual_holdings()。

实现示例（伪代码）：
```python
import re
def apply_decision(decision_id, execution_note, auto_update=True):
    cur.execute("SELECT * FROM decisions WHERE id=?", (decision_id,))
    row = cur.fetchone()
    summary = row['decision']
    # parse "012752 add: 加仓 ¥5,000"
    m = re.search(r'(\d{6}) (add|reduce): ?加?减?(\d+)', summary)
    if m and auto_update:
        code, action, amount = m.groups()
        # load actual_holdings
        holdings = json.load(open(ACTUAL_HOLDINGS_PATH))
        holdings['positions'][code]['amount'] = holdings['positions'][code].get('amount', 0) + int(amount)
        json.dump(holdings, open(ACTUAL_HOLDINGS_PATH, 'w'), indent=2)
```

**等待触发器**：用户 给我"加了 012752 ¥5000" 类消息 → 自动 apply_decision。

## 报告 5 步协议

未来生成 CIO 报告时，强制按 5 步：

1. 拉数据 → 2. 算指标 → 3. evaluate_v2() → 4. 自动 save_decisions → 5. 报告里"📝 已记录 decision_id=N"标注

**失败兜底**：如果 save_decision 失败，报告必须显式说"⚠️ decision recording 失败，建议未进回填系统"。

# verify_signals.py 数据新鲜度问题（2026-07-19 发现）

## TL;DR

`$MARKET_INTEL_ROOT/scripts/verify_signals.py` 自 2026-06-05 起 **沉默失效**：脚本每跑必报"✅ 验证 0 个信号"且无错误，实际因历史 CSV (`backtest/{qqq,gld,spy,xle}_10y.csv`) 未刷新，12+ 条 qualifying signals 永远进不了 `actual_outcome`。整个回填链路（月度复盘 / rule 胜率 / CIO 历史背书）当前处于"无数据"状态。

## 发现现场

**触发**: cron job（隐含在 26322edf978c 投资日报 wrapper）每日一次跑 `verify_signals.py` 做"30 天前 signal 回填"。

**盲测观察**: 2026-07-19 17:00 跑后看到 `[verify_signals] ✅ 验证 0 个信号`——第一直觉"无旧 signal 待验证，系统干净"。

**实际诊断**:

```bash
$ tail -1 $MARKET_INTEL_ROOT/backtest/qqq_10y.csv
2026-06-05,705.06

$ sqlite3 $MARKET_INTEL_ROOT/db/intel.db \
  "SELECT COUNT(*) FROM signals
   WHERE generated_at < datetime('now','-30 days')
     AND actual_outcome IS NULL"
12
```

有 12 条 qualifying signals 应该被验证，但 0 个完成——**因为 CSV 截止 2026-06-05，而 qualifying signal 的生成日期是 2026-06-17 之后，30 天后的回看日期 = 2026-07-17+，全在 CSV 数据范围外**。

## 2026-07-25 纠偏：不要再用 `max_age_days=3` 作为唯一刷新门槛

后续实测发现，CSV 仅落后 **1 个交易日**也会导致整批静默为 0：2026-07-25 运行时 4 个 CSV 已到 7/23，看似“未超过 3 天”，但本批 3 条信号的目标退出日正是 7/24；运行技能包内幂等刷新脚本追加 7/24 后，重跑立即验证 3 条。

因此以下旧方案中的 `age <= 3 → 不刷新` 仅保留为历史设计，**已被替代**。生产协议应为：

1. 验证前无条件运行一次幂等刷新（无新数据时追加 0 行，成本可控）：
   `python3 ~/.dsh/skills/productivity/financial-market-analysis/scripts/refresh_backtest_csv.py`
2. 或比较 CSV 覆盖范围与“最近完整交易日 / 本批最大有效退出日”，不能只比较自然日年龄。
3. 刷新后只重跑验证一次；若 CSV 已覆盖最近完整交易日仍为 0，转查周末/节假日精确匹配缺口，禁止循环刷新。
4. 运行前备份 SQLite；运行后必须从 SQLite 读回本批写入、累计胜率、平均 PnL 和剩余 qualifying。

完整现场见 `references/verify-signals-run-2026-07-25.md`。

## 根因树

```
verify_signals 报 0 verified
├─ verify_pending_signals() for 循环里每条都 continue
│  ├─ entry_price = fetch_price_on_date(code, gen_date)
│  │  └─ CSV 读不到 (gen_date > CSV last_date) → return None
│  └─ if not entry_price or not exit_price: continue
└─ 整个循环 0 完成 → 输出 ✅ 验证 0 个信号 (无 stderr, 无 exit≠0)
```

**关键双错叠加**：

1. **数据层**: `backtest/*_10y.csv` 是 backtest 准备时一次性生成（文件 mtime = Jun 6 18:20），没有 refresh cron 接续。Backtest 工具链默认 CSV 为"过去历史的完整快照"，生产环境里这个假设失效。
2. **脚本层**: `verify_signals.py` 没有 freshness probe 也没有"通过率自检"——它默认上游数据是新鲜的，所以 silent 0。

## 修复方案

### 方案 1（推荐）：verify_signals 内部 self-refresh

让脚本读 CSV 前先检查 fresh，stale 则自动从 Yahoo Finance 拉 60 天 append：

```python
# 在 verify_signals.py 增加：
import yfinance as yf

YAHOO_TICKER_MAP = {
    "012752": "QQQ",
    "022653": "GLD",
    "025857": "SPY",  # 用 SPY 代理电网设备
    "020274": "XLE",  # 用 XLE 代理化工
}

def ensure_fresh(csv_path: Path, ticker: str, max_age_days: int = 3) -> bool:
    """确保 CSV 不陈旧；如需 refetch 则追加新日期。返回是否做了 refetch。"""
    if not csv_path.exists():
        return False  # 缺数据，不是 verify_signals 的工作
    last_date_str = read_last_date(csv_path)
    if not last_date_str:
        return False
    last_dt = datetime.fromisoformat(last_date_str)
    age = (datetime.now() - last_dt).days
    if age <= max_age_days:
        return False
    log.warning(f"{csv_path.name} 过期 {age} 天，refetch 60d")
    df = yf.Ticker(ticker).history(period="60d")
    if df.empty:
        return False
    new_rows = df.reset_index()[["Date", "Close"]].rename(
        columns={"Date": "date", "Close": "close"}
    )
    new_rows["date"] = new_rows["date"].dt.strftime("%Y-%m-%d")
    # 去重：CSV 已有日期不重复 append
    existing = set(read_dates(csv_path))
    new_rows = new_rows[~new_rows["date"].isin(existing)]
    if not new_rows.empty:
        new_rows.to_csv(csv_path, mode="a", header=False, index=False)
        log.info(f"appended {len(new_rows)} new dates to {csv_path.name}")
    return True
```

调用处：

```python
def verify_pending_signals():
    # Step 1: 先保证数据新鲜
    for code, csv_name in asset_map.items():
        ensure_fresh(
            OUTPUT_DIR / f"{csv_name}.csv",
            YAHOO_TICKER_MAP[code],
        )
    # Step 2: 原 verify 逻辑
    cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, code, signal_type, generated_at, rule_id "
            "FROM signals WHERE generated_at < ? AND actual_outcome IS NULL LIMIT 50",
            (cutoff,)
        ).fetchall()
    qualified = len(rows)
    verified = 0
    for r in rows:
        # ... (原 fetch + 计算 + update 逻辑)
        verified += 1
    # Step 3: 通过率自检
    if qualified > 0 and verified == 0:
        log.warning(f"⚠️ {qualified} qualifying signals but 0 verified — "
                    "data freshness issue likely (CSV 过期 or Yahoo API fail)")
    elif qualified > 5 and verified / qualified < 0.5:
        log.warning(f"⚠️ 通过率低: {verified}/{qualified} = "
                    f"{verified/qualified:.0%} — 调查 skip 原因")
    log.info(f"回填完成: {verified}/{qualified} signals verified")
```

### 方案 2：单独 refresh cron

新建 `$MARKET_INTEL_ROOT/scripts/refresh_backtest_csv.py`：

```python
"""
每天 18:30 (美股收市后) refresh 4 个 CSV 的最近数据。
"""
import yfinance as yf
from pathlib import Path

TICKERS = {"qqq_10y": "QQQ", "gld_10y": "GLD",
           "spy_10y": "SPY", "xle_10y": "XLE"}
OUTPUT_DIR = Path("$MARKET_INTEL_ROOT/backtest").expanduser()


def refresh_one(csv_name, ticker):
    path = OUTPUT_DIR / f"{csv_name}.csv"
    if not path.exists():
        return
    df = yf.Ticker(ticker).history(period="60d")
    if df.empty:
        return
    new = df.reset_index()[["Date", "Close"]].rename(
        columns={"Date": "date", "Close": "close"}
    )
    new["date"] = new["date"].dt.strftime("%Y-%m-%d")
    existing = set(
        line.split(",")[0]
        for line in path.read_text().splitlines()[1:]
        if line.strip()
    )
    rows_to_append = new[~new["date"].isin(existing)]
    if not rows_to_append.empty:
        with path.open("a") as f:
            rows_to_append.to_csv(f, header=False, index=False)
        print(f"[refresh] {csv_name}: appended {len(rows_to_append)} dates")


if __name__ == "__main__":
    for csv, ticker in TICKERS.items():
        refresh_one(csv, ticker)
```

加 cron: `30 18 * * 1-5 python3 $MARKET_INTEL_ROOT/scripts/refresh_backtest_csv.py`
（schedule 在美股 16:00 ET 收盘 = 北京时间 04:00 次日 / 16:00 北京）；schedule `30 18 * * 1-5` 对应北京时间 18:30，应是 ET 04:30——这里有 timezone 风险，需 `Asia/Shanghai` 校准或用 `30 4 * * 2-6` 对应美东时间 04:30 = 北京次日 16:30。

### 方案 3（应急，一次性）：手动 refetch

2026-07-19 立即补数据：

```bash
python3 << 'EOF'
import yfinance as yf
import pandas as pd
from pathlib import Path

out = Path(os.environ.get("MARKET_INTEL_ROOT", "~/.dsh/market_intel")) / "backtest"
mapping = {"qqq_10y": "QQQ", "gld_10y": "GLD",
           "spy_10y": "SPY", "xle_10y": "XLE"}

for csv_name, ticker in mapping.items():
    p = out / f"{csv_name}.csv"
    df = yf.Ticker(ticker).history(period="60d")
    if df.empty:
        print(f"{ticker}: no data"); continue
    new = df.reset_index()[["Date", "Close"]].rename(
        columns={"Date": "date", "Close": "close"})
    new["date"] = new["date"].dt.strftime("%Y-%m-%d")
    # 读已有 dates
    existing = set()
    if p.exists():
        existing = {line.split(",")[0]
                    for line in p.read_text().splitlines()[1:] if line.strip()}
    append = new[~new["date"].isin(existing)]
    if not append.empty:
        append.to_csv(p, mode="a", header=False, index=False)
        print(f"{csv_name}: +{len(append)} dates, last={append['date'].iloc[-1]}")
    else:
        print(f"{csv_name}: already current")
EOF
```

跑完后立刻 `python3 verify_signals.py` 验证 12 条 signals 应该被处理。

## 影响范围（v1.7.13 P0-3 全线影响）

| 功能 | 当前状态 | 修复后状态 |
|---|---|---|
| `signals.actual_outcome` 回填 | 0 / 106 | 应有 ≥12 行 |
| `evaluate_today_v2.get_rule_stats()` | 返回空 stats | 应有真实胜率 |
| CIO 报告"📊 采纳建议的实际收益" | 无数据 | 有数据 |
| 月度复盘 cron | 0 数据 | 有数据 |
| 用户 90% 准确率叙事 | 无证据支撑 | 有证据支撑 |

## 长期防御（避免再发生）

1. **所有"读 CSV 类"脚本第一行** = freshness probe（last_date vs today）
2. **所有"验证类"脚本最后一行** = 通过率自检（verified/qualified ≥ 50% 否则 warn）
3. **backtest/*_10y.csv 性质明确**：是 backtest 一次性快照，不是 production 数据源。生产应该接 Yahoo Finance chart API（带 retry/cache）。
4. **季报 cron 健康检查**：每周末一个 cron 跑 `SELECT COUNT(*) FROM signals WHERE actual_outcome IS NULL AND generated_at < now-30d` → 若 ≥ 10 → 报警。

## 相关 Pitfall

- **Pitfall D6**（SKILL.md v1.7.14 节）：本次新增——"0 验证" ≠ "工作正常"
- **Pitfall D5**（v1.7.13 节）：signals 表用 `generated_at` 不是 `created_at`——本次诊断查询直接命中
- **D2 关联**：actual_holdings.json 也有"陈旧快照"问题，但本次未涉及

## 反模式（不要做的）

- ❌ 在 verify_signals 里加 try/except 屏蔽 skip — 掩盖问题
- ❌ 把回填任务改成"每天一次现拉 Yahoo"—— verify_signals 是批量回填，应预先准备好数据
- ❌ 等 用户 来提醒"为什么月度复盘没数据"——CIO 必修课：自己探活自己链路

## 相关 skill

- 主技能: `~/.dsh/skills/productivity/financial-market-analysis/SKILL.md`（Pitfall D6 + v1.7.14 changelog）
- `references/cron-runtime-pitfalls.md`（v1.7.x 综合踩坑）
- `references/decision-tracking-protocol.md`（decision_tracker.py 设计）

---
name: financial-market-analysis
description: >
  A-share, fund, QDII, gold, Asia-Pacific index and cross-border asset macro /
  policy / geo / rule-based market analysis framework for DeepSeek Harness.
  DISCLAIMER: for learning/research only, NOT investment advice.
  Works for market moves, fund analysis, holdings strategy, daily reports,
  hot-theme scanning, decision tracking, historical backtest and data-degrade
  fallback. Configurable portfolio & Feishu delivery; no personal data baked in.
platforms: [macos, linux]
triggers:
  - 帮我分析基金走势
  - 宏观政策对基金影响
  - 投资建议 市场分析
  - 每日投资日报
  - 监控投资理财热点
  - 帮我查一下XX基金
  - 生成投资早报/晚报
---

# 金融市场分析技能（通用版）

基于多数据源（A 股、基金、QDII、黄金、亚太指数、全球市场）生成投资日报/分析，
可配置持仓与飞书投递。**所有个人配置（持仓、投递群、凭据、数据目录）通过
`config/config.example.json` 提供，不写死在代码或文档中。**

## 配置

复制 `config/config.example.json` 为 `config/config.json` 并填写：

- `market_intel_root`：数据目录（脚本与 intel.db 所在），默认 `~/.dsh/market_intel`；
  也可用环境变量 `MARKET_INTEL_ROOT` 覆盖（`_lib.py` 读取）。
- `feishu`：`app_id_env`/`app_secret_env`（从环境变量读取凭据，不落盘）、
  `domain`、`deliver_chat_ids`（投递的飞书群/单聊 chat_id 列表）。
- `portfolio`：`total_capital`、`positions`（每只基金 code/name/amount/proxy 代理指数）、
  `cash_equivalent`。
- `reports`：早报/晚报的小时、分钟、工作日。
- `decision_expires_days`：决策追踪过期天数。

> 数据管道脚本（`scripts/`）期望 `db/intel.db`（表：intel/holdings/signals/rules/decisions）
> 位于 `market_intel_root` 下；首次运行 `run_all_p0.py` 会建库并抓取 P0 源。
> Python 依赖：`requests`、`feedparser`（建议 `pip install -r requirements.txt` 或用
> `PYTHONPATH=scripts python3 -m pip install --target .pyreqs requests feedparser`）。

## 核心流程（日报）

早报 09:00 / 晚报 16:00（可配）：

1. **指标追踪**：读 `decisions` 表最近 14 天未到期建议，用当日实时数据逐条核对状态
   （✅ 已触发 / ⏳ 未触发 / ⛔ 已破止损）。
2. **获取数据**：`export PYTHONPATH=scripts`，运行 `evaluate_today.py` /
   `evaluate_today_v2.py` / `ai_compute.py` / `hot_themes.py` 等，或 sqlite 查
   `db/intel.db`；失败按 `references/data-freshness-fallback-protocol-2026-08-06.md`
   的 fallback 链降级。
3. **生成报告**（首席投资分析师视角，大白话）：剩余资金配置 / 加减仓+止盈 / 新方向 / 风险。
4. **记录决策**：每条明确操作建议（有日期/金额/触发价）用
   `decision_tracker.save_decision()` 写入 `decisions` 表（30 天后可回填验证）。
5. **投递飞书**：用配置的凭据与 chat_ids 发 text 消息。

## 数据源

> 以下「采购/招标公告类」数据源仅用于行业景气与订单需求研究（如观察企业采购活跃度、电网设备招标同比作为行业指标），与投标代理 / 投标监控 / 竞标服务无关。

- 泰康 TIPVS（POST `tipvs.mobile.taikang.com/api/.../getTipTodoPublicMethodPost`） —— 采购公告类（行业研究）
- AIIB（GET `rfxrestapi.aiib.org:9090/publicapi/v1/jsonp/rfxopen`，timestamp+MD5 认证；
  status 全为 awarded，按 startDate 倒序 + responseDeadline>now 过滤） —— 采购公告类（行业研究）
- 奇瑞采购（POST `ebd.mychery.com/cms/api/dynamicData/queryContentPage`；报名或报价任一过期即过滤） —— 采购公告类（行业研究）
- 吉利电子招标（GET `glzb.geely.com/gpmp/notice/listnotice`；`publishtime/endtime` 为毫秒时间戳） —— 采购公告类（行业研究）
- UNGM（POST `www.ungm.org/Public/Notice/Search`，需先 GET 拿 cookie；NoticeTypes 用 checkbox id） —— 采购公告类（行业研究）
- 世界银行 WDS（GET `search.worldbank.org/api/v2/wds?format=json`；字段名 `projn/count`） —— 采购公告类（行业研究）
- 更多见 `references/data-source-gotchas.md` / `data-retrieval-apis.md`。

## 报告模板

见 `references/report-output-template-v2.md`。核心四层：宏观 → 市场全貌 →
剩余资金配置 → 持仓加减仓（持仓放最后）。**所有触发条件必须标注标的类型**
（指数点位 / ETF 价格 / 基金净值 / 涨跌幅），禁止只写一个数字。

## 决策追踪

- `decisions` 表：id/decision/rationale/sources/signal_ids/created_at/expires_at。
- `decision_tracker.py`：`save_decision()` 写入、`get_pending_decisions()` 读最近、
  `verify_decisions()` 30 天后回填 actual_outcome/pnl_pct。
- 协议见 `references/decision-tracking-protocol.md`。

## 定时任务（可选，macOS launchd）

参考 `examples/launchd/`：P0 入库（工作日 07:50）、早报（09:00）、晚报（16:00）。

## 免责声明

本技能提供的信息仅供参考，不构成投资建议。投资有风险，决策需谨慎。

## 文档

- `references/`：数据源、fallback 协议、模板、pitfall（方法论，通用）。
- `report_prompts/`：早报/晚报的 agent 提示词（占位符 `{{...}}` 由
  `scripts/render_prompts.py` 结合 config 渲染）。

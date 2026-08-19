# 微信投资理财日报 — 实测模板

用户 偏好：极简、数据驱动、关注宏观+地缘+持仓波动。微信渲染对 Markdown 表格/复杂标题支持差，**纯文本+emoji 列表**是经过实测的最稳形式。

---

## 模板（已 用户 确认，2026-06-06）

```
📊 投资理财日报 MM月DD日 HH:MM

🔻 持仓动态
- 012752 纳指QDII 估值X.XX | 今日xx% | 近1周xx% | 近1月xx% | 近1年xx%
- 022653 黄金ETF 估值X.XX | 今日xx% | 近1周xx% | 近1月xx% | 近1年xx%
- 025857 电网设备ETF 估值X.XX | 今日xx% | 近1周xx% | 近1月xx% | 近1年xx%

🌍 今日核心热点
1. （短标题） — 一句话影响
2. ...

🎯 未来1个月策略
① 012752 纳指QDII — [🟢加仓/🔵持有/🟡减仓/⚪观察] 一句话理由
   • 情景A（概率%）：... → 动作
   • 情景B（概率%）：... → 动作
   • 情景C（概率%）：... → 动作
   • 触发器：①xxx ②xxx
② ...

🆕 建仓候选
- 方向1：标的/工具思路 + 触发逻辑
- 方向2：...
- 方向3：...

⚠️ 风险声明：基于公开信息的情景分析，不构成投资建议；具体仓位和时点由 用户 独立决策。
```

---

## 硬约束

| 项 | 限制 | 原因 |
|---|---|---|
| 总字数 | ≤ 600 字 | 微信长消息折叠 + 用户 极简偏好 |
| 表格 | **不用** | 微信表格渲染差，列宽不一致 |
| Markdown 标题 | **不用**（`##`） | 微信只显示为纯文本 `# ## ###` |
| 加粗 | **不用**（`**xx**`） | 微信不渲染加粗，浪费时间 |
| 方向建议 | **🟢加仓 / 🔵持有 / 🟡减仓 / ⚪观察** | 4 个状态色已覆盖 + 避免误读 |
| 风险声明 | **必出现** | 既是合规要求也是 用户 决策边界 |
| 触发器 | **必出现** | 用户 据此判断是否行动 |

---

## 持仓阶段涨幅（必抓数据）

来源：`https://fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease?FCODE={code}&deviceid=W&plat=Wap&product=EFund&version=2.0.0`

字段映射（容易踩坑）：
- `Z` = 近 1 周
- `Y` = 近 1 月  ← 用户 最关注
- `3Y` = 近 3 月
- `6Y` = 近 6 月
- `1N` = 近 1 年
- `JN` = 今年来

返回字段：`syl`(本基金) / `avg`(同类均值) / `hs300`(沪深300同期) / `rank` / `sc`(样本数) / `diff`（rank diff）

注：东财 push2his.eastmoney.com 拉 NDX/AU9999/电网设备指数 30 天 kline **全部返回 rc:100**（无效 secid），日报里**不要用这个 API 拉指数**。直接用基金阶段涨幅已经够分析。

---

## Cron 监控日报模式

### Schedule
- 默认每天 **8:00 + 16:00 北京时间**（`schedule: "0 8,16 * * *"`）
- 周报/复盘可在周日单独一条（`"0 9 * * 0"`）

### Deliver
- 微信 DM：`deliver: "origin"`（=当前会话）
- 飞书群：`deliver: "feishu:oc_xxx"`
- 多通道：`deliver: "weixin:chat_id,feishu:oc_xxx"`（逗号分隔）

### Cron Prompt 自包含模板

```text
你是 用户 的投资理财日报机器人。Cron 每次触发时执行一次，生成当日投资理财日报（含策略建议层），作为 final response 输出（系统会自动投递到当前微信会话）。

## 必做步骤
1. 加载 financial-market-analysis skill 获取数据源 API 详细说明
2. 拉取 用户 持仓 3 只基金的最新数据（fundgz.1234567.com.cn + fundmobapi.eastmoney.com FundMNPeriodIncrease）
3. 拉取以下分类财经快讯各 5-8 条：101/102/106/107/108/109/113/116/118
4. 整合 3-5 条今日核心热点（去重合并）
5. 为 3 只基金分别生成未来 1 个月策略建议（方向性，不代为决策，不给具体买卖点位）
6. 列出 3-5 个建仓候选方向

## 输出格式：见 references/wechat-daily-report.md 模板
## 硬约束：≤600字，不用表格/Markdown标题/加粗，必含风险声明
## 用户 偏好：极简不堆砌，关注宏观+地缘+持仓波动
```

### 坑：`cronjob action=run` 不可靠

2026-06-06 实测：手动 `action=run` 后 `last_run_at` 仍为 null，等 30+ 秒也没更新。**fallback**：

- 想立即看微信效果 → 直接用 `send_message(action="send", target="weixin:<chat_id>")` 把报告内容发出去
- 验证 cron 本身 → 查 `next_run_at`（一定准时）+ 等 schedule 自然触发
- 不要把 `action=run` 当作"立即生成+投递"的稳定路径

新建 cron job_id 命名建议：`<topic>-<freq>`，例 `投资理财日报-08` `投资理财日报-16`。

---

## 失败恢复：两阶段诊断法（2026-06-07 实战）

日报 cron 失败分**两个独立阶段**，根因和修复方法完全不同。每次 8:00/16:00 没看到日报时，先按此法诊断再动手。

### Stage 1: LLM 生成失败（provider 连接抖动）

**症状**：`output/<job_id>/<timestamp>.md` 文件**仍然生成**，但内容是 prompt 模板全文 + 末尾 `## Error` 段落写 `RuntimeError: Connection error.`，**没有任何真实日报内容**

**根因**：LLM provider API 临时不可达（2026-06-07 8:00 实测：minimax 平台 provider 抖动）

**诊断**：
```bash
# 1. 找最新输出文件，看标题
LATEST=$(ls -t ~/.dsh/cron/output/26322edf978c/*.md | head -1)
head -1 "$LATEST"   # 期望: "# Cron Job: 投资理财日报（策略版） (FAILED)"
tail -10 "$LATEST"  # 期望: "## Error" + "RuntimeError: Connection error."
```

**修复**：
```bash
hermes cron run 26322edf978c   # 重跑
# 等 3-5 分钟（新 agent session 重新调 LLM）
# 再看文件: 标题应无 (FAILED) 标记, 内容是真日报
```

### Stage 2: 投递失败（WeChat iLink 限流 / SSL）

**症状**：报告**已生成**（文件 clean，无 FAILED 标记），但 `last_delivery_error` 显示 `Weixin send failed: Cannot connect to host ilinkai.weixin.qq.com:443 ssl:default [Connection reset by peer]`

**根因**：WeChat iLink 通道限流（2026-05-17 起常态化，6/7 8:00 实测）

**诊断**：
```bash
hermes cron list | grep -A3 "26322edf978c" | grep -i "delivery\|last_run"
```

**修复（两步）**：
```bash
# 1. 临时切到飞书投递（用户 主飞书 chat：oc_XXXX）
hermes cron update 26322edf978c --deliver "feishu:oc_XXXX"

# 2. 重新触发
hermes cron run 26322edf978c
```

### 经验法则

| 现象 | 阶段 | 修复 |
|------|------|------|
| 标题带 `(FAILED)` + 末尾 `RuntimeError` | Stage 1 | `cron run` 重跑 |
| 标题干净 + `last_delivery_error` 是 iLink SSL | Stage 2 | `cron update --deliver feishu:...` 切通道 + `cron run` |
| 文件小（<20KB）+ 标题干净但内容空 | Stage 1 变体 | 同 Stage 1 |
| `last_status=ok` 但用户没收到 | 投递到错误 channel | 检查 deliver 字段 |

### 长期建议

`26322edf978c` 默认 `deliver: origin`（= WeChat DM）是**已知脆弱配置**：
- WeChat iLink 限流/SSL 错误每周至少 1-2 次（2026-05/06 多次实测）
- 2026-06-07 已切到 `feishu:oc_XXXX`（用户 主飞书），稳定性显著提升
- **如果 用户 重新要求微信投递**，可以临时切回，但**默认保持 feishu** 是更稳的运营选择

类似 cron 也有同样脆弱性（任何用 `deliver: origin` 的都依赖 WeChat iLink）：建议全部加一份 feishu 作为 fallback。

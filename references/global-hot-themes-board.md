# 全球热点板块扫描管线（§7）

> **触发场景**：用户 问"现在的市场热点 / 投资方向" / "为什么报告不推 AI 算力" / cron 投资理财日报构建 "今日核心热点" / "建仓候选" 板块
>
> **状态**：v1.7.11 起为日报硬约束（2026-07-15 用户 痛批后新增）

## 核心问题（2026-07-15 用户 锁定）

CIO 元方法论（memory 多次记录）= **主动扫描全市场热门板块**，每次日报必含"持仓之外"机会清单 ≥3 个。但 v1.7.10 之前的 cron prompt 偷懒：
- "建仓候选"只套 KB 扫描结果（`kb_holdings_scan.py`），KB 只覆盖"用户 已配置的偏好行业"（保险/数据治理/亚太），**无法捕捉当周全市场热点**
- "今日核心热点"只拉东财 8 个分类快讯，没 RSS 全球财经新闻源

**结果**：AI 算力/半导体/医药/新能源这种当周全球热点板块**完全没有独立抓取脚本**，报告从来不提。用户 原话："现在AI和算力产业链都是热门板块为什么你的投资报告从来没有推荐或者分析 + 如果都需要我来提醒，我还要你干嘛"

## 数据源矩阵

| Source | URL | 频率 | 内容 |
|---|---|---|---|
| **ai_compute.py** (P1 #8) | Yahoo Finance chart API | 每次 P0 跑（含 18:50 二次）| 11 个 AI 算力/半导体/中概标的实时价 + 涨跌 + 5日 K 线 |
| **hot_themes.py** (P1 #9) | Yahoo Finance RSS + Investing.com RSS | 每次 P0 跑 | 30 条全球财经新闻，按 sector 自动分类 |

## 标的清单

**ai_compute.py（11 个）**：
- 算力芯片：NVDA / AMD / TSM / AVGO / ARM
- AI 软件：PLTR
- 服务器：SMCI
- 半导体 ETF：SOXX / SMH
- 软件 ETF：IGV
- 中概互联网：KWEB

**未覆盖但应评估**（未来可扩）：
- 软件：MSFT / GOOGL / ORCL / CRM（看 AI 应用）
- 网络/CRO/CDN：NOW / CRWD / NET
- 半导体设备：ASML / KLAC / AMAT / LRCX
- 中国 AI：寒武纪、商汤、百度（BABA）、阿里（BABA）
- 新能源电池：宁德时代（300750）/ CATL ETF (02828.HK)
- 医药：LLY / NVO / MRNA / PFE
- 中概：JD / BIDU / NTES / BILI

扩规则：每个 sector 加 1-2 个核心标的即可（11→15），不要无限扩张。

## cron 报告硬约束（v1.7.11 §7 规则 ABC）

| 规则 | 内容 | 失败后果 |
|---|---|---|
| **A - 今日核心热点** | ≥3 条来自 `source='hot_themes'`，≥2 个不同 sector，AI+宏观各 ≥1 条 | 不合格报告 |
| **B - 建仓候选** | ≥2 个标的来自当周全球热门板块（AI 算力/半导体/AI 软件/中概互联/医药/新能源）| 不合格报告 |
| **C - 全球市场全貌** | 必须包含亚太（港/日/韩）+ 美股 AI 算力 + 半导体 ETF（SOXX/SMH/IGV），任一单日 |涨跌|>3% 必须显式标注 | 不合格报告 |

## 反思铁律（写入 SKILL body）

- ❌ **不能再把 KB 扫描当 "建仓候选" 的充分条件** — KB 只算输入维度之一
- ❌ **不能再只写持仓相关, 必须主动扫描全市场**
- ❌ **不能漏掉当周全球热点**（AI 算力/半导体/医药/新能源, 任一 |涨跌|>3% 必标）
- ✅ **每份报告 = "全球市场全貌" + "今日核心热点" + "建仓候选" 三层全市场覆盖**

## 主脚本位置

```
$MARKET_INTEL_ROOT/scripts/ai_compute.py       # AI/半导体 11 标的
$MARKET_INTEL_ROOT/scripts/hot_themes.py        # 全球财经 RSS + sector 分类
scripts/p0_cron_wrapper.sh                     # P0 调度（含 ai_compute + hot_themes）
~/.dsh/cron/jobs.json                                 # cron job_id 26322edf978c + 362ea7b6333b
```

## 相关 changelog

- **v1.7.11** (2026-07-15)：新增 §7 + ai_compute.py + hot_themes.py + cron prompt 硬约束
- **v1.7.2 §6.6**：持仓 staleness 14 天分级（已过期，由 §6.11 升级为 30 天分级）
- **v1.7.5**：vix MA200 跨周期过滤器（与热点扫描正交，热点扫描看短中期）

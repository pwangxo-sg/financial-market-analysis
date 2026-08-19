# 多源数据基础设施 (P0 Pipeline)

> 2026-06-06 搭建。用户 投资分析的**数据骨架**。覆盖：财经新闻 + 监管 + 事件 + 情绪 + 商品价格 + 基金净值。

## 目录结构

```
$MARKET_INTEL_ROOT/
├── scripts/           # 抓取脚本
│   ├── _lib.py       # 共享 lib (get_db, save_intel, query_intel)
│   ├── rss_ingestor.py
│   ├── eastmoney_reports.py
│   ├── fed_sec_calendar.py
│   ├── usgs_noaa_monitor.py
│   ├── reddit_sentiment.py
│   ├── eia_commodity.py
│   ├── moltbook_ingestor.py
│   └── run_all_p0.py
├── db/intel.db        # SQLite 统一存储
├── logs/              # 每个脚本的运行日志
└── reports/           # 月度复盘报告（待建）
```

## 共享 lib (`_lib.py`)

所有抓取脚本 import 此模块。核心 API:

- `get_db()` — SQLite 连接 context manager
- `init_db()` — 初始化 schema
- `save_intel(items, source, source_type)` — 存储 intel，自动 hash 去重
- `query_intel(source, source_type, since, limit)` — 查询
- `stats_by_source(days)` — 统计各源抓取量
- `safe_get(url, ...)` — 带重试的 HTTP GET
- `BJT` — 北京时区

**去重策略**: hash = MD5(source + title + url)。同一条新闻多次抓取只入库一次。

## SQLite Schema (5 张表)

```sql
-- intel: 所有抓取内容（核心表）
CREATE TABLE intel (
  id INTEGER PRIMARY KEY,
  hash TEXT UNIQUE,        -- 去重 hash
  source TEXT,             -- e.g. "bloomberg_markets", "fed_press"
  source_type TEXT,        -- news/regulator/research/event/sentiment/commodity
  title TEXT,
  content TEXT,
  url TEXT,
  author TEXT,
  published_at TEXT,       -- ISO 8601
  fetched_at TEXT,
  tags TEXT,               -- JSON 数组
  severity INTEGER,        -- 1-5
  extra TEXT,              -- JSON
  used_in_rule TEXT
);

-- holdings: 持仓表
CREATE TABLE holdings (
  code TEXT PRIMARY KEY,
  name TEXT,
  type TEXT,               -- fund/etf/stock
  amount_rmb REAL,
  shares REAL,
  cost_basis REAL,
  added_at TEXT
);

-- signals: 规则引擎输出
CREATE TABLE signals (
  id INTEGER PRIMARY KEY,
  code TEXT,               -- 标的代码
  signal_type TEXT,        -- add/reduce/hold/observe
  direction TEXT,          -- long/short/hedge
  confidence INTEGER,      -- 0-100
  rule_id TEXT,            -- 触发的规则
  evidence TEXT,           -- JSON
  generated_at TEXT,
  expires_at TEXT,
  verified_at TEXT,
  actual_outcome TEXT,     -- win/loss/neutral
  pnl_pct REAL
);

-- rules: 规则定义
CREATE TABLE rules (
  rule_id TEXT PRIMARY KEY,
  description TEXT,
  scope TEXT,              -- fund/asset-class/cross-asset
  target_codes TEXT,       -- JSON
  conditions TEXT,         -- JSON 条件表达式
  expected_win_rate REAL,
  expected_hold_days INTEGER,
  enabled INTEGER,
  created_at TEXT,
  backtest_result TEXT     -- JSON 回测结果
);

-- decisions: 首席投资专家签字日志
CREATE TABLE decisions (
  id INTEGER PRIMARY KEY,
  decision TEXT,
  rationale TEXT,
  sources TEXT,            -- 引用 intel ID
  signal_ids TEXT,
  created_at TEXT,
  expires_at TEXT
);
```

## 8 个 P0 抓取脚本（2026-06-06 增 treasury_ingestor）

### 1. `rss_ingestor.py` — RSS 财经+监管+机构
- **覆盖**: Reuters / Bloomberg / AP / FT / CNBC + Fed / SEC / ECB / US Treasury / BIS + BlackRock / Goldman / JPM / MS
- **状态**: 9/20 工作（Reuters/AP SSL 错, Treasury/BIS 404, 4 大投行 RSS 失效）
- **数据量**: 每次 ~200 条
- **耗时**: ~25s

### 2. `eastmoney_reports.py` — 研报中心
- **覆盖**: 15 家头部机构（中金/中信/华泰/招商/海通/国泰君安/国信/广发/申万/兴业/高盛/摩根士丹利/摩根大通/瑞银/美银美林）
- **时间窗**: 最近 30 天
- **API**: `https://reportapi.eastmoney.com/report/list?cb=jQuery&...&orgCode=<id>`
- **注意**: 响应是 jQuery wrap，解析时 `data` 可能是 dict 或 list（必须用 `isinstance` 检查，不能直接 `data[:limit]`）

### 3. `fed_sec_calendar.py` — Fed + SEC
- **Fed**: FOMC 日历 + 讲话日程 (RSS)
- **SEC**: 8-K 重大事项（EDGAR full-text search API: `https://efts.sec.gov/LATEST/search-index?q=...`）
- **数据量**: Fed 35 条, SEC 20 条

### 4. `usgs_noaa_monitor.py` — 突发事件
- **USGS**: 过去 7 天 M2.5+ + 过去 1 天 M5.0+ 地震
- **关键地缘区域**: Hormuz/Taiwan/Japan/Turkey/Iran/Indonesia（自动坐标匹配 + 严重度升级）
- **NOAA**: 大西洋/东太平洋飓风 (RSS)
- **数据量**: USGS 319 条（含噪声）, NOAA 9 条

### 5. `reddit_sentiment.py` — Reddit 情绪
- **关键 workaround**: 用 RSS（`.rss`）替代 JSON API（被反爬 403）
- **4 个 subreddit**: wallstreetbets/stocks/investing/options
- **关注标的关键词**: 012752/022653/025857/020274 + 宏观（fed/rate/inflation 等）
- **情绪打分**: bull/bear 词频 → -1 到 +1
- **数据量**: 60 条/次

### 6. `eia_commodity.py` — 能源 + 黄金 + COT
- **WTI/天然气价格**: Yahoo Finance（CL=F / NG=F）
- **GLD**: Yahoo Finance 历史价格+成交量
- **CFTC COT 正确 URL**:
  - `https://www.cftc.gov/dea/newcot/deafut.txt` (Legacy Futures-Only)
  - `https://www.cftc.gov/dea/newcot/FinFutWk.txt` (Traders in Financial Futures)
  - 旧 URL `/sites/default/files/files/dea/cot/finfutfut.txt` 已 404

### 7. `moltbook_ingestor.py` — AI agent 视角
- **3 个 submolt**: agentfinance / trading / crypto
- **当前状态**: 临时不可用（平台 403/空页，2026-06-06 起）
- **graceful degradation**: 全部失败时写 `moltbook_status` source_type=system 的降级记录

### 8. `treasury_ingestor.py` — 美债名义 + TIPS 实际利率（2026-06-06 新增）
- **名义收益率**: 1Mo-30Yr 全期限（CSV）
- **TIPS 实际利率**: 5Y/7Y/10Y/20Y/30Y（关键！黄金/纳指规则核心）
- **URL pattern**: `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/{yyyymm}?type=daily_treasury_{real_}yield_curve&field_tdr_date_value_month={yyyymm}&page&_format=csv`
- **历史拉取**: `treasury_history.py` 拉 5 年 = 60 个月 = 1233 天
- **公开免代理**，用户 当前网络直连可用
- **重要发现**: 2026-06-05 TIPS 10Y = +2.25%（实际利率仍正，黄金"实际利率"逻辑短期不成立）

## 当前激活 13 个源 (2026-06-06 首次跑)

| 源 | source_type | 数据量/次 | 状态 |
|---|---|---|---|
| Bloomberg markets | news | 20 | ✅ |
| Bloomberg econ | news | 20 | ✅ |
| CNBC top | news | 20 | ✅ |
| CNBC economy | news | 20 | ✅ |
| FT markets | news | 20 | ✅ |
| FT world | news | 20 | ✅ |
| Fed press | regulator | 20 | ✅ |
| Fed speeches | regulator | 15 | ✅ |
| SEC press | regulator | 20 | ✅ |
| ECB press | regulator | 15 | ✅ |
| Reddit ×4 | sentiment | 15×4=60 | ✅ |
| GLD | commodity | 9 | ✅ |
| NOAA | event | 9 | ✅ |
| CFTC COT | commodity | 8 | ✅ |
| EIA oil/gas | commodity | 2 | ✅ |
| FOMC calendar | regulator | 1 | ✅ |

**首次跑总入库**: 279 条 (去重后)，~123 秒

## 失败源 + 修复方向

| 源 | 错误 | 根因 | 修复 |
|---|---|---|---|
| Reuters | SSL EOF | HK 出口 TLS 握手失败 | 换 HTTP client 或换源（FT/Bloomberg 够用可跳过）|
| AP News | SSL EOF | 同上 | 同上 |
| US Treasury | 404 | RSS URL 失效 | 找新 URL（`https://home.treasury.gov/news/press-releases/feed` 失效）|
| BIS | 404 | 旧 URL 失效 | 换正确路径 |
| BlackRock/Goldman/JPM/MS | 404/403 | 官方 RSS 失效 | 改网页抓取 |
| Moltbook | 403/空页 | 平台限流 | 等恢复（已加降级）|
| Eastmoney 研报 | API 解析 bug | data 可能是 dict 或 list | 已修（`isinstance` 检查）|

## 运行方式

```bash
# 跑全部
cd $MARKET_INTEL_ROOT/scripts && python3 run_all_p0.py

# 跑单个
python3 rss_ingestor.py
python3 eastmoney_reports.py

# 查 24h 统计
sqlite3 $MARKET_INTEL_ROOT/db/intel.db \
  "SELECT source, source_type, COUNT(*) as n, MAX(published_at) as latest
   FROM intel WHERE fetched_at >= datetime('now', '-1 day')
   GROUP BY source ORDER BY n DESC"

# 查关注标的最近 intel
sqlite3 $MARKET_INTEL_ROOT/db/intel.db \
  "SELECT source, title, published_at FROM intel
   WHERE tags LIKE '%nasdaq%' OR content LIKE '%QQQ%'
   ORDER BY published_at DESC LIMIT 20"
```

## 下一步扩展 (P1)

| 优先级 | 源 | 价值 | 估时 |
|---|---|---|---|
| P1 | 4 大投行网页抓取 | 机构观点 | 1h |
| P1 | X/Twitter 财经大 V | 实时情绪 | 2h |
| P1 | Polymarket 预测市场赔率 | 群体预测 | 1h |
| P1 | 航班/油轮跟踪 | 地缘事件核心 | 2h |
| P2 | 卫星图像（港口/工厂）| 另类数据 | 4h |
| P2 | 衍生品 COT 详细分析 | 持仓信号 | 2h |

## 关键设计决策

1. **hash 去重**: 同一新闻多源抓取只入库一次，节省空间 + 避免重复信号
2. **severity 字段**: 5 级严重度，让规则引擎优先看 severity ≥ 3 的事件
3. **tags JSON**: 灵活的标签系统（标的/地区/事件类型），便于过滤
4. **graceful degradation**: 每个抓取脚本独立失败，不阻断其他源
5. **结构化 extra JSON**: 保留源特有字段（如 Reddit sentiment score, CFTC market name）

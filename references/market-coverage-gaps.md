# 市场覆盖现状与"数据缺失"诊断（2026-06-14 锁定）

## 🚨 3 种"数据缺失"的根因（最重要的诊断铁律）

当日报/报告/任何输出出现"X 数据缺失"时，**根因有且只有 3 种**。**每种对应不同的修复**——不要上来就加数据源，先分类：

| 类型 | 含义 | 修复方式 | 案例（2026-06-14） |
|---|---|---|---|
| **Type A: 抓取脚本不存在** | 该市场/品种**完全没有** ingestor | 新建 ingestor 脚本 | **加密 BTC/ETH** — `scripts/` 下无任何 `crypto_ingestor.py`，`polymarket_ingestor` / `moltbook_ingestor` 只抓 AI 讨论文本而非真实价格 |
| **Type B: 脚本存在但缺代码** | ingestor 在跑，但 `SYMBOLS` 列表**没列这个标的** | 在现有脚本里加 code/常量 | **港股** — `yahoo_cn_index.py` 的 `CN_INDICES` 只有 A 股指数（沪深300/中证500/科创50/红利/创业板），**没有** `^HSI`/`^HSCE`/`^HSTECH` |
| **Type C: 数据已抓但报告没写** | ingestor 拉到了、DB/日志有值，但 Agent 写报告时**漏写**该段 | 改 cron prompt 模板硬约束 | **美债** — `evaluate_today.log` 显示 us10y=4.48 / us2y=4.09 都拉到了，**但 Agent 在"市场全貌"段没把美债数字写出来** |

**诊断流程（30 秒定位）**：

```
报告说"X 数据缺失"
    ↓
[1] 查 evaluate_today.log / run_all_p0.log → 有没有 "✅ x" 日志？
    ├─ 有 → Type C（数据有，报告漏写）→ 改 prompt 硬约束
    └─ 没有 ↓
[2] ls scripts/ | grep -i <x> → 有没有 ingestor 脚本？
    ├─ 有 → Type B（脚本在但缺代码）→ 在现有脚本加 SYMBOL/code
    └─ 没有 → Type A（脚本不存在）→ 新建 ingestor
```

**反向验证：必须两个证据**：
- Log 证据（确实拉到了/确实没拉到）
- Code 证据（脚本里有/没有该 symbol）

不能只信一个。

---

## 📊 当前 6 市场覆盖状态（2026-06-14 盘点）

| 市场 | 数据源 | 抓取脚本 | cron 时效 | 日报覆盖率 | 状态 |
|---|---|---|---|---|---|
| A 股（沪深300/中证500/科创50/红利/创业板） | Yahoo Finance | `yahoo_cn_index.py` | T+1 | ✅ 完整 | OK |
| **港股（HSI/HSCE/HSTECH）** | — | **❌ 缺代码** | — | ❌ "数据缺失" | **Type B 待修** |
| **港股 ETF（513180 恒科 / 513130 恒生科技）** | Sina HQ | **❌ 缺** | — | ❌ | **Type B 待修** |
| 美股（QQQ/SPY/GLD/DIA） | Yahoo Finance | `evaluate_today.py` 内嵌 | T+0 | ✅ 完整 | OK |
| 黄金（GLD + 022653） | Yahoo + 基金涨幅 | `evaluate_today.py` + Eastmoney | T+0 | ✅ 完整 | OK |
| **加密（BTC/ETH）** | — | **❌ 缺整个脚本** | — | ❌ | **Type A 待建** |
| 美债（10Y/2Y/TIPS/30Y） | Treasury CSV + Yahoo 备用 | `treasury_ingestor.py` + `evaluate_today.py` 内嵌 | T+1 | ⚠️ **数据有，报告漏写** | **Type C 待修** |
| 原油（WTI） | Yahoo Finance | `evaluate_today.py` 内嵌 | T+0 | ✅ 完整 | OK |
| 美元指数（DXY） | Yahoo Finance | `evaluate_today.py` 内嵌 | T+0 | ✅ 完整 | OK |
| VIX | Yahoo Finance | `evaluate_today.py` 内嵌 | T+0 | ✅ 完整 | OK |

**3 个 gap，按 ROI 排序**：

1. **港股 HSI 系列**（Type B，5 分钟修复）— 改一行 `CN_INDICES` 加 3 个 symbol
2. **美债漏写**（Type C，5 分钟修复）— cron prompt 加 6 市场硬约束
3. **加密 BTC/ETH**（Type A，15 分钟新建）— 新脚本 + DB 字段

---

## 🔧 3 个 Gap 的具体修复方案（待 用户 决定 2026-06-14）

### 1. 港股指数（Type B，5 min）

**文件**：`$MARKET_INTEL_ROOT/scripts/yahoo_cn_index.py`

**改**：`CN_INDICES` 字典加 3 个 Yahoo 代码：

```python
CN_INDICES = {
    "000300.SS": "沪深300",
    "000905.SS": "中证500",
    "000688.SS": "科创50",
    "000015.SS": "红利指数",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300（上交所）",
    # === 港股 (2026-06-14 新增) ===
    "^HSI": "恒生指数",
    "^HSCE": "恒生中国企业指数",
    "^HSTECH": "恒生科技指数",
}
```

**Yahoo Finance 代码验证（已查 2026-06-14）**：
- `^HSI` ✅（直连可用，HK IP 也 OK）
- `^HSCE` ✅
- `^HSTECH` ✅

**数据写入**：`backtest/^HSI.csv` / `^HSCE.csv` / `^HSTECH.csv`

### 2. 美债漏写（Type C，1 min 改 prompt）

**文件**：`~/.dsh/cron/output/26322edf978c/` 的 cron prompt（不是 SKILL.md）

**改**：在 cron prompt 模板的"🚨 报告结构铁律"段加第 7 条：

```text
7. "市场全貌" 段必须包含 6 个子段，每个 ≥1 行数据：
   - A股（沪深300/中证500/创业板 至少 1 个）
   - 港股（HSI/HSCE/HSTECH 至少 1 个）
   - 美股（QQQ/SPY/NDX 至少 1 个）
   - 黄金（GLD/AU9999/022653 至少 1 个）
   - 加密（BTC/ETH 至少 1 个 — 当前为 N/A 需说明原因）
   - 债券（10Y/2Y/TIPS 至少 1 个）
   即使某项数据缺失，也要明确写"X 数据：未接入"或"节假日无数据"
   禁止用"X 数据缺失"一句话敷衍。
```

### 3. 加密 BTC/ETH（Type A，15 min 新建）

**新文件**：`$MARKET_INTEL_ROOT/scripts/crypto_ingestor.py`

**API**（无 key，10 req/min 够用）：
```
https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true&include_7d_change=true&include_30d_change=true
```

**返回**：
```json
{
  "bitcoin": {"usd": 67890, "usd_24h_change": 1.2, "usd_7d_change": -3.4, "usd_30d_change": 8.9},
  "ethereum": {"usd": 3450, "usd_24h_change": 0.8, ...}
}
```

**写入**：sqlite `intel.signals` 表，source=`crypto_coingecko`，extra JSON 存全部字段

**evaluate_today.py 加指标**：
```python
# 11. BTC / ETH 24h/7d/30d
try:
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true&include_7d_change=true&include_30d_change=true"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    if resp:
        d = resp.json()
        indicators["btc_24h_pct"] = d["bitcoin"]["usd_24h_change"] / 100
        indicators["btc_7d_pct"] = d["bitcoin"]["usd_7d_change"] / 100
        indicators["btc_30d_pct"] = d["bitcoin"]["usd_30d_change"] / 100
        indicators["eth_24h_pct"] = d["ethereum"]["usd_24h_change"] / 100
        indicators["eth_7d_pct"] = d["ethereum"]["usd_7d_change"] / 100
        indicators["eth_30d_pct"] = d["ethereum"]["usd_30d_change"] / 100
except Exception as e:
    log.warning(f"  ❌ crypto: {e}")
```

**用户 关注度**：BTC 30d > 7d > 24h（与基金涨幅 Y/1N 逻辑一致）

---

## ⚠️ 港股 ETF 实时（用户 实际持仓相关）

虽然 用户 当前不持有 513180/513130，但**Plan B 默认配置含 513130 恒科 5 万**。日报需要跟踪：

- `hq.sinajs.cn/list=hk_513130`（Sina 港股 ETF 实时）
- 返回 `var hq_str_hk_513130="恒生科技ETF,1.234,0.012,2026-06-14,..."`

**优先级低于 1+2+3**（Plan B 未启动时不紧急）。

---

## 🔁 防止 3 个 Gap 再发生的检查清单

每次加新市场/品种到日报时：

- [ ] ingestor 脚本存在？
- [ ] 脚本里 `SYMBOLS`/`CODES`/`INDICES` 加了新 code？
- [ ] `evaluate_today.py` 加了对应指标？
- [ ] `run_all_p0.py` 调用了新 ingestor？
- [ ] cron prompt 模板的 6 市场子段约束覆盖了？
- [ ] 隔天跑一次确认数据真进了 DB？

**任何一项漏了 = 下次日报就报"X 数据缺失"**。

---

## 🎯 2026-06-15 实战:第 4 种路径（"cron-prompt 直拉 curl"）— 比建 ingestor 快 5-10x

**情境**：用户 02:04 问"为什么日报里港股/加密/美债数据缺失"。**实测发现**:

- 港股 / 加密 = Type A/B（无脚本或脚本没列 symbol）
- 美债 = Type C（`treasury_ingestor.py` 已建,数据有,Agent 漏写）

**理论上 3 种根因对应 3 段修复**（前面 §3,合计 ~21 分钟）：
- 港股: 5 min
- 美债: 1 min 改 prompt
- 加密: 15 min 新 ingestor

**但 用户 在 02:04 醒着等日报**,21 分钟太久。**新路径**（实测 5 分钟完成,8:00 cron 自动跑验证）:

| 步骤 | 动作 | 时间 |
|---|---|---|
| 1 | 验证 3 个 API 真的活着（curl/Python 一次过,Sina HK + CoinGecko + Treasury）| 30s |
| 2 | 解析格式验证（实测 Sina HK 字段位置[0]eng [1]中文 [2]现价 [3]昨收 [7]涨跌额 [8]涨跌幅% — **与 A 股/美股格式不同,常见误读**）| 1 min |
| 3 | cron prompt 加"步骤 3.0 拉取硬数据"段,3 个 curl + 解析示例 | 1 min |
| 4 | cp jobs.json{,.bak.20260615_*} 备份 | 10s |
| 5 | 实测 3 个 curl 拿到真实数据(HSI 24,501 +1.93% / BTC $63,733 -0.47% / 10Y 4.47%)| 30s |

**核心技巧**:**让 cron agent 现场拉 3 个 curl 写进报告,跳过了"建 ingestor + 入 DB + 改 evaluate_today + 改 run_all_p0"全链路**。

**代价（必须明确）**:
- ❌ 数据不入 DB,无法做 backtest 规则（BTC 24h > 5% 这种规则暂时没法跑）
- ❌ 数据无历史,无法画趋势
- ❌ cron 跑挂了就完全没数据
- ❌ 拉取失败时只能"今日不可用",没有兜底缓存

**对 用户 的建议**:
- **当前默认** = cron-prompt 直拉（5 min 上线,先看效果）
- **P1 升级** = 跑稳后,把 3 个 curl 升级为正式 ingestor,数据入 intel.db（30 min,可回溯可规则）
- **切换信号**: 30 天后数据稳定 + 0 失败 → 不动；中途想加 BTC 24h > 5% 类规则 → 升级 ingestor

**3 个 API 实战踩坑**（2026-06-15 实测,1-2 个小时后会被遗忘的细节,写在这里）:

1. **Sina HK 必带 Referer header**,否则空响应。`User-Agent: Mozilla/5.0` 也必带。
2. **Sina HK 字段位置**: 索引 [0]=英文 [1]=中文名(转 float 报 ValueError) [2]=现价 [3]=昨收 [4]=今开 [5]=最高 [6]=最低 [7]=涨跌额 [8]=涨跌幅%。**A 股/美股格式是 [0]=名称 [1]=现价,港股反过来多一个英文代码 + 中文名**,LLM 解析时容易卡。
3. **CoinGecko `usd_24h_change` 已经是百分比数值**(如 -0.47),**不要再 ×100**。
4. **US Treasury URL 月份参数必须动态**:`$(date +%Y%m)`,不是写死 `202606`。下月 cron 跑就 404。
5. **Eastmoney 港股 `secid=124.HSIHSI` 实测 rc:100 无效**——SKILL.md v1.5.1 标了"用 Yahoo ^HSI",但 Yahoo 2026-06-15 实际不可直连(测试时 200 OK 但其他时候会卡)。**Sina HK 更稳**。
6. **CoinCap `api.coincap.io` 实测 SSL EOF 错误**,Yahoo `BTC-USD` 兜底。

**已写进 SKILL.md 章节 3a/3b + cron prompt v1.7**,下个 session agent 直接读就能用。

**为什么选 P0 cron-prompt 直拉 而不 P1 建 ingestor**:用户 "?" 反例触发条件 = "等太久没结果",他更忍不了"等 30 分钟"而非"数据不入库"。**先让他看到数据,有感,再问要不要升级**。这是 "持续执行原则" + "做不到就说做不到" 的合流应用。

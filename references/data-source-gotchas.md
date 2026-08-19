# 数据源故障排查与已验证坑（2026-06-06 实战汇总）

> 当某个数据源突然失灵，先查本表再换源。**已踩过坑的源 + 解决方案**（按源字母序）。

## API 编码 / 字符问题

### NBS 中国 PMI HTML — `<span>` 拆词 + UTF-8 编码

**症状**: regex `制造业.*?PMI.*?(\d+\.\d+)\s*%` 在 `r.text` 上不匹配，明明肉眼能看到数字。

**根因**（两个独立问题叠加）:
1. **NBS HTML 把 "制造业" 和 "PMI" 拆到不同 `<span>` 标签里**：
   ```html
   <p><span>制造业</span><span style="...">PMI</span><span>为 50.0%</span></p>
   ```
   regex `制造业.*?PMI` 在 raw HTML 上跨不过去（因为中间有 span 标签），需要先 strip 标签。
2. **`requests` 默认编码可能是 latin-1**，r.text 里的汉字变乱码（`æ°è¿°åµ` 这种），regex 也匹配不到。

**修复**:
```python
# 1. 强制 utf-8 + strip 标签
if isinstance(html, bytes):
    clean = re.sub(r'<[^>]+>', ' ', html.decode('utf-8', errors='ignore'))
else:
    clean = re.sub(r'<[^>]+>', ' ', html)
clean = re.sub(r'\s+', ' ', clean)
# 2. 再 regex
m = re.search(r'制造业.{0,30}PMI.{0,30}为\s*(\d+\.\d+)\s*%', clean)
```

**验证**: 5 月制造业 PMI = **50.0%**（之前静态用 50.5 是错的！真实 NBS 数据是 50.0）

详见 [nbs-pmi-source.md](nbs-pmi-source.md)。

---

### 数字合理性 sanity check

NBS PMI 多分类指数 regex 容易匹配到"百分点变化"等无关数字（例如非制造业 "下降 0.1 个百分点"）→ 解析出 `non_mfg_pmi=0.1` 错得离谱。

**修复**: 范围约束
```python
m = re.search(r'非制造业.*?(?:商务活动|PMI).*?(\d+\.\d+)\s*%', clean)
if m and 45 <= float(m.group(1)) <= 60:  # PMI 必须在 45-60 范围内
    pmi['non_mfg_pmi'] = float(m.group(1))
```

---

## Eastmoney 移动 API JSON 结构 — `Datas` 不是 `Data`

### 基金阶段涨幅 API（`FundMNPeriodIncrease`，日报核心数据源）

**症状**: 解析时返回空数组或 KeyError，但脚本没报错继续跑下游 → 日报阶段涨幅全为 0/None。

**根因**: SKILL.md §2 示例暗示 `d['Data']['periodIncrease']['list']`，但**真实结构完全不同**——是顶层 `Datas`（带 s 的复数）flat list。

**真实 JSON 结构**（2026-06-13 实测 012752/022653/025857/020274 四只基金）:
```json
{
  "Datas": [
    {"title":"Z","syl":"-3.08","avg":"-3.27","hs300":"-0.82","rank":"159","sc":"360","diff":"143"},
    {"title":"Y","syl":"-0.15","avg":"-4.66","hs300":"-3.45","rank":"111","sc":"360","diff":"44"},
    {"title":"3Y","syl":"15.16","avg":"0.34","hs300":"1.91","rank":"78","sc":"360","diff":"5"},
    {"title":"1N","syl":"24.29","avg":"6.54","hs300":"22.74","rank":"105","sc":"342","diff":"15"},
    {"title":"JN","syl":"11.02","avg":"-1.06","hs300":"3.18","rank":"115","sc":"356","diff":"4"}
  ],
  "ErrCode": 0, "Success": true,
  "Expansion": {"ESTABDATE":"2021-09-22","TIME":"2026-06-11"}
}
```

**正确解析代码**:
```python
import json
d = json.loads(raw)
items = d['Datas']                       # ⚠️ 不是 Data.periodIncrease.list
periods = {it['title']: it for it in items}
one_month = float(periods['Y']['syl'])   # 近 1 月 (用户 最关注)
one_year  = float(periods['1N']['syl'])  # 近 1 年
ytd       = float(periods['JN']['syl'])  # 今年来
```

**坑**:
- `syl/avg/hs300/rank/sc/diff` **全是字符串**，必须 `float()` 否则算术报 TypeError
- 长周期（`2N/3N/5N`）对新基金可能 `syl=""` → 加 `try/except` 或显式跳过
- 错误写法 `d['Data']['periodIncrease']['list']` 在 Python 里**返回空列表（不报错）**，Agent 会误以为"无数据"——必须显式 KeyError/IndexError 触发才能发现。建议首行加 `assert 'Datas' in d, f"unexpected shape: {list(d.keys())[:5]}"`
- `ErrCode`/`Success` 是字符串 `"0"` / 布尔 `true`，需要字符串比较 `'0'` 或 bool 比较 `is True`

---

## API 限速 / 反爬

### Reuters / AP News RSS — SSL EOF

**症状**: `https://feeds.reuters.com/reuters/businessNews` 返回 `SSLEOFError(8, 'EOF occurred in violation of protocol')`

**根因**: 用户 当前网络（HK 出口）的 TLS 握手跟 Reuters 服务器协商失败

**Workaround**:
- 改用等价 RSS 源（**FT/CNBC/BBC** 已验证可用）
- 或用 Reuters 镜像（`feeds.reuters.com/reuters/...` vs `www.reutersagency.com/...`）
- 短期不做修复（FT/CNBC/BBC 已覆盖相同内容）

---

### Yahoo Finance — 多数可达，少数受限

**可用**（2026-06-06 实测）:
- `^VIX`, `DX-Y.NYB`, `CL=F`, `GLD`, `^TNX/^FVX/^IRX/^TYX` (返回 ×10，需 /10)
- `QQQ/SPY/TLT/XLE` 5 年 + 10 年日线

**不可用 / 受限**:
- `^TNX` 偶尔 SSL EOF，重试通常成功
- Yahoo 中国指数 (`000300.SS`, `000905.SS` 等) **多数返回 1 天数据**（2026-06-06 实测）→ 用 Sina/指数代理替代

**User-Agent 必带**: `Mozilla/5.0`（否则被反爬）

---

### Sina K-line — 500 天范围但可能回旧数据

**症状**: `https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000959&datalen=500` 返回 `2016-12-09 → 2018-12-25` 而不是 `2024 → 2026`

**根因**: Sina API 用 `datalen` 倒推起始日期，但对部分冷门指数（军工/红利）历史数据不全，倒推 500 个交易日会跳到 2016-2018

**Workaround**:
- 热门指数（`sh000300`, `sz399006`, `sh000905`）正常返回 2024+
- 冷门指数改用 **Yahoo 中国指数代码**（`000300.SS` 等）但**只返回 1 天**——没救
- 终极方案：**用户 自行下载数据**（Wind/同花顺客户端导出 CSV，存到 `$MARKET_INTEL_ROOT/backtest/`）

---

### Eastmoney 指数 K-line — `push2his.eastmoney.com` 大面积无效

**症状**: NDX / AU9999 / 电力设备 / 沪深 300 等指数 30 天 K-line 全部返回 `{"rc":100,"data":null}`

**根因**: API 路径变了或要求登录

**Workaround**:
- 用 **fundgz.1234567.com.cn**（场外基金净值 API，公开免代理）替代单标的历史
- 用 **Sina / Yahoo** 替代指数历史
- 研报数据用 `fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease`（日级字段）

---

### FRED CSV — ISM PMI 等被反爬

**症状**: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=MANEMPICNSA` 返回 HTML 反爬页（含 `<script>` 标签）而不是 CSV

**根因**: FRED 关键词级别反爬

**Workaround**:
- **FEDFUNDS / DGS10 / DGS2 / CPI 仍可用**
- **ISM PMI / 部分 CPI 返回 HTML** — 跳过，用其他源替代
- 终极方案：**FRED API key**（免费申请，每天 1000 次），用 JSON API 替代 CSV

---

### Reuters / AP News / Treasury / BIS RSS — 404

| 路径 | 状态 |
|---|---|
| `feeds.reuters.com/...` | SSL 失败（HK 出口）|
| `feeds.apnews.com/apf-business` | SSL 失败 |
| `home.treasury.gov/news/press-releases/feed` | 404 |
| `www.bis.org/doclist/bis_fsi.rss` | 404 |
| `www.goldmansachs.com/insights/rss` | 404 |
| `www.jpmorgan.com/insights/rss` | 404 |
| `www.morganstanley.com/ideas/rss` | 404 |
| `home.treasury.gov/.../feed` | 404 |

**Workaround**:
- Treasury 真实数据 = `daily-treasury-rates.csv`（CSV 端点，不是 RSS），OK
- 投行 RSS 多数改路径了 → 改用 **Eastmoney 研报 API**（15 家中文研报）
- Reuters → 用 **FT/CNBC/BBC 替代**

---

### OpenSky Network — 匿名 10s/req 限速

**症状**: 多次连发请求返回 `429` 或超时

**Workaround**:
- 6 个区域用 `time.sleep(3)` 间隔（保守）
- 匿名模式每 10 秒才能发一次，生产环境应注册免费账号拿 token

---

### Polymarket — 153 个市场一次 OK，10 分钟后可能 429

**Workaround**:
- 单次拉 ≤ 200 个市场（已实测）
- 1 天内多次跑会 429 → 加 `time.sleep(60)` 间隔
- 关键词过滤要避免"Jesus"、"FIFA World Cup"等误判词（`"ai"` 跟 `"GTA VI"` 标题共存）

---

## 投送 / 通知层

### WeChat iLink SSL 故障（cron 投递）

**症状**: cron `last_delivery_error`: `Weixin send failed: Cannot connect to host ilinkai.weixin.qq.com:443 ssl:default [Connection reset by peer]`

**根因**: iLink gateway 在某些时段有 SSL 握手问题

**Workaround**:
- **`send_message` 直发（不走 cron）通常 OK** → `success: true, platform: weixin`
- 重要通知用 `send_message` 直发，cron 仅用作 schedule trigger
- 不要让 cron 失败的"错误报告"刷屏 用户

**实测**: 2026-06-06 多次失败后用 `send_message` 直发全部成功（绕过 iLink）

---

### WeChat 限流（`ret=-2 errcode=None errmsg=rate limited`）

**症状**: 连续 `send_message` 失败，错误是限流

**Workaround**:
- 等 30-60 秒重试
- **不要重试 3+ 次**（系统会提示 loop warning）
- 长任务里**只发 1-3 个关键消息**，避免短时间大量 send_message
- 用 `time.sleep(60)` 在两次 send_message 之间

---

## Backtest 常见 Bug

### 再平衡 bug：固定百分比而非"总-股票"

**症状**: 10 标的组合回测显示回撤 56%（明显异常）

**根因**:
```python
# 错的写法
cash = value * NEW_PORTFOLIO["现金/短债"]["weight"]  # 永远是 value*0.2
# 这导致：value=100万, cash=20万, 股票=80万
# 但实际应该是 cash = value - sum(股票 target values) = 100 - 80 = 20万
# 单标的场景下"巧合"对，但跨标的总和不等于 target
```

**修复**:
```python
stock_total = sum(value * w for sym, w in target_w.items())
cash = value - stock_total
# 或: 明确说现金 = value * 现金权重
cash = value * CASH_WEIGHT  # 显式，bug 风险低
```

### 调仓后只设 shares 不算 value 偏差

**症状**: 调仓后 next day 计算 value 仍用旧 shares

**修复**:
```python
# 调仓日: 先用旧 shares 算当日 value, 再调 shares
for date in common_dates:
    value = cash + sum(shares[k] * price[k][date] for k in shares)
    values.append(value)
    if date in rebal_dates and value > 0:
        # 调仓: 重新分配
        for k in target_w:
            shares[k] = (value * target_w[k]) / price[k][date]
        cash = value * CASH_WEIGHT  # 显式现金
```

### 跨标的日期交集错位

**症状**: Sina 500 天 + Yahoo 5 年 → 调 `set.intersection` 经常返回 0

**根因**: 数据源起始日期不一致

**修复**:
- 用**最新源**（Sina 500 天）的日期范围
- Yahoo 数据**截取**到 Sina 范围
- 不用交集（会丢很多 Yahoo 数据）

```python
sina_keys = ["sh000905", "sh000688", ...]
sina_dates = set()
for code in NEW_PORTFOLIO.items():
    if info["proxy"] in sina_keys:
        sina_dates.update(proxies[code].keys())
common_dates = sorted(sina_dates)  # 不取交集
```

### 回测结果"完美" = 几乎肯定是 bug

**症状**: 某条规则胜率 100% / 平均收益 +40% / 触发 1 次

**铁律**:
- **1 次触发的 100% 胜率不可信**（统计意义 = 0）
- **5%/60d/70%/10 次触发** = 真实可执行
- **12%/180d/100%/1 次触发** = 过拟合陷阱，禁用

---

## 速查表

| 想做 | 用什么 | 坑 |
|---|---|---|
| 拉 A 股 ETF 净值 | `fundgz.1234567.com.cn/js/{code}.js` | 只覆盖 LOF 基金，不覆盖 ETF |
| 拉 A 股 ETF K-line | ❌ 不可用，Yahoo 返 1 天，Sina 返旧数据 | 用户 自行下载 |
| 拉 NBS 月度数据 | `https://www.stats.gov.cn/sj/zxfb/2026xx/...` | HTML 用 `<span>` 拆词，r.text 编码错 |
| 拉美股日线 | `query1.finance.yahoo.com/v8/finance/chart/{sym}` | UA 必带，SSL EOF 重试 |
| 拉基金阶段涨幅（日/周/月/年） | `fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease` | 顶层 `Datas`（不是 `Data.periodIncrease.list`），所有字段是字符串 |
| 拉 Treasury 利率 | `home.treasury.gov/.../daily-treasury-rates.csv` | 月度 CSV，列名 `10 Yr`（名义）或 `10 YR`（TIPS 大写）|
| 拉 IMF/WorldBank 博客 | RSS 多半改路径 | 跳过 |
| 拉 Polymarket 押注赔率 | `gamma-api.polymarket.com/markets?active=true&closed=false` | 关键词过滤要避开 "ai"/"eth" 误判 |
| 拉 OpenSky 航班 | `opensky-network.org/api/states/all` | 匿名 10s/req 限速 |
| 投递到微信 | `send_message` 直发（不走 cron）| iLink SSL 故障时绕行 |
| 跑回测 | 见 [multi-asset-backtest-template.py](../../templates/multi-asset-backtest-template.py) | 修 rebalance bug + 验证日期交集 |

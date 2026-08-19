# Fund Data Eastmoney API 速查 (2026-07-16 实测 + 2026-07-19 + 2026-07-20 + 2026-07-21 更新)

## 0. v1.7.20+ 决策树 — D11 后到底走哪条

| 需求 | 首选 endpoint | 兜底 | 备注 |
|---|---|---|---|
| 持仓**今日已确认单日**涨跌 (A 股 8:00-15:00 后) | `FundMNHisNetList` JZZZL | `pingzhongdata` equityReturn | QDII 美股 T+0 净值 T+1 才入库,等不了 |
| 持仓**阶段**涨幅 (1w/1m/3m/6m/ytd/1y) | `FundMNPeriodIncrease` | `pingzhongdata` syl_1y/syl_3y | D8 LIST 结构修复必须; D17 没有"今日"字段 |
| 实时盘中估值 gszzl | ⚠️ 无 HTTPS 替代,降级"今日不可用" | — | D11 fundgz HTTP 被拦,实测 Eastmoney Estimate 也 404 |
| 持仓历史净值 + 排名 + 机构占比 | `pingzhongdata/{code}.js` | — | 字段最全,但 JS 格式需 regex |
| 同源互验 | `fundmobapi period` + `pingzhongdata` 同时拉 | 差异 > 0.5% 报警 | 防单源异常 |

## 1. 实时净值估值 (`fundgz.1234567.com.cn`)
URL: http://fundgz.1234567.com.cn/js/{code}.js
Headers: User-Agent: Mozilla/5.0 (无需 Referer)
返回: jsonpgz({"fundcode":"...","name":"...","jzrq":"...","dwjz":"...","gsz":"...","gszzl":"...","gztime":"..."});
```

| 字段 | 含义 |
|---|---|
| `dwjz` | 单位净值 (昨日确认) |
| `gsz` | 估算净值 (今日盘中) |
| `gszzl` | 估算涨跌幅 % |
| `gztime` | 估算时间 (BJT) |

**示例 (4 只持仓 2026-07-16)**:
- 012752 纳指QDII: dwjz=3.3574 gsz=3.3484 gszzl=-0.27%
- 022653 黄金ETF: dwjz=3.0417 gsz=3.0394 gszzl=-0.08%
- 025857 电网设备ETF: dwjz=1.1750 gsz=1.1328 gszzl=-3.59%
- 020274 化工ETF: dwjz=1.3267 gsz=1.2897 gszzl=-2.79%

> ⚠️ **v1.7.20 起禁用**: `fundgz.1234567.com.cn` 是明文 HTTP,被 Tirith [HIGH] 拦,无人 cron session 永久卡住 (Pitfall D11)。日报"持仓动态"段**只展示阶段涨幅 + 已确认净值**即可,不要这字段。下面 §1.5 / §1.6 给出 D11 后的官方 HTTPS 替代。

## 1.5 今日已确认净值 — `FundMNHisNetList` (HTTPS, D11 后首选, 2026-07-20 实测)

```
URL: https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList
     ?FCODE={code}
     &pageIndex=1
     &pageSize=5
     &deviceid=1
     &plat=Android
     &version=1.0.0
     &product=EFund
     &appType=ttjj
Headers:
  User-Agent: Mozilla/5.0
  Referer: https://fund.eastmoney.com/   ← 必须, 不带返回 61136 限流
返回: {"Datas":[{"FSRQ":"2026-07-17","DWJZ":"1.0852","JZZZL":"-4.21","LJJZ":"1.0852",...}], "ErrCode":0}
```

**关键字段**: FSRQ 净值日期 / DWJZ 单位净值 / JZZZL 单日涨跌 % (字符串) / LJJZ 累计净值

**4 只持仓实测 (2026-07-20 19:00)**:
- 012752: 最新 2026-07-16 DWJZ 3.2955 JZZZL -1.45 (← T+1, 美股 07-17 数据 07-18 才入库)
- 022653: 最新 2026-07-20 DWJZ 3.0224 JZZZL +0.06 (← 唯一当日, A 股刚收盘)
- 025857: 最新 2026-07-17 DWJZ 1.0852 JZZZL -4.21
- 020274: 最新 2026-07-17 DWJZ 1.2761 JZZZL -1.17

**QDII 时差陷阱**: 012752 纳指QDII 美股 T+0 收盘 → 第二天 BJT 入库。报告"今日"需要 012752 真实"今日"表现,得**拿美股指数本身 (yfinance ^NDX / QQQ) 估算**,不要等基金净值。

**61136 限流兜底**: `ErrCode: 61136, ErrMsg: 网络繁忙` → 等 30s 重试;仍失败 → 走 §1.6 `pingzhongdata` 兜底。

## 1.6 净值历史 + 阶段涨幅 + 排名 + 机构占比 — `pingzhongdata/{code}.js` (HTTPS, D11 后字段最全, 2026-07-20 实测)

```
URL: https://fund.eastmoney.com/pingzhongdata/{code}.js
Headers:
  User-Agent: Mozilla/5.0
  Referer: https://fund.eastmoney.com/   ← 必须
返回: JS 变量包 (无 JSON wrapper, 需 regex 提取)
```

**关键变量 (实测 2026-07-20 全部 4 只持仓)**:
- `fS_name` / `fS_code`: 基金名/代码
- `Data_netWorthTrend`: 完整历史 `[{x: ts_ms, y: 净值, equityReturn: 当日%}, ...]`,末项 = 最新净值 + 涨跌幅 ← **D17 后做"今日单日估"首选**
- `syl_1y` / `syl_3y` / `syl_6y` / `syl_1n`: 近 1/3/6 月 / 1 年阶段涨幅 (字符串 %)
- `Data_rateInSimilarType`: `{x, y: rank, sc: 同类总数}`
- `Data_rateInSimilarPersent`: 同类分位百分数
- `Data_fluctuationScale`: 季度规模 + 变动 mom%
- `Data_holderStructure`: 机构/个人/内部持有比例 + 季度时点
- `stockCodesNew`: 持仓股票代码 (新市场号, 如 `105.NVDA`)
- `Data_currentFundManager`: 基金经理详情 (name, workTime, fundSize, power.avr)

**Python 解析模板**:
```python
import urllib.request, re, json
raw = urllib.request.urlopen(urllib.request.Request(
    f'https://fund.eastmoney.com/pingzhongdata/{code}.js',
    headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://fund.eastmoney.com/'}
), timeout=15).read().decode('utf8', 'ignore')

# 简单 var
syl_1n = re.search(r'var syl_1n\s*=\s*"([^"]*)"', raw).group(1) if re.search(r'var syl_1n', raw) else ''

# JSON-like var (Data_netWorthTrend)
m = re.search(r'var Data_netWorthTrend\s*=\s*(\[.+?\]);', raw, re.S)
trend = json.loads(m.group(1)) if m else []
last = trend[-1] if trend else {}  # {x: ts_ms, y: NAV, equityReturn: 当日%}
nav = last.get('y'); today_pct = last.get('equityReturn')
```

**`pingzhongdata` vs `fundmobapi period` 互验**:
- `syl_1n` 跟 `1N` 应该数值一致 (2026-07-20 022653 两者都 = 12.10%)
- 短期 (1w/1m) 走 `fundmobapi period` (字段更明确, Z/Y/3Y)
- 长期 (1y+) + 排名/分位/机构占比 走 `pingzhongdata`
- **双源差异 > 0.5%** → 报告标注"数据双源不一致, 谨慎"

**决策矩阵 (D11 + D17 后到底走哪条)**:
| 需求 | 首选 | 兜底 |
|---|---|---|
| **单日 (今日)** 涨跌 | `pingzhongdata` `Data_netWorthTrend[-1].equityReturn` | `FundMNHisNetList` JZZZL |
| 持仓阶段涨幅 (1w/1m/3m/6m/ytd/1y) | `FundMNPeriodIncrease` (注意: `Z`=周 NOT 今日) | `pingzhongdata` syl_1y/syl_3y |
| 实时盘中估值 gszzl | ⚠️ 无 HTTPS 替代, 降级"今日不可用" | — |
| 持仓历史净值 + 排名 + 机构占比 | `pingzhongdata/{code}.js` | — |
| QDII 美股敞口的"今日"美股表现 | yfinance ^NDX / QQQ (不是基金) | — |

## 2. 阶段涨幅 (`fundmobapi.eastmoney.com`)

```
URL: https://fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease?FCODE={code}&deviceid=ABC&plat=Wap&product=EFund&version=2.0.0
Headers:
  User-Agent: Mozilla/5.0
  Referer: https://m.eastmoney.com/   ← 必须, 不带返回空
返回: {"Datas":[{"title":"Z","syl":"1.35","avg":"1.49","hs300":"-3.65",...}, ...]}
```

> ⚠️ **🚨 D17 反直觉警告 (2026-07-21 19:00 实测)**: `fundmobapi Datas` **没有任何字段是"今日单日"**, 最细粒度是 `Z` = 近 1 周. 真"今日单日估"必须走 §1.5 `FundMNHisNetList` JZZZL 或 §1.6 `pingzhongdata` `Data_netWorthTrend[-1].equityReturn`. 不要写 `1d=periods.get('Z')` (这是历史踩坑), 单日估和阶段必须分两栏展示. `Z` 是中文"周"拼音首字母, 字母表排序首位, 但**不是 "Today" / "Zero day"**.

### ⚠️ 重要结构：`Datas` 是 LIST 不是 DICT（2026-07-19 实测坑）

```python
# ❌ 错 — 'list' object has no attribute 'get'
periods = data.get('Datas', {}).get('Z')

# ✅ 对 — list comprehension 转 dict
periods = {p['title']: p['syl'] for p in data['Datas']}
one_w = periods.get('Z', '?')      # 近 1 周  ← 不是单日!
one_m = periods.get('Y', '?')      # 近 1 月
one_y = periods.get('1N', '?')     # 近 1 年
```

每项元素是 dict，含 `title` / `syl` / `avg` / `hs300` / `rank` / `sc` / `diff`。

### title → 含义速查表

| title | 含义 | 同类均值字段 | D17 单日误用警示 |
|---|---|---|---|
| `Z` | **近 1 周** | `avg` | ⚠️ 不是"今日"/"1d" |
| `Y` | 近 1 月 | `avg` | — |
| `3Y` | 近 3 月 | `avg` | — |
| `6Y` | 近 6 月 | `avg` | — |
| `1N` | 近 1 年 | `avg` | — |
| `2N` | 近 2 年 | `avg` | — |
| `3N` | 近 3 年 | `avg` | — |
| `5N` | 近 5 年 | `avg` | — |
| `JN` | 今年来 | `avg` | — |
| `LN` | 去年全年 | `avg` | — |

**单字母来源猜测 (D17 教训)**: `Z`(周/拼音首字母) / `Y`(月/拼音首字母) / `N`(年/拼音首字母) + 数字 = 周期长度. 字母表排序让 `Z` 排首位, 中文/英文直觉容易误以为是 "Today" / "Zero day".

### 额外字段

- `rank`: 同类排名 (数字越小越好)
- `sc`: 同类总数
- `diff`: 与同类均值差 (pp)
- `hs300`: 同期沪深300 涨跌幅 %

### ⚠️ 空字符串陷阱（2026-07-19 实测）

基金成立不满该周期时长时，`syl` 返回 `""`（不是 `"0.00"` 也不是 None）。

**实测案例**：
- 025857 电网设备ETF：成立 ~2024-06，2026-07 跑 `1N`/`2N`/`3N` 返回 `""`（成立 < 周期长度）
- 022653 黄金ETF：`3N` (近 3 年) 返回 `""`（成立 < 3 年）
- 020274 化工ETF：`3N` (近 3 年) 返回 `""`

**正确渲染**：
```python
def fmt_pct(v):
    v = (v or '').strip()
    if not v:
        return '数据缺失'  # 成立不满周期 — 不要写 0.00% 误导
    return f'{float(v):+.2f}%'
```

**报告示例**（025857 1y 显示）：
```
1y 数据缺失    ← 真实
1y +0.00%     ← 错！基金没满 1 年不能说 0% 涨幅
```

### 报告"持仓动态"段必须双源组合 (D17 必读)

```python
# ✅ 组合模板: 单日估 (pingzhongdata) + 阶段 (fundmobapi)
single_day_pct = last.get('equityReturn')  # pingzhongdata
one_w = periods.get('Z')    # fundmobapi 周累计
one_m = periods.get('Y')    # fundmobapi 月累计
one_y = periods.get('1N')   # fundmobapi 年累计

# 报告模板 (两栏分离)
# 012752 纳指QDII 净值 3.2550 (7/17) | 1日估 -1.23% | 近1周 -3.70% | 近1月 -3.31% | 近1年 +15.72%
#                          ↑ pingzhongdata   ↑ fundmobapi Z   ↑ fundmobapi Y  ↑ fundmobapi 1N
```

## 3. A 股指数 (`hq.sinajs.cn`)

```
URL: https://hq.sinajs.cn/list=sh000300
Headers:
  User-Agent: Mozilla/5.0
  Referer: https://finance.sina.com.cn/   ← 必须
返回: var hq_str_sh000300="沪深300,4080.2344,4064.3223,4073.5540,4083.5679,4058.2342,...";
```

**字段位置** (逗号分隔):
- [0] 名称
- [1] 当前价
- [2] 昨收
- [3] 今开
- [4] 最高
- [5] 最低

**常用代码**: sh000300 (沪深300) / sh000016 (上证50) / sh000905 (中证500) / sz399006 (创业板指)

## 4. 失败兜底

- 任一 API 返回空 → 报告写"今日不可用", 不要凭印象编造
- Eastmoney 限流 (429) → 等 5s 重试, 或 fallback Sina
- Sina HQ 返回乱码 → 用 `raw.decode('gbk', errors='ignore')` (默认 UTF-8 错)
- D17 单日估: `pingzhongdata` 失败 → `FundMNHisNetList` JZZZL → 仍失败写"今日单日估不可用"

## 5. cron Python 环境注意（2026-07-19 实测）

macOS cron 默认 Python (`/Library/Developer/CommandLineTools/usr/bin/python3`) 是 3.9，系统 site-packages 不含第三方库。

```bash
# ✅ 用 cron Python 自带 pip 装到 user-site
python3 -m pip install yfinance
# 不需要 sudo, 默认 --user 模式

# ❌ 不要用 uv pip install --system (装到别处)
# ❌ 不要 sudo pip install (污染系统 Python)
```

涉及第三方库的任何 cron 脚本都要先验证 `python3 -c "import xxx"` 通过。

## 6. D17 实战教训 (2026-07-21 19:00 周二晚报 cron 实测)

**踩坑路径**:
1. cron prompt 模板 v1.7.21 误写 `1d=periods.get('Z')` 假设 Z=单日
2. 实际跑出 4 只基金 -3.70%~-7.89% 全是周累计, 用户 会以为"今日亏惨"
3. 实际单日 (pingzhongdata equityReturn): -1.23%/+0.06%/-0.06%/+0.02% — 几乎平盘
4. 报告已经靠手动分两栏 (`1日估 -1.23% | 近1周 -3.70%`) 抢救, 但 cron prompt 模板未改 → 下次还会踩

**修复 (写入 cron prompt 永久铁律)**:
- ❌ 不要再写 `1d=periods.get('Z')` 这种"字母猜语义"代码
- ✅ 报告"持仓动态"段模板固定: `净值 (日期) | 1日估 {pingzhongdata.equityReturn} | 近1周 {fundmobapi.Z} | 近1月 {fundmobapi.Y} | 近1年 {fundmobapi.1N}`
- ✅ 双源缺失时各自标"今日单日估不可用" / "周累计不可用", 不要混用
- ✅ QDII (012752) 加注 "T+1 时差, 实际今日表现参考 yfinance QQQ 现价"

**反思**: v1.7.20 修复 D11 (fundgz HTTP) 时只说"fundmobapi period 拿 1w/1m/3m/6y 已够用", 但**没说清楚 fundmobapi 没有"今日单日"字段**. API 替代不能只跑通, 必须确认字段语义 1:1 对应.

**Related**: Pitfall D8 (Datas LIST) + D9 (空字符串) + D11 (fundgz HTTP) + D14 (auto_adjust) + D17 (Z=周非今日), 全部沉淀在本文件 + SKILL.md 同名 Pitfall.
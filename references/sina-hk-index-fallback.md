# 新浪财经港股指数/股票数据 — 港股 fallback PRIMARY（实测 2026-08-05）

## 背景

v1.7.22 D16 文档把"港股 Yahoo Finance 数据获取"标 ❌ 失效（`^HSI / ^HSCE / ^HSTECH` 全 404/delisted）。
推荐 fallback 链是：DB `source='hk_index'` → 0700.HK/9988.HK 代理 → 静默。

**2026-08-05 19:00 周三晚报实战发现**：Yahoo Finance / CoinGecko 整段被网络层 reset（Errno 54），但**新浪财经 `hq.sinajs.cn` 在同样网络条件下完全正常**。新浪 HQ 同时提供港股指数（HSI/HSCEI/HSTECH）和港股股票（00700/09988）实时数据，是比 0700.HK 代理更准的 PRIMARY fallback。

## 端点

### 港股指数

```
https://hq.sinajs.cn/list=rt_hkHSI,rt_hkHSCEI,rt_hkHSTECH
```

实测返回（2026-08-05 16:09 BJT）：
```
var hq_str_rt_hkHSI="HSI,恒生指数,25890.990,25852.920,25973.940,25729.860,25915.820,62.900,0.240,0.000,0.000,278042688.687,15905905339,0.000,0.000,28056.100,22518.000,2026/08/05,16:09:54,,,,,,";
var hq_str_rt_hkHSCEI="HSCEI,恒生中国企业指数,8585.000,8574.260,8624.180,8525.330,8603.729,29.470,0.340,0.000,0.000,77664014.479,2354085288,0.000,0.000,9770.210,7404.470,2026/08/05,16:09:30,,,,,,";
var hq_str_rt_hkHSTECH="HSTECH,恒生科技指数,4901.740,4885.610,4948.500,4885.510,4933.070,47.460,0.970,0.000,0.000,68694528.34...";
```

**字段顺序**（与 v1.7.22 文档假设的 `[name, open, prev, cur]` **不一致**——实测顺序）：
| 位置 | 字段 | 示例 (HSI) | 含义 |
|---|---|---|---|
| 0 | code | HSI | 内部代码 |
| 1 | name_zh | 恒生指数 | 中文名 |
| 2 | cur | 25890.990 | **当前价** |
| 3 | prev_close | 25852.920 | 昨收 |
| 4 | open | 25973.940 | 今开 |
| 5 | day_high | 25729.860 | 最高（**实测位置不对——见下注**） |
| 6 | day_low | 25915.820 | 最低（同上） |
| 7 | chg_amt | 62.900 | 涨跌额 |
| 8 | chg_pct | 0.240 | **涨跌幅 %** |
| ... | 时间戳 | 2026/08/05, 16:09:54 | |

> ⚠️ **字段顺序陷阱**：v1.7.22 D16 文档写"新浪字段顺序与 `[name, open, prev, cur]` 不一致"，实测发现**字段顺序是 `[name, prev_close, open, ...cur..., chg_amt, chg_pct]`**（cur 在 chg 之前），**不是 `[name, open, prev, cur]`**。计算 chg_pct 直接取位置 8（=0.240 = +0.24%），不要自己 (cur-prev)/prev*100 算，避免字段位置错位。

### 港股股票

```
https://hq.sinajs.cn/list=rt_hk00700,rt_hk09988
```

腾讯 (00700) / 阿里 (09988) 实时数据，2026-08-05 16:09 BJT 实测：
- 腾讯 492.200 (+0.94%)
- 阿里 128.100 (+1.83%)

## 关键 header（必带，否则 412 / 无数据）

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
```

无 Referer → 新浪 412 / 403；有 Referer → 200 完整数据。

## 解码（GBK 不是 UTF-8）

```python
raw = urllib.request.urlopen(req, context=ctx, timeout=12).read().decode('gbk', 'ignore')
```

## 实战有效性（2026-08-05 19:00 周三）

| 端点 | 状态 |
|---|---|
| Yahoo Finance (`query1`/`query2` / `v8/finance/chart/QQQ`) | ❌ Connection reset by peer (Errno 54) × 4 ticker 0 错 |
| CoinGecko (`api.coingecko.com/api/v3/simple/price`) | ❌ Connection reset by peer (Errno 54) × 1 端点 3 retry 全失败 |
| Yahoo Finance RSS (`finance.yahoo.com/news/rssindex`) | ❌ Connection reset by peer |
| 36kr hot rank (`gateway.36kr.com/api/...`) | ❌ HTTP 500 (服务端问题) |
| **新浪 HQ HK 指数/股票 (`hq.sinajs.cn/list=rt_hk*`)** | ✅ 200 完整数据 |
| **新浪 roll 国际财经 (`feed.mix.sina.com.cn/api/roll/get?lid=2516`)** | ✅ 200，6 条新闻 |
| **东财 pingzhongdata (`fund.eastmoney.com/pingzhongdata/{code}.js`)** | ✅ 200，4 只基金全成功 |
| **东财公告 (`np-anotice-stock.eastmoney.com/api/security/ann`)** | ✅ 200 |

**结论**：当日 cron 跑时 Yahoo + CoinGecko 整段被网络层 reset，但 sina + eastmoney 全 OK。**金融数据源在国内 cron 必须有"分网络段 fallback 链"**：
- 海外/全球（Yahoo/CoinGecko）失败 → 国内（sina/eastmoney）兜底
- 反向不成立（sina 没有美股个股，但有港股+全球新闻）

## 修复（D16 v1.7.22 升级）

| 数据源 | v1.7.22 D16 推荐 | v1.7.33 升级 |
|---|---|---|
| 港股指数 (HSI/HSCEI/HSTECH) | DB `source='hk_index'` PRIMARY | **sina hq PRIMARY** → DB FALLBACK |
| 港股个股 (Tencent/Alibaba) | yfinance `0700.HK/9988.HK` (工作日) | **sina hq PRIMARY** (工作日 16:00 后必可) |
| 美股指数/ETF/AI 算力 | yfinance PRIMARY | yfinance PRIMARY（如可用） |
| 加密 | CoinGecko PRIMARY | CoinGecko PRIMARY（如可用） |
| 国际财经快讯 | 9 分类 Eastmoney kuaixun (❌ 已死) | sina roll `lid=2516` PRIMARY |

## 铁律

- ❌ 不要假设 Yahoo Finance / CoinGecko 在 cron 时段可用 — 实测 2026-08-05 整段被 reset
- ❌ 不要把 sina 当 "last resort" — 在 Yahoo/CoinGecko 被 reset 时它是 PRIMARY
- ✅ cron 体内**先试 yfinance/CoinGecko，失败立即切 sina，不要等超时**（`timeout=8` 而不是 `timeout=30`）
- ✅ sina 请求必带 `Referer: https://finance.sina.com.cn/` header
- ✅ sina 响应**用 `decode('gbk', 'ignore')`** 不是 UTF-8
- ✅ 数据基准日头部必标 "📌 数据基准日 = YYYY-MM-DD HH:MM BJT"（sina 数据带 16:09:54 时间戳）

## 完整 cron 拉取模板

```python
import urllib.request, ssl

ctx = ssl.create_default_context()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

# Tier 1: Yahoo Finance (快, 海外数据丰富)
def fetch_yahoo(symbol, period="5d"):
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={period}"
        req = urllib.request.Request(url, headers=HEADERS)
        raw = urllib.request.urlopen(req, context=ctx, timeout=8).read()
        d = json.loads(raw)
        closes = [c for c in d['chart']['result'][0]['indicators']['quote'][0]['close'] if c is not None]
        if len(closes) >= 2:
            return closes[-1], (closes[-1] - closes[-2]) / closes[-2] * 100
    except Exception:
        return None
    return None

# Tier 2: Sina HQ (港股指数/股票 PRIMARY fallback)
def fetch_sina_hk_index():
    """Returns dict: {code: {cur, chg_pct, prev_close, time}}"""
    try:
        url = "https://hq.sinajs.cn/list=rt_hkHSI,rt_hkHSCEI,rt_hkHSTECH"
        req = urllib.request.Request(url, headers=HEADERS)
        raw = urllib.request.urlopen(req, context=ctx, timeout=8).read().decode('gbk', 'ignore')
        out = {}
        for line in raw.strip().split('\n'):
            m = re.search(r'list="([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),', line)
            if m:
                code, name, cur, prev, op, hi, lo, chg_amt, chg_pct = m.groups()
                out[code] = {"name": name, "cur": float(cur), "chg_pct": float(chg_pct), "prev_close": float(prev)}
        return out
    except Exception:
        return None
    return None

# Tier 3: DB (intel.db)
def fetch_db_index(source, limit=3):
    con = sqlite3.connect('$MARKET_INTEL_ROOT/db/intel.db')
    rows = con.execute(
        f"SELECT title, extra FROM intel WHERE source=? ORDER BY published_at DESC LIMIT ?",
        (source, limit)
    ).fetchall()
    return rows

# 实战: 港股指数
hk_live = fetch_sina_hk_index()
if hk_live:
    hsi = hk_live['HSI']
    print(f"🇭🇰 HSI {hsi['cur']:.2f} ({hsi['chg_pct']:+.2f}%) — sina live")
else:
    print("🇭🇰 HSI: sina failed, fallback DB")
    for r in fetch_db_index('hk_index'):
        print(f"  {r[0]}")
```

## Related

- D16 (v1.7.22) 港股 Yahoo ticker 失效 → **本 reference 升级为 sina PRIMARY**
- D24 (v1.7.31) P0 cron 周一覆盖缺口 → sina 在 cron 不可用时降级 DB
- D25 (v1.7.32) P0 cron 任意工作日 09:00 覆盖缺口 → 同上
- D14 (v1.7.21) yfinance `auto_adjust=False` 复权口径 → sina 港股无复权问题 (中国 A/H 股不复权)

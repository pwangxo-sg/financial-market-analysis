# Market Data Ingestion Flow — 新数据源从 0 到日报

> 来源：2026-06-15 接入港股 3 指数 (hk_index.py) + 加密 5 币 (crypto.py) 全过程。
> 当 用户 提出"日报缺 X 数据"时,按本流程 5 步走完,**总工时 30-60 分钟**。

---

## 5 步流程

### Step 1: 实测数据源（5 分钟）

**不要凭印象写 API**。先 curl/requests 实测 ≥ 2 次,确认：
- HTTP 200（不是 403/SSL EOF）
- 数据结构稳定（JSON schema 不变）
- 字段足够（涨跌/价格/时间至少 3 个）
- 频率合理（5 min 一次 = 缓存友好；1 min 一次 = 浪费）

**踩坑速查**（2026-06-15 实测）：
| 数据源 | 现象 | 替代 |
|---|---|---|
| Sina HK `hq.sinajs.cn/list=hkHSI` 第 2 次连续 | HTTP 403 Forbidden | 用 Yahoo Finance `^HSI` / `^HSCE` / `HSTECH.HK` |
| Yahoo `^HSTECH` | "No data found, symbol may be delisted" | 改 ticker `HSTECH.HK` |
| Eastmoney `push2.eastmoney.com/api/qt/stock/get?secid=124.HSIHSI` | `rc:100` 数据空 | 用 Yahoo 或 Sina |
| CoinCap `api.coincap.io/v2/assets` | `SSLEOFError` SSL EOF | 用 CoinGecko |

**实测脚本模板**（直接 copy 改）:
```python
import requests, time
url = "https://api.example.com/v1/data"
for i in range(3):  # 测 3 次
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    print(f"  try {i+1}: HTTP {r.status_code}, len={len(r.text)}")
    print(f"  sample: {r.text[:200]}")
    time.sleep(2)
```

### Step 2: 写 ingestor 脚本（10-15 分钟）

**完全照 `treasury_ingestor.py` 的模板**（已在 `$MARKET_INTEL_ROOT/scripts/`）：

```python
"""
P1 #N: [数据源中文名] (补全日报"市场全貌"板块)
- [数据 1] / [数据 2] / [数据 3]
- 数据源: [API 域名] (实测 [环境] [是否]直连可用, [是否]需 Lantern)
- 拉每日最新, 入 intel.db
"""
import sys
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime

log = get_logger("[ingestor_name]")  # 日志文件名 = ingestor_name.log

# 配置
INDICES_OR_COINS = [
    {"key1": "val1", "key2": "val2"},  # 每条对应一个标的
]

def fetch_one(item):
    """拉一条数据;返回 dict 或 None"""
    url = f"https://api.example.com/v1/{item['key1']}"
    r = safe_get(url, timeout=15)
    if not r:
        return None
    try:
        d = r.json()
    except Exception as e:
        log.warning(f"  ❌ {item['key1']} JSON 解析失败: {e}")
        return None
    # 解析 + 提取字段
    return {
        "key1": item["key1"],
        "name": item.get("name_zh", ""),
        "price": d.get("price", 0),
        "chg_pct": d.get("chg_pct", 0),
        # ...
    }

def make_intel_items(quotes):
    """转 save_intel 格式"""
    items = []
    now = datetime.now(BJT).isoformat(timespec="seconds")
    for q in quotes:
        title = f"[emoji] {q['name']} ({q['key1']}) {q['price']} ({q['chg_pct']:+.2f}%)"
        items.append({
            "title": title,
            "content": json.dumps(q, ensure_ascii=False)[:2000],
            "url": "https://...",
            "author": "[数据源名]",
            "published_at": now,
            "tags": ["[tag1]", "[tag2]", "daily"],
            "severity": 3,
            "extra": q,  # ⭐ 关键:把 dict 放 extra,LLM 读 DB 时能拿结构化数据
        })
    return items

def run():
    log.info("=== [ingestor name] ===")
    quotes = [fetch_one(item) for item in INDICES_OR_COINS]
    quotes = [q for q in quotes if q]  # 过滤 None
    if not quotes:
        log.warning("  ❌ 全部失败, 无数据")
        return 0, 0
    items = make_intel_items(quotes)
    saved, dups = save_intel(items, "[ingestor_source_name]", "commodity")  # 或 regulator/news
    for q in quotes:
        log.info(f"  ✅ {q['key1']:8s} {q['price']:>10} {q['chg_pct']:+.2f}%")
    log.info(f"=== 完成: {saved} new, {dups} dup ===")
    return saved, dups


if __name__ == "__main__":
    run()
```

**关键约定**:
- `source` 字段:用 ingestor 名（如 `hk_index`, `crypto`, `treasury_nominal`）,**和文件名一致**
- `source_type`: `commodity` (价格类) / `regulator` (官方) / `news` (媒体) / `sentiment` (情绪)
- `extra` 字段:**把原始 dict 放进去**,LLM 读 DB 时能直接 JSON parse 拿结构化数据（不要只放字符串）
- `severity`: 1 (无关) / 2 (低) / 3 (中,默认) / 4 (高) / 5 (紧急)

### Step 3: 注册到 run_all_p0.py（30 秒）

```python
SCRIPTS = [
    # ... 已有 ...
    "treasury_ingestor",
    # P1 新增
    "polymarket_ingestor",
    "opensky_ingestor",
    "analyst_rss_v2",
    "nbs_pmi_ingestor_v2",
    # P1 #5/#6 (2026-06-15): 港股 3 指数 + 加密 5 币
    "hk_index",
    "crypto",
    # P1 #N (2026-MM-DD): [新数据源]
    "[new_ingestor_name]",
]
```

### Step 4: 改 cron prompt 3.0（3 分钟）

如果新数据源是给"市场全貌"用的,加 1 段到 `26322edf978c` prompt 的 3.0 步：

```text
3.0 读 intel.db 拿最新硬数据 (P0 抓取由独立 cron 2067be2f2ab7 跑,本 cron 触发时数据已入库):
   ① 港股: ...
   ② 加密: ...
   ③ 美债: ...
   ④ [新数据源] (source='[new_source_name]', source_type='[type]'):
     sqlite3 $MARKET_INTEL_ROOT/db/intel.db "SELECT title, extra FROM intel WHERE source='[new_source_name]' AND published_at >= datetime('now', '-1 day') ORDER BY published_at DESC LIMIT [N]"
     期望 [N] 行: [列每行代表什么]
```

**失败兜底**（必须写）：
```text
   失败兜底: 任一查询空 → 写"今日不可用", 不要凭印象编造
```

### Step 5: 实跑 + 验证（2 分钟）

```bash
# 1) 跑一次 ingestor
python3 $MARKET_INTEL_ROOT/scripts/[new_ingestor_name].py

# 2) 验证 DB
sqlite3 $MARKET_INTEL_ROOT/db/intel.db \
  "SELECT source, COUNT(*) n, MAX(published_at) latest FROM intel WHERE published_at >= datetime('now', '-1 day') GROUP BY source ORDER BY latest DESC"

# 3) 验证 7:50 P0 抓取 cron 能拉到
# (不用主动跑,等 cron 自己触发,然后看飞书 oc_bfc1ed699... 投递)
```

**期望看到**:新 source 在 24h 内有 N 条数据（hk_index=3 / crypto=5 / treasury_nominal=1）。

---

## 速查表:已有 P0/P1 ingestor

| Source 名 | 文件 | 类型 | 数据数/日 | API 域名 |
|---|---|---|---|---|
| `hk_index` | `hk_index.py` | commodity | 3 | query1.finance.yahoo.com |
| `crypto` | `crypto.py` | commodity | 5 | api.coingecko.com |
| `treasury_nominal` | `treasury_ingestor.py` | regulator | 1 | home.treasury.gov |
| `treasury_real` | `treasury_ingestor.py` | regulator | 1 | home.treasury.gov |
| `polymarket` | `polymarket_ingestor.py` | sentiment | 30-100 | gamma-api.polymarket.com |
| `opensky_*` | `opensky_ingestor.py` | event | 2×6 区域 | opensky-network.org |
| `nbs_pmi` | `nbs_pmi_ingestor_v2.py` | regulator | 1-2 | stats.gov.cn |
| `eia_oil_proxy` | `eia_commodity.py` | commodity | 2 | api.eia.gov (待开) |
| `gld_holdings` | `eia_commodity.py` | commodity | 1-2 | 暂未对接 ETF 持仓 API |
| `moltbook_status` | `moltbook_ingestor.py` | system | 1 | www.moltbook.com |
| 9 个 RSS/新闻 | `rss_ingestor.py` | news | 50-200 | bloomberg/cnbc/ft/bbc/... |

完整 13+ 源架构见 [multi-source-pipeline.md](multi-source-pipeline.md)。

---

## 故障排查（按出现频率排）

1. **"市场全貌"段还是写"X 数据缺失"**
   - 检查 cron prompt 3.0 段是否已加新 source 的 query 例子（最常见遗漏）
   - 跑一次新 ingestor 验证能不能写 DB
   - 检查 `intel.db` 用 sqlite3 查新 source 的最新一条 `published_at`

2. **ingestor 跑失败 `JSON 解析失败`**
   - 大概率 API 返回 HTML 错误页（403/429/500）
   - 用 `r.status_code` + `r.text[:200]` 调试
   - 加 `time.sleep(2)` rate limit

3. **数据写不进 DB**
   - 检查 `save_intel` 的 source/source_type 是否传字符串（不是 list）
   - 检查 `title` 不为空（empty title 会被跳过）

4. **run_all_p0.py 跑得越来越慢**
   - 默认每个 ingestor 间 `time.sleep(1)`,13 个 = 13s 等待
   - 实测 P0 完整跑 ~60-120s（Yahoo/CoinGecko API 限流）
   - 如果 > 3 min,看哪个 ingestor 卡住（用 `tail -50` 抓日志）

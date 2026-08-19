# 数据源完整 inventory 铁律 (v1.7.15, 2026-07-28)

## 起源

**4 轮估错 migration 数据大小** = 4GB 漏报. 根因: `du -sh` 抽样偏差. 写进 v1.7.14 reference, 这次完整化.

## 铁律: 100% 列 + 分类, 永不抽样

```bash
find ~/.dsh -maxdepth 1 -mindepth 1 \( -type f -o -type d \) -not -size 0 \
  -exec du -sh {} \; 2>/dev/null | sort -hr
```

**为什么**:
- `du -sh` 看几个大目录 = 抽样 = 漏小目录
- `find -maxdepth 1` 列出全部非 0 子项 = 100% 覆盖
- 例: 1.85GB 误报 (4 目录) → 实际 6.9GB (40+ 目录)

## 投资 domain 数据源铁律 (P0-12, 2026-07-28)

投资报告数据缺失的根因 = **`evaluate_today.py` 硬编码 macro**:
```python
# evaluate_today.py:256-257 (v1.7.14 前)
indicators["central_bank_net_buying_tons"] = 95  # 2025 月均 95 吨
indicators["ai_capex_yoy"] = 0.65  # 2025 hyperscaler capex +65%
```

这两个值**永不更新**, 13 天报告失真. **修复**: 拉 FRED DGS / yahoo / F&G 实时.

## 6 个新数据源 (全部入 `$MARKET_INTEL_ROOT/backtest/`)

| 文件 | 行数 | 来源 | 用途 |
|---|---|---|---|
| fear_greed_index_history.csv | 2,000 | alternative.me | CNN Fear & Greed 跨市场情绪 |
| vix_term_structure_10y.csv | 2,514 | Yahoo ^VIX ^VIX3M ^VIX6M | 远期曲线 (contango/backwardation) |
| gld_price_10y.csv | 2,512 | Yahoo GLD | 黄金 ETF 跟踪 |
| put_call_ratio_10y.csv | 2,512 | Yahoo ^PUT | 反向情绪 |
| treasury_10y_full_history.csv | 16,845 | **FRED DGS10 (1962 至今, 公开 CSV 无需 key)** | 衰退信号 (2-10 倒挂) |
| earnings_calendar_nasdaq.csv | 1,565 | NASDAQ 公开 API | 财报季预测 |

**FRED 公开 CSV 无需 API key**:
```python
# 示例: DGS10 10 年 10Y 美债收益率
url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
# DGS2/DGS5/DGS10/DGS30 4 期限
url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2,DGS5,DGS10,DGS30&cosd=2025-01-01"
```

**NASDAQ 财报日历公开 API**:
```python
url = "https://api.nasdaq.com/api/calendar/earnings?date=2026-07-28"
```

**alternative.me Fear & Greed**:
```python
url = "https://api.alternative.me/fng/?limit=2000&format=json"
```

## 数据源选择优先级

**Macro / 美债 / 利率**:
1. FRED (公开 CSV, 无 key, 历史长) ✅
2. Yahoo Finance (实时, 月度限制) ⚠️
3. Treasury Department 官方 (经常坏) ❌

**个股 / ETF 价格**:
1. Yahoo Finance (^VIX, GLD, QQQ, TLT) ✅
2. Stooq / AlphaVantage (Yahoo 不可用时) ⚠️

**财报**:
1. NASDAQ 公开 API (`api.nasdaq.com`) ✅
2. Yahoo `quoteSummary` (经常 401) ❌
3. EarningsWhispers RSS ⚠️

**情绪**:
1. CNN Fear & Greed (alternative.me JSON) ✅
2. AAII (aaii.com 不开放 API) ❌
3. VIX 远期 (yahoo ^VIX3M ^VIX6M) ✅

## 修复 evaluate_today.py 硬编码 bug 模板

```python
# ❌ 错 (v1.7.14 前)
indicators["central_bank_net_buying_tons"] = 95  # 2025 月均 95 吨
indicators["ai_capex_yoy"] = 0.65  # 2025 hyperscaler capex +65%

# ✅ 对 (v1.7.15)
# 1. FRED 公开 CSV 拉历史
url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>&cosd=2020-01-01"
# 2. yahoo 拉 ETF
url = "https://query1.finance.yahoo.com/v8/finance/chart/<SYMBOL>?interval=1d&range=10y"
# 3. 写 fallback (网络失败时)
indicators.setdefault("ai_capex_yoy", 0.65)  # 估值快照, 不更新
```

## 数据源完整 inventory 工具 (migration 用, 复用到投资)

```python
# $MARKET_INTEL_ROOT/scripts/data_gap_fill.py (参考)
import csv
from pathlib import Path

def full_inventory(root_dir):
    items = []
    for entry in Path(root_dir).iterdir():
        if entry.name.startswith('.'):
            continue
        if entry.is_file():
            size = entry.stat().st_size
        elif entry.is_dir():
            size = sum(f.stat().st_size for f in entry.rglob('*') if f.is_file())
        else:
            size = 0
        if size > 0:
            items.append((size, entry.name))
    return sorted(items, reverse=True)

# 永远先 100% 列
for size, name in full_inventory("~/.dsh")[:30]:
    print(f"  {size/1024/1024:>8.1f}MB  {name}")
```

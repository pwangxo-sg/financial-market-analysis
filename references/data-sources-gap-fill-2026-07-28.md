# 数据源 Gap Fill (v1.7.14, 2026-07-28)

## 背景
v1.7.13 回测发现：20 条 rule 中 **15 条 0 次触发**（数据缺失）。根因是 `full_backtest.py` 的 `build_indicators_dict()` 用 QQQ/GLD/DXY 老 CSV，没接新数据源。

## 补 6 个源（~28,000 行新数据）

| 文件 | 行数 | 范围 | 价值 |
|---|---|---|---|
| `fear_greed_index_history.csv` | 2,000 | 5+ 年 | 跨市场情绪 (alternative.me API) |
| `vix_term_structure_10y.csv` | 2,514 | 10 年 | VIX + VIX3M + VIX6M 远期曲线 |
| `gld_price_10y.csv` | 2,512 | 10 年 | 黄金 ETF 价格 |
| `put_call_ratio_10y.csv` | 2,512 | 10 年 | ^PUT 总量 (反向情绪) |
| `treasury_10y_full_history.csv` | **16,845** | **1962 至今** | FRED DGS10 长期 (衰退信号) |
| `earnings_calendar_nasdaq.csv` | 1,565 | ±30 天 | 财报季预期 (NASDAQ 公开 API) |

**总 ~28,000 行新数据**。

## 实战脚本: `scripts/data_gap_fill.py`
```bash
python3 $MARKET_INTEL_ROOT/scripts/data_gap_fill.py
# 自动拉 6 个源, 写到 backtest/ 目录
```

## 关键发现
- **FRED 公开 CSV 端点（无需 API key）**: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`
- **NASDAQ 公开 earnings API**: `https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`
- **alternative.me Fear & Greed**: `https://api.alternative.me/fng/?limit=2000&format=json`
- **put/call 用 `^PUT` 单 symbol** 即可（`^PCALL` 在 yahoo 已失效）
- **earnings 用 `query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=earnings`**（v7 已失效, v10 工作）

## 待做
- `full_backtest.py` 的 `build_indicators_dict()` 还没接这些新源 → 15 条失效 rule 仍 0 触发
- 需 patch full_backtest.py 加新源 loader

## 来源
paVisa 实战 (2026-07-28 16:38 BJT)
- 数据拉取脚本: `$MARKET_INTEL_ROOT/scripts/data_gap_fill.py`
- CSV 输出: `$MARKET_INTEL_ROOT/backtest/`

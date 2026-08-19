# Asia Index Coverage via Yahoo Finance (2026-07-14)

Production data fetchers for the report's "亚太+美股全貌" board. Mac 直连 OK, no Lantern needed.

## Why this exists

用户 asked (2026-07-14): "投资理财日报每日 2 次, 增加韩国日本香港股市行情数据, 作为投资决策的依据之一". HK coverage already existed (`hk_index.py`, P1 #5). This documents the parallel **`jp_index.py` (P1 #6)** and **`kr_index.py` (P1 #7)** added in the same session.

## Yahoo Finance ticker mapping

| 指数 | code | yahoo_ticker (URL-encoded) | status |
|---|---|---|---|
| 恒生指数 | HSI | `%5EHSI` | ✅ confirmed |
| 恒生中国企业指数 | HSCE | `%5EHSCE` | ✅ confirmed |
| 恒生科技指数 | HSTECH | `HSTECH.HK` | ✅ confirmed |
| 日经 225 | N225 | `%5EN225` | ✅ **only valid JP ticker** |
| ~~东证 (TOPIX)~~ | ~~TOPX~~ | `%5ETOPX` / `TPX.TYO` / `%5ETPX` | ❌ **all broken — delete TOPX** |
| 韩国综合 (KOSPI) | KS11 | `%5EKS11` | ✅ confirmed |
| 韩国创业板 (KOSDAQ) | KQ11 | `%5EKQ11` | ✅ confirmed |

### Pitfall: Yahoo Japan ticker confusion

`^TOPX` / `TPX.TYO` / `TOPIX.TYO` — **all return delisted / 404** as of 2026-07-14 test.
`^TPX` — returns CBO/OPRA options index data (`regularMarketTime` is 2015-10 epoch, wrong timezone EDT), NOT Tokyo Stock Exchange. **Do not use `^TPX`.**

Confirmed working JP ticker is **only `^N225` / `^NKY`**. N225 alone is sufficient as the authoritative Japan index — TOPIX coverage is not currently available via Yahoo Finance free API without auth.

To verify a ticker before adding: curl `https://query1.finance.yahoo.com/v8/finance/chart/<URL-ENCODED-TICKER>?interval=1d&range=5d` and check `chart.result[0].meta.regularMarketPrice` is non-null and timezone matches expected exchange.

## Endpoints and response shape

```
URL: https://query1.finance.yahoo.com/v8/finance/chart/<TICKER>?interval=1d&range=5d
Headers: User-Agent: Mozilla/5.0 (required — Yahoo returns degraded data without UA)
Timeout: 15s (safe within P0 wrapper 12s budget per source)
```

Key fields from `chart.result[0].meta`:
- `regularMarketPrice` — current price
- `chartPreviousClose` — previous close (for chg_pct calc)
- `regularMarketDayHigh` / `regularMarketDayLow` — intraday
- `currency` — JPY / KRW / HKD
- `regularMarketTime` (Unix epoch) — convert to BJT for display

## Ingestion pattern (shared by hk/jp/kr_index.py)

All three scripts follow the same skeleton — modeled after `hk_index.py` (P1 #5). To add a new Asia index:

1. Copy `hk_index.py` to `<cc>_index.py`
2. Replace `INDICES` list with new tickers (use URL-encoded `^` → `%5E`)
3. Replace log name, emoji flag (🇭🇰/🇯🇵/🇰🇷/🇸🇬/🇹🇼), tag prefix (`hk`/`jp`/`kr`)
4. Run `python3 <cc>_index.py` once — confirm log line `=== <CC> 完成: N new, M dup` (N ≥ 1 means save_intel works)
5. Add script to `scripts/p0_cron_wrapper.sh` phase-1 list AND the `critical = [...]` AND `name_map` blocks
6. If report runs twice a day (09:00 + 19:00 like 26322edf978c), add second-stage cron at 18:50 to refresh intel.db before the 19:00 run

## Connection to P0 cron pipeline

`scripts/p0_cron_wrapper.sh` runs `hk_index.py jp_index.py kr_index.py ...` sequentially, each with 12s timeout. Stage-3 DB check requires `jp_index` and `kr_index` in both `name_map` (runtime tag) and `critical = [...]` (DB verification). Without both entries, the verifier reports "❌ jp_index 缺失" even when the script ran fine.

Currently the wrapper runs daily at **07:50** (cron `a0a1d141f3dc`) and **18:50** (cron `362ea7b6333b`) — the second instance was added 2026-07-14 to ensure the 19:00 daily report has fresh intraday Asia data, not 11-hour-old morning data.

## Daily report prompt integration

When including Asia indexes in a daily report (`26322edf978c`), use this exact query for each source:

```sql
SELECT title, extra FROM intel
WHERE source='<cc>_index'
  AND published_at >= datetime('now', '-1 day')
ORDER BY published_at DESC
LIMIT N  -- N matches expected index count for that market
```

**Failure handling rule (already in daily prompt §3.0):** any source missing → write "今日不可用", never fabricate. Missing Asia index on a P0 wrapper failure → note "⚠️ P0 抓取失败, 数据来自 X 小时前" at top of section.

## Outlier handling

Markets can move hard intraday. 2026-07-14 actual real-world snapshot:
- 🇯🇵 N225 +1.38%
- 🇰🇷 KOSPI -10.44%, KOSDAQ -5.68% — single-day double-digit drop in KOSPI is unusual but **legitimate**, NOT a data error. Confirm via `chartPreviousClose` field vs `regularMarketPrice` (6878.83 vs 7656.31 = -10.16% computation matches).
- 🇭🇰 HSI +3.59% — large rally.

When any Asia index moves > 2% in a single session, the daily report prompt requires explicit mention in "今日核心热点" with one-line linkage to a 用户 holding (e.g. NDX → US tech valuation, gold → risk-off, chemical ETF → Asia demand).

# Supplementary Data Retrieval APIs — Absorbed from financial-market-data

This file consolidates the data retrieval details from the now-archived `financial-market-data` skill. The core analytical framework remains in the parent SKILL.md; these are supplementary API notes.

---

## Yahoo Finance via Proxy

**Proxy**: Lantern VPN at `127.0.0.1:49451` (HTTP), `49452` (SOCKS). Enable Lantern first, then set system proxy.

**Endpoint** (no Referer required):
```
https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo
```

**Shell example with proxy**:
```bash
curl -x http://127.0.0.1:49451 \
  "https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range=3mo"
```

**Known blocked**: Yahoo Finance is blocked in China without VPN.

---

## East Money Choice (push2.eastmoney.com)

**Endpoint**:
```
https://push2.eastmoney.com/api/qt/stock/get?secid=116.QQQ&fields=f43,f44,f45,f46,f47,f48,f57,f58
```

Requires auth token. Less reliable for unauthenticated use. Primarily used for Chinese A-share fundamental data.

---

## Sina Finance HQ API — Verified Working Tickers

*These are the verified-live ticker codes confirmed working via session testing.*

### US Markets
```
gb_qqq   → 纳斯达克100 ETF (Invesco QQQ Trust)
gb_ndx   → 纳斯达克100 指数
gb_spy   → S&P 500 ETF
gb_aapl  → Apple
gb_tsla  → Tesla
gb_nvda  → NVIDIA
```

### China A-share ETFs
```
sh518880 → 黄金ETF (Gold ETF — tracks spot gold price)
sh561170 → 电力设备ETF (Power Equipment sector)
sh562010 → 绿色能源ETF (Clean Energy sector)
sz159885 → 电力设备ETF (alternative provider)
```

### Multi-Ticker Retrieval
```bash
curl -s "https://hq.sinajs.cn/list=gb_qqq,sh518880,sh561170" \
  -H "Referer: https://finance.sina.com.cn"
```

---

## Sina HQ API — Actual Response Shapes

### US Stock (gb_qqq) — 2026-05-22
```
var hq_str_gb_qqq="纳指ETF,714.5100,0.19,2026-05-22 09:45:46,1.3600,708.9900,717.1200,706.7700,722.0300,502.7680,36415360,...";
```
Fields: name, price, change, datetime, ?, open, high, low, 52w_high, vol_m, ...

### China A-share ETF (sh518880) — 2026-05-22
```
var hq_str_sh518880="黄金ETF,,9.460,9.450,9.448,9.471,9.445,9.448,9.449,111749884,1056716120.000,30300,...";
```
Fields: name, ?, current, prev_close, open, high, low, ?, vol, amount, bid/ask depth... (11:30 = Chinese market lunch close)

### Parsing Pattern (Python)
```python
import re, json

raw = 'var hq_str_sh518880="黄金ETF,,9.460,9.450,9.448,9.471,9.445,9.448,9.449,111749884,..."'
m = re.search(r'"([^"]+)"', raw)
if m:
    fields = m.group(1).split(',')
    print(f"Name: {fields[0]}")
    print(f"Current: {fields[2]}")
    print(f"Prev close: {fields[3]}")
    print(f"Open: {fields[4]}")
    print(f"High: {fields[5]}")
    print(f"Low: {fields[6]}")
    print(f"Date: {fields[-3]}")
    print(f"Time: {fields[-2]}")
```

---

## VPN/Proxy Notes

- **Lantern VPN**: `/Applications/Lantern.app`, HTTP proxy port `49451`, SOCKS `49452`
- **Sina HQ API** does NOT need VPN — works directly from China
- **Yahoo Finance** (`query1.finance.yahoo.com`) IS blocked without VPN

---

## Coverage vs. Limitations

| What you CAN get | What you CANNOT get |
|-----------------|---------------------|
| Real-time price (during market hours) | Historical OHLCV (need different API) |
| Day's open/high/low | P/E, P/B, earnings data |
| Volume | Cash flow, balance sheet |
| 52-week price range | Dividend history |
| Fund NAV (ETF) | Fund holdings/portfolio |
| Bid/ask depth | Analyst ratings |

For historical data: consider `akshare` Python library, `investpy`, or East Money historical API.

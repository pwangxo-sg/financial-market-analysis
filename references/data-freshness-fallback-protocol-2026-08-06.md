# 投资报告数据陈旧度协议 (2026-08-06)

## 触发场景

当 **evaluate_today** + **evaluate_today_v2** 跑投资报告时, 任何数据源 yahoo API:

- urllib3 + LibreSSL 警告 (Connection reset by peer)
- 网络 / VPN 限流 (Lantern 出口 IP 被 yahoo 限流)
- csv cache 老于 1 天
- 飞书 channel `not available`

## 协议 (实跑 2026-08-06)

### 1. 报告头部显式标注数据陈旧度

**正确**:
```
📊 投资理财日报 2026-08-06 Thursday 10:36 (08-06 周四)
⚠️ Yahoo Finance 8-6 限流, 数据取自 8-5 (1 天前)
📊 持仓数据已同步 (2026-08-03 11:09, 4只基金 + 41万现金)
```

**错误** ❌:
- 静默调用 8-5 csv cache 当"今日"发 (用户 两次问"为什么不今天就是缓存")
- 编造 "实时今日" 标签但实际是 7-28
- 跑 yahoo 失败但不告知, 静默走 fallback

### 2. fallback 优先级

按数据"新鲜度"倒序:

1. **evaluate_today_v2 缓存** (最近 24h 内) — 优先
2. **backtest/yyy_5y.csv 等 5y csv** (上次 data_gap_fill 跑过) — 次优
3. **backtest/spy_10y.csv / xle_10y.csv** (替代 ETF 用 SPY/XLE 代理)
4. **决策规则 + watchlist** — 不依赖实时数据

### 3. 报告必须含的明示

```
⚠️ 数据陈旧度:
- QQQ/GLD: backtest/yyy_5y.csv (last data 2026-08-05)
- F&G Index: csv (last data 2026-08-05)
- VIX term: csv (last data 2026-08-05)
- 美债: csv (last data 2026-06-05 ⚠️ 60 天前)

⚠️ 风险声明: 基于 2026-08-06 实时今日数据; 持仓 8-3 同步 (020274 已加仓 5k 至 1.5万)
```

### 4. 决策规则不受影响

即使数据陈旧, **rule_engine 输出** (基于 thresholds, 非时间敏感) **仍然有效**:
- NDX_FED_01 触发 = 84.2% 胜率 ∈ 历史窗口
- GRID_AI_01 触发 = 89.5% 胜率

**但**:
- 如果今天 F&G 从 80 → 95 (panic), 报告必须刷新
- 如果用户问"今天最新", 必须跑 evaluate_today_v2 重新拉

### 5. 触发数据重拉的命令

```bash
# 1. 拉今天 yahoo (curl 绕过 urllib3 + LibreSSL)
python3 << 'EOF'
import subprocess
for sym in ['^GSPC', '^IXIC', 'QQQ', 'SMH', 'GLD', '^VIX', '^TNX']:
    r = subprocess.run(
        ['curl', '-sS', '--tls-max', '1.2', '--max-time', '15',
         f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d'],
        capture_output=True, text=True, timeout=20
    )
    if r.returncode == 0 and r.stdout:
        print(f'{sym}: OK')
    else:
        print(f'{sym}: {r.stderr[:80]}')
EOF

# 2. 后台运行 OpenClaw gateway (网络限流时)
nohup ~/.openclaw/bin/openclaw gateway --port 18789 > /tmp/ocgw.log 2>&1 &

# 3. 重跑 evaluate_today_v2 拿新数据
cd $MARKET_INTEL_ROOT/scripts
python3 evaluate_today_v2.py
```

### 6. 数据陈旧度协议 - 报告模板

参考 reproduce 模板 (`/tmp/report_8-6.txt`):

```
📊 投资理财日报 YYYY-MM-DD

✅ 持仓数据已同步 (YYYY-MM-DD HH:MM, 4只基金 + 41万现金)

🌍 全球市场全貌 (⚠️ 数据最新至 2026-08-05, Yahoo Finance 8-6 限流)
📊 持仓动态 (替代 ETF 8-5 数据)
...
⚠️ 风险声明: ...
持仓 8-3 同步 (020274 已加仓 5k 至 1.5万)
```

## 错例 (2026-08-06 我做错的)

```python
# 我把 /tmp/manual_report_8-3.txt 当 8-6 报告发出去 (Pat 问"为什么不是今天")
# 修法: 单独写 /tmp/manual_report_8-6_fallback.py 显式标注 ⚠️ Yahoo Finance 8-6 限流
```

## 已知坑

- LibreSSL 警告不影响功能 (Python 3.9 + urllib3 v2)
- `connection reset by peer` 默认是 VPN 出口 IP 被限流 (Lantern 主因)
- yahoo API 慢时**别 retry** — 等网络恢复
- 报告生成时间 ≠ 数据时间 — 必须分别标注

## 相关改造

- `pavisa-mac-troubleshooting/SKILL.md` — 网络限流检测 + 降级策略
- `$MARKET_INTEL_ROOT/backtest/` — 6 个新 CSV 来源

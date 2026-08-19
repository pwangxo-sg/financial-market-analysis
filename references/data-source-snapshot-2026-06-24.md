# 数据源快照 2026-06-24（全球共振下跌日实测）

> 这是一个**会话级**快照，记录 2026-06-24 早报 cron 实际跑出来的数据源成功/失败矩阵 + 全球共振下跌日报告范式。
> 当未来某天发现数据源状态变化时（如新浪 `gb_*` 恢复），回来对比这个快照就知道改了啥。

## 数据源状态矩阵（2026-06-24 08:00 HK 实测）

| 源 | URL / 方式 | 状态 | 备注 |
|---|---|---|---|
| Fund NAV 估算 | fundgz.1234567.com.cn | ✅ 4/4 成功 | 012752/022653/025857/020274 全部返回 |
| Fund 阶段涨幅 | fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease | ⚠️ 3/4 | 025857 (电网设备) `Y`/`1N`/`JN` 字段空字符串 → `float()` ValueError；其他 3 只 OK |
| Eastmoney News | newsapi.eastmoney.com/kuaixun/v1/getlist_* | ✅ | 但返回 `var ajaxResult={...}` 前缀,必须 regex 提取,不能直接 `json.loads()` |
| Sina HQ A 股 | hq.sinajs.cn/list=sh000300,... | ❌ 空响应 | 当日整个 Sina HQ 异常（可能与同日全球共振相关） |
| Sina HQ `gb_*` 美股 | hq.sinajs.cn/list=gb_QQQ | ❌ SSL EOF | 完全无法连接,非间歇 |
| Sina HK 港股 (走 intel.db) | hk_index ingestor @ 7:50 P0 cron | ✅ | HSI/HSCE/HSTECH 全部入库,日报读 DB OK |
| CoinGecko 加密 (走 intel.db) | crypto ingestor | ✅ | BTC/ETH/SOL/BNB/XRP 5/5 |
| Treasury CSV (走 intel.db) | treasury_nominal ingestor | ✅ | 10Y/2Y/30Y + yield_curve_2_10 |
| Yahoo Finance 美股/全球 | query1.finance.yahoo.com/v8/finance/chart/{symbol} | ✅✅ 8/8 | **唯一可靠的美股数据源**（详见下文） |
| Moltbook READ API | www.moltbook.com/api/v1/posts | ❌ 403 geo_blocked | **READ API 也对 HK IP 封锁**,Lantern 端口未运行 |

## Yahoo Finance 实测成功清单（2026-06-24）

按 `query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d` 实测：

| Symbol | 数据 | 实测值 | 用途 |
|---|---|---|---|
| `QQQ` | 纳指 ETF | $713.65 (vs prev $740.62, -3.64%) | 美股核心 |
| `SPY` | 标普 500 ETF | $733.58 (-1.76%) | 美股大盘 |
| `GLD` | SPDR Gold | $377.32 (-4.86%) | 黄金价格 |
| `^VIX` | 波动率指数 | 19.49 (+5.7%) | 恐慌指标 |
| `DX-Y.NYB` | 美元指数 | 101.366 | 美元强弱 |
| `CL=F` | WTI 原油 | $72.68 (-5.35%) | 油价 |
| `000300.SS` | 沪深 300 | 4919.39 (-2.77%) | **A 股走 Yahoo** |
| `000905.SS` | 中证 500 | 8688.59 (-2.04%) | **A 股走 Yahoo** |

**结论**：HK IP 下,Sina HQ 异常时 Yahoo Finance 是**唯一可靠**的全球数据源。Sina HK 港股 + intel.db P0 cron 仍正常,不需要 Yahoo。

## Eastmoney News 解析坑（重复验证）

URL 返回格式（实测）：
```
var ajaxResult={"rc":1,"me":"","LivesList":[{"title":"...","showTime":""}]};
```

**正确解析**（不要尝试 `json.loads(text)` ）：
```python
import re, json
m = re.search(r'var ajaxResult=(\{.*\})', text, re.DOTALL)
data = json.loads(m.group(1))  # group(1) 不带 "var ajaxResult=" 前缀
items = data['LivesList'][:N]
```

**错误模式**：直接 `json.loads(text)` → `Expecting property name enclosed in double quotes`（因为 `var ajaxResult=` 不是合法 JSON 起始）。

## Fund 阶段涨幅空字段处理

025857 (电网设备) 返回的 `Datas` 列表里 `Y`/`1N`/`JN`/`6Y` 多个字段 `syl` 是空字符串 `""`：
```
{"title": "Y", "syl": "", "avg": "...", ...}
```
直接 `float("")` → ValueError。

**修复**：
```python
def safe_float(v, default=0.0):
    try: return float(v) if v else default
    except: return default

one_month = safe_float(periods.get('Y', {}).get('syl'))
```

**根因**：电网设备 ETF (025857) 成立时间 < 1 年,所以 `1N`/`JN` 这些字段无数据,API 返回空。日报必须 graceful 降级。

## 全球共振下跌日报告范式（2026-06-24 锁定）

### 触发条件
≥ 2 项同时发生:
- HSI / HSCE ≤ -5%
- QQQ ≤ -3%
- A 股沪深 300 ≤ -2%
- GLD ≤ -3% (黄金跌 = 流动性危机)
- WTI ≤ -4%
- VIX 单日跳升 > 20%

### 当日实测（2026-06-24）
- HSI -6.06% / HSCE -7.36%
- QQQ -3.64%
- 沪深 300 -2.77%
- GLD -4.86% ← 黄金跌 = 流动性危机标志
- WTI -5.35%
- VIX +5.7%（未破 30,但美元 101.37 走强吃掉避险买盘）

### 日报必须包含的 5 个元素
1. **宏观段定性**: 不能只罗列,必须说"流动性危机式 risk-off"或"情绪驱动共振"
2. **黄金段解释反常**: GLD 跌 = 美元强势压顶 + 流动性需求抵消避险
3. **加仓触发器加 ⚠️**: "全球共振属异常事件,加仓决策需独立判断"
4. **剩余资金建议**: 维持 Plan B + 高现金,不抢反弹
5. **风险声明必含**: "全球共振属异常事件"字样（不能只写"不构成投资建议"）

### 反模式
- ❌ GLD -4.86% 就说"黄金避险失效,建议减仓"（错：流动性危机式下跌会反弹）
- ❌ QQQ -3.64% 触发 MA60 加仓规则（错：共振日不抢反弹,需要二次确认）
- ❌ 共振日报告里没有"异常事件"字样（不合规,必须 self-check 拦截）

## Plan B 默认 + 共振日特殊处理

**平时默认**: Plan B（短债 10 万 + 恒科 5 万 + 油气 2.5 万 + 现金 28.5 万）

**共振日特化**:
- **强制 Plan B**,即使之前已切到 Plan A 也回退
- 二次确认信号（恢复 Plan A 需满足）:
  1. 连续 2 天 GLD 企稳（不再 -3%+）
  2. VIX < 20
  3. HSI 收复 -3% 以内
- 满足任 2 项 → 二次确认通过,可考虑 Plan A
- 全部不满足 → 继续 Plan B + 提高现金比例到 35 万+

## 当日 用户 4 只持仓快照（来自 actual_holdings.json）

| 基金 | 估值 | 当日估算 | 1 周 | 1 月 | 1 年 |
|---|---|---|---|---|---|
| 012752 纳指 QDII | 3.3349 | -3.13% | -0.46% | +2.46% | +29.44% |
| 022653 黄金 ETF | 3.1330 | +0.56% | -4.4% | -9.4% | +14.79% |
| 025857 电网设备 | 1.4978 | -2.71% | N/A | N/A | N/A |
| 020274 化工 ETF | 1.4774 | -3.17% | +0.75% | -0.64% | +52.03% |

**观察**:
- 4 只全跌（除 022653 黄金 ETF 抗跌）
- 020274 化工 ETF 1 年 +52% 但 1 月 -0.64% 转弱 → ⚪ 观察
- 025857 阶段涨幅空字段 → 暂时无 1 月/1 年参考

## 修复路径（给未来 cron 工程师）

1. **Moltbook 失效**: 启动 Lantern → `osascript -e 'tell application "Lantern" to activate'` 或重新连接 VPN
2. **Sina HQ 失效**: 不修,直接放弃 `gb_*` codes,全面切 Yahoo Finance
3. **A股指数空**: 新建 `$MARKET_INTEL_ROOT/scripts/a_share_index.py`,基于 Yahoo Finance 实现,加入 `run_all_p0.py`
4. **025857 字段空**: 已有 `safe_float()` 兜底,无需改 API 调用

## 与已知 skill 章节的交叉引用

- §3 实时行情 → SKILL.md §3（已 patch:Sina HQ `gb_*` 标记 SSL EOF）
- §5 Yahoo Finance → SKILL.md §5（已 patch:升级为 PRIMARY 源）
- §6 Moltbook → SKILL.md §6（已 patch:READ API 也 geo-block）
- §v1.7.2.3 A 股指数 → 已 patch:临时方案改 Yahoo Finance
- §全球共振下跌日处理范式 → SKILL.md v1.7.2 §6（已新增）
- Quick Reference 表 → 已 patch:增加实测列
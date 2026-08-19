# NBS 中国 PMI 月度数据源（2026-06-06 新增）

> P1 高级源 #4。给 GRID_PMI_01 / CHEM_CNPMI_01 规则提供真实 PMI 数据，**替代 evaluate_today.py 之前用的静态 cn_pmi=50.5**（实测真实值是 50.0，验证了"数据源与数据质量是第一步"）。

## URL

每月初 NBS 在 `https://www.stats.gov.cn/sj/zxfb/` 发布 PMI 月度数据新闻稿：

```
# 列表页（找最新 PMI 新闻稿）
https://www.stats.gov.cn/sj/zxfb/

# 单篇新闻稿 URL 模式
https://www.stats.gov.cn/sj/zxfb/{YYYYMM}/t{YYYYMMDD}_{id}.html
```

例：2026 年 5 月 PMI 新闻稿 `https://www.stats.gov.cn/sj/zxfb/202605/t20260531_1963824.html`

## 抓取脚本

`scripts/nbs_pmi_ingestor_v2.py`（v1 已废，因 HTML 解析坑未修）。

实现流程：
1. 抓 `https://www.stats.gov.cn/sj/zxfb/` 列表
2. 找最近 8 篇新闻稿，依次 GET
3. 哪个有 "PMI" / "采购经理" 关键词 → 锁定
4. 抓 HTML 解析数字
5. 写 `intel.db`（source=nbs_pmi, source_type=regulator, severity=4）
6. 追加到 `backtest/nbs_pmi_history.csv`（用于跨月回测）

## 解析的关键数字

每篇 PMI 新闻稿含：
- 制造业 PMI（主数字）— 用户 重点
- 大型/中型/小型企业 PMI（行业结构）
- 非制造业 PMI / 商务活动指数
- 综合 PMI 产出指数
- 5 个构成指数（生产/新订单/原材料库存/从业人员/供应商配送时间）

## ⚠️ 重要 HTML 解析坑（首席投资专家 4 小时血泪）

**坑 1：`<span>` 标签拆词**

NBS 用 `<span>` 把 "制造业" 和 "PMI" 分开：
```html
<span>制造业</span><span>PMI</span><span>为 50.0%</span>
```

**❌ 错误 regex**: `r'制造业[^。]*?PMI[^。]*?(\d+\.\d+)'` — 跨标签不匹配
**✅ 正确做法**: 先 `re.sub(r'<[^>]+>', ' ', text)` strip 标签再 regex

```python
clean = re.sub(r'<[^>]+>', ' ', html)
clean = re.sub(r'\s+', ' ', clean)
m = re.search(r'制造业.{0,30}PMI.{0,30}为\s*(\d+\.\d+)\s*%', clean)
if m:
    pmi = float(m.group(1))
```

**坑 2：`requests` 默认编码可能错**

`r.text` 在 UTF-8 中文页面可能误判为 latin-1，**汉字变乱码**（"制造业" → "æ°è¿°åµ"）。

**✅ 解决**: 用 `r.content.decode('utf-8', errors='ignore')` 强制 utf-8。

```python
resp = safe_get(url, timeout=15)
html_bytes = resp.content  # bytes, 不解码
clean = re.sub(r'<[^>]+>', ' ', html_bytes.decode('utf-8', errors='ignore'))
```

**坑 3：regex 范围必须宽松（`.{0,30}`）**

原文用 "5 月份，制造业采购经理指数（ PMI ）为 50.0%"，"制造业"和"PMI"中间隔着 "采购经理指数（"。

**✅ 模板**: `r'制造业.{0,30}PMI.{0,30}为\s*(\d+\.\d+)\s*%'`

**坑 4：数字必须过滤合理范围**

防止误匹配到表格里的旧数据（如 PMI 历史表里 49.5 50.7 等）：
```python
if 45 <= float(m.group(1)) <= 60:
    pmi[k] = float(m.group(1))
```

## 验证过的实测数据

| 月份 | 制造业 PMI | 非制造业 | 综合 |
|---|---|---|---|
| 2026-05 | **50.0** | 50.1 | 50.5 |
| 2026-04 | 50.3 (推算: 50.0+0.3) | - | - |
| 2025-12 | 50.1 (历史表) | 50.x | - |
| 2025-11 | 49.2 | - | - |

## 在 evaluate_today.py 中怎么用

`evaluate_today.py` 已升级，不再用静态 `cn_pmi = 50.5`：

```python
# 7. CN PMI (用 NBS 真实数据, 不是静态)
try:
    with get_db() as conn:
        row = conn.execute(
            """SELECT extra FROM intel
            WHERE source = 'nbs_pmi' AND source_type = 'regulator'
            ORDER BY published_at DESC LIMIT 1"""
        ).fetchone()
        if row:
            pmi_data = json.loads(row["extra"]).get("pmi_data", {})
            if "mfg_pmi" in pmi_data:
                indicators["cn_pmi"] = pmi_data["mfg_pmi"]
except Exception:
    indicators["cn_pmi"] = 50.0  # fallback
```

这样**评估器自动用最新 NBS 数据**，不用每月手动更新。

## 在规则引擎中怎么用

`GRID_PMI_01` (cn_pmi > 52 + power_equipment_export_yoy > 0.15) — 等 PMI > 52 才触发电网设备加仓
`CHEM_CNPMI_01` (cn_pmi > 51 + global_mfg_pmi > 50) — 等 PMI > 51 才触发化工加仓

之前 2 条规则**因为 cn_pmi 静态 50.5 永远触发不了**（52 阈值永远达不到），现在用真实 50.0 数据，规则按设计运行（5 月 50.0 < 52 阈值，规则不触发 → 等待）。

## cron 自动跑

`scripts/run_all_p0.py` 已把 `nbs_pmi_ingestor_v2` 加入 SCRIPTS 列表，**每天跑全套会自动检查 NBS 是否有新 PMI 数据**（每月初 1 次更新入库，但 cron 每天检查不浪费——靠 hash 去重）。

## CSV 历史格式

`backtest/nbs_pmi_history.csv`:
```
date,mfg_pmi,non_mfg_pmi,composite_pmi,large_enterprise_pmi,mid_enterprise_pmi,small_enterprise_pmi
2026/05/31,50.0,50.1,50.5,51.1,,48.6
```

可用 pandas 读取后做跨月回测 + 宏观规则触发判断。

## 完整代码

`$MARKET_INTEL_ROOT/scripts/nbs_pmi_ingestor_v2.py` — **v2 是唯一可用版**，v1 已在 v2 写完后废弃

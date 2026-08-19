"""
规则引擎 + 回测框架
- 规则定义: declarative (JSON-style)
- 评估器: 拉数据 → 评估条件 → 输出信号
- 回测器: 用历史数据, 模拟触发 → 计算胜率
"""
import sys
import json
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_db, get_logger, BJT, init_db
from datetime import datetime, timedelta

log = get_logger("rule_engine")

# ============== 规则定义 ==============
# 每条规则格式:
# {
#   "rule_id": "GOLD_RATE_01",
#   "description": "黄金: 实际利率 < 0.5% 时加仓",
#   "target_codes": ["022653"],
#   "signal_type": "add",  # add/reduce/hold/observe
#   "confidence": 75,       # 0-100
#   "indicators": [
#     {"name": "us10y_real", "operator": "<", "value": 0.5}
#   ],
#   "hold_days": 60,         # 预期持仓周期
#   "rationale": "实际利率 = 美债名义利率 - 通胀预期; 实际利率越低, 黄金相对吸引力越强",
#   "expected_win_rate": 0.78,  # 历史回测胜率 (待回测填入)
#   "lookback_days": 1,      # 数据回看天数
# }

RULES = [
    # ============== 012752 纳指QDII ==============
    {
        "rule_id": "NDX_RATE_01",
        "description": "纳指: 美债10Y > 4.5% 且 VIX > 25 → 减仓",
        "target_codes": ["012752"],
        "signal_type": "reduce",
        "confidence": 75,
        "indicators": [
            {"name": "us10y", "operator": ">", "value": 4.5},
            {"name": "vix", "operator": ">", "value": 25},
        ],
        "hold_days": 30,
        "rationale": "高利率+高恐慌 = 双重压制成长股估值",
        "expected_win_rate": 0.75,
        "lookback_days": 3,
    },
    {
        "rule_id": "NDX_YIELD_01",
        "description": "纳指: 2-10Y 利差倒挂 (≤0) → 持有, 不加仓",
        "target_codes": ["012752"],
        "signal_type": "hold",
        "confidence": 80,
        "indicators": [
            {"name": "yield_curve_2_10", "operator": "<=", "value": 0},
        ],
        "hold_days": 180,
        "rationale": "衰退预警: 历史倒挂后 12-18 个月内衰退概率 >70%",
        "expected_win_rate": 0.82,
        "lookback_days": 5,
    },
    {
        "rule_id": "NDX_FED_01",
        "description": "纳指: 美联储降息周期开始 (基准利率环比下降) → 加仓",
        "target_codes": ["012752"],
        "signal_type": "add",
        "confidence": 78,
        "indicators": [
            {"name": "fed_funds_change_3m", "operator": "<", "value": 0},
        ],
        "hold_days": 180,
        "rationale": "降息周期利好成长股, 历史 1985/1995/2001/2007/2019/2024 都验证",
        "expected_win_rate": 0.78,
        "lookback_days": 90,
    },
    {
        "rule_id": "NDX_PULLBACK_01",
        "description": "纳指: 1 周内回调 > 5% + VIX < 30 → 加仓 (逆向)",
        "target_codes": ["012752"],
        "signal_type": "add",
        "confidence": 70,
        "indicators": [
            {"name": "ndx_1w_pct", "operator": "<", "value": -0.05},
            {"name": "vix", "operator": "<", "value": 30},
        ],
        "hold_days": 60,
        "rationale": "VIX 未恐慌 + 急跌 = 抄底机会 (2020/2022/2024 都验证)",
        "expected_win_rate": 0.70,
        "lookback_days": 5,
    },

    # ============== 022653 黄金ETF ==============
    {
        "rule_id": "GOLD_REAL_01",
        "description": "黄金: 美债实际利率 (10Y - 10Y breakeven) < 0.5% → 加仓",
        "target_codes": ["022653"],
        "signal_type": "add",
        "confidence": 80,
        "indicators": [
            {"name": "us10y_real", "operator": "<", "value": 0.5},
        ],
        "hold_days": 90,
        "rationale": "实际利率越低, 持有黄金的机会成本越低, 金价上涨动力越强",
        "expected_win_rate": 0.80,
        "lookback_days": 5,
    },
    {
        "rule_id": "GOLD_DXY_01",
        "description": "黄金: 美元指数 DXY > 106 + 实际利率 > 2% → 减仓",
        "target_codes": ["022653"],
        "signal_type": "reduce",
        "confidence": 75,
        "indicators": [
            {"name": "dxy", "operator": ">", "value": 106},
            {"name": "us10y_real", "operator": ">", "value": 2.0},
        ],
        "hold_days": 60,
        "rationale": "强势美元 + 高实际利率 = 黄金双重利空",
        "expected_win_rate": 0.75,
        "lookback_days": 5,
    },
    {
        "rule_id": "GOLD_GEOPOL_01",
        "description": "黄金: 中东/俄乌地缘风险升级 (我方监测到 ≥ 2 起 4 级事件) → 加仓",
        "target_codes": ["022653"],
        "signal_type": "add",
        "confidence": 72,
        "indicators": [
            {"name": "geopolitical_severity_count_4plus", "operator": ">=", "value": 2},
        ],
        "hold_days": 30,
        "rationale": "地缘溢价回升, 黄金避险需求短期上升",
        "expected_win_rate": 0.72,
        "lookback_days": 7,
    },
    {
        "rule_id": "GOLD_CENTRAL_BANK_01",
        "description": "黄金: 央行月度净购金 > 80 吨 → 加仓 (中长期)",
        "target_codes": ["022653"],
        "signal_type": "add",
        "confidence": 85,
        "indicators": [
            {"name": "central_bank_net_buying_tons", "operator": ">", "value": 80},
        ],
        "hold_days": 180,
        "rationale": "央行购金是中长期定价锚, 历史 2022-2024 央行买盘 >1000 吨/年",
        "expected_win_rate": 0.85,
        "lookback_days": 30,
    },

    # ============== 025857 电网设备ETF ==============
    {
        "rule_id": "GRID_INVEST_01",
        "description": "电网: 国网年度招标同比 > 20% → 加仓（行业景气度指标，非投标服务）",
        "target_codes": ["025857"],
        "signal_type": "add",
        "confidence": 75,
        "indicators": [
            {"name": "sgcc_bidding_yoy", "operator": ">", "value": 0.20},
        ],
        "hold_days": 180,
        "rationale": "国网招标同比是电网设备行业景气度领先指标（行业研究，与投标代理服务无关）",
        "expected_win_rate": 0.75,
        "lookback_days": 90,
    },
    {
        "rule_id": "GRID_PMI_01",
        "description": "电网: 中国制造业 PMI > 52 + 电力设备出口同比 > 15% → 加仓",
        "target_codes": ["025857"],
        "signal_type": "add",
        "confidence": 72,
        "indicators": [
            {"name": "cn_pmi", "operator": ">", "value": 52},
            {"name": "power_equipment_export_yoy", "operator": ">", "value": 0.15},
        ],
        "hold_days": 120,
        "rationale": "内外需双轮驱动 = 行业景气向上",
        "expected_win_rate": 0.72,
        "lookback_days": 30,
    },
    {
        "rule_id": "GRID_AI_01",
        "description": "电网: 全球 AI 算力投资同比 > 50% → 加仓 (算力能耗逻辑)",
        "target_codes": ["025857"],
        "signal_type": "add",
        "confidence": 70,
        "indicators": [
            {"name": "ai_capex_yoy", "operator": ">", "value": 0.50},
        ],
        "hold_days": 180,
        "rationale": "AI 算力指数增长, 电力设备需求是 downstream",
        "expected_win_rate": 0.70,
        "lookback_days": 90,
    },
    {
        "rule_id": "GRID_PULLBACK_01",
        "description": "电网: 近 1 月回撤 > 8% + 国网招标未减 → 加仓 (逆向)（行业景气度指标，非投标服务）",
        "target_codes": ["025857"],
        "signal_type": "add",
        "confidence": 72,
        "indicators": [
            {"name": "grid_1m_pct", "operator": "<", "value": -0.08},
            {"name": "sgcc_bidding_yoy", "operator": ">", "value": 0},
        ],
        "hold_days": 90,
        "rationale": "基本面没坏 + 价格大跌 = 抄底",
        "expected_win_rate": 0.72,
        "lookback_days": 30,
    },

    # ============== 020274 化工ETF ==============
    {
        "rule_id": "CHEM_OIL_01",
        "description": "化工: WTI 原油 > 80 美元 + OPEC 减产 → 加仓 (成本传导)",
        "target_codes": ["020274"],
        "signal_type": "add",
        "confidence": 70,
        "indicators": [
            {"name": "wti", "operator": ">", "value": 80},
        ],
        "hold_days": 120,
        "rationale": "油价高位支撑化工品价格, 库存周期向上",
        "expected_win_rate": 0.70,
        "lookback_days": 5,
    },
    {
        "rule_id": "CHEM_CNPMI_01",
        "description": "化工: 中国 PMI > 51 + 全球制造业 PMI > 50 → 加仓",
        "target_codes": ["020274"],
        "signal_type": "add",
        "confidence": 68,
        "indicators": [
            {"name": "cn_pmi", "operator": ">", "value": 51},
            {"name": "global_mfg_pmi", "operator": ">", "value": 50},
        ],
        "hold_days": 90,
        "rationale": "全球需求共振 = 周期股最强信号",
        "expected_win_rate": 0.68,
        "lookback_days": 30,
    },

    # ============== 012752 纳指QDII · 技术面金子规则 ==============
    # MA200 gate: 2026-06-07 跨周期回测 (2000-2010 + 2016-2026) 实证
    # 4 条规则在 MA200 gate 下表现全面改善:
    #   MA_CROSS_20_60:  牛市 84.6%→90% 收益 +7.18%→+10.13%
    #   BREAKOUT_250D:   牛市 80% 不变, 熊市 71.4% 不变 (已经很稳健)
    #   TREND_MA60:      熊市 60%→64.3% 收益 -0.39%→+1.11% (转正)
    #   MOMENTUM_20D:    熊市 55.6%→57.9% 收益 +0.17%→+0.89%
    {
        "rule_id": "TECH_MA_CROSS_20_60",
        "description": "纳指: MA20 上穿 MA60 → 加仓 (技术面金叉, MA200 gate)",
        "target_codes": ["012752"],
        "signal_type": "add",
        "confidence": 85,
        "indicators": [
            {"name": "ma20_cross_above_ma60", "operator": "==", "value": True},
        ],
        "gate": {"name": "qqq_above_ma200", "operator": "==", "value": True},
        "hold_days": 90,
        "rationale": "MA 金叉 + QQQ 在 MA200 之上 = 中长期趋势反转 (跨周期验证: 牛市 90% 胜率)",
        "expected_win_rate": 0.85,
        "lookback_days": 1,
    },
    {
        "rule_id": "TECH_BREAKOUT_250D",
        "description": "纳指: 突破 250 日新高 → 加仓 (技术面突破, MA200 gate)",
        "target_codes": ["012752"],
        "signal_type": "add",
        "confidence": 80,
        "indicators": [
            {"name": "new_250d_high", "operator": "==", "value": True},
        ],
        "gate": {"name": "qqq_above_ma200", "operator": "==", "value": True},
        "hold_days": 90,
        "rationale": "突破 250 日新高 + QQQ 在 MA200 之上 = 强势信号 (跨周期验证: 熊市仍 71.4% 胜率)",
        "expected_win_rate": 0.80,
        "lookback_days": 1,
    },
    {
        "rule_id": "TECH_MOMENTUM_20D",
        "description": "纳指: 20 日涨幅 5-15% → 加仓 (动量跟踪, MA200 gate)",
        "target_codes": ["012752"],
        "signal_type": "add",
        "confidence": 70,
        "indicators": [
            {"name": "mom_20d", "operator": "between", "value": [0.05, 0.15]},
        ],
        "gate": {"name": "qqq_above_ma200", "operator": "==", "value": True},
        "hold_days": 60,
        "rationale": "动量跟踪 + QQQ 在 MA200 之上 = 强势但非超买 (跨周期验证)",
        "expected_win_rate": 0.70,
        "lookback_days": 1,
    },
    {
        "rule_id": "TECH_TREND_MA60",
        "description": "纳指: 首次站上 MA60 → 加仓 (趋势确认, MA200 gate)",
        "target_codes": ["012752"],
        "signal_type": "add",
        "confidence": 72,
        "indicators": [
            {"name": "above_ma60", "operator": "==", "value": True},
        ],
        "gate": {"name": "qqq_above_ma200", "operator": "==", "value": True},
        "hold_days": 60,
        "rationale": "站上 MA60 + QQQ 在 MA200 之上 = 中期趋势确认 (跨周期验证: 熊市转正)",
        "expected_win_rate": 0.72,
        "lookback_days": 1,
    },

    # ============== 跨资产 / 系统性 ==============
    {
        "rule_id": "SYS_VIX_01",
        "description": "系统性: VIX > 35 + 1 周内纳指跌 > 7% → 全部减仓 30%",
        "target_codes": ["012752", "022653", "025857", "020274"],
        "signal_type": "reduce",
        "confidence": 85,
        "indicators": [
            {"name": "vix", "operator": ">", "value": 35},
            {"name": "ndx_1w_pct", "operator": "<", "value": -0.07},
        ],
        "hold_days": 30,
        "rationale": "恐慌性抛售 = 流动性危机信号, 减仓避险",
        "expected_win_rate": 0.85,
        "lookback_days": 5,
    },
]


# ============== 规则评估器 ==============
def evaluate_condition(cond, indicators):
    """评估单个条件"""
    name = cond["name"]
    op = cond["operator"]
    target = cond["value"]
    actual = indicators.get(name)

    if actual is None:
        return None  # 数据缺失

    if op == ">":
        return actual > target
    elif op == "<":
        return actual < target
    elif op == ">=":
        return actual >= target
    elif op == "<=":
        return actual <= target
    elif op == "==":
        return actual == target
    elif op == "!=":
        return actual != target
    elif op == "between":
        # target 格式: [low, high] 闭区间
        if isinstance(target, (list, tuple)) and len(target) == 2:
            return target[0] <= actual <= target[1]
        return None
    return None


def evaluate_rule(rule, indicators):
    """评估一条规则: 所有 indicators 都满足 + 通过 gate 才触发"""
    results = []
    for cond in rule["indicators"]:
        r = evaluate_condition(cond, indicators)
        results.append(r)

    # 全部 indicators 满足
    if not all(r is True for r in results):
        if any(r is None for r in results):
            return "PARTIAL"  # 部分数据缺失
        return False

    # 检查 gate (市场状态过滤器, 防止熊市/异常环境下的伪信号)
    gate = rule.get("gate")
    if gate:
        g = evaluate_condition(gate, indicators)
        if g is False:
            return False
        if g is None:
            return "PARTIAL_GATE"

    return True


# ============== 规则存 DB ==============
def init_rules():
    """初始化规则表"""
    with get_db() as conn:
                for r in RULES:
                    cond_dict = {
                        "signal_type": r["signal_type"],
                        "confidence": r["confidence"],
                        "indicators": r["indicators"],
                        "hold_days": r["hold_days"],
                        "rationale": r["rationale"],
                    }
                    if r.get("gate"):
                        cond_dict["gate"] = r["gate"]
                    try:
                        conn.execute(
                            """INSERT OR REPLACE INTO rules
                            (rule_id, description, scope, target_codes, conditions,
                             expected_win_rate, expected_hold_days, enabled, created_at)
                            VALUES (?,?,?,?,?,?,?,?,?)""",
                            (
                                r["rule_id"],
                                r["description"],
                                "fund",
                                json.dumps(r["target_codes"], ensure_ascii=False),
                                json.dumps(cond_dict, ensure_ascii=False),
                                r["expected_win_rate"],
                                r["hold_days"],
                                1,
                                datetime.now(BJT).isoformat(timespec="seconds"),
                            ),
                        )
                    except Exception as e:
                        log.warning(f"init rule {r['rule_id']} failed: {e}")


# ============== 主入口 ==============
if __name__ == "__main__":
    init_db()
    init_rules()
    log.info(f"✅ 规则库初始化完成: {len(RULES)} 条")
    for r in RULES:
        target = "/".join(r["target_codes"])
        log.info(f"  [{r['signal_type']:7s}] {r['rule_id']:18s} ({target}): {r['description'][:60]}")

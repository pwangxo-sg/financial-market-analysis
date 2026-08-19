"""
增强版今日评估
- 加 timing 层: 区分"中期信号" vs "短期时机"
- 综合判断: 中期看好 + 短期没回调 → "持有, 等待回调"
            中期看好 + 短期回调 → "现在加仓"
            中期看空 + 短期反弹 → "减仓"
            中期看空 + 短期下跌 → "观察"
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_db, get_logger, BJT, safe_get
from rule_engine import RULES, evaluate_rule
from datetime import datetime, timedelta
from evaluate_today import fetch_indicators
from decision_tracker import save_decisions_from_evaluate_v2

log = get_logger("evaluate_today_v2")


def timing_advice(code, indicators, base_action):
    """
    根据短期动量 + 波动率给 timing 建议
    base_action: "add" | "reduce" | "hold" | "observe"
    """
    advice = {
        "timing": "neutral",
        "wait_for_pullback": False,
        "add_now": False,
        "reduce_now": False,
        "explanation": "",
    }

    # 提取该基金相关指标
    if code == "012752":  # 纳指
        ndx_1d = indicators.get("ndx_1d_pct", 0)
        ndx_1w = indicators.get("ndx_1w_pct", 0)
        ndx_1m = indicators.get("ndx_1m_pct", 0)
        vix = indicators.get("vix", 20)
        if base_action == "add":
            if ndx_1d < -0.04:
                # 单日急跌, 强烈逆向
                advice["timing"] = "buy_dip_strong"
                advice["add_now"] = True
                advice["explanation"] = f"今日单日急跌{ndx_1d*100:.1f}%, 是中期加仓好时机 (如基本面未变)"
            elif ndx_1w < -0.03:
                advice["timing"] = "buy_dip"
                advice["add_now"] = True
                advice["explanation"] = f"近1周跌{ndx_1w*100:.1f}%, 是逆向加仓好时机"
            elif ndx_1m > 0.10:
                advice["timing"] = "wait_pullback"
                advice["wait_for_pullback"] = True
                advice["explanation"] = f"近1月已涨{ndx_1m*100:.1f}%, 建议等回调5%+再加"
            elif vix > 25:
                advice["timing"] = "wait"
                advice["wait_for_pullback"] = True
                advice["explanation"] = f"VIX {vix} 偏高, 市场恐慌, 暂观望"
            else:
                advice["timing"] = "slow_add"
                advice["add_now"] = True
                advice["explanation"] = f"近1周{ndx_1w*100:+.1f}%, 可分批加仓"
        elif base_action == "reduce":
            advice["timing"] = "reduce_gradually"
            advice["reduce_now"] = True
            advice["explanation"] = "中期信号看空, 减仓执行"
        elif base_action == "hold":
            advice["timing"] = "hold"
            advice["explanation"] = "中期信号持有, 不主动加仓"
        else:
            advice["timing"] = "observe"
            advice["explanation"] = "无明确中期信号, 观察"

    elif code == "022653":  # 黄金
        dxy = indicators.get("dxy", 100)
        us10y_real = indicators.get("us10y_real", 0)
        geopolitical = indicators.get("geopolitical_severity_count_4plus", 0)
        if base_action == "add":
            # 黄金加仓时机: 实际利率低 + 地缘风险高 + 美元不强势
            if us10y_real < 0 and dxy < 105 and geopolitical >= 2:
                advice["timing"] = "add_aggressive"
                advice["add_now"] = True
                advice["explanation"] = f"实际利率{us10y_real}%, DXY {dxy}, 地缘事件{geopolitical}起, 黄金多重利好共振, 可积极加仓"
            elif dxy > 105:
                advice["timing"] = "wait"
                advice["wait_for_pullback"] = True
                advice["explanation"] = f"DXY {dxy} 偏强, 短期压制金价, 建议分批加"
            else:
                advice["timing"] = "slow_add"
                advice["add_now"] = True
                advice["explanation"] = "可分批加仓"
        elif base_action == "reduce":
            advice["timing"] = "reduce"
            advice["reduce_now"] = True
        else:
            advice["timing"] = "hold"

    elif code == "025857":  # 电网
        grid_1m = indicators.get("grid_1m_pct", 0)
        if base_action == "add":
            if grid_1m > 0.08:
                advice["timing"] = "wait_pullback"
                advice["wait_for_pullback"] = True
                advice["explanation"] = f"近1月+{grid_1m*100:.1f}%, 累积涨幅大, 建议等回调5-8%再加"
            elif grid_1m < -0.05:
                advice["timing"] = "buy_dip"
                advice["add_now"] = True
                advice["explanation"] = f"近1月{grid_1m*100:.1f}%, 是逆向加仓机会"
            else:
                advice["timing"] = "slow_add"
                advice["add_now"] = True
                advice["explanation"] = "可分批加仓"
        elif base_action == "reduce":
            advice["timing"] = "reduce"
            advice["reduce_now"] = True
        else:
            advice["timing"] = "hold"

    elif code == "020274":  # 化工
        wti = indicators.get("wti", 70)
        chem_1m = indicators.get("chem_1m_pct", 0)
        chem_1d = indicators.get("chem_1d_pct", 0)
        if base_action == "add":
            if chem_1m < -0.10:
                # 大跌, 强烈逆向
                advice["timing"] = "buy_dip_strong"
                advice["add_now"] = True
                advice["explanation"] = f"化工近1月{chem_1m*100:.1f}%, 大幅下跌 + WTI ${wti} 强支撑 + 周期股逻辑 → 强力逆向加仓"
            elif wti > 85:
                advice["timing"] = "add_on_strength"
                advice["add_now"] = True
                advice["explanation"] = f"WTI ${wti} 处于强势区间, 化工成本传导顺畅, 可加"
            elif wti < 70:
                advice["timing"] = "wait"
                advice["wait_for_pullback"] = True
                advice["explanation"] = f"WTI ${wti} 偏弱, 化工成本端承压, 暂观望"
            else:
                advice["timing"] = "slow_add"
                advice["add_now"] = True
                advice["explanation"] = "可分批加仓"
        elif base_action == "reduce":
            advice["timing"] = "reduce"
            advice["reduce_now"] = True
        else:
            advice["timing"] = "hold"

    return advice


def evaluate_v2():
    log.info("=" * 60)
    log.info(f"📊 增强版规则评估 - {datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    indicators = fetch_indicators()

    # 1. 跑基础规则
    log.info("\n--- 基础规则评估 ---")
    triggered = []
    for rule in RULES:
        if evaluate_rule(rule, indicators) is True:
            triggered.append(rule)

    log.info(f"触发: {len(triggered)} 条")

    # 2. 每只基金综合判断
    log.info("\n--- 每只基金: 中期信号 + 短期时机 ---")
    fund_decisions = {}
    for code in ["012752", "022653", "025857", "020274"]:
        code_triggered = [r for r in triggered if code in r["target_codes"]]
        add_score = sum(r["confidence"] for r in code_triggered if r["signal_type"] == "add")
        reduce_score = sum(r["confidence"] for r in code_triggered if r["signal_type"] == "reduce")
        hold_score = sum(r["confidence"] for r in code_triggered if r["signal_type"] == "hold")

        # 基础判断 (中期信号)
        if reduce_score > add_score and reduce_score > 60:
            base = "reduce"
        elif add_score > reduce_score + 30 and add_score > 60:
            base = "add"
        elif hold_score > 0:
            base = "hold"
        elif add_score > 0 and reduce_score == 0:
            base = "add"
        else:
            base = "observe"

        # Timing 层
        timing = timing_advice(code, indicators, base)

        # 最终决策
        if timing["add_now"]:
            final = "✅ 现在加仓"
            emoji = "🟢"
        elif timing["reduce_now"]:
            final = "🟡 减仓"
            emoji = "🟡"
        elif timing["wait_for_pullback"]:
            final = "⏸️ 持有, 等待回调再加"
            emoji = "🔵"
        else:
            final = "⚪ 观察"
            emoji = "⚪"

        fund_decisions[code] = {
            "base_action": base,
            "timing": timing,
            "final": final,
            "emoji": emoji,
            "add_score": add_score,
            "reduce_score": reduce_score,
            "triggered_rules": [r["rule_id"] for r in code_triggered],
        }

        log.info(f"\n  {emoji} {code}: {final}")
        log.info(f"     中期信号: {base} (add +{add_score} / reduce -{reduce_score})")
        log.info(f"     短期时机: {timing['timing']}")
        log.info(f"     触发规则: {fund_decisions[code]['triggered_rules']}")
        log.info(f"     说明: {timing['explanation']}")

    # 3. 输出
    result = {
        "timestamp": datetime.now(BJT).isoformat(timespec="seconds"),
        "indicators_count": len(indicators),
        "indicators": indicators,
        "triggered_count": len(triggered),
        "fund_decisions": fund_decisions,
    }

    # 4. (P0-12) 市场情绪面板 (情绪 + 美债曲线)
    try:
        from sentiment_panel import get_sentiment_panel
        panel = get_sentiment_panel(indicators)
        result["sentiment_panel"] = panel
        log.info(f"\n  📊 情绪面板: F&G {panel['fng']['latest']} ({panel['fng']['classification']}) | VIX {panel['vix']['current']} ({panel['vix']['level']}) | 综合 {panel['composite_score']}/100 → {panel['signal']}")
    except Exception as e:
        log.warning(f"  ❌ sentiment_panel: {e}")

    # 5. (P0-12) 持仓相关性矩阵
    try:
        from correlation_matrix import compute_holdings_correlation
        corr = compute_holdings_correlation(include_smh=True)
        if corr:
            result["correlation_matrix"] = corr
            log.info(f"\n  📊 相关性矩阵 ({corr['period_days']} 天): avg={corr['analysis']['avg_correlation']}, {corr['analysis']['diversification_comment']}")
            # 高相关警告 (>0.8)
            for p in corr["analysis"]["all_pairs"]:
                if p["correlation"] > 0.8:
                    log.warning(f"     ⚠️  {p['codes'][0]} ↔ {p['codes'][1]}: {p['correlation']:+.2f} (高度同步, 伪分散)")
    except Exception as e:
        log.warning(f"  ❌ correlation_matrix: {e}")
    output_path = "/tmp/today_signals_v2.json"
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 完整结果: {output_path}")

    # 4. (P0 #11) 自动写 decisions 表 — 任何 add/reduce 都记录
    try:
        saved_ids = save_decisions_from_evaluate_v2(result, source_note="evaluate_today_v2")
        if saved_ids:
            log.info(f"  💾 saved {len(saved_ids)} decisions: {saved_ids}")
        result["saved_decision_ids"] = saved_ids
    except Exception as e:
        log.error(f"  ❌ save_decisions_from_evaluate_v2 failed: {e}")

    return result


if __name__ == "__main__":
    evaluate_v2()

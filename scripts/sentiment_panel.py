"""
市场情绪面板 (P0-12, 2026-07-28)
- 综合多个情绪指标输出 0-100 情绪分数 + 信号
- 用于投资报告 "市场情绪" 段
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT

BJT = timezone(timedelta(hours=8))
log = get_logger("market_sentiment_panel")


def load_fng(path=None):
    """F&G Index 最近 30 天 (csv)"""
    if path is None:
        path = Path('~/.dsh/market_intel/backtest/fear_greed_index_history.csv').expanduser()
    if not path.exists():
        return None
    rows = []
    with open(path) as f:
        for line in f.readlines()[1:]:
            parts = line.strip().split(",")
            if len(parts) >= 2 and parts[1].isdigit():
                rows.append(int(parts[1]))
    return rows


def load_vix_term(path=None):
    """VIX ^VIX3M / ^VIX 比率 (CSV)"""
    if path is None:
        path = Path('~/.dsh/market_intel/backtest/vix_term_structure_10y.csv').expanduser()
    if not path.exists():
        return None
    rows = []
    with open(path) as f:
        header = f.readline().strip().split(",")
        for line in f.readlines()[-30:]:
            parts = line.strip().split(",")
            if len(parts) >= 3 and parts[0]:
                try:
                    row = {"Date": parts[0]}
                    for i, h in enumerate(header[1:], 1):
                        if i < len(parts) and parts[i]:
                            try:
                                row[h] = float(parts[i])
                            except ValueError:
                                pass
                    if "^VIX" in row and "^VIX3M" in row and row["^VIX3M"]:
                        row["ratio"] = round(row["^VIX3M"] / row["^VIX"], 3)
                    rows.append(row)
                except (ValueError, IndexError):
                    continue
    return rows


def load_put_call(path=None):
    """^PUT 总量 (CSV) 30 天"""
    if path is None:
        path = Path('~/.dsh/market_intel/backtest/put_call_ratio_10y.csv').expanduser()
    if not path.exists():
        return None
    rows = []
    with open(path) as f:
        for line in f.readlines()[-30:]:
            parts = line.strip().split(",")
            if len(parts) >= 2:
                try:
                    rows.append({"Date": parts[0], "value": float(parts[1])})
                except (ValueError, IndexError):
                    continue
    return rows


def compute_sentiment_score(fng_latest, fng_30d_mean, vix_ratio, put_call_dev):
    """
    综合情绪分数 0-100 (0=极恐惧=买, 100=极贪婪=卖)
    输入: F&G 最新/30d均值, VIX term ratio, P/C 偏离 5d
    """
    score = 50  # 中性基准
    notes = []

    # 1. F&G 偏离 30d 均值 (主权重 50%)
    if fng_latest is not None and fng_30d_mean is not None:
        diff = fng_latest - fng_30d_mean
        score += diff * 0.5
        if abs(diff) > 10:
            notes.append(f"F&G 偏离 30d {diff:+.0f} (显著)")

    # 2. VIX term structure (权重 30%)
    if vix_ratio is not None:
        # ratio > 1.1 = contango (正常), < 0.9 = backwardation (恐慌)
        if vix_ratio < 0.9:
            score -= 15
            notes.append(f"VIX 远期 backwardation ({vix_ratio:.2f}, 恐慌)")
        elif vix_ratio > 1.1:
            score -= 3  # 略偏紧
        else:
            score += 0  # 正常

    # 3. Put/Call 偏离 5d (权重 20%)
    if put_call_dev is not None:
        # dev > 20% = 异常 put 上升 = 恐慌
        if put_call_dev > 20:
            score -= 12
            notes.append(f"P/C 5d 偏离 {put_call_dev:+.0f}% (异常 put 上升)")
        elif put_call_dev < -20:
            score += 8
            notes.append(f"P/C 5d 偏离 {put_call_dev:+.0f}% (看多)")
        else:
            score += 0

    # 限幅 [0, 100]
    score = max(0, min(100, score))
    return round(score, 1), notes


def get_sentiment_panel(indicators=None):
    """
    主入口: 给报告生成用
    返回: {
      "fng": {latest, mean_30d, classification, ...},
      "vix_term": {ratio, status, ...},
      "put_call": {current, dev_5d, ...},
      "composite_score": 0-100,
      "signal": "extreme_fear|fear|neutral|greed|extreme_greed",
      "notes": [...]
    }
    """
    # 从 indicators 拿, 拿不到从 CSV 兜底
    if indicators is None:
        indicators = {}

    fng_latest = indicators.get("fng_latest")
    fng_30d_mean = indicators.get("fng_30d_mean")
    vix_ratio = indicators.get("vix_term_ratio")
    put_call_dev = indicators.get("put_call_vs_5d")
    vix = indicators.get("vix", 18.21)

    # 兜底: 从 CSV 拉
    fng_rows = load_fng()
    if fng_rows:
        if fng_latest is None:
            fng_latest = fng_rows[-1]
        if fng_30d_mean is None and len(fng_rows) >= 30:
            fng_30d_mean = round(sum(fng_rows[-30:]) / 30, 1)
        elif fng_30d_mean is None:
            fng_30d_mean = round(sum(fng_rows) / len(fng_rows), 1)

    vix_rows = load_vix_term()
    if vix_ratio is None and vix_rows and vix_rows[-1].get("ratio"):
        vix_ratio = vix_rows[-1]["ratio"]

    pc_rows = load_put_call()
    if put_call_dev is None and pc_rows and len(pc_rows) >= 5:
        cur = pc_rows[-1]["value"]
        avg5 = sum(r["value"] for r in pc_rows[-5:]) / 5
        put_call_dev = round((cur - avg5) / avg5 * 100, 2)

    # F&G 分类
    def fng_class(v):
        if v is None: return "未知"
        if v < 25: return "Extreme Fear"
        if v < 45: return "Fear"
        if v < 55: return "Neutral"
        if v < 75: return "Greed"
        return "Extreme Greed"

    # 情绪分数
    composite, notes = compute_sentiment_score(fng_latest, fng_30d_mean, vix_ratio, put_call_dev)

    # 信号
    if composite < 25: signal = "EXTREME_FEAR (买)"
    elif composite < 45: signal = "FEAR (偏买)"
    elif composite < 55: signal = "NEUTRAL"
    elif composite < 75: signal = "GREED (偏卖)"
    else: signal = "EXTREME_GREED (卖)"

    # VIX 状态
    if vix_ratio is None: vix_status = "未知"
    elif vix_ratio < 0.9: vix_status = "Backwardation (恐慌)"
    elif vix_ratio < 1.0: vix_status = "略平"
    else: vix_status = "Contango (正常)"

    return {
        "fng": {
            "latest": fng_latest,
            "mean_30d": fng_30d_mean,
            "dev_from_mean": round(fng_latest - fng_30d_mean, 1) if (fng_latest and fng_30d_mean) else None,
            "classification": fng_class(fng_latest),
        },
        "vix": {
            "current": vix,
            "level": "高" if vix > 25 else ("中" if vix > 15 else "低"),
        },
        "vix_term": {
            "ratio_3m_spot": vix_ratio,
            "status": vix_status,
        },
        "put_call": {
            "current": pc_rows[-1]["value"] if pc_rows else None,
            "dev_5d_pct": put_call_dev,
            "interpretation": "put 异常上升 → 恐慌" if (put_call_dev and put_call_dev > 20) else ("正常" if put_call_dev else "未知"),
        },
        "composite_score": composite,
        "signal": signal,
        "notes": notes,
        "generated_at": datetime.now(BJT).isoformat(timespec="seconds"),
    }


def format_panel_for_report(panel):
    """
    生成投资报告可粘贴的纯文本 (中文, 简洁)
    """
    fng = panel["fng"]
    vix = panel["vix"]
    vt = panel["vix_term"]
    pc = panel["put_call"]
    score = panel["composite_score"]
    signal = panel["signal"]

    lines = [
        "📊 市场情绪面板 (2026-07-28 10:00 实时):",
        f"  • F&G Index: {fng['latest']} ({fng['classification']}), 30d 均 {fng['mean_30d']}, 偏离 {fng['dev_from_mean']}",
        f"  • VIX 现货: {vix['current']} ({vix['level']}位)",
        f"  • VIX 远期曲线 (3M/Spot): {vt['ratio_3m_spot']} ({vt['status']})",
        f"  • Put/Call 总量 5d 偏离: {pc['dev_5d_pct']:+.1f}% ({pc['interpretation']})",
        f"  • 综合情绪分数: {score}/100",
        f"  • 信号: {signal}",
    ]
    if panel["notes"]:
        lines.append("  • 提示: " + "; ".join(panel["notes"]))
    return "\n".join(lines)


# 简易测试
if __name__ == "__main__":
    # 模拟 indicators
    test_ind = {
        "fng_latest": 80,
        "fng_30d_mean": 82.9,
        "vix_term_ratio": 1.08,
        "put_call_vs_5d": -0.1,
        "vix": 18.21,
    }
    panel = get_sentiment_panel(test_ind)
    print("=== JSON ===")
    print(json.dumps(panel, ensure_ascii=False, indent=2, default=str))
    print("\n=== 报告文本 ===")
    print(format_panel_for_report(panel))

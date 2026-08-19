"""
evaluate_today_v2.py - freshness tag patch (P0-13)

核心: 报告里每个指标段 + 持仓动态段都标"今日数据 / N天前缓存 / 缺失"
防止 Patrick 基于滞后数据做决策.

规则:
- "TODAY" 数据基准日 = 今天 (8-10)
- "1D_OLD" = 1 天前 (8-9 收盘)
- "N_DAY_OLD" = N 天前
- "MISSING" = 拉取失败
- "UNKNOWN" = 无法判断

判断依据:
- 每个 indicator 来源的 "last_data_date" vs today
- 持仓动态: 每只基金的估值日期 vs today
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


def freshness_label(data_date_str, today_date_str):
    """
    返回 freshness 标签:
    - "TODAY"     同日
    - "1D_OLD"    1 天前
    - "N_DAY_OLD" N 天前
    - "MISSING"   无数据日期
    - "WEEK_OLD"  ≥5 天
    """
    if not data_date_str or data_date_str in ("", "N/A", "缺失"):
        return "MISSING"
    try:
        from datetime import datetime
        d_data = datetime.strptime(data_date_str[:10], "%Y-%m-%d")
        d_today = datetime.strptime(today_date_str[:10], "%Y-%m-%d")
        days = (d_today - d_data).days
        if days == 0: return "TODAY"
        if days == 1: return "1D_OLD"
        if days < 5: return f"{days}D_OLD"
        if days < 30: return f"WEEK_OLD ({days}D)"
        return f"STALE ({days}D)"
    except Exception:
        return "UNKNOWN"


def freshness_emoji(label):
    """根据 freshness 返回 emoji"""
    if "TODAY" in label: return "🟢"
    if "1D" in label: return "🟡"
    if "WEEK" in label: return "🟠"
    if "STALE" in label: return "🔴"
    if "MISSING" in label: return "⚫"
    return "⚪"

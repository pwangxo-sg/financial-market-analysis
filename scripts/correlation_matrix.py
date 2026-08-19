"""
持仓相关性矩阵 (P0-12, 2026-07-28)
- 4 只基金 + SMH (候选) 的 1y 日度收益率
- Pearson 相关性 + 协方差
- 报告用: 风险分散 / 加仓 SMH 决策
"""
import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT, safe_get

log = get_logger("correlation_matrix")


def fetch_yahoo_returns(symbol, days=365):
    """拉 yahoo 日度收盘价 → 算 daily returns"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={days}d"
    resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    if not resp:
        return []
    d = resp.json()
    result = d.get("chart", {}).get("result", [{}])[0]
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    ts = result.get("timestamp", [])
    # close → daily returns
    data = []
    prev = None
    for t, c in zip(ts, closes):
        if c is None or prev is None or prev == 0:
            prev = c
            continue
        ret = (c - prev) / prev
        date = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        data.append({"date": date, "ret": ret, "close": c})
        prev = c
    return data


def pearson(x, y):
    """Pearson 相关系数"""
    n = len(x)
    if n < 2:
        return 0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    if var_x == 0 or var_y == 0:
        return 0
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def compute_correlation_matrix(returns_dict):
    """returns_dict = {code: [{date, ret}, ...]}, 求 code 间相关性"""
    codes = list(returns_dict.keys())
    n = len(codes)
    if n < 2:
        return {}

    # 找公共日期
    date_sets = [set(r["date"] for r in rets) for rets in returns_dict.values()]
    common_dates = sorted(set.intersection(*date_sets))
    log.info(f"  公共日期: {len(common_dates)} 天 (代码 {n} 个)")

    # 提取公共日期的 returns 向量
    vectors = {}
    for code, rets in returns_dict.items():
        d = {r["date"]: r["ret"] for r in rets}
        vectors[code] = [d[date] for date in common_dates]

    # 相关性矩阵
    matrix = {}
    for c1 in codes:
        matrix[c1] = {}
        for c2 in codes:
            matrix[c1][c2] = round(pearson(vectors[c1], vectors[c2]), 3)
    return matrix


def analyze_diversification(matrix, holdings):
    """
    分析组合分散度
    holdings = {code: amount}
    返回: {total_corr, max_corr_pair, comment}
    """
    codes = list(holdings.keys())
    if not codes:
        return {}
    pairs = []
    for i, c1 in enumerate(codes):
        for c2 in codes[i+1:]:
            pairs.append(((c1, c2), matrix[c1][c2]))

    avg_corr = sum(v for _, v in pairs) / len(pairs) if pairs else 0
    max_pair, max_corr = max(pairs, key=lambda x: x[1]) if pairs else (None, 0)
    min_pair, min_corr = min(pairs, key=lambda x: x[1]) if pairs else (None, 0)

    if avg_corr > 0.7:
        comment = f"⚠️ 高度相关 (avg {avg_corr:.2f}), 伪分散风险"
    elif avg_corr > 0.4:
        comment = f"🟡 中等相关 ({avg_corr:.2f}), 部分分散"
    else:
        comment = f"✅ 低相关 ({avg_corr:.2f}), 真分散"

    return {
        "avg_correlation": round(avg_corr, 3),
        "max_pair": {"codes": list(max_pair) if max_pair else None, "correlation": max_corr},
        "min_pair": {"codes": list(min_pair) if min_pair else None, "correlation": min_corr},
        "all_pairs": [{"codes": list(p), "correlation": v} for p, v in sorted(pairs, key=lambda x: -x[1])],
        "diversification_comment": comment,
    }


def format_for_report(matrix, analysis):
    """生成报告可粘贴的纯文本"""
    codes = list(matrix.keys())
    n = len(codes)

    lines = [f"📊 持仓相关性矩阵 (近 1y 日度收益率, {n} 标的)"]
    # 表头
    lines.append("    " + " " * 12 + "  ".join(f"{c:>10}" for c in codes))
    # 数据
    for c1 in codes:
        row = [f"{c1:>12}"]
        for c2 in codes:
            if c1 == c2:
                row.append(f"     --   ")
            else:
                v = matrix[c1][c2]
                emoji = "🔴" if v > 0.7 else ("🟡" if v > 0.4 else "🟢")
                row.append(f" {v:+.2f} {emoji}")
        lines.append("    " + "  ".join(row))

    lines.append("")
    lines.append(f"    {analysis['diversification_comment']}")
    if analysis.get("max_pair"):
        codes_str = " ↔ ".join(analysis["max_pair"]["codes"])
        lines.append(f"    最强相关: {codes_str} ({analysis['max_pair']['correlation']:+.2f})")
    if analysis.get("min_pair"):
        codes_str = " ↔ ".join(analysis["min_pair"]["codes"])
        lines.append(f"    最弱相关: {codes_str} ({analysis['min_pair']['correlation']:+.2f})")
    return "\n".join(lines)


# ============== 主入口 (给投资报告用) ==============
def compute_holdings_correlation(holdings=None, include_smh=False):
    """
    持仓 {code: name} → 相关性矩阵 + 分散度分析
    默认查 Patrick 实际持仓 4 只基金
    include_smh: 把 SMH 候选标的也加入
    """
    if holdings is None:
        holdings = {
            "012752": "建信纳指QDII C",
            "022653": "华安黄金ETF I",
            "025857": "华夏电网设备ETF C",
            "020274": "富国化工ETF C",
        }

    # Yahoo 替代 ETF (基金无 yahoo ticker, 用替代品)
    code_to_yahoo = {
        "012752": "QQQ",      # 纳指 QDII → QQQ
        "022653": "GLD",      # 黄金 ETF → GLD
        "025857": "FXN",      # 电网设备 → FXN (能源设备)
        "020274": "XLE",      # 化工 ETF → XLE (能源化工)
        "SMH": "SMH",        # 半导体 ETF
        "KWEB": "KWEB",      # 中概互联
    }

    log.info(f"=== 持仓相关性计算 ({len(holdings)} 只基金) ===")
    returns = {}
    for code, name in holdings.items():
        yf = code_to_yahoo.get(code)
        if not yf:
            log.warning(f"  ⚠️  {code} {name} 无 yahoo 替代, skip")
            continue
        rets = fetch_yahoo_returns(yf, days=365)
        if rets:
            returns[code] = rets
            log.info(f"  ✅ {code} {name} → {yf}: {len(rets)} 天")
        else:
            log.warning(f"  ❌ {code} {name} → {yf} 取数失败")

    if include_smh:
        smh_rets = fetch_yahoo_returns("SMH", days=365)
        if smh_rets:
            returns["SMH"] = smh_rets
            log.info(f"  ✅ SMH 半导体 ETF: {len(smh_rets)} 天")

    if len(returns) < 2:
        log.error(f"  ❌ 数据不足, 只有 {len(returns)} 个标的")
        return None

    matrix = compute_correlation_matrix(returns)
    holdings_with_smh = dict(holdings)
    if include_smh:
        holdings_with_smh["SMH"] = "VanEck 半导体 ETF"
    analysis = analyze_diversification(matrix, holdings_with_smh)

    return {
        "codes": list(returns.keys()),
        "code_names": {code: code_to_yahoo.get(code, code) for code in returns.keys()},
        "matrix": matrix,
        "analysis": analysis,
        "report_text": format_for_report(matrix, analysis),
        "period_days": len(list(returns.values())[0]) if returns else 0,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# 简易测试
if __name__ == "__main__":
    result = compute_holdings_correlation(include_smh=True)
    if result:
        print("=== 报告文本 ===")
        print(result["report_text"])
        print()
        print("=== JSON ===")
        print(json.dumps({k: v for k, v in result.items() if k != "matrix"}, ensure_ascii=False, indent=2))
        print()
        print("=== matrix ===")
        for c1, row in result["matrix"].items():
            print(f"  {c1}: {row}")

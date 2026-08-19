#!/usr/bin/env python3
"""
知识库 → CIO 持仓之外机会扫描的输入源 (2026-06-10 新增)

功能：
- 读 ~/.dsh/knowledge/index/index.json 的所有条目
- 抽行业关键词 + 触发逻辑
- 匹配"持仓之外"主题 ETF 关键词库
- 输出纯文本（cron prompt 第 6 步直接 cat 进去用）

Patrick 偏好极简：只输出能直接驱动 cron 报告"建仓候选"板块的内容。

用法:
    python3 ~/.dsh/market_intel/scripts/kb_holdings_scan.py
    python3 ~/.dsh/market_intel/scripts/kb_holdings_scan.py --json
"""
import argparse
import json
import re
from pathlib import Path
from collections import defaultdict

# CIO 报告"持仓之外"主题 ETF 关键词映射（粗粒度，不绑死具体 ETF 代码）
# 命名 = Patrick 投资兴趣对齐
INDUSTRY_KEYWORDS = {
    "半导体/AI 算力": ["半导体", "AI", "算力", "数字研发", "数字孪生", "AI+", "国产替代"],
    "AI 主题（应用层）": ["人工智能", "智能制造", "智能服务", "数字化转型", "AI 客服", "智能辅销"],
    "创新药/医药": ["创新药", "医保", "医药", "生物"],
    "军工/国防": ["军工", "国防", "地缘", "台海", "中东", "冲突"],
    "汽车/新能源": ["车企", "汽车", "新能源", "车联网", "T-Box", "充电桩", "动力电池"],
    "金融科技/银行": ["IBM", "农村金融", "银行", "ESB", "SOA", "金融集团", "多法人"],
    "保险/金融": ["保险", "泰康", "精算", "承保", "理赔"],  # 泰康为保险公司名（行业关键词，非投标相关）,
    "供应链/物流": ["供应链", "采购云", "物流", "区块链", "协同平台"],
    "宽基/A股": ["沪深300", "宽基", "A股", "国家队", "估值修复"],
    "数据治理/企业服务": ["数据治理", "主数据", "数据安全", "数据质量", "ESB", "ERP"],
}

# Patrick 已知持仓的关键词（要排除/标低优先级）
HOLDING_KEYWORDS = {
    "012752 纳指QDII": ["纳指", "纳斯达克", "美股", "QQQ"],
    "022653 黄金ETF": ["黄金", "避险", "实际利率"],
    "025857 电网设备ETF": ["电网", "电力", "电网设备"],
    "020274 化工ETF": ["化工", "细分化工", "富国化工"],
}


def load_kb(index_path: Path) -> list:
    if not index_path.exists():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return data.get("entries", [])


def classify_article(entry: dict) -> dict:
    """把单篇知识库文章分类到 industry 主题"""
    text = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(entry.get("tags", [])),
    ])

    scores = defaultdict(int)
    for keyword in (entry.get("tags", []) + [entry.get("title", "")]):
        keyword_lower = keyword.lower()
        for industry, kws in INDUSTRY_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in keyword_lower:
                    scores[industry] += 2
        for industry, kws in HOLDING_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in keyword_lower:
                    scores[industry] -= 3  # 持仓相关 = 扣分

    # 标题权重更高
    title_text = entry.get("title", "").lower()
    for industry, kws in INDUSTRY_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in title_text:
                scores[industry] += 1

    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "tags": entry.get("tags", []),
        "source": entry.get("source"),
        "date": entry.get("date"),
        "scores": dict(scores),
    }


def scan_for_opportunities(articles: list, top_n: int = 5) -> list:
    """聚合所有文章 → 输出 top N 持仓之外行业主题"""
    industry_articles = defaultdict(list)
    industry_max_score = defaultdict(int)

    for art in articles:
        cls = classify_article(art)
        for ind, score in cls["scores"].items():
            if score > 0:
                industry_articles[ind].append({
                    "title": art["title"],
                    "date": art["date"],
                    "score": score,
                })
                industry_max_score[ind] = max(industry_max_score[ind], score)

    # 按最高分排序
    sorted_inds = sorted(
        industry_articles.keys(),
        key=lambda x: -industry_max_score[x]
    )

    results = []
    for ind in sorted_inds[:top_n]:
        arts = sorted(industry_articles[ind], key=lambda x: -x["score"])
        results.append({
            "industry": ind,
            "max_score": industry_max_score[ind],
            "articles": arts[:3],  # 最多 3 篇参考
        })

    return results


def format_text(results: list) -> str:
    """输出纯文本格式（CIO 报告 prompt 直接 cat）"""
    if not results:
        return "📚 知识库扫描：今日无新持仓之外线索\n"

    out = ["📚 知识库 → 持仓之外机会（top 5 主题）\n"]
    for i, r in enumerate(results, 1):
        out.append(f"{i}. {r['industry']}（知识库命中 {r['max_score']} 次）")
        for art in r["articles"][:2]:
            out.append(f"   - {art['date']}｜{art['title'][:50]}")
        out.append("")

    out.append("⚠️ 知识库给的是行业趋势 + 客户案例，不是具体 ETF 代码。")
    out.append("   cron agent 需把行业主题映射到具体主题 ETF（参考 holdings-external-scan.md 已有候选）。")

    return "\n".join(out)


def format_json(results: list) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="知识库 → CIO 持仓之外扫描")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--kb-index", default=str(Path.home() / ".dsh/knowledge/index/index.json"))
    parser.add_argument("--top", type=int, default=5, help="输出 top N 行业主题")
    args = parser.parse_args()

    articles = load_kb(Path(args.kb_index))
    if not articles:
        print("❌ 知识库为空或路径错", file=__import__("sys").stderr)
        return 1

    results = scan_for_opportunities(articles, top_n=args.top)

    if args.json:
        print(format_json(results))
    else:
        print(format_text(results))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

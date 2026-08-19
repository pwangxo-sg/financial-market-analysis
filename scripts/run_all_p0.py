"""
统一调度: 跑所有 P0 抓取脚本
- 顺序: news → research → regulator → event → sentiment → commodity
- 总耗时: ~60-90 秒
- 输出: 数据量统计
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# 先初始化 DB
from _lib import init_db, stats_by_source, get_logger

log = get_logger("run_all_p0")

SCRIPTS = [
    "rss_ingestor",
    "eastmoney_reports",
    "fed_sec_calendar",
    "usgs_noaa_monitor",
    "reddit_sentiment",
    "eia_commodity",
    "moltbook_ingestor",
    "treasury_ingestor",
    # P1 新增
    "polymarket_ingestor",
    "opensky_ingestor",
    "analyst_rss_v2",
    "nbs_pmi_ingestor_v2",
    # P1 #5/#6 (2026-06-15): 港股 3 指数 + 加密 5 币 (补全日报"市场全貌")
    "hk_index",
    "crypto",
]


def run_all():
    """跑所有 P0 抓取"""
    init_db()
    log.info("=" * 60)
    log.info("🚀 P0 完整抓取开始")
    log.info("=" * 60)

    t0 = time.time()
    results = {}
    for name in SCRIPTS:
        log.info(f"\n--- {name} ---")
        try:
            mod = __import__(name)
            t_start = time.time()
            saved, dups = mod.run()
            elapsed = time.time() - t_start
            results[name] = {"saved": saved, "dups": dups, "elapsed_s": round(elapsed, 1), "ok": True}
        except Exception as e:
            log.warning(f"❌ {name} 失败: {e}")
            results[name] = {"saved": 0, "dups": 0, "elapsed_s": 0, "ok": False, "error": str(e)}
        time.sleep(1)  # rate limit

    total_elapsed = time.time() - t0
    total_saved = sum(r["saved"] for r in results.values())

    log.info("\n" + "=" * 60)
    log.info(f"✅ 全部完成: {total_saved} new, {total_elapsed:.1f}s")
    log.info("=" * 60)

    # 统计
    stats = stats_by_source(days=1)
    log.info("\n📊 24h 抓取统计 (按 source):")
    for s in stats:
        log.info(f"  {s['source']:30s} ({s['source_type']:12s}): {s['n']:4d} 条  最新 {s['latest']}")

    return results


if __name__ == "__main__":
    run_all()

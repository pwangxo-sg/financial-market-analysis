"""
P1-3: OpenSky Network 全球航班跟踪
- 公开 API 无需 key (匿名有频率限制, 10 秒/请求)
- 监控关键地缘区域: 霍尔木兹海峡 / 台湾海峡 / 俄乌边境 / 朝鲜
- 航班数突变 = 军事/商业活动变化 = 地缘事件信号
"""
import sys
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get
from datetime import datetime, timedelta

log = get_logger("opensky_flights")

# OpenSky Network API
OPENSKY_STATES = "https://opensky-network.org/api/states/all"

# 关键地缘区域 (lat/lon box)
WATCH_BOXES = {
    "Hormuz": {
        "lat_min": 24, "lat_max": 28, "lon_min": 50, "lon_max": 60,
        "label": "霍尔木兹海峡 (伊朗/阿曼/沙特)",
        "importance": "高 - 全球 20% 石油运输, 中东冲突核心",
    },
    "Taiwan": {
        "lat_min": 21, "lat_max": 26, "lon_min": 118, "lon_max": 125,
        "label": "台湾海峡",
        "importance": "高 - 台海紧张, 半导体供应链",
    },
    "Crimea": {
        "lat_min": 44, "lat_max": 48, "lon_min": 32, "lon_max": 37,
        "label": "克里米亚/黑海",
        "importance": "高 - 俄乌冲突核心",
    },
    "Suez": {
        "lat_min": 27, "lat_max": 32, "lon_min": 32, "lon_max": 36,
        "label": "苏伊士运河/红海",
        "importance": "高 - 全球航运关键, 胡塞武装袭击区",
    },
    "Korea_DMZ": {
        "lat_min": 37, "lat_max": 39, "lon_min": 124, "lon_max": 128,
        "label": "朝鲜 DMZ/三八线",
        "importance": "中 - 朝鲜半岛紧张",
    },
    "Israel": {
        "lat_min": 29, "lat_max": 34, "lon_min": 34, "lon_max": 36,
        "label": "以色列",
        "importance": "高 - 中东核心",
    },
}


def fetch_opensky(box=None):
    """拉 OpenSky 状态, 可选 bbox"""
    if box:
        url = f"{OPENSKY_STATES}?lamin={box['lat_min']}&lomin={box['lon_min']}&lamax={box['lat_max']}&lomax={box['lon_max']}"
    else:
        url = OPENSKY_STATES
    resp = safe_get(url, timeout=30)
    if not resp:
        return None
    try:
        return resp.json()
    except Exception as e:
        log.warning(f"json parse failed: {e}")
        return None


def count_states(data):
    """统计状态数"""
    if not data:
        return 0
    states = data.get("states", [])
    return len(states)


def is_military(callsign, origin_country):
    """简单判断军用/政府/可疑"""
    if not callsign:
        return False
    cs = callsign.upper()
    mil_keywords = ["RCH", "CNV", "GOV", "MIL", "NAVY", "ARMY", "FORCE", "REACH", "EVAC", "USAF", "RAF", "RFR"]
    for kw in mil_keywords:
        if kw in cs:
            return True
    return False


def summarize_box(name, box_info, data):
    """汇总一个区域的数据"""
    if not data or not data.get("states"):
        return None
    states = data["states"]
    n = len(states)
    if n == 0:
        return None
    # 解析状态 (OpenSky 格式: icao24, callsign, origin_country, time_position, last_contact, longitude, latitude, baro_altitude, on_ground, velocity, ...)
    countries = set()
    military_count = 0
    for s in states[:50]:
        if len(s) >= 4:
            callsign = s[1] or ""
            country = s[2] or ""
            countries.add(country)
            if is_military(callsign, country):
                military_count += 1
    summary = (
        f"实时航班: {n} 架 | "
        f"涉及国家: {', '.join(list(countries)[:5])} | "
        f"疑似军用: {military_count} | "
        f"区域: {box_info['label']} | "
        f"重要性: {box_info['importance']}"
    )
    return {
        "title": f"✈️ {name} 区域 {n} 架航班 (含疑似军用 {military_count})",
        "content": summary,
        "tags": ["flight_tracking", "geopolitical", f"region:{name}", "opensky"],
        "severity": 3 if n > 10 else 2,
        "extra": {
            "region": name,
            "flight_count": n,
            "countries": list(countries)[:10],
            "military_estimated": military_count,
            "importance": box_info["importance"],
        },
    }


def run():
    log.info("=" * 60)
    log.info("✈️ OpenSky Network 全球航班跟踪")
    log.info("=" * 60)
    total = 0
    dups = 0

    # 1. 全球总数
    log.info("\n--- 全球航班总数 ---")
    global_data = fetch_opensky()
    if global_data:
        n = count_states(global_data)
        log.info(f"  全球实时航班: {n} 架")
        # 全局记录
        global_intel = {
            "title": f"✈️ 全球实时航班 {n} 架",
            "content": f"OpenSky Network 全球 ADS-B 实时统计: {n} 架飞机在飞",
            "tags": ["flight_tracking", "global", "opensky"],
            "severity": 1,
            "extra": {"region": "global", "flight_count": n},
        }
        s, d = save_intel([global_intel], "opensky_global", "event")
        total += s
        log.info(f"  ✅ 全球: +{s} new")

    # 2. 6 个关键区域
    log.info("\n--- 6 个关键地缘区域 ---")
    for name, box_info in WATCH_BOXES.items():
        try:
            data = fetch_opensky(box={
                "lat_min": box_info["lat_min"],
                "lat_max": box_info["lat_max"],
                "lon_min": box_info["lon_min"],
                "lon_max": box_info["lon_max"],
            })
            intel_data = summarize_box(name, box_info, data)
            if intel_data:
                s, d = save_intel([intel_data], f"opensky_{name.lower()}", "event")
                total += s
                log.info(f"  ✅ {name}: {intel_data['extra']['flight_count']} 架 (含 {intel_data['extra']['military_estimated']} 疑似军用)")
            else:
                log.info(f"  ⚠️ {name}: 无数据")
        except Exception as e:
            log.warning(f"  ❌ {name}: {e}")
        time.sleep(3)  # rate limit (匿名 10s/req, 我留 3s 缓冲)

    log.info(f"=== OpenSky 完成: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

"""
P0-4: USGS 地震 + NOAA 飓风/天气
- 监控全球 M5.0+ 地震（地缘风险 indicator）
- NOAA 大西洋/东太平洋飓风（影响能源 + 农业）
- USGS 公开 API, 无需 key
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, save_intel, safe_get, BJT
from datetime import datetime, timedelta

log = get_logger("usgs_noaa")

# USGS 过去 7 天 M2.5+ 地震
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"
# 过去 1 天 M5.0+
USGS_M5_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/5.0_day.geojson"

# NOAA NHC 大西洋飓风
NOAA_ATLANTIC = "https://www.nhc.noaa.gov/index-at.xml"
NOAA_PACIFIC = "https://www.nhc.noaa.gov/index-ep.xml"

# 关键地缘地震区域 (影响市场)
KEY_REGIONS = {
    "Hormuz":  {"lat_range": (24, 30), "lon_range": (50, 60)},   # 霍尔木兹海峡
    "Taiwan":  {"lat_range": (20, 27), "lon_range": (118, 125)}, # 台湾
    "Japan":   {"lat_range": (30, 46), "lon_range": (130, 146)}, # 日本
    "Turkey":  {"lat_range": (36, 42), "lon_range": (26, 45)},   # 土耳其/地中海
    "Iran":    {"lat_range": (25, 40), "lon_range": (44, 63)},   # 伊朗
    "Indonesia":{"lat_range": (-10, 6), "lon_range": (95, 141)}, # 印尼
}


def in_key_region(lat, lon):
    for name, r in KEY_REGIONS.items():
        if r["lat_range"][0] <= lat <= r["lat_range"][1] and r["lon_range"][0] <= lon <= r["lon_range"][1]:
            return name
    return None


def fetch_usgs():
    """USGS 地震"""
    items = []
    for url, source_key, min_mag in [
        (USGS_URL, "usgs_m2.5", 2.5),
        (USGS_M5_URL, "usgs_m5.0", 5.0),
    ]:
        resp = safe_get(url, timeout=15)
        if not resp:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry", {}).get("coordinates", [0, 0])
            lon, lat = geom[0], geom[1]
            mag = props.get("mag", 0)
            place = props.get("place", "")
            time_ms = props.get("time", 0)
            url_detail = props.get("detail", "")
            if time_ms:
                pub_iso = datetime.fromtimestamp(time_ms / 1000, BJT).isoformat(timespec="seconds")
            else:
                pub_iso = datetime.now(BJT).isoformat(timespec="seconds")
            region = in_key_region(lat, lon)
            severity = 4 if (region and mag >= 4.0) else (3 if mag >= 5.0 else 2)
            tags = ["earthquake", f"m{mag:.1f}"]
            if region:
                tags.append(f"region:{region}")
                tags.append("geopolitical")
            title = f"M{mag:.1f} {place[:60]}"
            if region:
                title = f"⚠️ {title} [{region}]"
            items.append({
                "title": title,
                "content": f"Magnitude: {mag} | Depth: {props.get('depth','?')}km | Place: {place}",
                "url": url_detail,
                "author": "USGS",
                "published_at": pub_iso,
                "tags": tags,
                "severity": severity,
                "extra": {"magnitude": mag, "lat": lat, "lon": lon, "region": region, "depth_km": props.get("depth")},
            })
    return items


def fetch_noaa():
    """NOAA NHC 飓风"""
    items = []
    for url, source_key in [(NOAA_ATLANTIC, "nhc_atlantic"), (NOAA_PACIFIC, "nhc_pacific")]:
        resp = safe_get(url, timeout=12)
        if not resp:
            continue
        import feedparser
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:8]:
            title = entry.get("title", "").strip()
            if not title:
                continue
            content = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")
            pub = entry.get("published", "")
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                from datetime import datetime as _dt
                pub_iso = _dt(*entry.published_parsed[:6], tzinfo=BJT).isoformat(timespec="seconds")
            else:
                pub_iso = pub
            items.append({
                "title": f"🌀 {title}",
                "content": content[:1500],
                "url": link,
                "author": "NOAA NHC",
                "published_at": pub_iso,
                "tags": ["hurricane", "weather", "noaa", "natural_event"],
                "severity": 4,
            })
    return items


def run():
    log.info("=== USGS + NOAA 抓取 ===")
    total = 0
    dups = 0
    try:
        items = fetch_usgs()
        s, d = save_intel(items, "usgs", "event")
        total += s; dups += d
        log.info(f"  ✅ USGS: +{s} new (总扫描 {len(items)} 条)")
    except Exception as e:
        log.warning(f"  ❌ USGS: {e}")
    try:
        items = fetch_noaa()
        s, d = save_intel(items, "noaa", "event")
        total += s; dups += d
        log.info(f"  ✅ NOAA: +{s} new")
    except Exception as e:
        log.warning(f"  ❌ NOAA: {e}")
    log.info(f"=== 突发事件: {total} new ===")
    return total, dups


if __name__ == "__main__":
    run()

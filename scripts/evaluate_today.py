"""
今日信号评估
- 拉当前指标快照 (us10y, vix, dxy, wti 等)
- 跑 15 条规则
- 输出: 每只基金的最终建议 + 触发证据
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_db, get_logger, BJT, safe_get
from rule_engine import RULES, evaluate_rule
from datetime import datetime, timedelta
import re
import csv
import io
import json as _json

log = get_logger("evaluate_today")


def fetch_indicators():
    """拉取今日所有指标 (用 Yahoo + 其他源)"""
    import csv
    import io
    indicators = {}
    today = datetime.now(BJT).isoformat(timespec="seconds")
    # 重新 import (LSP 误报, 但运行时也偶发 - 强制)
    from _lib import safe_get as _safe_get
    global safe_get
    safe_get = _safe_get

    # ============== 1. 美债收益率 (优先用 Treasury 真实数据) ==============
    yyyymm = datetime.now().strftime("%Y%m")
    treasury_url = (
        f"https://home.treasury.gov/resource-center/data-chart-center/"
        f"interest-rates/daily-treasury-rates.csv/all/{yyyymm}?"
        f"type=daily_treasury_yield_curve&field_tdr_date_value_month={yyyymm}&page&_format=csv"
    )
    treasury_real_url = (
        f"https://home.treasury.gov/resource-center/data-chart-center/"
        f"interest-rates/daily-treasury-rates.csv/all/{yyyymm}?"
        f"type=daily_treasury_real_yield_curve&field_tdr_date_value_month={yyyymm}&page&_format=csv"
    )
    treasury_data = safe_get(treasury_url, timeout=15)
    treasury_real_data = safe_get(treasury_real_url, timeout=15)
    if treasury_data:
        try:
            reader = csv.DictReader(io.StringIO(treasury_data.text))
            rows = list(reader)
            if rows:
                latest = rows[0]
                # 解析关键期限
                if "10 Yr" in latest:
                    indicators["us10y"] = float(latest["10 Yr"])
                    log.info(f"  ✅ us10y (Treasury): {indicators['us10y']}")
                if "2 Yr" in latest:
                    indicators["us2y"] = float(latest["2 Yr"])
                    log.info(f"  ✅ us2y (Treasury): {indicators['us2y']}")
                if "5 Yr" in latest:
                    indicators["us5y"] = float(latest["5 Yr"])
                if "3 Mo" in latest:
                    indicators["us3m"] = float(latest["3 Mo"])
                if "30 Yr" in latest:
                    indicators["us30y"] = float(latest["30 Yr"])
                if "1 Yr" in latest:
                    indicators["us1y"] = float(latest["1 Yr"])
        except Exception as e:
            log.warning(f"  ❌ Treasury CSV parse: {e}")

    if "us10y" in indicators and "us2y" in indicators:
        indicators["yield_curve_2_10"] = round(indicators["us10y"] - indicators["us2y"], 3)
        log.info(f"  ✅ yield_curve_2_10: {indicators['yield_curve_2_10']:.3f}")

    # Treasury TIPS (实际利率)
    if treasury_real_data:
        try:
            reader = csv.DictReader(io.StringIO(treasury_real_data.text))
            rows = list(reader)
            if rows:
                latest = rows[0]
                if "10 Yr" in latest:
                    indicators["us10y_real"] = float(latest["10 Yr"])
                    log.info(f"  ✅ us10y_real (TIPS 真实): {indicators['us10y_real']}")
                if "5 Yr" in latest:
                    indicators["us5y_real"] = float(latest["5 Yr"])
                if "30 Yr" in latest:
                    indicators["us30y_real"] = float(latest["30 Yr"])
        except Exception as e:
            log.warning(f"  ❌ TIPS parse: {e}")

    # 备用: Yahoo + FRED (日度数据)
    # 月 Treasury CSV 经常坏, 用 FRED DGS2/DGS5/DGS10/DGS30 日度作为权威源
    try:
        fred_resp = safe_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2,DGS5,DGS10,DGS30&cosd=2025-01-01", headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
        if fred_resp and fred_resp.text:
            lines = fred_resp.text.strip().split("\n")[1:]
            valid = []
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 5:
                    try:
                        valid.append({
                            "Date": parts[0],
                            "us2y": float(parts[1]) if parts[1] not in ("", ".") else None,
                            "us5y": float(parts[2]) if parts[2] not in ("", ".") else None,
                            "us10y": float(parts[3]) if parts[3] not in ("", ".") else None,
                            "us30y": float(parts[4]) if parts[4] not in ("", ".") else None,
                        })
                    except (ValueError, IndexError):
                        continue
            if valid:
                latest = valid[-1]
                # 月度 Treasury CSV 只填缺的, FRED 日度覆盖
                for t in ("us2y", "us5y", "us10y", "us30y"):
                    if latest.get(t) and t not in indicators:
                        indicators[t] = latest[t]
                # 5d 变化 (衰退信号)
                if len(valid) >= 5:
                    last5_avg = {
                        t: sum(v[t] for v in valid[-5:] if v.get(t)) / sum(1 for v in valid[-5:] if v.get(t))
                        for t in ("us2y", "us5y", "us10y", "us30y")
                    }
                    for t in ("us2y", "us5y", "us10y", "us30y"):
                        if latest.get(t) and last5_avg.get(t):
                            indicators[f"{t}_5d_chg_bp"] = round((latest[t] - last5_avg[t]) * 100, 1)
                # 2-10 倒挂 (衰退信号)
                if latest.get("us10y") and latest.get("us2y"):
                    indicators["yield_curve_2_10"] = round(latest["us10y"] - latest["us2y"], 3)
                    indicators["yield_curve_2_10_inverted"] = latest["us10y"] < latest["us2y"]
                if latest.get("us10y") and latest.get("us30y"):
                    indicators["yield_curve_10_30"] = round(latest["us30y"] - latest["us10y"], 3)
                log.info(f"  ✅ FRED DGS: 2Y={latest.get('us2y')}, 5Y={latest.get('us5y')}, 10Y={latest.get('us10y')}, 30Y={latest.get('us30y')} | 2-10={indicators.get('yield_curve_2_10')}{' ⚠️倒挂' if indicators.get('yield_curve_2_10_inverted') else ''}")
    except Exception as e:
        log.warning(f"  ❌ FRED DGS2-30: {e}")

    # ============== 3. VIX (Yahoo) ==============
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/^VIX?interval=1d&range=5d"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if closes and closes[-1]:
                indicators["vix"] = round(closes[-1], 2)
                log.info(f"  ✅ vix: {indicators['vix']}")
    except Exception as e:
        log.warning(f"  ❌ vix: {e}")

    # ============== 4. DXY (美元指数) ==============
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=5d"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if closes and closes[-1]:
                indicators["dxy"] = round(closes[-1], 2)
                log.info(f"  ✅ dxy: {indicators['dxy']}")
    except Exception as e:
        log.warning(f"  ❌ dxy: {e}")

    # ============== 5. WTI 原油 (已有 EIA proxy) ==============
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1d&range=5d"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if closes and closes[-1]:
                indicators["wti"] = round(closes[-1], 2)
                log.info(f"  ✅ wti: ${indicators['wti']}")
    except Exception as e:
        log.warning(f"  ❌ wti: {e}")

    # ============== 6. 实际利率 (优先用 TIPS, 否则 breakeven 估算) ==============
    if "us10y_real" not in indicators and "us10y" in indicators:
        # 10Y breakeven 平均 2.3% (历史)
        indicators["us10y_real"] = round(indicators["us10y"] - 2.3, 3)
        log.info(f"  ✅ us10y_real (估算): {indicators['us10y_real']}")

    # ============== 7. CN PMI (用 NBS 真实数据, 不是静态) ==============
    # 从 intel DB 拿最近一条 nbs_pmi
    try:
        with get_db() as conn:
            row = conn.execute(
                """SELECT extra FROM intel
                WHERE source = 'nbs_pmi' AND source_type = 'regulator'
                ORDER BY published_at DESC LIMIT 1"""
            ).fetchone()
            if row:
                import json as _json
                pmi_data = _json.loads(row["extra"]).get("pmi_data", {})
                if "mfg_pmi" in pmi_data:
                    indicators["cn_pmi"] = pmi_data["mfg_pmi"]
                    log.info(f"  ✅ cn_pmi (NBS 真实): {indicators['cn_pmi']}")
    except Exception as e:
        log.warning(f"  ❌ cn_pmi 加载失败: {e}")
    if "cn_pmi" not in indicators:
        indicators["cn_pmi"] = 50.0  # fallback
        log.info(f"  ⚠️ cn_pmi (fallback): {indicators['cn_pmi']}")

    # ============== 8. 1 日 / 1 周 / 1 月 涨跌幅 (从 Yahoo Finance 实拉, 不再硬编码 7-15 数据) ==============
    # 原代码是 Patrick 2026-07-15 当天手动写的快照, 8 天后 (2026-07-23) 严重过期.
    # 修复 (P0 #12): 现场拉 Yahoo 5d + 1mo 数据, 自己算 1d/5d/20d chg_pct
    try:
        import urllib.request as _ur
        fund_yahoo_map = {
            "012752": "QQQ",      # 纳指QDII → QQQ
            "022653": "GLD",      # 黄金ETF → GLD
            "025857": "FXN",      # 电网设备ETF → FXN (能源板块代理)
            "020274": "XLE",      # 化工ETF → XLE (能源化工代理)
        }
        for code, yf_t in fund_yahoo_map.items():
            try:
                _url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_t}?interval=1d&range=2mo"
                _req = _ur.Request(_url, headers={"User-Agent": "Mozilla/5.0"})
                _d = json.loads(_ur.urlopen(_req, timeout=8).read())
                _closes = _d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
                _ts = _d["chart"]["result"][0]["timestamp"]
                _valid = [(t,c) for t,c in zip(_ts, _closes) if c is not None]
                if len(_valid) < 22:
                    log.warning(f"  ⚠️ {code} {yf_t} 数据点不足 {len(_valid)}, skip")
                    continue
                _cur = _valid[-1][1]
                _1d = (_cur - _valid[-2][1]) / _valid[-2][1]
                _5d = (_cur - _valid[-5][1]) / _valid[-5][1]
                _20d = (_cur - _valid[-20][1]) / _valid[-20][1]
                indicators[f"{code}_fund_1d"] = round(_1d, 4)
                indicators[f"{code}_fund_5d"] = round(_5d, 4)
                indicators[f"{code}_fund_20d"] = round(_20d, 4)
                # ndx_1d_pct 兼容旧代码 (012752 替代)
                if code == "012752":
                    indicators["ndx_1d_pct"] = round(_1d, 4)
                    indicators["ndx_1w_pct"] = round(_5d, 4)
                    indicators["ndx_1m_pct"] = round(_20d, 4)
                # 化工 1m 兼容
                if code == "020274":
                    indicators["chem_1d_pct"] = round(_1d, 4)
                    indicators["chem_1m_pct"] = round(_20d, 4)
                # 电网 1m 兼容
                if code == "025857":
                    indicators["grid_1d_pct"] = round(_1d, 4)
                    indicators["grid_1m_pct"] = round(_20d, 4)
                # 黄金 1m 兼容
                if code == "022653":
                    indicators["gold_1d_pct"] = round(_1d, 4)
                    indicators["gold_1m_pct"] = round(_20d, 4)
                log.info(f"  ✅ {code} {yf_t}: 今日 {_1d*100:+.2f}% 5d {_5d*100:+.2f}% 20d {_20d*100:+.2f}%")
            except Exception as inner_e:
                log.warning(f"  ❌ {code} {yf_t}: {inner_e}")
    except Exception as e:
        log.warning(f"  ❌ 实拉基金替代数据失败: {e}")

    # fallback (防止网络问题): 用 7-15 硬编码 (Patrick 已知)
    if "ndx_1d_pct" not in indicators:
        log.warning(f"  ⚠️ fallback 到 7-15 硬编码数据 (不推荐)")
        indicators["ndx_1d_pct"] = -0.0453
        indicators["ndx_1w_pct"] = 0.0051
        indicators["ndx_1m_pct"] = 0.0919
        indicators["chem_1m_pct"] = -0.1391
        indicators["chem_1d_pct"] = 0.0033
        indicators["grid_1m_pct"] = 0.0563
        indicators["grid_1d_pct"] = -0.0179
        indicators["gold_1m_pct"] = -0.0390
        indicators["gold_1d_pct"] = -0.0001

    # ============== 9. 地缘事件计数 (从 intel.db 查 7 天内 severity>=4) ==============
    try:
        with get_db() as conn:
            cutoff = (datetime.now(BJT) - timedelta(days=7)).isoformat()
            row = conn.execute(
                """SELECT COUNT(*) as n FROM intel
                WHERE published_at >= ? AND severity >= 4
                AND (tags LIKE '%geopolitical%' OR source = 'usgs' AND tags LIKE '%region:Hormuz%'
                     OR source = 'usgs' AND tags LIKE '%region:Iran%')""",
                (cutoff,),
            ).fetchone()
            indicators["geopolitical_severity_count_4plus"] = row["n"] if row else 0
            log.info(f"  ✅ geopolitical_severity_count_4plus: {indicators['geopolitical_severity_count_4plus']}")
    except Exception as e:
        log.warning(f"  ❌ geopolitical: {e}")
        indicators["geopolitical_severity_count_4plus"] = 0

    # ============== 10. 接入新数据源 (P0-12, 2026-07-28) ==============
    # 6 个新 CSV: backtest/{fear_greed, vix_term_structure, gld_price, put_call_ratio, treasury_10y_full, earnings_calendar_nasdaq}
    # 接规则: GOLD_GEOPOL (情绪) / GOLD_CENTRAL_BANK (VIX 远期) / AI_CAPEX (PE ratio proxy)
    try:
        import csv
        from pathlib import Path
        bt = Path('~/.dsh/market_intel/backtest').expanduser()

        # 1. Fear & Greed 30d mean (情绪)
        fng_path = bt / "fear_greed_index_history.csv"
        if fng_path.exists():
            with open(fng_path) as f:
                rows = list(csv.DictReader(f))[-30:]  # 近 30 天
            vals = [int(r["fng_value"]) for r in rows if r["fng_value"]]
            indicators["fng_30d_mean"] = round(sum(vals)/len(vals), 1) if vals else 50
            indicators["fng_latest"] = int(rows[-1]["fng_value"]) if rows else 50
            log.info(f"  ✅ F&G latest={indicators['fng_latest']}, 30d mean={indicators['fng_30d_mean']}")

        # 2. VIX term structure (近 30d contango/backwardation)
        vix_path = bt / "vix_term_structure_10y.csv"
        if vix_path.exists():
            with open(vix_path) as f:
                rows = list(csv.DictReader(f))[-30:]
            spot = [float(r["^VIX"]) for r in rows if r.get("^VIX")]
            vix3m = [float(r["^VIX3M"]) for r in rows if r.get("^VIX3M") and r["^VIX3M"]]
            if spot and vix3m and len(vix3m) >= 10:
                # Contango = VIX3M > VIX (正常), Backwardation = VIX3M < VIX (恐慌)
                avg_spot = sum(spot[-10:]) / len(spot[-10:])
                avg_vix3m = sum(vix3m[-10:]) / len(vix3m[-10:])
                indicators["vix_term_ratio"] = round(avg_vix3m / avg_spot, 3)
                log.info(f"  ✅ VIX term ratio: {indicators['vix_term_ratio']:.2f} (1=flat, >1=contango, <1=backwardation/panic)")
            else:
                indicators["vix_term_ratio"] = 1.0  # 默认正常

        # 3. GLD 价格 5d / 20d 涨跌 (短期 vs 中期)
        gld_path = bt / "gld_price_10y.csv"
        if gld_path.exists():
            with open(gld_path) as f:
                rows = list(csv.DictReader(f))[-30:]
            if len(rows) >= 20:
                cur = float(rows[-1]["GLD_price"])
                d5 = float(rows[-5]["GLD_price"])
                d20 = float(rows[-20]["GLD_price"])
                indicators["gld_5d_chg"] = round((cur - d5) / d5 * 100, 2)
                indicators["gld_20d_chg"] = round((cur - d20) / d20 * 100, 2)
                log.info(f"  ✅ GLD 5d={indicators['gld_5d_chg']}%, 20d={indicators['gld_20d_chg']}%")

        # 4. Put/Call 5d 变动 (情绪反向指标)
        pc_path = bt / "put_call_ratio_10y.csv"
        if pc_path.exists():
            with open(pc_path) as f:
                rows = list(csv.DictReader(f))[-30:]
            if len(rows) >= 5:
                cur = float(rows[-1]["value"])
                avg5 = sum(float(r["value"]) for r in rows[-5:]) / 5
                indicators["put_call_5d_avg"] = round(avg5, 0)
                indicators["put_call_vs_5d"] = round((cur - avg5) / avg5 * 100, 2)  # 异常升高 = 恐慌
                log.info(f"  ✅ P/C 5d avg={avg5:.0f}, today={cur}, dev={indicators['put_call_vs_5d']}%")

        # 5. Treasury 10Y 5d 变化 (实际利率方向)
        try:
            from _lib import safe_get
            # 优先用本地 CSV, FRED 作为 fallback
            t_path = Path('~/.dsh/market_intel/backtest/treasury_10y_full_history.csv').expanduser()
            valid = []
            if t_path.exists():
                with open(t_path) as tcsv:
                    for line in tcsv.readlines()[1:]:
                        parts = line.strip().split(",")
                        if len(parts) >= 2 and parts[1] not in (".", ""):
                            try:
                                valid.append((parts[0], float(parts[1])))
                            except ValueError:
                                continue
            else:
                # 现场拉 FRED
                t_resp = safe_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2025-01-01", headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
                if t_resp and t_resp.text:
                    for line in t_resp.text.strip().split("\n")[1:]:
                        parts = line.split(",")
                        if len(parts) >= 2 and parts[1] not in (".", ""):
                            try:
                                valid.append((parts[0], float(parts[1])))
                            except ValueError:
                                continue
            if len(valid) >= 5:
                cur = valid[-1][1]
                avg5 = sum(v[1] for v in valid[-5:]) / 5
                indicators["dgs10_latest"] = cur
                indicators["dgs10_5d_chg"] = round((cur - avg5) * 100, 1)  # bp
                log.info(f"  ✅ DGS10 latest={cur}%, 5d chg={indicators['dgs10_5d_chg']:.1f}bp")
        except Exception as e:
            log.warning(f"  ❌ DGS10: {e}")
            indicators["dgs10_5d_chg"] = 0

    except Exception as e:
        log.warning(f"  ❌ 新数据源接入: {e}")

    # ============== 10. QQQ 技术面金子指标 (MA20/MA60/MA200 + cross/breakout) ==============
    # 4 条技术面规则 (TECH_*) 需要这些指标 + MA200 gate
    try:
        # 拉 QQQ 280 天 daily data (覆盖 MA200 + 250-day breakout)
        url = "https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range=1y"
        resp = safe_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
            if len(closes) >= 200:
                last = closes[-1]
                prev = closes[-2]
                ma20 = sum(closes[-20:]) / 20
                ma60 = sum(closes[-60:]) / 60
                ma200 = sum(closes[-200:]) / 200
                ma20_prev = sum(closes[-21:-1]) / 20
                ma60_prev = sum(closes[-61:-1]) / 60

                # 4 条技术面指标
                indicators["ma20_cross_above_ma60"] = (ma20 > ma60) and (ma20_prev <= ma60_prev)
                indicators["new_250d_high"] = last > max(closes[-250:-1])
                indicators["above_ma60"] = (last > ma60) and (prev <= ma60)
                mom_20d = (last - closes[-21]) / closes[-21]
                indicators["mom_20d"] = round(mom_20d, 4)
                # MA200 gate (4 条规则共用)
                indicators["qqq_above_ma200"] = last > ma200

                log.info(f"  ✅ QQQ 技术面指标: ma20={ma20:.2f} ma60={ma60:.2f} ma200={ma200:.2f} last={last:.2f}")
                log.info(f"     cross={indicators['ma20_cross_above_ma60']} breakout={indicators['new_250d_high']} above_ma60={indicators['above_ma60']} mom_20d={mom_20d:.2%}")
                log.info(f"     qqq_above_ma200 gate: {indicators['qqq_above_ma200']}")
            else:
                log.warning(f"  ❌ QQQ closes 不足 200 ({len(closes)}), 跳过技术面指标")
    except Exception as e:
        log.warning(f"  ❌ QQQ 技术面指标: {e}")

    log.info(f"\n📊 共拉取 {len(indicators)} 个指标")
    return indicators


def evaluate_all_rules(indicators):
    """跑所有规则"""
    log.info("=" * 60)
    log.info("🎯 规则引擎评估 (今日)")
    log.info("=" * 60)

    triggered = []
    not_triggered = []
    partial = []

    for rule in RULES:
        result = evaluate_rule(rule, indicators)
        if result is True:
            triggered.append(rule)
            target = "/".join(rule["target_codes"])
            log.info(f"  ✅ 触发: {rule['rule_id']:25s} {rule['signal_type']:7s} ({target})")
            log.info(f"     {rule['description'][:80]}")
            log.info(f"     置信度: {rule['confidence']}% | 预期持仓: {rule['hold_days']}天")
        elif result == "PARTIAL":
            partial.append(rule)
            log.info(f"  ⚠️  部分: {rule['rule_id']:25s} 数据缺失")
        else:
            not_triggered.append(rule)

    return triggered, partial, not_triggered


def per_fund_summary(triggered, all_rules):
    """每只基金的最终建议"""
    summary = {}
    # 对每只基金收集所有触发 + 反触发信号
    for code in ["012752", "022653", "025857", "020274"]:
        triggered_rules = [r for r in triggered if code in r["target_codes"]]
        all_targeted = [r for r in all_rules if code in r["target_codes"]]

        # 综合判断
        add_score = sum(r["confidence"] for r in triggered_rules if r["signal_type"] == "add")
        reduce_score = sum(r["confidence"] for r in triggered_rules if r["signal_type"] == "reduce")
        hold_score = sum(r["confidence"] for r in triggered_rules if r["signal_type"] == "hold")

        if reduce_score > add_score and reduce_score > 0:
            action = "reduce"
            emoji = "🟡"
        elif add_score > reduce_score and add_score > 0:
            action = "add"
            emoji = "🟢"
        elif hold_score > 0:
            action = "hold"
            emoji = "🔵"
        elif reduce_score + add_score == 0:
            action = "observe"
            emoji = "⚪"
        else:
            action = "mixed"
            emoji = "🟠"

        summary[code] = {
            "action": action,
            "emoji": emoji,
            "triggered_count": len(triggered_rules),
            "add_score": add_score,
            "reduce_score": reduce_score,
            "hold_score": hold_score,
            "triggered_rules": [r["rule_id"] for r in triggered_rules],
        }

    return summary


def main():
    log.info("=" * 60)
    log.info(f"📅 今日信号评估 - {datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    # 1. 拉指标
    log.info("\n--- 1. 拉指标 ---")
    indicators = fetch_indicators()

    # 2. 跑规则
    log.info("\n--- 2. 跑规则 ---")
    triggered, partial, not_triggered = evaluate_all_rules(indicators)

    # 3. 每只基金汇总
    log.info("\n--- 3. 每只基金汇总 ---")
    summary = per_fund_summary(triggered, RULES)
    for code, s in summary.items():
        log.info(f"\n  {s['emoji']} {code}: {s['action'].upper()}")
        log.info(f"     触发: {s['triggered_count']} 条规则")
        if s["triggered_rules"]:
            log.info(f"     IDs: {s['triggered_rules']}")
        log.info(f"     Score: +{s['add_score']} (add) | -{s['reduce_score']} (reduce) | ={s['hold_score']} (hold)")

    # 4. 输出 JSON 给后续使用
    result = {
        "timestamp": datetime.now(BJT).isoformat(timespec="seconds"),
        "indicators": indicators,
        "triggered_count": len(triggered),
        "partial_count": len(partial),
        "not_triggered_count": len(not_triggered),
        "triggered_rules": [r["rule_id"] for r in triggered],
        "fund_summary": summary,
    }
    output_path = "/tmp/today_signals.json"
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n💾 完整结果保存到 {output_path}")
    log.info(f"\n📋 总览: 触发 {len(triggered)} | 部分 {len(partial)} | 未触发 {len(not_triggered)}")
    return result


if __name__ == "__main__":
    main()

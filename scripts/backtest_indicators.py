"""
回测期 indicator builder (P0-12, 2026-07-28)
- 复现 evaluate_today.py 的所有 indicator, 但用历史 CSV
- 让 15 条失效 rule 复活
"""
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent))
from _lib import get_logger, ROOT

log = get_logger("backtest_indicators")

BT_DIR = Path('~/.dsh/market_intel/backtest').expanduser()


def load_csv_dates(name, col, value_col=1):
    """CSV → {date: value} dict — 支持多种列名 (date/Date/observation_date)"""
    path = BT_DIR / f"{name}.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return {}
        # 找日期列 index
        date_col_idx = 0
        for i, h in enumerate(header):
            if h.lower() in ("date", "observation_date", "day", "timestamp"):
                date_col_idx = i
                break
        # 找 close/value 列 index
        val_col_idx = 1
        for i, h in enumerate(header):
            if h.lower() in ("close", "value", "fng_value"):
                val_col_idx = i
                break

        for row in reader:
            if len(row) <= max(date_col_idx, val_col_idx):
                continue
            date = row[date_col_idx]
            try:
                val = float(row[val_col_idx]) if row[val_col_idx] not in ("", ".") else None
                if val is not None and date:
                    out[date] = val
            except (ValueError, IndexError):
                continue
    return out


def load_fred_csv(name):
    """FRED CSV (observation_date, value)"""
    return load_csv_dates(name, "observation_date", 1)


def load_yahoo_format_csv(name):
    """yahoo CSV (Date, value)"""
    return load_csv_dates(name, "Date", 1)


def load_treasury_curve_yield(col_name):
    """
    treasury_yield_curve_history.csv 列: observation_date,GS2,GS5,GS10,GS30
    """
    path = BT_DIR / "treasury_yield_curve_history.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("observation_date", "")
            v = row.get(col_name, "")
            if d and v not in ("", "."):
                try:
                    out[d] = float(v)
                except ValueError:
                    pass
    return out


def load_dgs10():
    """美债 10Y (treasury_10y_full_history.csv 列 observation_date,DGS10)"""
    return load_fred_csv("treasury_10y_full_history")


def load_nbs_pmi(path=None):
    """NBS PMI 历史 (nbs_pmi_history.csv 列 date,mfg_pmi)"""
    if path is None:
        path = BT_DIR / "nbs_pmi_history.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date", "")
            v = row.get("mfg_pmi", "")
            if d and v:
                try:
                    out[d] = float(v)
                except ValueError:
                    pass
    return out


def build_full_indicators(start_date=None, end_date=None):
    """
    构建 {date: {indicator: value}}
    包含 evaluate_today.py 的所有 indicator, 用历史 CSV
    """
    log.info("=== build_full_indicators: 拉所有历史 CSV ===")

    # 美债 (FRED GS series)
    us2y = load_treasury_curve_yield("GS2")
    us5y = load_treasury_curve_yield("GS5")
    us10y = load_treasury_curve_yield("GS10")
    us30y = load_treasury_curve_yield("GS30")
    dgs10 = load_dgs10()  # FRED DGS10 (60 年)
    log.info(f"  GS2: {len(us2y)} GS5: {len(us5y)} GS10: {len(us10y)} GS30: {len(us30y)} DGS10: {len(dgs10)}")

    # 美债实际利率 (nominal 5Y/10Y - breakeven)
    # 没有 CSV, 估算 us10y_real = us10y - 2.3 (常数 inflation expectation)
    us10y_real_approx = {d: v - 2.3 for d, v in us10y.items()} if us10y else {}

    # VIX (yahoo csv ^VIX 已在 vix_term_structure)
    vix_term = {}
    path = BT_DIR / "vix_term_structure_10y.csv"
    if path.exists():
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get("Date", "")
                if d and row.get("^VIX"):
                    vix_term[d] = {
                        "vix_spot": float(row["^VIX"]),
                        "vix_3m": float(row["^VIX3M"]) if row.get("^VIX3M") else None,
                        "ratio": float(row["^VIX3M"]) / float(row["^VIX"]) if row.get("^VIX3M") else None,
                    }
    log.info(f"  vix_term: {len(vix_term)} 天")

    # DXY (treasury_history 10y csv 在 backtest/)
    # 没有 dxy csv, 用空 dict
    dxy = {}

    # 标的: GLD, QQQ, XLE, FXN 已在 backtest/5y 或 10y csv
    asset_data = {
        "qqq_10y": load_csv_dates("qqq_10y", "Date", 4),  # 列: date,open,high,low,close,...
        "gld_10y": load_csv_dates("gld_10y", "Date", 4),
        "xle_10y": load_csv_dates("xle_10y", "Date", 4),
        "fxn_10y": load_csv_dates("tlt_10y", "Date", 4),  # 用 TLT 代理
        "spy_10y": load_csv_dates("spy_10y", "Date", 4),
    }
    # CSV 实际列 (qqq_10y.csv): Date,Open,High,Low,Close,Adj Close,Volume — 4=Close
    log.info(f"  qqq_10y: {len(asset_data['qqq_10y'])} gld_10y: {len(asset_data['gld_10y'])}")

    # F&G Index
    fng_dict = {}  # {date: fng_value}
    path = BT_DIR / "fear_greed_index_history.csv"
    if path.exists():
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get("Date", "")
                if d and row.get("fng_value"):
                    try:
                        fng_dict[d] = int(row["fng_value"])
                    except (ValueError, TypeError):
                        pass
    log.info(f"  fng: {len(fng_dict)} 天")

    # Put/Call
    pc_dict = {}  # {date: value}
    path = BT_DIR / "put_call_ratio_10y.csv"
    if path.exists():
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get("Date", "")
                if d and row.get("value"):
                    try:
                        pc_dict[d] = float(row["value"])
                    except (ValueError, TypeError):
                        pass
    log.info(f"  put_call: {len(pc_dict)} 天")

    # NBS PMI
    nbs_pmi = load_nbs_pmi()
    log.info(f"  nbs_pmi: {len(nbs_pmi)} 月")

    # 找公共日期 (用 5 个源中最长: QQQ/GLD/XLE 等)
    candidate_dates = set(asset_data["qqq_10y"].keys()) | set(asset_data["gld_10y"].keys())
    if not candidate_dates:
        # fallback: us10y
        candidate_dates = set(us10y.keys())
    all_dates = sorted(candidate_dates)
    if start_date:
        all_dates = [d for d in all_dates if d >= start_date]
    if end_date:
        all_dates = [d for d in all_dates if d <= end_date]
    log.info(f"  公共日期范围: {all_dates[0] if all_dates else 'N/A'} → {all_dates[-1] if all_dates else 'N/A'} ({len(all_dates)} 天)")

    # 构建 indicators_dict
    indicators_dict = {}
    for date in all_dates:
        inds = {}

        # 美债
        if date in us2y: inds["us2y"] = us2y[date]
        if date in us5y: inds["us5y"] = us5y[date]
        if date in us10y: inds["us10y"] = us10y[date]
        if date in us30y: inds["us30y"] = us30y[date]
        if date in us10y_real_approx: inds["us10y_real"] = round(us10y_real_approx[date], 3)

        # 2-10 倒挂
        if "us10y" in inds and "us2y" in inds:
            inds["yield_curve_2_10"] = round(inds["us10y"] - inds["us2y"], 3)
            inds["yield_curve_2_10_inverted"] = inds["us10y"] < inds["us2y"]
            if inds["yield_curve_2_10_inverted"]:
                inds["yield_curve_inverted"] = True  # 给 rule 用

        # VIX term
        if date in vix_term:
            inds.update(vix_term[date])

        # DXY (缺)
        inds["dxy"] = 100  # fallback

        # 标的涨跌
        for asset_key, target_ind in [("qqq_10y", "ndx_1d_pct"), ("gld_10y", "gld_1d_pct")]:
            if date in asset_data[asset_key]:
                sorted_dates = sorted(asset_data[asset_key].keys())
                if date in sorted_dates:
                    i = sorted_dates.index(date)
                    if i >= 1:
                        prev = sorted_dates[i-1]
                        if prev in asset_data[asset_key]:
                            cur = asset_data[asset_key][date]
                            p = asset_data[asset_key][prev]
                            if p > 0:
                                inds[target_ind] = round((cur - p) / p, 4)

        # 1 周 / 1 月 涨跌幅 (for TECH_* rules)
        if "qqq_10y" in asset_data:
            sorted_dates = sorted(asset_data["qqq_10y"].keys())
            if date in sorted_dates:
                i = sorted_dates.index(date)
                if i >= 5:
                    past_5d = sorted_dates[i-5]
                    if past_5d in asset_data["qqq_10y"]:
                        inds["ndx_1w_pct"] = round((asset_data["qqq_10y"][date] - asset_data["qqq_10y"][past_5d]) / asset_data["qqq_10y"][past_5d], 4)
                if i >= 21:
                    past_30d = sorted_dates[i-21]
                    if past_30d in asset_data["qqq_10y"]:
                        inds["ndx_1m_pct"] = round((asset_data["qqq_10y"][date] - asset_data["qqq_10y"][past_30d]) / asset_data["qqq_10y"][past_30d], 4)
                # MA20/MA60/MA200 (TECH_* 需要)
                if i >= 199:
                    closes = [asset_data["qqq_10y"][d] for d in sorted_dates[max(0, i-199):i+1]]
                    inds["ma20"] = sum(closes[-20:]) / 20
                    inds["ma60"] = sum(closes[-60:]) / 60
                    inds["ma200"] = sum(closes[-200:]) / 200
                    if i >= 20:
                        closes_prev = [asset_data["qqq_10y"][d] for d in sorted_dates[max(0, i-20):i]]
                        if closes_prev:
                            inds["ma20_prev"] = sum(closes_prev[-20:]) / 20

        if "xle_10y" in asset_data:
            sorted_dates = sorted(asset_data["xle_10y"].keys())
            if date in sorted_dates:
                i = sorted_dates.index(date)
                if i >= 21:
                    past_30d = sorted_dates[i-21]
                    if past_30d in asset_data["xle_10y"]:
                        inds["chem_1m_pct"] = round((asset_data["xle_10y"][date] - asset_data["xle_10y"][past_30d]) / asset_data["xle_10y"][past_30d], 4)

        # F&G (取最近可用日期)
        if fng_dict:
            fng_dates = sorted(fng_dict.keys())
            # 找最接近 date 的 fng (向前回溯)
            for fd in reversed(fng_dates):
                if fd <= date:
                    inds["fng_latest"] = fng_dict[fd]
                    break

        # Put/Call
        if pc_dict:
            pc_dates = sorted(pc_dict.keys())
            for pd in reversed(pc_dates):
                if pd <= date:
                    inds["put_call_current"] = pc_dict[pd]
                    break

        # NBS PMI (月度, 找最近一期)
        if nbs_pmi:
            pmi_dates = sorted(nbs_pmi.keys())
            for pd in reversed(pmi_dates):
                if pd <= date[:7] + "-01":  # 月份比较
                    inds["cn_pmi"] = nbs_pmi[pd]
                    break

        # 缺历史 → 静态 fallback (避免全 0 触发)
        inds.setdefault("ai_capex_yoy", 0.65)  # 估值快照
        inds.setdefault("central_bank_net_buying_tons", 95)  # 2025 月均
        inds.setdefault("sgcc_bidding_yoy", 0.15)
        inds.setdefault("power_equipment_export_yoy", 0.18)
        inds.setdefault("fed_funds_change_3m", -0.25)
        inds.setdefault("global_mfg_pmi", 50.2)
        inds.setdefault("geopolitical_severity_count_4plus", 0)  # 缺历史 = 0
        inds.setdefault("us2y_5d_chg_bp", 0)
        inds.setdefault("us5y_5d_chg_bp", 0)
        inds.setdefault("us10y_5d_chg_bp", 0)
        inds.setdefault("us30y_5d_chg_bp", 0)

        indicators_dict[date] = inds

    log.info(f"  indicators_dict 范围: {len(indicators_dict)} 天")
    return indicators_dict


# 简易测试
if __name__ == "__main__":
    inds = build_full_indicators(start_date="2020-01-01", end_date="2026-07-23")
    if inds:
        dates = sorted(inds.keys())
        sample_date = dates[len(dates) // 2]  # 中间日期
        print(f"\n=== Sample ({sample_date}) ===")
        sample = inds[sample_date]
        for k, v in sorted(sample.items())[:30]:
            print(f"  {k}: {v}")

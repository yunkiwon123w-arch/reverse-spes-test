# -*- coding: utf-8 -*-
"""
RS20 PROGRAM_FLOW v1.1 Stability / Regime Audit
================================================

PURPOSE
Audit whether the PROGRAM_FLOW relationships found in v1 are stable across:
- calendar month
- market (ALL / KOSPI / KOSDAQ)
- chronological TRAIN70 / HOLDOUT30
- traded-value regime
- pre-entry 30-minute price-range regime
- stock concentration

This script DOES NOT search for a new optimum threshold.
It reuses TRAIN quartile cutpoints already frozen in:
  rs20_program_flow_predictive_holdout_v1.csv

PRIMARY FEATURES
- pf_net_amt_0
- pf_irds_sum_m5_0
- pf_net_amt_delta_m10_0
- pf_net_amt_delta_m5_0

NO KIWOOM API.
NO ORDER API.
NO source-rule changes.
"""

import csv
import gzip
import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ALIGNED_FILE = "rs20_program_flow_aligned_features_v1.csv"
HOLDOUT_FILE = "rs20_program_flow_predictive_holdout_v1.csv"
BIAS_FILE = "rs20_program_flow_coverage_bias_event_level_v1.csv"

MINUTE_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")

OUT_ENRICHED = "rs20_program_flow_stability_enriched_events_v1_1.csv"
OUT_MONTHLY = "rs20_program_flow_stability_monthly_v1_1.csv"
OUT_REGIME = "rs20_program_flow_stability_regime_v1_1.csv"
OUT_CONCENTRATION = "rs20_program_flow_stability_stock_concentration_v1_1.csv"
OUT_SCORECARD = "rs20_program_flow_stability_scorecard_v1_1.csv"
OUT_SUMMARY = "rs20_program_flow_stability_summary_v1_1.txt"

FEATURES = [
    "pf_net_amt_0",
    "pf_irds_sum_m5_0",
    "pf_net_amt_delta_m10_0",
    "pf_net_amt_delta_m5_0",
]

CONT_OUTCOMES = ["mfe_pct", "mae_pct", "eod_return_pct"]
BIN_OUTCOMES = ["hit_up_3", "hit_up_5", "hit_up_10",
                "hit_dn_1", "hit_dn_2", "hit_dn_3", "eod_positive"]


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def sf(v):
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", "").replace("+", "")
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def norm_code(v):
    s = str(v or "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def key_of(row):
    return norm_code(row.get("stock_code", "")), str(row.get("trade_date", "")).strip()


def pct(n, d):
    return n / d * 100.0 if d else 0.0


def rankdata(values):
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def pearson(x, y):
    if len(x) < 3 or len(x) != len(y):
        return None
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def spearman(x, y):
    if len(x) < 3:
        return None
    return pearson(rankdata(x), rankdata(y))


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    f = pos - lo
    return sorted_vals[lo] * (1 - f) + sorted_vals[hi] * f


def quartile_breaks(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None, None, None
    return quantile(vals, 0.25), quantile(vals, 0.50), quantile(vals, 0.75)


def assign_q(v, q1, q2, q3):
    if v is None or q1 is None:
        return ""
    if v <= q1:
        return "Q1"
    if v <= q2:
        return "Q2"
    if v <= q3:
        return "Q3"
    return "Q4"


def parse_touch_time(row):
    s = str(row.get("event_touch_time", "")).strip()
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) >= 14:
        try:
            return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        except Exception:
            return None
    return None


class MinuteCache:
    def __init__(self, base):
        self.base = base
        self.mem = {}

    def load_stock(self, code):
        if code in self.mem:
            return self.mem[code]

        path = self.base / MINUTE_CACHE_ROOT / f"{code}.csv.gz"
        rows = []

        if path.exists():
            try:
                with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
                    for r in csv.DictReader(f):
                        tm = str(r.get("cntr_tm", "")).strip()
                        if len(tm) != 14 or not tm.isdigit():
                            continue
                        try:
                            ts = datetime.strptime(tm, "%Y%m%d%H%M%S")
                            high = abs(float(str(r.get("high_pric", "")).replace(",", "").replace("+", "")))
                            low = abs(float(str(r.get("low_pric", "")).replace(",", "").replace("+", "")))
                            close = abs(float(str(r.get("cur_prc", "")).replace(",", "").replace("+", "")))
                        except Exception:
                            continue
                        rows.append((ts, high, low, close))
            except Exception:
                rows = []

        rows.sort(key=lambda x: x[0])
        self.mem[code] = rows
        return rows

    def pre30_range_pct(self, code, touch_dt):
        rows = self.load_stock(code)
        if not rows:
            return None

        times = [x[0] for x in rows]
        start = touch_dt - timedelta(minutes=30)
        i = bisect_left(times, start)
        j = bisect_right(times, touch_dt)

        window = rows[i:j]
        if not window:
            return None

        highs = [x[1] for x in window if x[1] > 0]
        lows = [x[2] for x in window if x[2] > 0]
        closes = [x[3] for x in window if x[3] > 0]
        if not highs or not lows or not closes:
            return None

        lo = min(lows)
        hi = max(highs)
        ref = closes[0]
        if ref <= 0:
            return None

        return (hi - lo) / ref * 100.0


def load_train_quartiles(rows):
    """
    predictive_holdout_v1 repeats train_q1/q2/q3 on each row.
    Freeze one tuple per market+feature.
    """
    out = {}
    for r in rows:
        market = str(r.get("market", "")).strip().upper()
        feature = str(r.get("feature", "")).strip()
        if feature not in FEATURES:
            continue
        q1, q2, q3 = sf(r.get("train_q1")), sf(r.get("train_q2")), sf(r.get("train_q3"))
        if q1 is None or q2 is None or q3 is None:
            continue
        out[(market, feature)] = (q1, q2, q3)
    return out


def chrono_split(rows):
    rr = sorted(rows, key=lambda r: (r["trade_date"], r["event_touch_time"], r["stock_code"]))
    if len(rr) <= 1:
        return rr, []
    cut = int(len(rr) * 0.70)
    cut = max(1, min(cut, len(rr)-1))
    return rr[:cut], rr[cut:]


def summarize_bucket(rows):
    out = {"n": len(rows)}
    for f in CONT_OUTCOMES:
        vv = [sf(r.get(f)) for r in rows]
        vv = [v for v in vv if v is not None]
        out[f"{f}_mean"] = mean(vv) if vv else ""
        out[f"{f}_median"] = median(vv) if vv else ""
    for f in BIN_OUTCOMES:
        vv = [sf(r.get(f)) for r in rows]
        vv = [v for v in vv if v is not None]
        out[f"{f}_pct"] = pct(sum(1 for v in vv if v > 0), len(vv))
    return out


def main():
    base = Path(__file__).resolve().parent

    for fn in [ALIGNED_FILE, HOLDOUT_FILE, BIAS_FILE]:
        if not (base / fn).exists():
            raise SystemExit(f"REQUIRED FILE NOT FOUND: {fn}")

    aligned = read_csv(base / ALIGNED_FILE)
    holdout_rows = read_csv(base / HOLDOUT_FILE)
    bias = read_csv(base / BIAS_FILE)

    bias_idx = {key_of(r): r for r in bias}
    frozen_q = load_train_quartiles(holdout_rows)

    minute_cache = MinuteCache(base)

    enriched = []
    for i, r in enumerate(aligned, 1):
        rr = dict(r)
        code, dt = key_of(rr)
        b = bias_idx.get((code, dt), {})

        rr["stock_code"] = code
        rr["trade_date"] = dt
        rr["month"] = dt[:6] if len(dt) >= 6 else ""
        rr["year"] = dt[:4] if len(dt) >= 4 else ""

        # Existing descriptive/non-leaky event metadata from bias file.
        rr["turnover_eok"] = b.get("turnover_eok", "")
        rr["m_value_eok"] = b.get("m_value_eok", "")
        rr["m_ratio_pct"] = b.get("m_ratio_pct", "")

        touch_dt = parse_touch_time(rr)
        vol = minute_cache.pre30_range_pct(code, touch_dt) if touch_dt else None
        rr["pre30_price_range_pct"] = "" if vol is None else vol

        enriched.append(rr)

        if i % 50 == 0 or i == len(aligned):
            print(f"ENRICH {i:03d}/{len(aligned)}")

    # TRAIN/HOLDOUT tag within each market and globally.
    split_tags = {}
    for market_name, group in [
        ("ALL", enriched),
        ("KOSPI", [r for r in enriched if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in enriched if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]:
        tr, ho = chrono_split(group)
        for r in tr:
            split_tags[(market_name, r["stock_code"], r["trade_date"])] = "TRAIN70"
        for r in ho:
            split_tags[(market_name, r["stock_code"], r["trade_date"])] = "HOLDOUT30"

    # Predeclare regimes from TRAIN only within each market.
    regime_breaks = {}
    for market_name, group in [
        ("ALL", enriched),
        ("KOSPI", [r for r in enriched if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in enriched if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]:
        tr, _ = chrono_split(group)
        for field in ["turnover_eok", "pre30_price_range_pct"]:
            vv = [sf(r.get(field)) for r in tr]
            vv = [v for v in vv if v is not None]
            regime_breaks[(market_name, field)] = quartile_breaks(vv)

    # Output enriched event rows with split and regime labels.
    for r in enriched:
        market = str(r.get("market", "")).upper()
        for market_name in ["ALL", market]:
            r[f"split_{market_name.lower()}"] = split_tags.get(
                (market_name, r["stock_code"], r["trade_date"]), ""
            )

        for market_name in ["ALL", market]:
            for field in ["turnover_eok", "pre30_price_range_pct"]:
                qs = regime_breaks.get((market_name, field), (None, None, None))
                label = "turnover" if field == "turnover_eok" else "pre30_vol"
                r[f"{label}_quartile_{market_name.lower()}"] = assign_q(
                    sf(r.get(field)), *qs
                )

    # Monthly stability: frozen TRAIN quartiles from v1.
    monthly_rows = []
    for market_name, group in [
        ("ALL", enriched),
        ("KOSPI", [r for r in enriched if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in enriched if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]:
        for feature in FEATURES:
            q = frozen_q.get((market_name, feature))
            if not q:
                continue

            months = defaultdict(list)
            for r in group:
                months[r["month"]].append(r)

            for month, rr in sorted(months.items()):
                valid = [(sf(r.get(feature)), r) for r in rr]
                valid = [(v, r) for v, r in valid if v is not None]
                if not valid:
                    continue

                xs = [v for v, _ in valid]
                mfe = [sf(r.get("mfe_pct")) for _, r in valid]
                pairs = [(x, y) for x, y in zip(xs, mfe) if y is not None]
                rho = spearman(
                    [x for x, _ in pairs],
                    [y for _, y in pairs]
                ) if pairs else None

                buckets = defaultdict(list)
                for v, r in valid:
                    buckets[assign_q(v, *q)].append(r)

                q1s = summarize_bucket(buckets.get("Q1", []))
                q4s = summarize_bucket(buckets.get("Q4", []))

                monthly_rows.append({
                    "market": market_name,
                    "feature": feature,
                    "month": month,
                    "n": len(valid),
                    "spearman_mfe": "" if rho is None else rho,
                    "q1_n": q1s["n"],
                    "q1_mfe_median": q1s["mfe_pct_median"],
                    "q1_eod_median": q1s["eod_return_pct_median"],
                    "q1_up5_pct": q1s["hit_up_5_pct"],
                    "q4_n": q4s["n"],
                    "q4_mfe_median": q4s["mfe_pct_median"],
                    "q4_eod_median": q4s["eod_return_pct_median"],
                    "q4_up5_pct": q4s["hit_up_5_pct"],
                    "q1_minus_q4_mfe_median": (
                        q1s["mfe_pct_median"] - q4s["mfe_pct_median"]
                        if q1s["mfe_pct_median"] != "" and q4s["mfe_pct_median"] != ""
                        else ""
                    ),
                })

    # Regime audit: turnover and pre-entry volatility quartiles frozen from TRAIN.
    regime_rows = []
    for market_name, group in [
        ("ALL", enriched),
        ("KOSPI", [r for r in enriched if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in enriched if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]:
        tr, ho = chrono_split(group)

        for feature in FEATURES:
            qf = frozen_q.get((market_name, feature))
            if not qf:
                continue

            for regime_field in ["turnover_eok", "pre30_price_range_pct"]:
                qreg = regime_breaks.get((market_name, regime_field))
                if not qreg or qreg[0] is None:
                    continue

                for split_name, split_rows in [("TRAIN70", tr), ("HOLDOUT30", ho)]:
                    for rq in ["Q1", "Q2", "Q3", "Q4"]:
                        subset = [
                            r for r in split_rows
                            if assign_q(sf(r.get(regime_field)), *qreg) == rq
                        ]
                        valid = [(sf(r.get(feature)), r) for r in subset]
                        valid = [(v, r) for v, r in valid if v is not None]
                        if not valid:
                            continue

                        buckets = defaultdict(list)
                        for v, r in valid:
                            buckets[assign_q(v, *qf)].append(r)

                        q1s = summarize_bucket(buckets.get("Q1", []))
                        q4s = summarize_bucket(buckets.get("Q4", []))

                        xs, ys = [], []
                        for v, r in valid:
                            y = sf(r.get("mfe_pct"))
                            if y is not None:
                                xs.append(v); ys.append(y)
                        rho = spearman(xs, ys)

                        regime_rows.append({
                            "market": market_name,
                            "split": split_name,
                            "feature": feature,
                            "regime_field": regime_field,
                            "regime_quartile": rq,
                            "n": len(valid),
                            "spearman_mfe": "" if rho is None else rho,
                            "q1_n": q1s["n"],
                            "q1_mfe_median": q1s["mfe_pct_median"],
                            "q1_eod_median": q1s["eod_return_pct_median"],
                            "q1_up5_pct": q1s["hit_up_5_pct"],
                            "q4_n": q4s["n"],
                            "q4_mfe_median": q4s["mfe_pct_median"],
                            "q4_eod_median": q4s["eod_return_pct_median"],
                            "q4_up5_pct": q4s["hit_up_5_pct"],
                        })

    # Stock concentration for the most interesting v1 feature: pf_net_amt_0.
    concentration_rows = []
    for market_name, group in [
        ("ALL", enriched),
        ("KOSPI", [r for r in enriched if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in enriched if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]:
        feature = "pf_net_amt_0"
        q = frozen_q.get((market_name, feature))
        if not q:
            continue

        tr, ho = chrono_split(group)
        for split_name, split_rows in [("TRAIN70", tr), ("HOLDOUT30", ho)]:
            q1 = [r for r in split_rows if assign_q(sf(r.get(feature)), *q) == "Q1"]
            stock_counts = Counter(r["stock_code"] for r in q1)

            total = len(q1)
            unique = len(stock_counts)
            top1 = stock_counts.most_common(1)[0][1] if stock_counts else 0
            top3 = sum(v for _, v in stock_counts.most_common(3))
            top5 = sum(v for _, v in stock_counts.most_common(5))

            concentration_rows.append({
                "market": market_name,
                "split": split_name,
                "feature": feature,
                "q1_n": total,
                "q1_unique_stocks": unique,
                "top1_stock_share_pct": pct(top1, total),
                "top3_stock_share_pct": pct(top3, total),
                "top5_stock_share_pct": pct(top5, total),
                "top_stocks": ";".join(f"{k}:{v}" for k, v in stock_counts.most_common(10)),
            })

    # Scorecard: direction consistency only, no threshold optimization.
    score_rows = []
    for market_name, group in [
        ("ALL", enriched),
        ("KOSPI", [r for r in enriched if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in enriched if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]:
        tr, ho = chrono_split(group)

        for feature in FEATURES:
            q = frozen_q.get((market_name, feature))
            if not q:
                continue

            def stats(rows):
                valid = [(sf(r.get(feature)), r) for r in rows]
                valid = [(v, r) for v, r in valid if v is not None]

                xs, ys = [], []
                for v, r in valid:
                    y = sf(r.get("mfe_pct"))
                    if y is not None:
                        xs.append(v); ys.append(y)
                rho = spearman(xs, ys)

                b = defaultdict(list)
                for v, r in valid:
                    b[assign_q(v, *q)].append(r)
                q1s = summarize_bucket(b.get("Q1", []))
                q4s = summarize_bucket(b.get("Q4", []))
                return {
                    "n": len(valid),
                    "rho": rho,
                    "q1_n": q1s["n"], "q4_n": q4s["n"],
                    "q1_mfe": q1s["mfe_pct_median"],
                    "q4_mfe": q4s["mfe_pct_median"],
                    "q1_eod": q1s["eod_return_pct_median"],
                    "q4_eod": q4s["eod_return_pct_median"],
                    "q1_up5": q1s["hit_up_5_pct"],
                    "q4_up5": q4s["hit_up_5_pct"],
                }

            a, b = stats(tr), stats(ho)

            train_dir = None if a["rho"] is None else (1 if a["rho"] > 0 else (-1 if a["rho"] < 0 else 0))
            hold_dir = None if b["rho"] is None else (1 if b["rho"] > 0 else (-1 if b["rho"] < 0 else 0))
            same_dir = (
                train_dir == hold_dir and train_dir not in (None, 0)
            )

            score_rows.append({
                "market": market_name,
                "feature": feature,
                "train_n": a["n"],
                "holdout_n": b["n"],
                "train_spearman_mfe": "" if a["rho"] is None else a["rho"],
                "holdout_spearman_mfe": "" if b["rho"] is None else b["rho"],
                "same_spearman_direction": int(same_dir),
                "train_q1_n": a["q1_n"],
                "train_q4_n": a["q4_n"],
                "holdout_q1_n": b["q1_n"],
                "holdout_q4_n": b["q4_n"],
                "train_q1_minus_q4_mfe": (
                    a["q1_mfe"] - a["q4_mfe"]
                    if a["q1_mfe"] != "" and a["q4_mfe"] != "" else ""
                ),
                "holdout_q1_minus_q4_mfe": (
                    b["q1_mfe"] - b["q4_mfe"]
                    if b["q1_mfe"] != "" and b["q4_mfe"] != "" else ""
                ),
                "train_q1_minus_q4_eod": (
                    a["q1_eod"] - a["q4_eod"]
                    if a["q1_eod"] != "" and a["q4_eod"] != "" else ""
                ),
                "holdout_q1_minus_q4_eod": (
                    b["q1_eod"] - b["q4_eod"]
                    if b["q1_eod"] != "" and b["q4_eod"] != "" else ""
                ),
                "train_q1_minus_q4_up5_pp": (
                    a["q1_up5"] - a["q4_up5"]
                    if a["q1_up5"] != "" and a["q4_up5"] != "" else ""
                ),
                "holdout_q1_minus_q4_up5_pp": (
                    b["q1_up5"] - b["q4_up5"]
                    if b["q1_up5"] != "" and b["q4_up5"] != "" else ""
                ),
            })

    # Write files.
    enriched_fields = list(dict.fromkeys(
        list(enriched[0].keys())
        if enriched else []
    ))
    write_csv(base / OUT_ENRICHED, enriched_fields, enriched)

    write_csv(base / OUT_MONTHLY, [
        "market","feature","month","n","spearman_mfe",
        "q1_n","q1_mfe_median","q1_eod_median","q1_up5_pct",
        "q4_n","q4_mfe_median","q4_eod_median","q4_up5_pct",
        "q1_minus_q4_mfe_median"
    ], monthly_rows)

    write_csv(base / OUT_REGIME, [
        "market","split","feature","regime_field","regime_quartile","n","spearman_mfe",
        "q1_n","q1_mfe_median","q1_eod_median","q1_up5_pct",
        "q4_n","q4_mfe_median","q4_eod_median","q4_up5_pct"
    ], regime_rows)

    write_csv(base / OUT_CONCENTRATION, [
        "market","split","feature","q1_n","q1_unique_stocks",
        "top1_stock_share_pct","top3_stock_share_pct","top5_stock_share_pct","top_stocks"
    ], concentration_rows)

    write_csv(base / OUT_SCORECARD, [
        "market","feature","train_n","holdout_n",
        "train_spearman_mfe","holdout_spearman_mfe","same_spearman_direction",
        "train_q1_n","train_q4_n","holdout_q1_n","holdout_q4_n",
        "train_q1_minus_q4_mfe","holdout_q1_minus_q4_mfe",
        "train_q1_minus_q4_eod","holdout_q1_minus_q4_eod",
        "train_q1_minus_q4_up5_pp","holdout_q1_minus_q4_up5_pp"
    ], score_rows)

    # Summary
    lines = [
        "RS20 PROGRAM_FLOW v1.1 Stability / Regime Audit",
        "",
        f"aligned_events: {len(enriched)}",
        f"features: {FEATURES}",
        "",
        "MARKET COUNTS",
    ]
    for m in ["ALL", "KOSPI", "KOSDAQ"]:
        if m == "ALL":
            g = enriched
        else:
            g = [r for r in enriched if str(r.get("market", "")).upper() == m]
        tr, ho = chrono_split(g)
        lines.append(f"- {m}: total={len(g)}, TRAIN70={len(tr)}, HOLDOUT30={len(ho)}")

    lines += [
        "",
        "PRIMARY QUESTION",
        "- Are v1 PROGRAM_FLOW effects stable by month, market, turnover, pre-entry volatility, and stock concentration?",
        "",
        "IMPORTANT",
        "- TRAIN quartile cutpoints are reused from v1 predictive study.",
        "- No new optimum threshold is searched.",
        "- Turnover and pre-entry-volatility regime quartiles are frozen from TRAIN only.",
        "- Pre-entry volatility = 30-minute high-low range / first close in that window.",
        "- Stock concentration checks whether Q1 effect is dominated by a few names.",
        "- No result here changes the frozen RS20 source rules.",
        "- NO Kiwoom API / NO order API.",
        "",
        f"enriched_output: {OUT_ENRICHED}",
        f"monthly_output: {OUT_MONTHLY}",
        f"regime_output: {OUT_REGIME}",
        f"concentration_output: {OUT_CONCENTRATION}",
        f"scorecard_output: {OUT_SCORECARD}",
    ]
    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 100)
    print("RS20 PROGRAM_FLOW v1.1 STABILITY / REGIME AUDIT")
    print(f"ALIGNED EVENTS           : {len(enriched):,}")
    print(f"MONTHLY ROWS             : {len(monthly_rows):,}")
    print(f"REGIME ROWS              : {len(regime_rows):,}")
    print(f"CONCENTRATION ROWS       : {len(concentration_rows):,}")
    print(f"SCORECARD ROWS           : {len(score_rows):,}")
    print(f"MONTHLY FILE             : {OUT_MONTHLY}")
    print(f"REGIME FILE              : {OUT_REGIME}")
    print(f"CONCENTRATION FILE       : {OUT_CONCENTRATION}")
    print(f"SCORECARD FILE           : {OUT_SCORECARD}")
    print(f"SUMMARY                  : {OUT_SUMMARY}")
    print("NO Kiwoom API / NO order API")
    print("=" * 100)


if __name__ == "__main__":
    main()

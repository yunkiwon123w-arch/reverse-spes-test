# -*- coding: utf-8 -*-
"""
RS20 PROGRAM_FLOW Alignment / Predictive Study v1
=================================================

PURPOSE
- Align already-cached Kiwoom ka90008 program-trading data to each RS20
  first exact Reverse-38 touch.
- Use only pre-entry / entry-time information for entry predictive tests.
- Keep post-entry windows separate as descriptive path-management research.
- Split ALL / KOSPI / KOSDAQ.
- Use chronological TRAIN70 / HOLDOUT30.
- Do NOT modify frozen RS20 source rules.

NO KIWOOM API.
NO ORDER API.

REQUIRED INPUTS
- rs20_program_flow_coverage_bias_event_level_v1.csv
- rs20_post_entry_path_diagnostic_v1.csv
- common_market_data/program_flow_ka90008_v1/YYYY/MM/<stock>_<date>.csv.gz

OPTIONAL
- rs20_source_event_state_machine_candidate_summary_v1_2.csv
  Used only if exact-touch time is missing from the bias event file.

DESIGN PRINCIPLES
1) Causal entry study:
   only -30/-10/-5/-3/-1/0 minute features are eligible.
2) Post-entry +1/+3/+5/+10/+30 are recorded separately and never used to
   claim entry predictiveness.
3) No hand-picked threshold.
   TRAIN quartiles are frozen and then applied to HOLDOUT.
4) ALL, KOSPI, KOSDAQ are reported separately because Coverage/Bias Audit
   showed strong market-composition differences.
5) No source-rule change is made by this script.
"""

import csv
import gzip
import math
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

BIAS_FILE = "rs20_program_flow_coverage_bias_event_level_v1.csv"
PATH_FILE = "rs20_post_entry_path_diagnostic_v1.csv"
EVENT_FILE = "rs20_source_event_state_machine_candidate_summary_v1_2.csv"
CACHE_ROOT = Path("common_market_data/program_flow_ka90008_v1")

OUT_ALIGNED = "rs20_program_flow_aligned_features_v1.csv"
OUT_FEATURE_STUDY = "rs20_program_flow_predictive_feature_study_v1.csv"
OUT_HOLDOUT = "rs20_program_flow_predictive_holdout_v1.csv"
OUT_POST = "rs20_program_flow_post_entry_descriptive_v1.csv"
OUT_SUMMARY = "rs20_program_flow_alignment_predictive_summary_v1.txt"

PRE_WINDOWS = [-30, -10, -5, -3, -1, 0]
POST_WINDOWS = [1, 3, 5, 10, 30]

# Predeclared causal entry features. No later tuning in this v1.
CAUSAL_FEATURES = [
    "pf_net_amt_0",
    "pf_imbalance_0",
    "pf_net_amt_delta_m30_0",
    "pf_net_amt_delta_m10_0",
    "pf_net_amt_delta_m5_0",
    "pf_imbalance_delta_m30_0",
    "pf_imbalance_delta_m10_0",
    "pf_imbalance_delta_m5_0",
    "pf_irds_sum_m5_0",
]

OUTCOMES_CONT = ["mfe_pct", "mae_pct", "eod_return_pct"]
OUTCOMES_BIN = ["hit_up_3", "hit_up_5", "hit_up_10",
                "hit_dn_1", "hit_dn_2", "hit_dn_3", "eod_positive"]


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def norm_code(v):
    s = str(v or "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def sf(v):
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", "").replace("+", "")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def first_present(row, names):
    for n in names:
        if n in row and str(row.get(n, "")).strip() != "":
            return row.get(n)
    return None


def key_of(row):
    code = norm_code(first_present(row, ["stock_code", "stk_cd", "code"]))
    dt = str(first_present(row, ["trade_date", "date", "dt"]) or "").strip()
    return code, dt


def index_by_key(rows):
    out = {}
    for r in rows:
        k = key_of(r)
        if k[0] and k[1]:
            out[k] = r
    return out


def parse_event_dt(trade_date, raw):
    s = str(raw or "").strip()
    digits = "".join(c for c in s if c.isdigit())

    try:
        if len(digits) >= 14:
            return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        if len(digits) == 12:
            return datetime.strptime(digits, "%Y%m%d%H%M")
        if len(digits) == 6:
            return datetime.strptime(trade_date + digits, "%Y%m%d%H%M%S")
        if len(digits) == 4:
            return datetime.strptime(trade_date + digits + "00", "%Y%m%d%H%M%S")
    except Exception:
        return None
    return None


def cache_path(base, code, dt):
    return base / CACHE_ROOT / dt[:4] / dt[4:6] / f"{code}_{dt}.csv.gz"


def load_pf_cache(path, trade_date):
    """
    Returns sorted rows:
      [(datetime, data_dict), ...]

    Amount fields are kept in the raw official unit used by collector
    (amt_qty_tp=1 -> million KRW). We do not reinterpret them as source rules.
    """
    rows = []
    if not path.exists():
        return rows

    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            tm = str(r.get("tm", "")).strip()
            digits = "".join(c for c in tm if c.isdigit())
            if len(digits) == 6:
                raw_ts = trade_date + digits
            elif len(digits) >= 14:
                raw_ts = digits[:14]
            else:
                continue
            try:
                dt = datetime.strptime(raw_ts, "%Y%m%d%H%M%S")
            except Exception:
                continue

            sell_amt = sf(r.get("prm_sell_amt"))
            buy_amt = sf(r.get("prm_buy_amt"))
            net_amt = sf(r.get("prm_netprps_amt"))
            irds = sf(r.get("prm_netprps_amt_irds"))

            imbalance = None
            if buy_amt is not None and sell_amt is not None:
                den = abs(buy_amt) + abs(sell_amt)
                if den > 0:
                    # Unit-free cumulative imbalance descriptor.
                    imbalance = (buy_amt - sell_amt) / den

            rows.append((dt, {
                "sell_amt": sell_amt,
                "buy_amt": buy_amt,
                "net_amt": net_amt,
                "irds": irds,
                "imbalance": imbalance,
            }))

    rows.sort(key=lambda x: x[0])
    return rows


def snapshot_at_or_before(series, target_dt):
    if not series:
        return None
    times = [x[0] for x in series]
    i = bisect_right(times, target_dt) - 1
    if i < 0:
        return None
    return series[i]


def sum_irds_between(series, start_exclusive, end_inclusive):
    vals = []
    for ts, d in series:
        if start_exclusive < ts <= end_inclusive:
            v = d.get("irds")
            if v is not None:
                vals.append(v)
    return sum(vals) if vals else None


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
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def qcuts(values):
    s = sorted(values)
    return quantile(s, 0.25), quantile(s, 0.50), quantile(s, 0.75)


def assign_q(v, q1, q2, q3):
    if v is None:
        return ""
    if v <= q1:
        return "Q1"
    if v <= q2:
        return "Q2"
    if v <= q3:
        return "Q3"
    return "Q4"


def pct(n, d):
    return n / d * 100.0 if d else 0.0


def market_groups(rows):
    return [
        ("ALL", rows),
        ("KOSPI", [r for r in rows if str(r.get("market", "")).upper() == "KOSPI"]),
        ("KOSDAQ", [r for r in rows if str(r.get("market", "")).upper() == "KOSDAQ"]),
    ]


def chronological_split(rows, ratio=0.70):
    rows = sorted(rows, key=lambda r: (r["trade_date"], r["event_touch_time"], r["stock_code"]))
    if not rows:
        return [], []
    cut = int(len(rows) * ratio)
    cut = max(1, min(cut, len(rows)-1)) if len(rows) > 1 else len(rows)
    return rows[:cut], rows[cut:]


def main():
    base = Path(__file__).resolve().parent

    for fn in [BIAS_FILE, PATH_FILE]:
        if not (base / fn).exists():
            raise SystemExit(f"REQUIRED FILE NOT FOUND: {fn}")

    bias_rows = read_csv(base / BIAS_FILE)
    path_rows = read_csv(base / PATH_FILE)
    event_rows = read_csv(base / EVENT_FILE) if (base / EVENT_FILE).exists() else []

    path_idx = index_by_key(path_rows)
    event_idx = index_by_key(event_rows)

    covered = [r for r in bias_rows if str(r.get("coverage", "")).upper() == "COVERED"]

    aligned = []
    unavailable = 0

    for i, b in enumerate(covered, 1):
        code, dt = key_of(b)
        p = path_idx.get((code, dt), {})
        e = event_idx.get((code, dt), {})

        touch_raw = first_present(b, [
            "event_touch_time", "first_exact_touch_after_activation_time",
            "first_exact_touch_time", "entry_time"
        ])
        if touch_raw is None:
            touch_raw = first_present(e, [
                "first_exact_touch_after_activation_time",
                "first_exact_touch_time", "event_touch_time"
            ])
        if touch_raw is None:
            touch_raw = first_present(p, ["entry_time", "event_touch_time"])

        touch_dt = parse_event_dt(dt, touch_raw)
        cp = cache_path(base, code, dt)
        series = load_pf_cache(cp, dt)

        if touch_dt is None or not series:
            unavailable += 1
            continue

        row = {
            "stock_code": code,
            "stock_name": b.get("stock_name", ""),
            "trade_date": dt,
            "market": b.get("market", ""),
            "event_touch_time": touch_dt.strftime("%Y%m%d%H%M%S"),
            "cache_rows": len(series),
        }

        # Outcomes
        for k in OUTCOMES_CONT + OUTCOMES_BIN:
            v = first_present(b, [k])
            if v is None:
                v = first_present(p, [k])
            row[k] = "" if v is None else v

        snaps = {}
        for w in PRE_WINDOWS + POST_WINDOWS:
            target = touch_dt + timedelta(minutes=w)
            snap = snapshot_at_or_before(series, target)
            label = f"m{abs(w)}" if w < 0 else ("0" if w == 0 else f"p{w}")
            if snap is None:
                snaps[w] = None
                row[f"pf_obs_time_{label}"] = ""
                row[f"pf_net_amt_{label}"] = ""
                row[f"pf_imbalance_{label}"] = ""
                row[f"pf_irds_{label}"] = ""
            else:
                ts, d = snap
                snaps[w] = d
                row[f"pf_obs_time_{label}"] = ts.strftime("%Y%m%d%H%M%S")
                row[f"pf_net_amt_{label}"] = "" if d["net_amt"] is None else d["net_amt"]
                row[f"pf_imbalance_{label}"] = "" if d["imbalance"] is None else d["imbalance"]
                row[f"pf_irds_{label}"] = "" if d["irds"] is None else d["irds"]

        def delta(field, a, z):
            da, dz = snaps.get(a), snaps.get(z)
            if not da or not dz:
                return ""
            va, vz = da.get(field), dz.get(field)
            if va is None or vz is None:
                return ""
            return vz - va

        row["pf_net_amt_delta_m30_0"] = delta("net_amt", -30, 0)
        row["pf_net_amt_delta_m10_0"] = delta("net_amt", -10, 0)
        row["pf_net_amt_delta_m5_0"] = delta("net_amt", -5, 0)
        row["pf_imbalance_delta_m30_0"] = delta("imbalance", -30, 0)
        row["pf_imbalance_delta_m10_0"] = delta("imbalance", -10, 0)
        row["pf_imbalance_delta_m5_0"] = delta("imbalance", -5, 0)

        # Convenience aliases used by the causal feature list.
        row["pf_net_amt_0"] = row.get("pf_net_amt_0", "")
        row["pf_imbalance_0"] = row.get("pf_imbalance_0", "")
        row["pf_irds_sum_m5_0"] = (
            sum_irds_between(series, touch_dt - timedelta(minutes=5), touch_dt)
        )
        if row["pf_irds_sum_m5_0"] is None:
            row["pf_irds_sum_m5_0"] = ""

        aligned.append(row)

        if i % 25 == 0 or i == len(covered):
            print(f"ALIGN {i:03d}/{len(covered)} | usable={len(aligned)} unavailable={unavailable}")

    if not aligned:
        raise SystemExit("NO ALIGNED PROGRAM_FLOW EVENTS")

    # Dynamic aligned output fields
    aligned_fields = [
        "stock_code", "stock_name", "trade_date", "market", "event_touch_time", "cache_rows",
        *OUTCOMES_CONT, *OUTCOMES_BIN,
    ]
    for w in PRE_WINDOWS + POST_WINDOWS:
        label = f"m{abs(w)}" if w < 0 else ("0" if w == 0 else f"p{w}")
        aligned_fields += [
            f"pf_obs_time_{label}", f"pf_net_amt_{label}",
            f"pf_imbalance_{label}", f"pf_irds_{label}"
        ]
    aligned_fields += [
        "pf_net_amt_delta_m30_0", "pf_net_amt_delta_m10_0", "pf_net_amt_delta_m5_0",
        "pf_imbalance_delta_m30_0", "pf_imbalance_delta_m10_0", "pf_imbalance_delta_m5_0",
        "pf_irds_sum_m5_0",
    ]
    write_csv(base / OUT_ALIGNED, aligned_fields, aligned)

    feature_rows = []
    holdout_rows = []

    for market_name, group in market_groups(aligned):
        train, holdout = chronological_split(group, 0.70)

        for feature in CAUSAL_FEATURES:
            tx, train_valid_rows = [], []
            for r in train:
                v = sf(r.get(feature))
                if v is not None:
                    tx.append(v)
                    train_valid_rows.append(r)

            if len(tx) < 12:
                continue

            q1, q2, q3 = qcuts(tx)

            # Feature correlations: TRAIN and HOLDOUT separately.
            for split_name, split_rows in [("TRAIN70", train), ("HOLDOUT30", holdout)]:
                for outcome in OUTCOMES_CONT:
                    xs, ys = [], []
                    for r in split_rows:
                        x = sf(r.get(feature))
                        y = sf(r.get(outcome))
                        if x is not None and y is not None:
                            xs.append(x)
                            ys.append(y)
                    rho = spearman(xs, ys)
                    feature_rows.append({
                        "market": market_name,
                        "split": split_name,
                        "feature": feature,
                        "outcome": outcome,
                        "n": len(xs),
                        "spearman_rho": "" if rho is None else rho,
                        "train_q1": q1,
                        "train_q2": q2,
                        "train_q3": q3,
                    })

            # Frozen TRAIN quartiles applied to HOLDOUT.
            for split_name, split_rows in [("TRAIN70", train), ("HOLDOUT30", holdout)]:
                buckets = defaultdict(list)
                for r in split_rows:
                    v = sf(r.get(feature))
                    if v is not None:
                        buckets[assign_q(v, q1, q2, q3)].append(r)

                for qname in ["Q1", "Q2", "Q3", "Q4"]:
                    rr = buckets.get(qname, [])
                    if not rr:
                        continue
                    hrow = {
                        "market": market_name,
                        "split": split_name,
                        "feature": feature,
                        "quartile": qname,
                        "n": len(rr),
                        "train_q1": q1, "train_q2": q2, "train_q3": q3,
                    }
                    for outcome in OUTCOMES_CONT:
                        vv = [sf(r.get(outcome)) for r in rr]
                        vv = [v for v in vv if v is not None]
                        hrow[f"{outcome}_mean"] = mean(vv) if vv else ""
                        hrow[f"{outcome}_median"] = median(vv) if vv else ""
                    for outcome in OUTCOMES_BIN:
                        vv = [sf(r.get(outcome)) for r in rr]
                        vv = [v for v in vv if v is not None]
                        hrow[f"{outcome}_pct"] = pct(sum(1 for v in vv if v > 0), len(vv))
                    holdout_rows.append(hrow)

    write_csv(base / OUT_FEATURE_STUDY, [
        "market", "split", "feature", "outcome", "n", "spearman_rho",
        "train_q1", "train_q2", "train_q3"
    ], feature_rows)

    holdout_fields = [
        "market", "split", "feature", "quartile", "n",
        "train_q1", "train_q2", "train_q3",
    ]
    for o in OUTCOMES_CONT:
        holdout_fields += [f"{o}_mean", f"{o}_median"]
    for o in OUTCOMES_BIN:
        holdout_fields += [f"{o}_pct"]
    write_csv(base / OUT_HOLDOUT, holdout_fields, holdout_rows)

    # Post-entry descriptive only: correlations with later snapshots.
    post_rows = []
    for market_name, group in market_groups(aligned):
        for w in POST_WINDOWS:
            label = f"p{w}"
            feature = f"pf_net_amt_{label}"
            for outcome in OUTCOMES_CONT:
                xs, ys = [], []
                for r in group:
                    x, y = sf(r.get(feature)), sf(r.get(outcome))
                    if x is not None and y is not None:
                        xs.append(x); ys.append(y)
                rho = spearman(xs, ys)
                post_rows.append({
                    "market": market_name,
                    "window_min_after_entry": w,
                    "feature": feature,
                    "outcome": outcome,
                    "n": len(xs),
                    "spearman_rho": "" if rho is None else rho,
                    "classification": "POST_ENTRY_DESCRIPTIVE_ONLY",
                })
    write_csv(base / OUT_POST, [
        "market", "window_min_after_entry", "feature",
        "outcome", "n", "spearman_rho", "classification"
    ], post_rows)

    # Summary
    lines = [
        "RS20 PROGRAM_FLOW Alignment / Predictive Study v1",
        "",
        f"covered_input_events: {len(covered)}",
        f"aligned_usable_events: {len(aligned)}",
        f"unavailable_events: {unavailable}",
        "",
        "MARKET COUNTS",
    ]
    for market_name, group in market_groups(aligned):
        tr, ho = chronological_split(group, 0.70)
        lines.append(
            f"- {market_name}: total={len(group)}, TRAIN70={len(tr)}, HOLDOUT30={len(ho)}"
        )

    lines += [
        "",
        "CAUSAL ENTRY FEATURES",
    ]
    for f in CAUSAL_FEATURES:
        lines.append(f"- {f}")

    lines += [
        "",
        "RULES",
        "- Entry predictiveness uses only -30/-10/-5/-3/-1/0 minute information.",
        "- +1/+3/+5/+10/+30 minute data are POST_ENTRY_DESCRIPTIVE_ONLY.",
        "- TRAIN quartile cutpoints are frozen and applied unchanged to HOLDOUT.",
        "- ALL/KOSPI/KOSDAQ are reported separately.",
        "- No threshold is added to frozen RS20 source rules.",
        "- No Kiwoom API and no order API are used.",
        "",
        f"aligned_output: {OUT_ALIGNED}",
        f"feature_study_output: {OUT_FEATURE_STUDY}",
        f"holdout_output: {OUT_HOLDOUT}",
        f"post_entry_output: {OUT_POST}",
    ]
    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 100)
    print("RS20 PROGRAM_FLOW ALIGNMENT / PREDICTIVE STUDY v1")
    print(f"COVERED INPUT            : {len(covered):,}")
    print(f"ALIGNED USABLE           : {len(aligned):,}")
    print(f"UNAVAILABLE              : {unavailable:,}")
    for market_name, group in market_groups(aligned):
        tr, ho = chronological_split(group, 0.70)
        print(f"{market_name:<10} TOTAL/TRAIN/HOLDOUT : {len(group):>3}/{len(tr):>3}/{len(ho):>3}")
    print(f"ALIGNED FILE             : {OUT_ALIGNED}")
    print(f"FEATURE STUDY            : {OUT_FEATURE_STUDY}")
    print(f"HOLDOUT STUDY            : {OUT_HOLDOUT}")
    print(f"POST-ENTRY DESCRIPTIVE   : {OUT_POST}")
    print(f"SUMMARY                  : {OUT_SUMMARY}")
    print("NO Kiwoom API / NO order API")
    print("=" * 100)


if __name__ == "__main__":
    main()

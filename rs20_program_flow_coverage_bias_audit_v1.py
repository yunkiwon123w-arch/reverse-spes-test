# -*- coding: utf-8 -*-
"""
RS20 PROGRAM_FLOW Coverage / Bias Audit v1

Purpose:
Compare ka90008-covered RS20 exact-touch events against NO_DATA events
before any predictive PROGRAM_FLOW study.

NO Kiwoom API.
NO order API.
"""

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, pstdev

STATUS_FILE = "rs20_program_flow_collection_status_v1_5.csv"
PATH_FILE = "rs20_post_entry_path_diagnostic_v1.csv"
EVENT_FILE = "rs20_source_event_state_machine_candidate_summary_v1_2.csv"
NUMERIC_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

OUT_EVENT = "rs20_program_flow_coverage_bias_event_level_v1.csv"
OUT_GROUP = "rs20_program_flow_coverage_bias_group_summary_v1.csv"
OUT_METRIC = "rs20_program_flow_coverage_bias_metric_comparison_v1.csv"
OUT_MONTH = "rs20_program_flow_coverage_bias_monthly_v1.csv"
OUT_STOCK = "rs20_program_flow_coverage_bias_stock_concentration_v1.csv"
OUT_SUMMARY = "rs20_program_flow_coverage_bias_summary_v1.txt"


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


def norm_code(v):
    s = str(v or "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def sf(v):
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", "").replace("%", "")
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def first_present(row, names):
    for n in names:
        if n in row and str(row.get(n, "")).strip() != "":
            return row.get(n)
    return None


def first_float(row, names):
    return sf(first_present(row, names))


def key_of(row):
    code = norm_code(first_present(row, ["stock_code", "stk_cd", "code", "종목코드"]))
    dt = str(first_present(row, ["trade_date", "date", "dt", "일자"]) or "").strip()
    return code, dt


def index_by_key(rows):
    out = {}
    for r in rows:
        k = key_of(r)
        if k[0] and k[1]:
            out[k] = r
    return out


def classify_coverage(status):
    s = str(status or "").strip().upper()
    if s in {"COLLECTED", "CACHED"}:
        return "COVERED"
    if s == "NO_DATA":
        return "NO_DATA"
    return s or "UNKNOWN"


def infer_market(row):
    v = first_present(row, ["market", "market_name", "mrkt", "시장", "market_type"])
    if v is None:
        return "UNKNOWN"
    s = str(v).strip().upper()
    if "KOSDAQ" in s or "코스닥" in s:
        return "KOSDAQ"
    if "KOSPI" in s or "코스피" in s:
        return "KOSPI"
    return s or "UNKNOWN"


def vals(rows, field):
    out = []
    for r in rows:
        v = sf(r.get(field))
        if v is not None and math.isfinite(v):
            out.append(v)
    return out


def smd(a, b):
    if not a or not b:
        return None
    va = pstdev(a) ** 2 if len(a) > 1 else 0.0
    vb = pstdev(b) ** 2 if len(b) > 1 else 0.0
    pooled = math.sqrt((va + vb) / 2.0)
    if pooled == 0:
        return 0.0 if mean(a) == mean(b) else None
    return (mean(a) - mean(b)) / pooled


def pct(n, d):
    return n / d * 100.0 if d else 0.0


def main():
    base = Path(__file__).resolve().parent
    status_path = base / STATUS_FILE
    if not status_path.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {STATUS_FILE}")

    status_rows = read_csv(status_path)

    optional = {}
    for label, filename in [("path", PATH_FILE), ("event", EVENT_FILE), ("numeric", NUMERIC_FILE)]:
        p = base / filename
        optional[label] = read_csv(p) if p.exists() else []

    idx_path = index_by_key(optional["path"])
    idx_event = index_by_key(optional["event"])
    idx_numeric = index_by_key(optional["numeric"])

    events = []

    for s in status_rows:
        k = key_of(s)
        merged = dict(s)

        for src in [idx_path.get(k, {}), idx_event.get(k, {}), idx_numeric.get(k, {})]:
            for kk, vv in src.items():
                if kk not in merged or str(merged.get(kk, "")).strip() == "":
                    merged[kk] = vv

        code, dt = k
        coverage = classify_coverage(s.get("status"))

        mfe = first_float(merged, ["mfe_pct", "MFE_pct", "mfe", "max_favorable_excursion_pct"])
        mae = first_float(merged, ["mae_pct", "MAE_pct", "mae", "max_adverse_excursion_pct"])
        eod = first_float(merged, ["eod_return_pct", "eod_ret_pct", "eod_return", "close_return_pct"])

        m_value = first_float(merged, [
            "m_at_event", "m_value", "m_eok", "M", "m_indicator_eok",
            "first_touch_m_eok", "core_m_eok",
        ])
        turnover = first_float(merged, [
            "turnover_eok", "traded_value_eok", "cum_turnover_eok",
            "trade_value_eok", "trde_prica_eok",
        ])
        m_ratio = first_float(merged, [
            "m_ratio_pct", "m_to_turnover_pct", "m_ratio",
            "first_touch_m_ratio_pct", "core_m_ratio_pct",
        ])
        if m_ratio is not None and abs(m_ratio) <= 1.5:
            m_ratio *= 100.0

        core_raw = first_present(merged, [
            "touch_while_core_on", "core_on_at_touch",
            "first_exact_touch_core_on", "core_state_at_touch",
        ])
        core = ""
        if core_raw is not None:
            sr = str(core_raw).strip().upper()
            if sr in {"ON", "Y", "YES", "TRUE", "1"}:
                core = "ON"
            elif sr in {"OFF", "N", "NO", "FALSE", "0"}:
                core = "OFF"
            else:
                core = sr

        events.append({
            "stock_code": code,
            "stock_name": first_present(merged, ["stock_name", "name", "stk_nm", "종목명"]) or "",
            "trade_date": dt,
            "year": dt[:4] if len(dt) >= 4 else "",
            "month": dt[:6] if len(dt) >= 6 else "",
            "coverage": coverage,
            "collection_status": s.get("status", ""),
            "market": infer_market(merged),
            "core_at_touch": core,
            "mfe_pct": "" if mfe is None else mfe,
            "mae_pct": "" if mae is None else mae,
            "eod_return_pct": "" if eod is None else eod,
            "m_value_eok": "" if m_value is None else m_value,
            "turnover_eok": "" if turnover is None else turnover,
            "m_ratio_pct": "" if m_ratio is None else m_ratio,
            "hit_up_3": int(mfe is not None and mfe >= 3),
            "hit_up_5": int(mfe is not None and mfe >= 5),
            "hit_up_10": int(mfe is not None and mfe >= 10),
            "hit_dn_1": int(mae is not None and mae <= -1),
            "hit_dn_2": int(mae is not None and mae <= -2),
            "hit_dn_3": int(mae is not None and mae <= -3),
            "eod_positive": int(eod is not None and eod > 0),
        })

    covered = [r for r in events if r["coverage"] == "COVERED"]
    no_data = [r for r in events if r["coverage"] == "NO_DATA"]
    other = [r for r in events if r["coverage"] not in {"COVERED", "NO_DATA"}]

    group_rows = []
    for name, rows in [("COVERED", covered), ("NO_DATA", no_data), ("OTHER", other)]:
        n = len(rows)
        valid_mfe = sum(r["mfe_pct"] != "" for r in rows)
        valid_mae = sum(r["mae_pct"] != "" for r in rows)
        valid_eod = sum(r["eod_return_pct"] != "" for r in rows)
        market_counts = Counter(r["market"] for r in rows)
        core_counts = Counter(r["core_at_touch"] for r in rows if r["core_at_touch"])
        group_rows.append({
            "group": name,
            "n": n,
            "pct_of_total": round(pct(n, len(events)), 6),
            "kospi_n": market_counts.get("KOSPI", 0),
            "kosdaq_n": market_counts.get("KOSDAQ", 0),
            "market_unknown_n": market_counts.get("UNKNOWN", 0),
            "core_on_n": core_counts.get("ON", 0),
            "core_off_n": core_counts.get("OFF", 0),
            "up3_hit_pct": round(pct(sum(r["hit_up_3"] for r in rows), valid_mfe), 6),
            "up5_hit_pct": round(pct(sum(r["hit_up_5"] for r in rows), valid_mfe), 6),
            "up10_hit_pct": round(pct(sum(r["hit_up_10"] for r in rows), valid_mfe), 6),
            "down1_hit_pct": round(pct(sum(r["hit_dn_1"] for r in rows), valid_mae), 6),
            "down2_hit_pct": round(pct(sum(r["hit_dn_2"] for r in rows), valid_mae), 6),
            "down3_hit_pct": round(pct(sum(r["hit_dn_3"] for r in rows), valid_mae), 6),
            "eod_positive_pct": round(pct(sum(r["eod_positive"] for r in rows), valid_eod), 6),
        })

    metric_rows = []
    for field, label in [
        ("mfe_pct", "MFE %"),
        ("mae_pct", "MAE %"),
        ("eod_return_pct", "EOD return %"),
        ("m_value_eok", "M value (eok)"),
        ("turnover_eok", "Turnover (eok)"),
        ("m_ratio_pct", "M / turnover %"),
    ]:
        a, b = vals(covered, field), vals(no_data, field)
        sv = smd(a, b)
        metric_rows.append({
            "metric": label,
            "field": field,
            "covered_n": len(a),
            "covered_mean": mean(a) if a else "",
            "covered_median": median(a) if a else "",
            "no_data_n": len(b),
            "no_data_mean": mean(b) if b else "",
            "no_data_median": median(b) if b else "",
            "mean_diff_covered_minus_no_data": (mean(a) - mean(b)) if a and b else "",
            "median_diff_covered_minus_no_data": (median(a) - median(b)) if a and b else "",
            "standardized_mean_diff": "" if sv is None else sv,
            "abs_smd": "" if sv is None else abs(sv),
        })

    month_map = defaultdict(lambda: {"total": 0, "covered": 0, "no_data": 0, "other": 0})
    for r in events:
        m = r["month"] or "UNKNOWN"
        month_map[m]["total"] += 1
        if r["coverage"] == "COVERED":
            month_map[m]["covered"] += 1
        elif r["coverage"] == "NO_DATA":
            month_map[m]["no_data"] += 1
        else:
            month_map[m]["other"] += 1

    month_rows = []
    for m in sorted(month_map):
        x = month_map[m]
        month_rows.append({
            "month": m,
            "total": x["total"],
            "covered": x["covered"],
            "no_data": x["no_data"],
            "other": x["other"],
            "coverage_pct": round(pct(x["covered"], x["total"]), 6),
            "no_data_pct": round(pct(x["no_data"], x["total"]), 6),
        })

    stock_map = defaultdict(lambda: {"stock_name": "", "total": 0, "covered": 0, "no_data": 0})
    for r in events:
        x = stock_map[r["stock_code"]]
        x["stock_name"] = r["stock_name"] or x["stock_name"]
        x["total"] += 1
        if r["coverage"] == "COVERED":
            x["covered"] += 1
        elif r["coverage"] == "NO_DATA":
            x["no_data"] += 1

    stock_rows = []
    for code, x in stock_map.items():
        stock_rows.append({
            "stock_code": code,
            "stock_name": x["stock_name"],
            "total_events": x["total"],
            "covered_events": x["covered"],
            "no_data_events": x["no_data"],
            "coverage_pct": round(pct(x["covered"], x["total"]), 6),
            "no_data_pct": round(pct(x["no_data"], x["total"]), 6),
        })
    stock_rows.sort(key=lambda r: (-r["no_data_events"], r["stock_code"]))

    write_csv(base / OUT_EVENT, [
        "stock_code","stock_name","trade_date","year","month","coverage","collection_status",
        "market","core_at_touch","mfe_pct","mae_pct","eod_return_pct","m_value_eok",
        "turnover_eok","m_ratio_pct","hit_up_3","hit_up_5","hit_up_10",
        "hit_dn_1","hit_dn_2","hit_dn_3","eod_positive"
    ], events)

    write_csv(base / OUT_GROUP, [
        "group","n","pct_of_total","kospi_n","kosdaq_n","market_unknown_n",
        "core_on_n","core_off_n","up3_hit_pct","up5_hit_pct","up10_hit_pct",
        "down1_hit_pct","down2_hit_pct","down3_hit_pct","eod_positive_pct"
    ], group_rows)

    write_csv(base / OUT_METRIC, [
        "metric","field","covered_n","covered_mean","covered_median",
        "no_data_n","no_data_mean","no_data_median",
        "mean_diff_covered_minus_no_data",
        "median_diff_covered_minus_no_data",
        "standardized_mean_diff","abs_smd"
    ], metric_rows)

    write_csv(base / OUT_MONTH, [
        "month","total","covered","no_data","other","coverage_pct","no_data_pct"
    ], month_rows)

    write_csv(base / OUT_STOCK, [
        "stock_code","stock_name","total_events","covered_events","no_data_events",
        "coverage_pct","no_data_pct"
    ], stock_rows)

    largest = None
    largest_metric = ""
    for r in metric_rows:
        v = sf(r["abs_smd"])
        if v is not None and (largest is None or v > largest):
            largest = v
            largest_metric = r["metric"]

    lines = [
        "RS20 PROGRAM_FLOW Coverage / Bias Audit v1",
        "",
        f"total_events: {len(events)}",
        f"covered_events: {len(covered)} ({pct(len(covered), len(events)):.2f}%)",
        f"no_data_events: {len(no_data)} ({pct(len(no_data), len(events)):.2f}%)",
        f"other_status_events: {len(other)}",
        "",
        "OPTIONAL INPUT AVAILABILITY",
        f"{PATH_FILE}: {'FOUND' if optional['path'] else 'NOT FOUND'}",
        f"{EVENT_FILE}: {'FOUND' if optional['event'] else 'NOT FOUND'}",
        f"{NUMERIC_FILE}: {'FOUND' if optional['numeric'] else 'NOT FOUND'}",
        "",
        "DESCRIPTIVE BIAS CHECK",
    ]

    if largest is None:
        lines.append("- Continuous-metric bias could not be assessed because enrichment metrics were unavailable.")
    else:
        lines.append(f"- Largest absolute SMD: {largest:.4f} ({largest_metric})")
        lines.append("- SMD is descriptive only; it is not a significance test or strategy rule.")

    if month_rows:
        high = max(month_rows, key=lambda r: r["coverage_pct"])
        low = min(month_rows, key=lambda r: r["coverage_pct"])
        lines.append(f"- Highest monthly coverage: {high['month']} {high['coverage_pct']:.2f}% (n={high['total']})")
        lines.append(f"- Lowest monthly coverage: {low['month']} {low['coverage_pct']:.2f}% (n={low['total']})")

    lines += ["", "TOP STOCKS BY NO_DATA EVENT COUNT"]
    for r in [x for x in stock_rows if x["no_data_events"] > 0][:10]:
        lines.append(
            f"- {r['stock_code']} {r['stock_name']} | "
            f"NO_DATA {r['no_data_events']}/{r['total_events']} ({r['no_data_pct']:.2f}%)"
        )

    lines += [
        "",
        "INTERPRETATION",
        "- COVERED = COLLECTED or CACHED.",
        "- NO_DATA is never treated as zero program flow.",
        "- This audit checks representativeness before predictive analysis.",
        "- No result here changes the frozen RS20 source rules.",
        "- Strong coverage concentration means later PROGRAM_FLOW conclusions must be restricted.",
        "",
        "NO KIWOOM API. NO ORDER API.",
    ]

    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 96)
    print("RS20 PROGRAM_FLOW COVERAGE / BIAS AUDIT v1")
    print(f"TOTAL EVENTS             : {len(events):,}")
    print(f"COVERED                  : {len(covered):,} ({pct(len(covered), len(events)):.2f}%)")
    print(f"NO_DATA                  : {len(no_data):,} ({pct(len(no_data), len(events)):.2f}%)")
    print(f"OTHER                    : {len(other):,}")
    print(f"PATH ENRICHMENT          : {'FOUND' if optional['path'] else 'NOT FOUND'}")
    print(f"EVENT ENRICHMENT         : {'FOUND' if optional['event'] else 'NOT FOUND'}")
    print(f"NUMERIC ENRICHMENT       : {'FOUND' if optional['numeric'] else 'NOT FOUND'}")
    print(f"LARGEST ABS SMD          : {largest:.4f} ({largest_metric})" if largest is not None else "LARGEST ABS SMD          : N/A")
    print(f"SUMMARY                  : {OUT_SUMMARY}")
    print("NO Kiwoom API / NO order API")
    print("=" * 96)


if __name__ == "__main__":
    main()

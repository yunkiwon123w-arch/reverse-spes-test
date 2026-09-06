# -*- coding: utf-8 -*-
"""
RS20 Reverse-38 Structure Diagnostic v1
=======================================

SOURCE-FAITHFUL PURPOSE
- Input is the frozen RS20 numeric-core candidate set.
- Use ONLY the already-saved local 1-minute cache.
- Diagnose the source concept:
    rising wave -> Reverse Fibonacci 38 line -> first pullback
- DO NOT invent:
    * a minimum rising-wave percentage
    * a tolerance for "near 38"
    * a mechanical definition of "세력주/수급세력주"
    * a mechanical definition of "3파 차트"
    * a mechanical new-listing period
    * an arbitrary "wait N minutes after high" rule
- NO Kiwoom API calls.
- NO order API.

Reverse-Fibonacci lecture naming:
    K = high - low
    lecture "38 line" = low + K * 0.618

Diagnostic method:
1) For each candidate day, read 1-minute bars from local cache.
2) Track running day-low and every NEW running day-high.
3) Each new running-high is preserved as an anchor candidate.
4) For each anchor candidate:
   - freeze low/high at that anchor
   - calculate reverse 38 line
   - search ONLY after the anchor bar
   - record first exact 1-minute bar whose [low, high] contains the 38 line
   - also record nearest post-anchor distance to the 38 line
5) Separately expose the FINAL running-high anchor of the day.
   This is a diagnostic reference only; it is NOT declared the source's
   true wave mechanically.

Outputs:
- rs20_fib38_structure_candidate_summary_v1.csv
- rs20_fib38_structure_anchors_v1.csv
- rs20_fib38_structure_unavailable_v1.csv
- rs20_fib38_structure_summary_v1.txt
"""

import csv
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

INPUT_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_SUMMARY = "rs20_fib38_structure_candidate_summary_v1.csv"
OUT_ANCHORS = "rs20_fib38_structure_anchors_v1.csv"
OUT_UNAVAILABLE = "rs20_fib38_structure_unavailable_v1.csv"
OUT_TXT = "rs20_fib38_structure_summary_v1.txt"

SUMMARY_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "traded_value_eok", "m_value_eok", "m_ratio_pct",
    "bar_count",
    "day_open", "day_high", "day_low", "day_close",
    "day_high_time", "day_low_time",
    "running_high_anchor_count",
    "anchors_with_exact_38_touch",
    "anchors_without_exact_38_touch",
    "final_anchor_no",
    "final_anchor_time",
    "final_anchor_low",
    "final_anchor_high",
    "final_anchor_wave_pct",
    "final_anchor_fib38",
    "final_anchor_first_exact_touch_time",
    "final_anchor_first_exact_touch_low",
    "final_anchor_first_exact_touch_high",
    "final_anchor_minutes_by_bar_count_to_touch",
    "final_anchor_nearest_time",
    "final_anchor_nearest_price",
    "final_anchor_nearest_distance_pct",
    "final_anchor_nearest_relation",
    "final_anchor_has_exact_touch",
    "diagnostic_status"
]

ANCHOR_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "anchor_no",
    "anchor_time",
    "anchor_low",
    "anchor_low_time",
    "anchor_high",
    "anchor_high_time",
    "wave_pct",
    "fib38",
    "first_exact_touch_time",
    "first_exact_touch_low",
    "first_exact_touch_high",
    "minutes_by_bar_count_to_touch",
    "nearest_time",
    "nearest_price",
    "nearest_distance_pct",
    "nearest_relation",
    "has_exact_touch",
    "is_final_running_high_anchor"
]

UNAVAILABLE_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date", "reason"
]


def norm_code(v):
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def sf(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return default


def af(v, default=None):
    x = sf(v, default)
    return abs(x) if x is not None else default


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


def parse_bar(r):
    tm = str(r.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    o = af(r.get("open_pric"))
    h = af(r.get("high_pric"))
    l = af(r.get("low_pric"))
    c = af(r.get("cur_prc"))
    v = af(r.get("trde_qty"), 0.0)

    if None in (o, h, l, c):
        return None

    return {
        "cntr_tm": tm,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v or 0.0,
    }


def load_stock_cache(path):
    bars = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            b = parse_bar(r)
            if b:
                # exact timestamp dedup
                bars[b["cntr_tm"]] = b
    return bars


def load_date_cache(path):
    bars = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            b = parse_bar(r)
            if b:
                bars[b["cntr_tm"]] = b
    return bars


def find_date_cache(base, code, dt):
    yyyy = dt[:4]
    mm = dt[4:6]
    candidates = [
        base / DATE_CACHE_ROOT / yyyy / mm / f"{code}_{dt}.csv.gz",
        base / DATE_CACHE_ROOT / f"{code}_{dt}.csv.gz",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def fmt_num(x, digits=6):
    if x is None:
        return ""
    return round(float(x), digits)


def relation_to_line(bar, line):
    # Exact touch if bar range contains the line.
    if bar["low"] <= line <= bar["high"]:
        return 0.0, line, "TOUCH"

    if bar["low"] > line:
        # Whole bar is above line; nearest point is low.
        d = (bar["low"] - line) / line * 100.0
        return abs(d), bar["low"], "ABOVE"

    # Whole bar is below line; nearest point is high.
    d = (bar["high"] - line) / line * 100.0
    return abs(d), bar["high"], "BELOW"


def analyze_candidate(cand, daybars):
    code = norm_code(cand.get("stock_code", ""))
    name = cand.get("stock_name", "")
    market = cand.get("market", "")
    dt = str(cand.get("trade_date", "")).strip()

    daybars = sorted(daybars, key=lambda x: x["cntr_tm"])
    if not daybars:
        return None, []

    day_open = daybars[0]["open"]
    day_close = daybars[-1]["close"]

    day_high_bar = max(daybars, key=lambda x: (x["high"], -int(x["cntr_tm"])))
    day_low_bar = min(daybars, key=lambda x: (x["low"], int(x["cntr_tm"])))
    day_high = max(b["high"] for b in daybars)
    day_low = min(b["low"] for b in daybars)

    running_low = None
    running_low_time = ""
    running_high = None
    anchors = []

    # Preserve every NEW running-high state with the current running low.
    for idx, b in enumerate(daybars):
        if running_low is None or b["low"] < running_low:
            running_low = b["low"]
            running_low_time = b["cntr_tm"]

        if running_high is None or b["high"] > running_high:
            running_high = b["high"]

            if running_low is None or running_high <= running_low:
                continue

            wave_pct = (running_high - running_low) / running_low * 100.0
            fib38 = running_low + (running_high - running_low) * 0.618

            first_touch = None
            first_touch_index = None

            nearest = None
            nearest_dist = None
            nearest_price = None
            nearest_rel = None

            # IMPORTANT: search starts AFTER anchor bar.
            for j in range(idx + 1, len(daybars)):
                pb = daybars[j]
                dist, nprice, rel = relation_to_line(pb, fib38)

                if nearest_dist is None or dist < nearest_dist:
                    nearest_dist = dist
                    nearest = pb
                    nearest_price = nprice
                    nearest_rel = rel

                if pb["low"] <= fib38 <= pb["high"]:
                    first_touch = pb
                    first_touch_index = j
                    break

            anchors.append({
                "_anchor_idx": idx,
                "_touch_idx": first_touch_index,
                "stock_code": code,
                "stock_name": name,
                "market": market,
                "trade_date": dt,
                "anchor_no": len(anchors) + 1,
                "anchor_time": b["cntr_tm"],
                "anchor_low": fmt_num(running_low),
                "anchor_low_time": running_low_time,
                "anchor_high": fmt_num(running_high),
                "anchor_high_time": b["cntr_tm"],
                "wave_pct": fmt_num(wave_pct),
                "fib38": fmt_num(fib38),
                "first_exact_touch_time": first_touch["cntr_tm"] if first_touch else "",
                "first_exact_touch_low": fmt_num(first_touch["low"]) if first_touch else "",
                "first_exact_touch_high": fmt_num(first_touch["high"]) if first_touch else "",
                "minutes_by_bar_count_to_touch": (
                    first_touch_index - idx if first_touch_index is not None else ""
                ),
                "nearest_time": nearest["cntr_tm"] if nearest else "",
                "nearest_price": fmt_num(nearest_price) if nearest else "",
                "nearest_distance_pct": fmt_num(nearest_dist) if nearest_dist is not None else "",
                "nearest_relation": nearest_rel or "",
                "has_exact_touch": "Y" if first_touch else "N",
                "is_final_running_high_anchor": "N",
            })

    if not anchors:
        summary = {
            "stock_code": code,
            "stock_name": name,
            "market": market,
            "trade_date": dt,
            "traded_value_eok": cand.get("traded_value_eok", ""),
            "m_value_eok": cand.get("m_value_eok", ""),
            "m_ratio_pct": cand.get("m_ratio_pct", ""),
            "bar_count": len(daybars),
            "day_open": fmt_num(day_open),
            "day_high": fmt_num(day_high),
            "day_low": fmt_num(day_low),
            "day_close": fmt_num(day_close),
            "day_high_time": day_high_bar["cntr_tm"],
            "day_low_time": day_low_bar["cntr_tm"],
            "running_high_anchor_count": 0,
            "anchors_with_exact_38_touch": 0,
            "anchors_without_exact_38_touch": 0,
            "diagnostic_status": "NO_VALID_ANCHOR",
        }
        return summary, []

    anchors[-1]["is_final_running_high_anchor"] = "Y"
    final = anchors[-1]

    exact_count = sum(1 for a in anchors if a["has_exact_touch"] == "Y")

    summary = {
        "stock_code": code,
        "stock_name": name,
        "market": market,
        "trade_date": dt,
        "traded_value_eok": cand.get("traded_value_eok", ""),
        "m_value_eok": cand.get("m_value_eok", ""),
        "m_ratio_pct": cand.get("m_ratio_pct", ""),
        "bar_count": len(daybars),
        "day_open": fmt_num(day_open),
        "day_high": fmt_num(day_high),
        "day_low": fmt_num(day_low),
        "day_close": fmt_num(day_close),
        "day_high_time": day_high_bar["cntr_tm"],
        "day_low_time": day_low_bar["cntr_tm"],
        "running_high_anchor_count": len(anchors),
        "anchors_with_exact_38_touch": exact_count,
        "anchors_without_exact_38_touch": len(anchors) - exact_count,
        "final_anchor_no": final["anchor_no"],
        "final_anchor_time": final["anchor_time"],
        "final_anchor_low": final["anchor_low"],
        "final_anchor_high": final["anchor_high"],
        "final_anchor_wave_pct": final["wave_pct"],
        "final_anchor_fib38": final["fib38"],
        "final_anchor_first_exact_touch_time": final["first_exact_touch_time"],
        "final_anchor_first_exact_touch_low": final["first_exact_touch_low"],
        "final_anchor_first_exact_touch_high": final["first_exact_touch_high"],
        "final_anchor_minutes_by_bar_count_to_touch": final["minutes_by_bar_count_to_touch"],
        "final_anchor_nearest_time": final["nearest_time"],
        "final_anchor_nearest_price": final["nearest_price"],
        "final_anchor_nearest_distance_pct": final["nearest_distance_pct"],
        "final_anchor_nearest_relation": final["nearest_relation"],
        "final_anchor_has_exact_touch": final["has_exact_touch"],
        "diagnostic_status": "OK",
    }

    # Remove internal-only fields.
    for a in anchors:
        a.pop("_anchor_idx", None)
        a.pop("_touch_idx", None)

    return summary, anchors


def main():
    base = Path(__file__).resolve().parent
    input_path = base / INPUT_FILE

    if not input_path.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    candidates = read_csv(input_path)

    print("=" * 80)
    print("RS20 Reverse-38 Structure Diagnostic v1")
    print(f"INPUT NUMERIC CANDIDATES : {len(candidates):,}")
    print("LOCAL CACHE ONLY")
    print("NO Kiwoom API / NO ORDER API")
    print("NO invented wave/tolerance/3-wave/new-listing thresholds")
    print("=" * 80)

    # Group candidates by stock so each stock cache is opened once.
    by_stock = defaultdict(list)
    for c in candidates:
        by_stock[norm_code(c.get("stock_code", ""))].append(c)

    summary_rows = []
    anchor_rows = []
    unavailable_rows = []

    stock_cache_hits = 0
    date_cache_hits = 0

    for si, (code, stock_candidates) in enumerate(sorted(by_stock.items()), 1):
        stock_path = base / STOCK_CACHE_ROOT / f"{code}.csv.gz"
        stock_bars = None

        if stock_path.exists():
            stock_bars = load_stock_cache(stock_path)
            stock_cache_hits += 1

        for cand in stock_candidates:
            dt = str(cand.get("trade_date", "")).strip()
            daybars = []

            if stock_bars is not None:
                daybars = [
                    b for tm, b in stock_bars.items()
                    if tm.startswith(dt)
                ]

            if not daybars:
                date_path = find_date_cache(base, code, dt)
                if date_path:
                    db = load_date_cache(date_path)
                    daybars = [
                        b for tm, b in db.items()
                        if tm.startswith(dt)
                    ]
                    date_cache_hits += 1

            if not daybars:
                unavailable_rows.append({
                    "stock_code": code,
                    "stock_name": cand.get("stock_name", ""),
                    "market": cand.get("market", ""),
                    "trade_date": dt,
                    "reason": "LOCAL_1M_CACHE_NOT_FOUND_FOR_DATE",
                })
                continue

            s, a = analyze_candidate(cand, daybars)
            if s:
                summary_rows.append(s)
            anchor_rows.extend(a)

        if si % 25 == 0 or si == len(by_stock):
            print(
                f"[{si:03d}/{len(by_stock)} stocks] "
                f"summary {len(summary_rows):,} / "
                f"anchors {len(anchor_rows):,} / "
                f"unavailable {len(unavailable_rows):,}"
            )

    summary_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))
    anchor_rows.sort(
        key=lambda r: (r["trade_date"], r["stock_code"], int(r["anchor_no"]))
    )
    unavailable_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    write_csv(base / OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(base / OUT_ANCHORS, ANCHOR_FIELDS, anchor_rows)
    write_csv(base / OUT_UNAVAILABLE, UNAVAILABLE_FIELDS, unavailable_rows)

    ok_rows = [r for r in summary_rows if r["diagnostic_status"] == "OK"]
    final_touch = [r for r in ok_rows if r["final_anchor_has_exact_touch"] == "Y"]
    any_touch = [
        r for r in ok_rows
        if int(r["anchors_with_exact_38_touch"]) > 0
    ]

    nearest_vals = [
        sf(r["final_anchor_nearest_distance_pct"])
        for r in ok_rows
        if sf(r["final_anchor_nearest_distance_pct"]) is not None
    ]

    wave_vals = [
        sf(r["final_anchor_wave_pct"])
        for r in ok_rows
        if sf(r["final_anchor_wave_pct"]) is not None
    ]

    def median(vals):
        vals = sorted(vals)
        n = len(vals)
        if n == 0:
            return None
        if n % 2:
            return vals[n // 2]
        return (vals[n // 2 - 1] + vals[n // 2]) / 2.0

    lines = [
        "RS20 Reverse-38 Structure Diagnostic v1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"input_numeric_candidates: {len(candidates)}",
        f"analyzed_candidates: {len(summary_rows)}",
        f"unavailable_local_cache_dates: {len(unavailable_rows)}",
        f"unique_candidate_stocks: {len(by_stock)}",
        f"stock_cache_files_used: {stock_cache_hits}",
        f"date_cache_fallback_hits: {date_cache_hits}",
        "",
        f"total_running_high_anchors: {len(anchor_rows)}",
        f"candidates_with_any_exact_38_touch: {len(any_touch)}",
        f"candidates_final_anchor_exact_38_touch: {len(final_touch)}",
        f"final_anchor_exact_touch_rate_pct: "
        f"{(len(final_touch)/len(ok_rows)*100.0 if ok_rows else 0):.4f}",
        f"median_final_anchor_wave_pct: "
        f"{(median(wave_vals) if wave_vals else 0):.6f}",
        f"median_final_anchor_nearest_distance_pct: "
        f"{(median(nearest_vals) if nearest_vals else 0):.6f}",
        "",
        "SOURCE-FAITHFUL LIMITS:",
        "- '38 line vicinity' tolerance is NOT defined here.",
        "- 'first pullback' is recorded relative to each preserved running-high anchor.",
        "- the true source wave is NOT auto-selected.",
        "- final running-high anchor is diagnostic only.",
        "- 세력주/수급세력주 is NOT mechanically defined.",
        "- 3-wave chart exclusion is NOT mechanically defined.",
        "- new-listing period is NOT mechanically defined.",
        "- no orders and no Kiwoom API calls.",
    ]

    (base / OUT_TXT).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 80)
    print("COMPLETE")
    print(f"ANALYZED                : {len(summary_rows):,} / {len(candidates):,}")
    print(f"LOCAL CACHE UNAVAILABLE : {len(unavailable_rows):,}")
    print(f"TOTAL ANCHORS            : {len(anchor_rows):,}")
    print(f"ANY EXACT 38 TOUCH       : {len(any_touch):,}")
    print(f"FINAL ANCHOR EXACT TOUCH : {len(final_touch):,}")
    print(f"CANDIDATE SUMMARY        : {OUT_SUMMARY}")
    print(f"ANCHOR DETAIL            : {OUT_ANCHORS}")
    print(f"UNAVAILABLE              : {OUT_UNAVAILABLE}")
    print(f"SUMMARY TXT              : {OUT_TXT}")
    print("=" * 80)


if __name__ == "__main__":
    main()

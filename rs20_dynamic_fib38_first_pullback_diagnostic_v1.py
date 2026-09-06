# -*- coding: utf-8 -*-
"""
RS20 Dynamic Reverse-Fib38 First-Pullback Diagnostic v1
=======================================================

SOURCE BASIS
The lecture's Fibonacci formula uses the CURRENT TRADING DAY extremes:
    a = dayhigh()
    b = daylow()
    k = a - b
    lecture "0.382 / 38 line" = b + k * 0.618

Therefore this diagnostic does NOT invent a separate local swing/wave selector.

PURPOSE
- Input: frozen RS20 numeric candidates.
- Data: LOCAL 1-minute cache only.
- Reconstruct the lecture's dynamic DayHigh/DayLow Reverse-Fib38 line minute by minute.
- Correct the previous "all running-high anchors stay valid forever" diagnostic:
  an old line is superseded immediately when DayHigh OR DayLow changes.
- Measure the first pullback toward the ACTIVE 38 line only while that line is valid.
- Preserve exact-touch and nearest-distance diagnostics.
- DO NOT invent a numeric tolerance for "38 line vicinity".
- NO Kiwoom API.
- NO order API.

IMPORTANT
"Exact touch" is diagnostic only. The source says "38선 부근", so exact touch is
NOT treated as the final source PASS condition.
"""

import csv
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

INPUT_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_SUMMARY = "rs20_dynamic_fib38_candidate_summary_v1.csv"
OUT_INTERVALS = "rs20_dynamic_fib38_active_intervals_v1.csv"
OUT_UNAVAILABLE = "rs20_dynamic_fib38_unavailable_v1.csv"
OUT_TXT = "rs20_dynamic_fib38_summary_v1.txt"

SUMMARY_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "traded_value_eok", "m_value_eok", "m_ratio_pct",
    "bar_count",
    "day_open", "day_high", "day_low", "day_close",
    "active_interval_count",
    "intervals_with_post_revision_bars",
    "intervals_with_exact_touch",
    "first_exact_touch_interval_no",
    "first_exact_touch_time",
    "first_exact_touch_fib38",
    "first_exact_touch_low",
    "first_exact_touch_high",
    "first_exact_touch_minutes_by_bar_count",
    "best_nearest_interval_no",
    "best_nearest_time",
    "best_nearest_fib38",
    "best_nearest_price",
    "best_nearest_distance_pct",
    "best_nearest_relation",
    "final_active_interval_no",
    "final_active_start_time",
    "final_active_day_low",
    "final_active_day_high",
    "final_active_fib38",
    "final_active_exact_touch_time",
    "final_active_nearest_distance_pct",
    "diagnostic_status"
]

INTERVAL_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "interval_no",
    "start_time",
    "end_time",
    "revision_reason",
    "day_low",
    "day_low_time",
    "day_high",
    "day_high_time",
    "wave_pct",
    "fib38",
    "post_revision_bar_count",
    "first_exact_touch_time",
    "first_exact_touch_low",
    "first_exact_touch_high",
    "minutes_by_bar_count_to_exact_touch",
    "nearest_time",
    "nearest_price",
    "nearest_distance_pct",
    "nearest_relation",
    "min_post_low",
    "min_post_low_time",
    "min_post_low_vs_fib38_pct",
    "has_exact_touch",
    "is_final_active_interval"
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


def fmt(x, digits=6):
    if x is None:
        return ""
    return round(float(x), digits)


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


def load_gzip_bars(path):
    bars = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            b = parse_bar(r)
            if b:
                bars[b["cntr_tm"]] = b
    return bars


def find_date_cache(base, code, dt):
    yyyy, mm = dt[:4], dt[4:6]
    candidates = [
        base / DATE_CACHE_ROOT / yyyy / mm / f"{code}_{dt}.csv.gz",
        base / DATE_CACHE_ROOT / f"{code}_{dt}.csv.gz",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def distance_to_line(bar, line):
    """
    Absolute distance from the bar's [low,high] range to line, in % of line.
    relation:
      TOUCH = bar range contains line
      ABOVE = entire bar above line
      BELOW = entire bar below line
    """
    if bar["low"] <= line <= bar["high"]:
        return 0.0, line, "TOUCH"
    if bar["low"] > line:
        d = (bar["low"] - line) / line * 100.0
        return abs(d), bar["low"], "ABOVE"
    d = (bar["high"] - line) / line * 100.0
    return abs(d), bar["high"], "BELOW"


def close_interval(interval, end_time, post_bars):
    interval["end_time"] = end_time
    interval["post_revision_bar_count"] = len(post_bars)

    line = interval["_fib38"]

    first_touch = None
    first_touch_idx = None
    nearest = None
    nearest_price = None
    nearest_dist = None
    nearest_rel = None
    min_low_bar = None

    for i, b in enumerate(post_bars, 1):
        dist, price, rel = distance_to_line(b, line)

        if nearest_dist is None or dist < nearest_dist:
            nearest_dist = dist
            nearest = b
            nearest_price = price
            nearest_rel = rel

        if min_low_bar is None or b["low"] < min_low_bar["low"]:
            min_low_bar = b

        if first_touch is None and b["low"] <= line <= b["high"]:
            first_touch = b
            first_touch_idx = i

    interval["first_exact_touch_time"] = first_touch["cntr_tm"] if first_touch else ""
    interval["first_exact_touch_low"] = fmt(first_touch["low"]) if first_touch else ""
    interval["first_exact_touch_high"] = fmt(first_touch["high"]) if first_touch else ""
    interval["minutes_by_bar_count_to_exact_touch"] = first_touch_idx if first_touch_idx is not None else ""

    interval["nearest_time"] = nearest["cntr_tm"] if nearest else ""
    interval["nearest_price"] = fmt(nearest_price) if nearest else ""
    interval["nearest_distance_pct"] = fmt(nearest_dist) if nearest_dist is not None else ""
    interval["nearest_relation"] = nearest_rel or ""

    interval["min_post_low"] = fmt(min_low_bar["low"]) if min_low_bar else ""
    interval["min_post_low_time"] = min_low_bar["cntr_tm"] if min_low_bar else ""
    interval["min_post_low_vs_fib38_pct"] = (
        fmt((min_low_bar["low"] - line) / line * 100.0)
        if min_low_bar else ""
    )

    interval["has_exact_touch"] = "Y" if first_touch else "N"
    interval.pop("_fib38", None)
    return interval


def analyze_candidate(cand, daybars):
    code = norm_code(cand.get("stock_code", ""))
    name = cand.get("stock_name", "")
    market = cand.get("market", "")
    dt = str(cand.get("trade_date", "")).strip()

    daybars = sorted(daybars, key=lambda x: x["cntr_tm"])
    if not daybars:
        return None, []

    # Running day extremes exactly follow source formulas.
    running_high = None
    running_low = None
    running_high_time = ""
    running_low_time = ""

    intervals = []
    current = None
    post_bars = []

    for idx, b in enumerate(daybars):
        old_high = running_high
        old_low = running_low

        new_high = old_high is None or b["high"] > old_high
        new_low = old_low is None or b["low"] < old_low

        if new_high:
            running_high = b["high"]
            running_high_time = b["cntr_tm"]
        if new_low:
            running_low = b["low"]
            running_low_time = b["cntr_tm"]

        revised = new_high or new_low

        if revised:
            # The previous source line becomes invalid immediately when
            # DayHigh or DayLow changes. Close it BEFORE the revision bar.
            if current is not None:
                prev_tm = daybars[idx - 1]["cntr_tm"] if idx > 0 else current["start_time"]
                intervals.append(close_interval(current, prev_tm, post_bars))

            post_bars = []

            if running_high is not None and running_low is not None and running_high > running_low:
                if new_high and new_low:
                    reason = "DAY_HIGH_AND_LOW_UPDATE"
                elif new_high:
                    reason = "DAY_HIGH_UPDATE"
                else:
                    reason = "DAY_LOW_UPDATE"

                fib38 = running_low + (running_high - running_low) * 0.618
                wave_pct = (running_high - running_low) / running_low * 100.0

                current = {
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "trade_date": dt,
                    "interval_no": len(intervals) + 1,
                    "start_time": b["cntr_tm"],
                    "end_time": "",
                    "revision_reason": reason,
                    "day_low": fmt(running_low),
                    "day_low_time": running_low_time,
                    "day_high": fmt(running_high),
                    "day_high_time": running_high_time,
                    "wave_pct": fmt(wave_pct),
                    "fib38": fmt(fib38),
                    "_fib38": fib38,
                    "is_final_active_interval": "N",
                }
            else:
                current = None

            # Revision bar itself is never counted as its own pullback.
            continue

        if current is not None:
            post_bars.append(b)

    if current is not None:
        intervals.append(close_interval(current, daybars[-1]["cntr_tm"], post_bars))

    if intervals:
        intervals[-1]["is_final_active_interval"] = "Y"

    # Renumber defensively after closes.
    for i, r in enumerate(intervals, 1):
        r["interval_no"] = i

    exact_intervals = [r for r in intervals if r.get("has_exact_touch") == "Y"]
    post_intervals = [r for r in intervals if int(r.get("post_revision_bar_count") or 0) > 0]

    first_exact = exact_intervals[0] if exact_intervals else None

    nearest_candidates = [
        r for r in intervals
        if sf(r.get("nearest_distance_pct")) is not None
    ]
    best_nearest = (
        min(nearest_candidates, key=lambda r: sf(r.get("nearest_distance_pct")))
        if nearest_candidates else None
    )

    final = intervals[-1] if intervals else None

    summary = {
        "stock_code": code,
        "stock_name": name,
        "market": market,
        "trade_date": dt,
        "traded_value_eok": cand.get("traded_value_eok", ""),
        "m_value_eok": cand.get("m_value_eok", ""),
        "m_ratio_pct": cand.get("m_ratio_pct", ""),
        "bar_count": len(daybars),
        "day_open": fmt(daybars[0]["open"]),
        "day_high": fmt(max(b["high"] for b in daybars)),
        "day_low": fmt(min(b["low"] for b in daybars)),
        "day_close": fmt(daybars[-1]["close"]),
        "active_interval_count": len(intervals),
        "intervals_with_post_revision_bars": len(post_intervals),
        "intervals_with_exact_touch": len(exact_intervals),

        "first_exact_touch_interval_no": first_exact["interval_no"] if first_exact else "",
        "first_exact_touch_time": first_exact["first_exact_touch_time"] if first_exact else "",
        "first_exact_touch_fib38": first_exact["fib38"] if first_exact else "",
        "first_exact_touch_low": first_exact["first_exact_touch_low"] if first_exact else "",
        "first_exact_touch_high": first_exact["first_exact_touch_high"] if first_exact else "",
        "first_exact_touch_minutes_by_bar_count": (
            first_exact["minutes_by_bar_count_to_exact_touch"] if first_exact else ""
        ),

        "best_nearest_interval_no": best_nearest["interval_no"] if best_nearest else "",
        "best_nearest_time": best_nearest["nearest_time"] if best_nearest else "",
        "best_nearest_fib38": best_nearest["fib38"] if best_nearest else "",
        "best_nearest_price": best_nearest["nearest_price"] if best_nearest else "",
        "best_nearest_distance_pct": best_nearest["nearest_distance_pct"] if best_nearest else "",
        "best_nearest_relation": best_nearest["nearest_relation"] if best_nearest else "",

        "final_active_interval_no": final["interval_no"] if final else "",
        "final_active_start_time": final["start_time"] if final else "",
        "final_active_day_low": final["day_low"] if final else "",
        "final_active_day_high": final["day_high"] if final else "",
        "final_active_fib38": final["fib38"] if final else "",
        "final_active_exact_touch_time": final["first_exact_touch_time"] if final else "",
        "final_active_nearest_distance_pct": final["nearest_distance_pct"] if final else "",

        "diagnostic_status": "OK" if intervals else "NO_VALID_DYNAMIC_RANGE",
    }

    return summary, intervals


def median(vals):
    vals = sorted(vals)
    n = len(vals)
    if n == 0:
        return None
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def main():
    base = Path(__file__).resolve().parent
    input_path = base / INPUT_FILE

    if not input_path.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    candidates = read_csv(input_path)

    print("=" * 84)
    print("RS20 Dynamic Reverse-Fib38 First-Pullback Diagnostic v1")
    print(f"INPUT NUMERIC CANDIDATES : {len(candidates):,}")
    print("SOURCE FORMULA: DayHigh / DayLow dynamic Reverse-Fib38")
    print("LOCAL CACHE ONLY / NO Kiwoom API / NO ORDER API")
    print("NO invented '38 vicinity' tolerance")
    print("=" * 84)

    by_stock = defaultdict(list)
    for c in candidates:
        by_stock[norm_code(c.get("stock_code", ""))].append(c)

    summary_rows = []
    interval_rows = []
    unavailable_rows = []

    stock_cache_hits = 0
    date_cache_hits = 0

    for si, (code, items) in enumerate(sorted(by_stock.items()), 1):
        stock_path = base / STOCK_CACHE_ROOT / f"{code}.csv.gz"
        stock_bars = None

        if stock_path.exists():
            stock_bars = load_gzip_bars(stock_path)
            stock_cache_hits += 1

        for cand in items:
            dt = str(cand.get("trade_date", "")).strip()
            daybars = []

            if stock_bars is not None:
                daybars = [b for tm, b in stock_bars.items() if tm.startswith(dt)]

            if not daybars:
                p = find_date_cache(base, code, dt)
                if p:
                    db = load_gzip_bars(p)
                    daybars = [b for tm, b in db.items() if tm.startswith(dt)]
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

            s, intervals = analyze_candidate(cand, daybars)
            if s:
                summary_rows.append(s)
            interval_rows.extend(intervals)

        if si % 25 == 0 or si == len(by_stock):
            print(
                f"[{si:03d}/{len(by_stock)} stocks] "
                f"summary {len(summary_rows):,} / "
                f"active intervals {len(interval_rows):,} / "
                f"unavailable {len(unavailable_rows):,}"
            )

    summary_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))
    interval_rows.sort(
        key=lambda r: (r["trade_date"], r["stock_code"], int(r["interval_no"]))
    )
    unavailable_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    write_csv(base / OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(base / OUT_INTERVALS, INTERVAL_FIELDS, interval_rows)
    write_csv(base / OUT_UNAVAILABLE, UNAVAILABLE_FIELDS, unavailable_rows)

    ok = [r for r in summary_rows if r["diagnostic_status"] == "OK"]
    any_exact = [r for r in ok if int(r["intervals_with_exact_touch"] or 0) > 0]

    nearest_vals = [
        sf(r["best_nearest_distance_pct"])
        for r in ok
        if sf(r["best_nearest_distance_pct"]) is not None
    ]

    first_touch_minutes = [
        sf(r["first_exact_touch_minutes_by_bar_count"])
        for r in any_exact
        if sf(r["first_exact_touch_minutes_by_bar_count"]) is not None
    ]

    lines = [
        "RS20 Dynamic Reverse-Fib38 First-Pullback Diagnostic v1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"input_numeric_candidates: {len(candidates)}",
        f"analyzed_candidates: {len(summary_rows)}",
        f"unavailable_local_cache_dates: {len(unavailable_rows)}",
        f"unique_candidate_stocks: {len(by_stock)}",
        f"stock_cache_files_used: {stock_cache_hits}",
        f"date_cache_fallback_hits: {date_cache_hits}",
        "",
        f"total_active_dynamic_intervals: {len(interval_rows)}",
        f"candidates_with_any_active_exact_touch: {len(any_exact)}",
        f"active_exact_touch_candidate_rate_pct: "
        f"{(len(any_exact)/len(ok)*100.0 if ok else 0):.4f}",
        f"median_best_nearest_distance_pct: "
        f"{(median(nearest_vals) if nearest_vals else 0):.6f}",
        f"median_first_exact_touch_bars_after_revision: "
        f"{(median(first_touch_minutes) if first_touch_minutes else 0):.6f}",
        "",
        "SOURCE BASIS:",
        "- lecture Fibonacci formula uses dayhigh() and daylow().",
        "- lecture 38 line = daylow + (dayhigh-daylow)*0.618.",
        "- old line is superseded immediately when DayHigh or DayLow changes.",
        "",
        "SOURCE-FIDELITY LIMITS:",
        "- exact touch is diagnostic only; source says '38 line vicinity'.",
        "- no +/-N% vicinity tolerance is invented.",
        "- no separate local swing/wave threshold is invented.",
        "- 세력주/수급세력주 is not mechanically defined here.",
        "- 3-wave chart exclusion is not mechanically defined here.",
        "- new-listing period is not mechanically defined here.",
        "- no Kiwoom API and no orders.",
    ]

    (base / OUT_TXT).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 84)
    print("COMPLETE")
    print(f"ANALYZED                   : {len(summary_rows):,} / {len(candidates):,}")
    print(f"LOCAL CACHE UNAVAILABLE    : {len(unavailable_rows):,}")
    print(f"ACTIVE DYNAMIC INTERVALS   : {len(interval_rows):,}")
    print(f"ANY ACTIVE EXACT 38 TOUCH  : {len(any_exact):,}")
    print(f"CANDIDATE SUMMARY          : {OUT_SUMMARY}")
    print(f"ACTIVE INTERVAL DETAIL     : {OUT_INTERVALS}")
    print(f"UNAVAILABLE                : {OUT_UNAVAILABLE}")
    print(f"SUMMARY TXT                : {OUT_TXT}")
    print("=" * 84)


if __name__ == "__main__":
    main()

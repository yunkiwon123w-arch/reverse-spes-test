# -*- coding: utf-8 -*-
"""
RS20 SOURCE EVENT STATE MACHINE v1.1
====================================

FIX FROM v1
- A CORE_ON transition bar can no longer count as the "first pullback" bar.
- Pullback diagnostics begin from the NEXT 1-minute bar after each CORE_ON event.
- Each CORE_ON -> CORE_OFF segment is handled independently.
- If CORE turns ON again later, a new segment starts and again skips its own
  transition bar for pullback detection.

WHY
The source concept is sequential:
    numeric/core condition forms -> later price pulls back toward Reverse 38.
Counting the same 1-minute bar as both "condition formation" and "later pullback"
breaks that temporal order.

This is NOT a new "wait 1 minute" trading rule.
It is only causal ordering: the event-defining bar cannot also be the subsequent
pullback event.

SOURCE-MECHANICAL RULES
1) Dynamic Reverse Fibonacci:
      day_high = running DayHigh()
      day_low  = running DayLow()
      fib38    = day_low + (day_high - day_low) * 0.618

2) M indicator:
      typical = (H+O+L+C)/4
      signed amount =
          + typical*V/1e8  if C>O
          - typical*V/1e8  if C<O
          0                 if C==O
      M = cumulative signed amount for trading day

3) Numeric core:
      M >= 200 eok
      M / cumulative reconstructed traded value >= 20%

NOT INVENTED
- no numeric tolerance for "38선 부근"
- no minimum wave-rise %
- no minimum wait minutes
- no mechanical 세력주/수급세력주 classification
- no mechanical 3파 definition
- no new-listing period

NO Kiwoom API.
NO order API.
"""

import csv
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

INPUT_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_SUMMARY = "rs20_source_event_state_machine_candidate_summary_v1_1.csv"
OUT_SEGMENTS = "rs20_source_event_state_machine_segments_v1_1.csv"
OUT_EVENTS = "rs20_source_event_state_machine_events_v1_1.csv"
OUT_UNAVAILABLE = "rs20_source_event_state_machine_unavailable_v1_1.csv"
OUT_TXT = "rs20_source_event_state_machine_summary_v1_1.txt"

M_MIN_EOK = 200.0
M_RATIO_MIN_PCT = 20.0

SUMMARY_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "eod_traded_value_eok", "eod_m_value_eok", "eod_m_ratio_pct",
    "bar_count",
    "day_open", "day_high", "day_low", "day_close",

    "core_segment_count",
    "core_on_minute_count",
    "core_turned_off_after_first_on",

    "first_core_on_time",
    "first_core_on_m_eok",
    "first_core_on_ratio_pct",
    "first_core_on_fib38",

    "segments_with_post_start_bars",
    "segments_with_exact_touch_after_start",
    "candidate_has_exact_touch_after_core_start",

    "first_valid_touch_segment_no",
    "first_valid_touch_time",
    "first_valid_touch_fib38",
    "first_valid_touch_low",
    "first_valid_touch_high",
    "bars_after_segment_start_to_touch",

    "nearest_after_core_start_time",
    "nearest_after_core_start_fib38",
    "nearest_after_core_start_price",
    "nearest_after_core_start_distance_pct",
    "nearest_after_core_start_relation",

    "diagnostic_status"
]

SEGMENT_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "segment_no",
    "core_on_time",
    "core_off_time",
    "segment_end_time",
    "core_on_m_eok",
    "core_on_cum_turnover_eok",
    "core_on_ratio_pct",
    "core_on_day_low",
    "core_on_day_high",
    "core_on_fib38",

    "post_start_bar_count",
    "first_valid_exact_touch_time",
    "first_valid_exact_touch_fib38",
    "first_valid_exact_touch_low",
    "first_valid_exact_touch_high",
    "bars_after_segment_start_to_touch",

    "nearest_time",
    "nearest_fib38",
    "nearest_price",
    "nearest_distance_pct",
    "nearest_relation",

    "has_valid_exact_touch_after_start",
    "segment_status"
]

EVENT_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "event_no", "segment_no", "event_type", "event_time",
    "m_eok", "cum_turnover_eok", "m_ratio_pct",
    "day_low", "day_high", "fib38",
    "bar_low", "bar_high", "bar_close",
    "fib38_distance_pct", "fib38_relation"
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


def bar_distance_to_line(bar, line):
    if line is None or line <= 0:
        return None, None, ""

    if bar["low"] <= line <= bar["high"]:
        return 0.0, line, "TOUCH"

    if bar["low"] > line:
        d = (bar["low"] - line) / line * 100.0
        return abs(d), bar["low"], "ABOVE"

    d = (bar["high"] - line) / line * 100.0
    return abs(d), bar["high"], "BELOW"


def analyze_candidate(cand, daybars):
    code = norm_code(cand.get("stock_code", ""))
    name = cand.get("stock_name", "")
    market = cand.get("market", "")
    dt = str(cand.get("trade_date", "")).strip()

    daybars = sorted(daybars, key=lambda x: x["cntr_tm"])
    if not daybars:
        return None, [], []

    running_high = None
    running_low = None
    cum_m = 0.0
    cum_turnover = 0.0

    prev_core = False
    core_on_minute_count = 0

    first_core = None
    core_turned_off_after_first_on = False

    current_segment = None
    segments = []
    events = []
    event_no = 0
    segment_no = 0

    for idx, b in enumerate(daybars):
        running_high = b["high"] if running_high is None else max(running_high, b["high"])
        running_low = b["low"] if running_low is None else min(running_low, b["low"])

        typical = (b["high"] + b["open"] + b["low"] + b["close"]) / 4.0
        turnover_eok = typical * b["volume"] / 100000000.0
        cum_turnover += turnover_eok

        if b["close"] > b["open"]:
            cum_m += turnover_eok
        elif b["close"] < b["open"]:
            cum_m -= turnover_eok

        ratio_pct = cum_m / cum_turnover * 100.0 if cum_turnover > 0 else None

        fib38 = None
        if running_high > running_low:
            fib38 = running_low + (running_high - running_low) * 0.618

        core_on = (
            cum_m >= M_MIN_EOK
            and ratio_pct is not None
            and ratio_pct >= M_RATIO_MIN_PCT
        )

        dist, near_price, relation = bar_distance_to_line(b, fib38)

        # CORE ON transition
        if core_on and not prev_core:
            segment_no += 1
            event_no += 1

            current_segment = {
                "stock_code": code,
                "stock_name": name,
                "market": market,
                "trade_date": dt,
                "segment_no": segment_no,
                "core_on_time": b["cntr_tm"],
                "core_off_time": "",
                "segment_end_time": "",
                "core_on_m_eok": fmt(cum_m),
                "core_on_cum_turnover_eok": fmt(cum_turnover),
                "core_on_ratio_pct": fmt(ratio_pct),
                "core_on_day_low": fmt(running_low),
                "core_on_day_high": fmt(running_high),
                "core_on_fib38": fmt(fib38),

                "_start_idx": idx,
                "_post_start_bar_count": 0,
                "_first_touch_idx": None,
                "_first_touch_time": "",
                "_first_touch_fib38": None,
                "_first_touch_low": None,
                "_first_touch_high": None,

                "_nearest_time": "",
                "_nearest_fib38": None,
                "_nearest_price": None,
                "_nearest_distance": None,
                "_nearest_relation": "",
            }

            events.append({
                "stock_code": code,
                "stock_name": name,
                "market": market,
                "trade_date": dt,
                "event_no": event_no,
                "segment_no": segment_no,
                "event_type": "CORE_ON",
                "event_time": b["cntr_tm"],
                "m_eok": fmt(cum_m),
                "cum_turnover_eok": fmt(cum_turnover),
                "m_ratio_pct": fmt(ratio_pct),
                "day_low": fmt(running_low),
                "day_high": fmt(running_high),
                "fib38": fmt(fib38),
                "bar_low": fmt(b["low"]),
                "bar_high": fmt(b["high"]),
                "bar_close": fmt(b["close"]),
                "fib38_distance_pct": fmt(dist) if dist is not None else "",
                "fib38_relation": relation,
            })

            if first_core is None:
                first_core = {
                    "time": b["cntr_tm"],
                    "m": cum_m,
                    "ratio": ratio_pct,
                    "fib38": fib38,
                }

            # CRITICAL FIX:
            # Do NOT test this CORE_ON bar itself as a pullback bar.

        # Continuing inside an already-open CORE segment
        elif core_on and prev_core:
            if current_segment is not None:
                current_segment["_post_start_bar_count"] += 1

                if dist is not None:
                    old = current_segment["_nearest_distance"]
                    if old is None or dist < old:
                        current_segment["_nearest_distance"] = dist
                        current_segment["_nearest_time"] = b["cntr_tm"]
                        current_segment["_nearest_fib38"] = fib38
                        current_segment["_nearest_price"] = near_price
                        current_segment["_nearest_relation"] = relation

                exact_touch = (
                    fib38 is not None
                    and b["low"] <= fib38 <= b["high"]
                )

                if exact_touch and current_segment["_first_touch_idx"] is None:
                    current_segment["_first_touch_idx"] = idx
                    current_segment["_first_touch_time"] = b["cntr_tm"]
                    current_segment["_first_touch_fib38"] = fib38
                    current_segment["_first_touch_low"] = b["low"]
                    current_segment["_first_touch_high"] = b["high"]

                    event_no += 1
                    events.append({
                        "stock_code": code,
                        "stock_name": name,
                        "market": market,
                        "trade_date": dt,
                        "event_no": event_no,
                        "segment_no": current_segment["segment_no"],
                        "event_type": "FIRST_VALID_EXACT_38_TOUCH_AFTER_CORE_START",
                        "event_time": b["cntr_tm"],
                        "m_eok": fmt(cum_m),
                        "cum_turnover_eok": fmt(cum_turnover),
                        "m_ratio_pct": fmt(ratio_pct),
                        "day_low": fmt(running_low),
                        "day_high": fmt(running_high),
                        "fib38": fmt(fib38),
                        "bar_low": fmt(b["low"]),
                        "bar_high": fmt(b["high"]),
                        "bar_close": fmt(b["close"]),
                        "fib38_distance_pct": fmt(dist),
                        "fib38_relation": relation,
                    })

        # CORE OFF transition
        elif (not core_on) and prev_core:
            core_turned_off_after_first_on = True

            if current_segment is not None:
                current_segment["core_off_time"] = b["cntr_tm"]
                current_segment["segment_end_time"] = daybars[idx - 1]["cntr_tm"] if idx > 0 else current_segment["core_on_time"]
                segments.append(current_segment)
                current_segment = None

            event_no += 1
            events.append({
                "stock_code": code,
                "stock_name": name,
                "market": market,
                "trade_date": dt,
                "event_no": event_no,
                "segment_no": segment_no,
                "event_type": "CORE_OFF",
                "event_time": b["cntr_tm"],
                "m_eok": fmt(cum_m),
                "cum_turnover_eok": fmt(cum_turnover),
                "m_ratio_pct": fmt(ratio_pct) if ratio_pct is not None else "",
                "day_low": fmt(running_low),
                "day_high": fmt(running_high),
                "fib38": fmt(fib38),
                "bar_low": fmt(b["low"]),
                "bar_high": fmt(b["high"]),
                "bar_close": fmt(b["close"]),
                "fib38_distance_pct": fmt(dist) if dist is not None else "",
                "fib38_relation": relation,
            })

        if core_on:
            core_on_minute_count += 1

        prev_core = core_on

    # Close an open segment at EOD
    if current_segment is not None:
        current_segment["segment_end_time"] = daybars[-1]["cntr_tm"]
        segments.append(current_segment)

    # Finalize segment public fields
    public_segments = []
    for seg in segments:
        first_idx = seg["_first_touch_idx"]
        start_idx = seg["_start_idx"]

        public_segments.append({
            "stock_code": seg["stock_code"],
            "stock_name": seg["stock_name"],
            "market": seg["market"],
            "trade_date": seg["trade_date"],
            "segment_no": seg["segment_no"],
            "core_on_time": seg["core_on_time"],
            "core_off_time": seg["core_off_time"],
            "segment_end_time": seg["segment_end_time"],
            "core_on_m_eok": seg["core_on_m_eok"],
            "core_on_cum_turnover_eok": seg["core_on_cum_turnover_eok"],
            "core_on_ratio_pct": seg["core_on_ratio_pct"],
            "core_on_day_low": seg["core_on_day_low"],
            "core_on_day_high": seg["core_on_day_high"],
            "core_on_fib38": seg["core_on_fib38"],

            "post_start_bar_count": seg["_post_start_bar_count"],
            "first_valid_exact_touch_time": seg["_first_touch_time"],
            "first_valid_exact_touch_fib38": fmt(seg["_first_touch_fib38"]) if seg["_first_touch_fib38"] is not None else "",
            "first_valid_exact_touch_low": fmt(seg["_first_touch_low"]) if seg["_first_touch_low"] is not None else "",
            "first_valid_exact_touch_high": fmt(seg["_first_touch_high"]) if seg["_first_touch_high"] is not None else "",
            "bars_after_segment_start_to_touch": (
                first_idx - start_idx
                if first_idx is not None else ""
            ),

            "nearest_time": seg["_nearest_time"],
            "nearest_fib38": fmt(seg["_nearest_fib38"]) if seg["_nearest_fib38"] is not None else "",
            "nearest_price": fmt(seg["_nearest_price"]) if seg["_nearest_price"] is not None else "",
            "nearest_distance_pct": fmt(seg["_nearest_distance"]) if seg["_nearest_distance"] is not None else "",
            "nearest_relation": seg["_nearest_relation"],

            "has_valid_exact_touch_after_start": "Y" if first_idx is not None else "N",
            "segment_status": (
                "NO_POST_START_BAR"
                if seg["_post_start_bar_count"] == 0
                else "VALID_TOUCH"
                if first_idx is not None
                else "NO_EXACT_TOUCH"
            ),
        })

    valid_touch_segments = [
        s for s in public_segments
        if s["has_valid_exact_touch_after_start"] == "Y"
    ]
    post_start_segments = [
        s for s in public_segments
        if int(s["post_start_bar_count"]) > 0
    ]

    first_valid_touch = valid_touch_segments[0] if valid_touch_segments else None

    nearest_segments = [
        s for s in public_segments
        if sf(s["nearest_distance_pct"]) is not None
    ]
    best_nearest = (
        min(nearest_segments, key=lambda x: sf(x["nearest_distance_pct"]))
        if nearest_segments else None
    )

    summary = {
        "stock_code": code,
        "stock_name": name,
        "market": market,
        "trade_date": dt,
        "eod_traded_value_eok": cand.get("traded_value_eok", ""),
        "eod_m_value_eok": cand.get("m_value_eok", ""),
        "eod_m_ratio_pct": cand.get("m_ratio_pct", ""),
        "bar_count": len(daybars),
        "day_open": fmt(daybars[0]["open"]),
        "day_high": fmt(max(b["high"] for b in daybars)),
        "day_low": fmt(min(b["low"] for b in daybars)),
        "day_close": fmt(daybars[-1]["close"]),

        "core_segment_count": len(public_segments),
        "core_on_minute_count": core_on_minute_count,
        "core_turned_off_after_first_on": "Y" if core_turned_off_after_first_on else "N",

        "first_core_on_time": first_core["time"] if first_core else "",
        "first_core_on_m_eok": fmt(first_core["m"]) if first_core else "",
        "first_core_on_ratio_pct": fmt(first_core["ratio"]) if first_core else "",
        "first_core_on_fib38": fmt(first_core["fib38"]) if first_core and first_core["fib38"] is not None else "",

        "segments_with_post_start_bars": len(post_start_segments),
        "segments_with_exact_touch_after_start": len(valid_touch_segments),
        "candidate_has_exact_touch_after_core_start": "Y" if first_valid_touch else "N",

        "first_valid_touch_segment_no": first_valid_touch["segment_no"] if first_valid_touch else "",
        "first_valid_touch_time": first_valid_touch["first_valid_exact_touch_time"] if first_valid_touch else "",
        "first_valid_touch_fib38": first_valid_touch["first_valid_exact_touch_fib38"] if first_valid_touch else "",
        "first_valid_touch_low": first_valid_touch["first_valid_exact_touch_low"] if first_valid_touch else "",
        "first_valid_touch_high": first_valid_touch["first_valid_exact_touch_high"] if first_valid_touch else "",
        "bars_after_segment_start_to_touch": first_valid_touch["bars_after_segment_start_to_touch"] if first_valid_touch else "",

        "nearest_after_core_start_time": best_nearest["nearest_time"] if best_nearest else "",
        "nearest_after_core_start_fib38": best_nearest["nearest_fib38"] if best_nearest else "",
        "nearest_after_core_start_price": best_nearest["nearest_price"] if best_nearest else "",
        "nearest_after_core_start_distance_pct": best_nearest["nearest_distance_pct"] if best_nearest else "",
        "nearest_after_core_start_relation": best_nearest["nearest_relation"] if best_nearest else "",

        "diagnostic_status": "OK" if first_core else "NO_INTRADAY_CORE_ON",
    }

    return summary, public_segments, events


def median(vals):
    vals = sorted(vals)
    n = len(vals)
    if not vals:
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

    print("=" * 88)
    print("RS20 SOURCE EVENT STATE MACHINE v1.1")
    print(f"INPUT NUMERIC CANDIDATES : {len(candidates):,}")
    print("FIX: CORE_ON transition bar is excluded from subsequent pullback detection")
    print("LOCAL CACHE ONLY / NO Kiwoom API / NO ORDER API")
    print("=" * 88)

    by_stock = defaultdict(list)
    for c in candidates:
        by_stock[norm_code(c.get("stock_code", ""))].append(c)

    summary_rows = []
    segment_rows = []
    event_rows = []
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

            s, segs, evs = analyze_candidate(cand, daybars)
            if s:
                summary_rows.append(s)
            segment_rows.extend(segs)
            event_rows.extend(evs)

        if si % 25 == 0 or si == len(by_stock):
            print(
                f"[{si:03d}/{len(by_stock)} stocks] "
                f"summary {len(summary_rows):,} / "
                f"segments {len(segment_rows):,} / "
                f"events {len(event_rows):,} / "
                f"unavailable {len(unavailable_rows):,}"
            )

    summary_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))
    segment_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"], int(r["segment_no"])))
    event_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"], int(r["event_no"])))
    unavailable_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    write_csv(base / OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(base / OUT_SEGMENTS, SEGMENT_FIELDS, segment_rows)
    write_csv(base / OUT_EVENTS, EVENT_FIELDS, event_rows)
    write_csv(base / OUT_UNAVAILABLE, UNAVAILABLE_FIELDS, unavailable_rows)

    ok = [r for r in summary_rows if r["diagnostic_status"] == "OK"]
    touched = [
        r for r in ok
        if r["candidate_has_exact_touch_after_core_start"] == "Y"
    ]

    multi_segment = [
        r for r in ok
        if int(r["core_segment_count"] or 0) > 1
    ]

    no_post = [
        s for s in segment_rows
        if s["segment_status"] == "NO_POST_START_BAR"
    ]

    touch_bars = [
        sf(r["bars_after_segment_start_to_touch"])
        for r in touched
        if sf(r["bars_after_segment_start_to_touch"]) is not None
    ]

    nearest_vals = [
        sf(r["nearest_after_core_start_distance_pct"])
        for r in ok
        if sf(r["nearest_after_core_start_distance_pct"]) is not None
    ]

    lines = [
        "RS20 SOURCE EVENT STATE MACHINE v1.1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"input_numeric_candidates: {len(candidates)}",
        f"analyzed_candidates: {len(summary_rows)}",
        f"unavailable_local_cache_dates: {len(unavailable_rows)}",
        f"unique_candidate_stocks: {len(by_stock)}",
        f"stock_cache_files_used: {stock_cache_hits}",
        f"date_cache_fallback_hits: {date_cache_hits}",
        "",
        f"intraday_core_on_candidates: {len(ok)}",
        f"total_core_segments: {len(segment_rows)}",
        f"multi_core_segment_candidates: {len(multi_segment)}",
        f"segments_without_any_post_start_bar: {len(no_post)}",
        f"valid_exact_touch_after_core_start_candidates: {len(touched)}",
        f"valid_exact_touch_rate_pct: "
        f"{(len(touched)/len(ok)*100.0 if ok else 0):.4f}",
        f"median_bars_after_segment_start_to_touch: "
        f"{(median(touch_bars) if touch_bars else 0):.6f}",
        f"median_nearest_distance_pct_after_core_start: "
        f"{(median(nearest_vals) if nearest_vals else 0):.6f}",
        "",
        "V1.1 CAUSAL FIX:",
        "- the CORE_ON transition bar cannot count as the subsequent pullback.",
        "- pullback inspection starts on the next 1-minute bar.",
        "- each CORE_ON segment is handled independently.",
        "- a later CORE re-entry creates a new segment.",
        "",
        "NOT A NEW SOURCE THRESHOLD:",
        "- this is causal ordering, not a 1-minute waiting strategy rule.",
        "- no numeric tolerance for '38 line vicinity' is added.",
        "",
        "NO Kiwoom API / NO orders.",
    ]

    (base / OUT_TXT).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 88)
    print("COMPLETE")
    print(f"ANALYZED                      : {len(summary_rows):,} / {len(candidates):,}")
    print(f"LOCAL CACHE UNAVAILABLE       : {len(unavailable_rows):,}")
    print(f"TOTAL CORE SEGMENTS           : {len(segment_rows):,}")
    print(f"MULTI-SEGMENT CANDIDATES      : {len(multi_segment):,}")
    print(f"VALID EXACT 38 AFTER CORE     : {len(touched):,}")
    print(f"CANDIDATE SUMMARY             : {OUT_SUMMARY}")
    print(f"SEGMENT DETAIL                : {OUT_SEGMENTS}")
    print(f"STATE EVENTS                  : {OUT_EVENTS}")
    print(f"UNAVAILABLE                   : {OUT_UNAVAILABLE}")
    print(f"SUMMARY TXT                   : {OUT_TXT}")
    print("=" * 88)


if __name__ == "__main__":
    main()

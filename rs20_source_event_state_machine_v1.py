# -*- coding: utf-8 -*-
"""
RS20 SOURCE EVENT STATE MACHINE v1
==================================

PURPOSE
Reconstruct RS20 intraday conditions from the source-faithful numeric rules
using LOCAL 1-minute OHLCV only.

NO invented thresholds.

Source-mechanical rules used
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
      M = cumulative signed amount for the trading day

3) RS20 numeric core:
      M >= 200 eok
      M / cumulative traded value >= 20%

IMPORTANT
- The cumulative traded value below is reconstructed from the same 1-minute
  OHLCV using typical-price * volume. It is used for time-path diagnostics.
- "38 line vicinity" has NO numeric tolerance in the source, so this script
  does NOT create one.
- Exact touch is diagnostic only.
- 세력주/수급세력주 is NOT mechanically classified here.
- 3파 chart exclusion is NOT mechanically classified here.
- 신규상장 period is NOT invented here.
- NO Kiwoom API.
- NO order API.

STATE MODEL
PRE_CORE
  -> CORE_ON when source numeric core is simultaneously satisfied.

After that, every minute records:
- whether CORE is currently ON/OFF
- current DayHigh/DayLow/Fib38
- distance from current bar to the ACTIVE Fib38
- whether exact 38 touch occurs while CORE is ON

The script also records whether the core later turns OFF again.
It does not assume that the first ON state remains valid forever.
"""

import csv
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

INPUT_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_SUMMARY = "rs20_source_event_state_machine_candidate_summary_v1.csv"
OUT_EVENTS = "rs20_source_event_state_machine_events_v1.csv"
OUT_MINUTE = "rs20_source_event_state_machine_core_minutes_v1.csv"
OUT_UNAVAILABLE = "rs20_source_event_state_machine_unavailable_v1.csv"
OUT_TXT = "rs20_source_event_state_machine_summary_v1.txt"

M_MIN_EOK = 200.0
M_RATIO_MIN_PCT = 20.0

SUMMARY_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "eod_traded_value_eok", "eod_m_value_eok", "eod_m_ratio_pct",
    "bar_count",
    "day_open", "day_high", "day_low", "day_close",

    "first_core_on_time",
    "first_core_on_m_eok",
    "first_core_on_cum_turnover_eok",
    "first_core_on_ratio_pct",
    "first_core_on_day_low",
    "first_core_on_day_high",
    "first_core_on_fib38",

    "core_on_minute_count",
    "core_on_segment_count",
    "core_turned_off_after_first_on",

    "first_exact_touch_while_core_on_time",
    "first_exact_touch_while_core_on_fib38",
    "first_exact_touch_while_core_on_low",
    "first_exact_touch_while_core_on_high",
    "bars_from_first_core_on_to_first_exact_touch",

    "nearest_while_core_on_time",
    "nearest_while_core_on_fib38",
    "nearest_while_core_on_price",
    "nearest_while_core_on_distance_pct",
    "nearest_while_core_on_relation",

    "first_core_on_to_eod_high_pct",
    "first_core_on_to_eod_low_pct",

    "has_exact_touch_while_core_on",
    "diagnostic_status"
]

EVENT_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "event_no", "event_type", "event_time",
    "m_eok", "cum_turnover_eok", "m_ratio_pct",
    "day_low", "day_high", "fib38",
    "bar_low", "bar_high", "bar_close",
    "fib38_distance_pct", "fib38_relation"
]

MINUTE_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "cntr_tm",
    "open", "high", "low", "close", "volume",
    "cum_m_eok", "cum_turnover_eok", "m_ratio_pct",
    "day_low", "day_high", "fib38",
    "core_on",
    "fib38_exact_touch",
    "fib38_distance_pct",
    "fib38_relation"
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
    ever_core = False
    core_segment_count = 0
    core_on_minute_count = 0
    core_turned_off_after_first_on = False

    first_core = None
    first_core_idx = None

    first_touch = None
    first_touch_idx = None

    nearest = None
    nearest_distance = None
    nearest_price = None
    nearest_relation = None
    nearest_fib38 = None

    events = []
    core_minutes = []

    event_no = 0

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

        ratio_pct = (
            cum_m / cum_turnover * 100.0
            if cum_turnover > 0 else None
        )

        fib38 = None
        if running_high is not None and running_low is not None and running_high > running_low:
            fib38 = running_low + (running_high - running_low) * 0.618

        core_on = (
            cum_m >= M_MIN_EOK
            and ratio_pct is not None
            and ratio_pct >= M_RATIO_MIN_PCT
        )

        dist, near_price, relation = bar_distance_to_line(b, fib38)

        if core_on:
            core_on_minute_count += 1

            if not prev_core:
                core_segment_count += 1
                event_no += 1
                events.append({
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "trade_date": dt,
                    "event_no": event_no,
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
                        "turnover": cum_turnover,
                        "ratio": ratio_pct,
                        "day_low": running_low,
                        "day_high": running_high,
                        "fib38": fib38,
                        "price": b["close"],
                    }
                    first_core_idx = idx

            if dist is not None and (nearest_distance is None or dist < nearest_distance):
                nearest_distance = dist
                nearest = b
                nearest_price = near_price
                nearest_relation = relation
                nearest_fib38 = fib38

            exact_touch = (
                fib38 is not None and
                b["low"] <= fib38 <= b["high"]
            )

            if exact_touch and first_touch is None:
                first_touch = {
                    "time": b["cntr_tm"],
                    "fib38": fib38,
                    "low": b["low"],
                    "high": b["high"],
                }
                first_touch_idx = idx

                event_no += 1
                events.append({
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "trade_date": dt,
                    "event_no": event_no,
                    "event_type": "FIRST_EXACT_38_TOUCH_WHILE_CORE_ON",
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

            core_minutes.append({
                "stock_code": code,
                "stock_name": name,
                "market": market,
                "trade_date": dt,
                "cntr_tm": b["cntr_tm"],
                "open": fmt(b["open"]),
                "high": fmt(b["high"]),
                "low": fmt(b["low"]),
                "close": fmt(b["close"]),
                "volume": fmt(b["volume"], 0),
                "cum_m_eok": fmt(cum_m),
                "cum_turnover_eok": fmt(cum_turnover),
                "m_ratio_pct": fmt(ratio_pct),
                "day_low": fmt(running_low),
                "day_high": fmt(running_high),
                "fib38": fmt(fib38),
                "core_on": "Y",
                "fib38_exact_touch": "Y" if exact_touch else "N",
                "fib38_distance_pct": fmt(dist) if dist is not None else "",
                "fib38_relation": relation,
            })

            ever_core = True

        else:
            if prev_core:
                core_turned_off_after_first_on = True
                event_no += 1
                events.append({
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "trade_date": dt,
                    "event_no": event_no,
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

        prev_core = core_on

    if first_core is None:
        status = "NO_INTRADAY_CORE_ON"
    else:
        status = "OK"

    first_core_price = first_core["price"] if first_core else None
    eod_high_after = None
    eod_low_after = None

    if first_core_idx is not None:
        after = daybars[first_core_idx:]
        eod_high_after = max(b["high"] for b in after)
        eod_low_after = min(b["low"] for b in after)

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

        "first_core_on_time": first_core["time"] if first_core else "",
        "first_core_on_m_eok": fmt(first_core["m"]) if first_core else "",
        "first_core_on_cum_turnover_eok": fmt(first_core["turnover"]) if first_core else "",
        "first_core_on_ratio_pct": fmt(first_core["ratio"]) if first_core else "",
        "first_core_on_day_low": fmt(first_core["day_low"]) if first_core else "",
        "first_core_on_day_high": fmt(first_core["day_high"]) if first_core else "",
        "first_core_on_fib38": fmt(first_core["fib38"]) if first_core and first_core["fib38"] is not None else "",

        "core_on_minute_count": core_on_minute_count,
        "core_on_segment_count": core_segment_count,
        "core_turned_off_after_first_on": "Y" if core_turned_off_after_first_on else "N",

        "first_exact_touch_while_core_on_time": first_touch["time"] if first_touch else "",
        "first_exact_touch_while_core_on_fib38": fmt(first_touch["fib38"]) if first_touch else "",
        "first_exact_touch_while_core_on_low": fmt(first_touch["low"]) if first_touch else "",
        "first_exact_touch_while_core_on_high": fmt(first_touch["high"]) if first_touch else "",
        "bars_from_first_core_on_to_first_exact_touch": (
            first_touch_idx - first_core_idx
            if first_touch_idx is not None and first_core_idx is not None
            else ""
        ),

        "nearest_while_core_on_time": nearest["cntr_tm"] if nearest else "",
        "nearest_while_core_on_fib38": fmt(nearest_fib38) if nearest_fib38 is not None else "",
        "nearest_while_core_on_price": fmt(nearest_price) if nearest_price is not None else "",
        "nearest_while_core_on_distance_pct": fmt(nearest_distance) if nearest_distance is not None else "",
        "nearest_while_core_on_relation": nearest_relation or "",

        "first_core_on_to_eod_high_pct": (
            fmt((eod_high_after - first_core_price) / first_core_price * 100.0)
            if first_core_price and eod_high_after is not None else ""
        ),
        "first_core_on_to_eod_low_pct": (
            fmt((eod_low_after - first_core_price) / first_core_price * 100.0)
            if first_core_price and eod_low_after is not None else ""
        ),

        "has_exact_touch_while_core_on": "Y" if first_touch else "N",
        "diagnostic_status": status,
    }

    return summary, events, core_minutes


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

    print("=" * 86)
    print("RS20 SOURCE EVENT STATE MACHINE v1")
    print(f"INPUT NUMERIC CANDIDATES : {len(candidates):,}")
    print("LOCAL 1-MINUTE CACHE ONLY")
    print("M>=200 + M/cumulative-turnover>=20% + dynamic DayHigh/DayLow Fib38")
    print("NO Kiwoom API / NO ORDER API / NO invented 38-vicinity tolerance")
    print("=" * 86)

    by_stock = defaultdict(list)
    for c in candidates:
        by_stock[norm_code(c.get("stock_code", ""))].append(c)

    summary_rows = []
    event_rows = []
    minute_rows = []
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

            s, ev, mins = analyze_candidate(cand, daybars)
            if s:
                summary_rows.append(s)
            event_rows.extend(ev)
            minute_rows.extend(mins)

        if si % 25 == 0 or si == len(by_stock):
            print(
                f"[{si:03d}/{len(by_stock)} stocks] "
                f"summary {len(summary_rows):,} / "
                f"events {len(event_rows):,} / "
                f"core-minutes {len(minute_rows):,} / "
                f"unavailable {len(unavailable_rows):,}"
            )

    summary_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))
    event_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"], int(r["event_no"])))
    minute_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"], r["cntr_tm"]))
    unavailable_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    write_csv(base / OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(base / OUT_EVENTS, EVENT_FIELDS, event_rows)
    write_csv(base / OUT_MINUTE, MINUTE_FIELDS, minute_rows)
    write_csv(base / OUT_UNAVAILABLE, UNAVAILABLE_FIELDS, unavailable_rows)

    core_on = [r for r in summary_rows if r["diagnostic_status"] == "OK"]
    no_core = [r for r in summary_rows if r["diagnostic_status"] == "NO_INTRADAY_CORE_ON"]
    exact = [r for r in core_on if r["has_exact_touch_while_core_on"] == "Y"]

    nearest_vals = [
        sf(r["nearest_while_core_on_distance_pct"])
        for r in core_on
        if sf(r["nearest_while_core_on_distance_pct"]) is not None
    ]

    touch_bars = [
        sf(r["bars_from_first_core_on_to_first_exact_touch"])
        for r in exact
        if sf(r["bars_from_first_core_on_to_first_exact_touch"]) is not None
    ]

    lines = [
        "RS20 SOURCE EVENT STATE MACHINE v1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"input_numeric_candidates: {len(candidates)}",
        f"analyzed_candidates: {len(summary_rows)}",
        f"unavailable_local_cache_dates: {len(unavailable_rows)}",
        f"unique_candidate_stocks: {len(by_stock)}",
        f"stock_cache_files_used: {stock_cache_hits}",
        f"date_cache_fallback_hits: {date_cache_hits}",
        "",
        f"intraday_numeric_core_on_candidates: {len(core_on)}",
        f"no_intraday_numeric_core_on_candidates: {len(no_core)}",
        f"exact_38_touch_while_core_on_candidates: {len(exact)}",
        f"exact_touch_rate_among_core_on_pct: "
        f"{(len(exact)/len(core_on)*100.0 if core_on else 0):.4f}",
        f"median_nearest_38_distance_pct_while_core_on: "
        f"{(median(nearest_vals) if nearest_vals else 0):.6f}",
        f"median_bars_from_core_on_to_exact_touch: "
        f"{(median(touch_bars) if touch_bars else 0):.6f}",
        f"total_core_on_minutes_saved: {len(minute_rows)}",
        f"total_state_events_saved: {len(event_rows)}",
        "",
        "SOURCE-MECHANICAL RULES USED:",
        "- cumulative M >= 200 eok",
        "- cumulative M / cumulative reconstructed traded value >= 20%",
        "- dynamic DayHigh/DayLow Reverse Fib38",
        "",
        "NOT AUTOMATED / NOT INVENTED:",
        "- numeric tolerance for '38 line vicinity'",
        "- 세력주 / 수급세력주 classification",
        "- 3-wave chart definition",
        "- new-listing period",
        "",
        "NOTE:",
        "- cumulative traded value is reconstructed from 1-minute typical-price*volume.",
        "- end-of-day candidate file remains the frozen numeric universe.",
        "- this output is diagnostic; it does not declare final RS20 trades.",
        "- NO Kiwoom API and NO orders.",
    ]

    (base / OUT_TXT).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 86)
    print("COMPLETE")
    print(f"ANALYZED                    : {len(summary_rows):,} / {len(candidates):,}")
    print(f"LOCAL CACHE UNAVAILABLE     : {len(unavailable_rows):,}")
    print(f"INTRADAY CORE ON            : {len(core_on):,}")
    print(f"NO INTRADAY CORE ON         : {len(no_core):,}")
    print(f"EXACT 38 TOUCH WHILE CORE   : {len(exact):,}")
    print(f"CORE-ON MINUTES SAVED       : {len(minute_rows):,}")
    print(f"CANDIDATE SUMMARY           : {OUT_SUMMARY}")
    print(f"STATE EVENTS                : {OUT_EVENTS}")
    print(f"CORE MINUTES                : {OUT_MINUTE}")
    print(f"UNAVAILABLE                 : {OUT_UNAVAILABLE}")
    print(f"SUMMARY TXT                 : {OUT_TXT}")
    print("=" * 86)


if __name__ == "__main__":
    main()

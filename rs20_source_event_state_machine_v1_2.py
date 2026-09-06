# -*- coding: utf-8 -*-
"""
RS20 SOURCE EVENT STATE MACHINE v1.2
====================================

SOURCE-EVENT MODEL
- One stock/date = at most ONE RS20 intraday event.
- Event activates at the FIRST intraday moment when:
      M >= 200 eok
      AND M / cumulative reconstructed traded value >= 20%
- After activation, later CORE OFF/ON changes DO NOT reset the event.
- The activation bar itself is excluded from "subsequent pullback" detection.
- From the NEXT 1-minute bar through EOD:
      keep dynamic DayHigh / DayLow / Reverse Fib38
      record the FIRST exact Fib38 touch only once
      record nearest distance to Fib38 even if no exact touch occurs.

This removes the v1.1 mistake of treating each later CORE re-entry as a new
"first pullback" opportunity.

IMPORTANT
- Exact touch remains DIAGNOSTIC ONLY.
- The source says "38선 부근"; no numeric tolerance is invented here.
- No minimum wave rise %, no time limit, no M re-entry requirement.
- 세력주/수급세력주 classification remains unresolved.
- 3파 mechanical definition remains unresolved.
- 신규상장 exclusion period remains unresolved.
- NO Kiwoom API.
- NO order API.
"""

import csv
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

INPUT_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_SUMMARY = "rs20_source_event_state_machine_candidate_summary_v1_2.csv"
OUT_EVENTS = "rs20_source_event_state_machine_events_v1_2.csv"
OUT_UNAVAILABLE = "rs20_source_event_state_machine_unavailable_v1_2.csv"
OUT_TXT = "rs20_source_event_state_machine_summary_v1_2.txt"

M_MIN_EOK = 200.0
M_RATIO_MIN_PCT = 20.0

SUMMARY_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "eod_traded_value_eok", "eod_m_value_eok", "eod_m_ratio_pct",
    "bar_count", "day_open", "day_high", "day_low", "day_close",

    "event_activated",
    "event_activation_time",
    "event_activation_m_eok",
    "event_activation_cum_turnover_eok",
    "event_activation_ratio_pct",
    "event_activation_day_low",
    "event_activation_day_high",
    "event_activation_fib38",

    "post_activation_bar_count",

    "core_off_count_after_activation",
    "core_reentry_count_after_activation",
    "core_ever_off_after_activation",

    "first_exact_touch_after_activation_time",
    "first_exact_touch_after_activation_fib38",
    "first_exact_touch_after_activation_low",
    "first_exact_touch_after_activation_high",
    "bars_after_activation_to_first_exact_touch",
    "core_state_at_first_exact_touch",

    "nearest_after_activation_time",
    "nearest_after_activation_fib38",
    "nearest_after_activation_price",
    "nearest_after_activation_distance_pct",
    "nearest_after_activation_relation",
    "core_state_at_nearest",

    "has_exact_touch_after_activation",
    "diagnostic_status"
]

EVENT_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "event_no", "event_type", "event_time",
    "core_on",
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


def event_row(code, name, market, dt, event_no, event_type, b,
              core_on, cum_m, cum_turnover, ratio_pct,
              running_low, running_high, fib38):
    dist, _, relation = bar_distance_to_line(b, fib38)
    return {
        "stock_code": code,
        "stock_name": name,
        "market": market,
        "trade_date": dt,
        "event_no": event_no,
        "event_type": event_type,
        "event_time": b["cntr_tm"],
        "core_on": "Y" if core_on else "N",
        "m_eok": fmt(cum_m),
        "cum_turnover_eok": fmt(cum_turnover),
        "m_ratio_pct": fmt(ratio_pct) if ratio_pct is not None else "",
        "day_low": fmt(running_low),
        "day_high": fmt(running_high),
        "fib38": fmt(fib38) if fib38 is not None else "",
        "bar_low": fmt(b["low"]),
        "bar_high": fmt(b["high"]),
        "bar_close": fmt(b["close"]),
        "fib38_distance_pct": fmt(dist) if dist is not None else "",
        "fib38_relation": relation,
    }


def analyze_candidate(cand, daybars):
    code = norm_code(cand.get("stock_code", ""))
    name = cand.get("stock_name", "")
    market = cand.get("market", "")
    dt = str(cand.get("trade_date", "")).strip()

    daybars = sorted(daybars, key=lambda x: x["cntr_tm"])
    if not daybars:
        return None, []

    running_high = None
    running_low = None
    cum_m = 0.0
    cum_turnover = 0.0

    prev_core = False

    activated = False
    activation_idx = None
    activation = None

    first_touch = None
    first_touch_idx = None
    first_touch_core_on = None

    nearest_bar = None
    nearest_fib38 = None
    nearest_price = None
    nearest_distance = None
    nearest_relation = ""
    nearest_core_on = None

    post_activation_bar_count = 0
    core_off_count = 0
    core_reentry_count = 0
    ever_core_off = False

    events = []
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

        ratio_pct = cum_m / cum_turnover * 100.0 if cum_turnover > 0 else None

        fib38 = None
        if running_high is not None and running_low is not None and running_high > running_low:
            fib38 = running_low + (running_high - running_low) * 0.618

        core_on = (
            cum_m >= M_MIN_EOK
            and ratio_pct is not None
            and ratio_pct >= M_RATIO_MIN_PCT
        )

        # Activate only once per stock/date.
        if not activated and core_on:
            activated = True
            activation_idx = idx
            activation = {
                "time": b["cntr_tm"],
                "m": cum_m,
                "turnover": cum_turnover,
                "ratio": ratio_pct,
                "day_low": running_low,
                "day_high": running_high,
                "fib38": fib38,
            }

            event_no += 1
            events.append(
                event_row(
                    code, name, market, dt,
                    event_no, "RS20_EVENT_ACTIVATED",
                    b, core_on, cum_m, cum_turnover, ratio_pct,
                    running_low, running_high, fib38
                )
            )

            # CAUSAL RULE:
            # activation bar itself is not a subsequent pullback bar.
            prev_core = core_on
            continue

        if activated:
            post_activation_bar_count += 1

            # CORE state changes are logged, but DO NOT reset the event.
            if prev_core and not core_on:
                core_off_count += 1
                ever_core_off = True
                event_no += 1
                events.append(
                    event_row(
                        code, name, market, dt,
                        event_no, "CORE_OFF_AFTER_ACTIVATION",
                        b, core_on, cum_m, cum_turnover, ratio_pct,
                        running_low, running_high, fib38
                    )
                )

            elif (not prev_core) and core_on:
                core_reentry_count += 1
                event_no += 1
                events.append(
                    event_row(
                        code, name, market, dt,
                        event_no, "CORE_REENTRY_SAME_EVENT",
                        b, core_on, cum_m, cum_turnover, ratio_pct,
                        running_low, running_high, fib38
                    )
                )

            dist, near_price, relation = bar_distance_to_line(b, fib38)

            if dist is not None and (nearest_distance is None or dist < nearest_distance):
                nearest_distance = dist
                nearest_bar = b
                nearest_fib38 = fib38
                nearest_price = near_price
                nearest_relation = relation
                nearest_core_on = core_on

            exact_touch = (
                fib38 is not None
                and b["low"] <= fib38 <= b["high"]
            )

            # FIRST touch after activation only. Never reset.
            if exact_touch and first_touch is None:
                first_touch_idx = idx
                first_touch_core_on = core_on
                first_touch = {
                    "time": b["cntr_tm"],
                    "fib38": fib38,
                    "low": b["low"],
                    "high": b["high"],
                }

                event_no += 1
                events.append(
                    event_row(
                        code, name, market, dt,
                        event_no, "FIRST_EXACT_38_TOUCH_SAME_EVENT",
                        b, core_on, cum_m, cum_turnover, ratio_pct,
                        running_low, running_high, fib38
                    )
                )

        prev_core = core_on

    status = "OK" if activated else "NO_INTRADAY_CORE_ON"

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

        "event_activated": "Y" if activated else "N",
        "event_activation_time": activation["time"] if activation else "",
        "event_activation_m_eok": fmt(activation["m"]) if activation else "",
        "event_activation_cum_turnover_eok": fmt(activation["turnover"]) if activation else "",
        "event_activation_ratio_pct": fmt(activation["ratio"]) if activation else "",
        "event_activation_day_low": fmt(activation["day_low"]) if activation else "",
        "event_activation_day_high": fmt(activation["day_high"]) if activation else "",
        "event_activation_fib38": fmt(activation["fib38"]) if activation and activation["fib38"] is not None else "",

        "post_activation_bar_count": post_activation_bar_count,

        "core_off_count_after_activation": core_off_count,
        "core_reentry_count_after_activation": core_reentry_count,
        "core_ever_off_after_activation": "Y" if ever_core_off else "N",

        "first_exact_touch_after_activation_time": first_touch["time"] if first_touch else "",
        "first_exact_touch_after_activation_fib38": fmt(first_touch["fib38"]) if first_touch else "",
        "first_exact_touch_after_activation_low": fmt(first_touch["low"]) if first_touch else "",
        "first_exact_touch_after_activation_high": fmt(first_touch["high"]) if first_touch else "",
        "bars_after_activation_to_first_exact_touch": (
            first_touch_idx - activation_idx
            if first_touch_idx is not None and activation_idx is not None else ""
        ),
        "core_state_at_first_exact_touch": (
            "ON" if first_touch_core_on is True
            else "OFF" if first_touch_core_on is False
            else ""
        ),

        "nearest_after_activation_time": nearest_bar["cntr_tm"] if nearest_bar else "",
        "nearest_after_activation_fib38": fmt(nearest_fib38) if nearest_fib38 is not None else "",
        "nearest_after_activation_price": fmt(nearest_price) if nearest_price is not None else "",
        "nearest_after_activation_distance_pct": fmt(nearest_distance) if nearest_distance is not None else "",
        "nearest_after_activation_relation": nearest_relation,
        "core_state_at_nearest": (
            "ON" if nearest_core_on is True
            else "OFF" if nearest_core_on is False
            else ""
        ),

        "has_exact_touch_after_activation": "Y" if first_touch else "N",
        "diagnostic_status": status,
    }

    return summary, events


def median(vals):
    vals = sorted(vals)
    if not vals:
        return None
    n = len(vals)
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def main():
    base = Path(__file__).resolve().parent
    input_path = base / INPUT_FILE

    if not input_path.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    candidates = read_csv(input_path)

    print("=" * 90)
    print("RS20 SOURCE EVENT STATE MACHINE v1.2")
    print(f"INPUT NUMERIC CANDIDATES : {len(candidates):,}")
    print("ONE STOCK/DATE = ONE CONTINUOUS RS20 EVENT")
    print("CORE OFF/REENTRY DOES NOT RESET FIRST-PULLBACK SEARCH")
    print("LOCAL CACHE ONLY / NO Kiwoom API / NO ORDER API")
    print("=" * 90)

    by_stock = defaultdict(list)
    for c in candidates:
        by_stock[norm_code(c.get("stock_code", ""))].append(c)

    summary_rows = []
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

            s, evs = analyze_candidate(cand, daybars)
            if s:
                summary_rows.append(s)
            event_rows.extend(evs)

        if si % 25 == 0 or si == len(by_stock):
            print(
                f"[{si:03d}/{len(by_stock)} stocks] "
                f"summary {len(summary_rows):,} / "
                f"events {len(event_rows):,} / "
                f"unavailable {len(unavailable_rows):,}"
            )

    summary_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))
    event_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"], int(r["event_no"])))
    unavailable_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    write_csv(base / OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(base / OUT_EVENTS, EVENT_FIELDS, event_rows)
    write_csv(base / OUT_UNAVAILABLE, UNAVAILABLE_FIELDS, unavailable_rows)

    activated = [r for r in summary_rows if r["event_activated"] == "Y"]
    touched = [r for r in activated if r["has_exact_touch_after_activation"] == "Y"]
    touched_core_on = [r for r in touched if r["core_state_at_first_exact_touch"] == "ON"]
    touched_core_off = [r for r in touched if r["core_state_at_first_exact_touch"] == "OFF"]
    ever_off = [r for r in activated if r["core_ever_off_after_activation"] == "Y"]
    reentered = [r for r in activated if int(r["core_reentry_count_after_activation"] or 0) > 0]

    touch_bars = [
        sf(r["bars_after_activation_to_first_exact_touch"])
        for r in touched
        if sf(r["bars_after_activation_to_first_exact_touch"]) is not None
    ]

    nearest_vals = [
        sf(r["nearest_after_activation_distance_pct"])
        for r in activated
        if sf(r["nearest_after_activation_distance_pct"]) is not None
    ]

    no_touch = [r for r in activated if r["has_exact_touch_after_activation"] == "N"]

    near_counts = {}
    for threshold in (0.10, 0.25, 0.50, 1.00, 1.50, 2.00):
        near_counts[threshold] = sum(
            1 for r in no_touch
            if sf(r["nearest_after_activation_distance_pct"]) is not None
            and sf(r["nearest_after_activation_distance_pct"]) <= threshold
        )

    lines = [
        "RS20 SOURCE EVENT STATE MACHINE v1.2",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"input_numeric_candidates: {len(candidates)}",
        f"analyzed_candidates: {len(summary_rows)}",
        f"unavailable_local_cache_dates: {len(unavailable_rows)}",
        f"unique_candidate_stocks: {len(by_stock)}",
        f"stock_cache_files_used: {stock_cache_hits}",
        f"date_cache_fallback_hits: {date_cache_hits}",
        "",
        f"event_activated_candidates: {len(activated)}",
        f"core_ever_off_after_activation: {len(ever_off)}",
        f"core_reentry_after_activation: {len(reentered)}",
        f"first_exact_touch_after_activation: {len(touched)}",
        f"touch_rate_pct: {(len(touched)/len(activated)*100.0 if activated else 0):.4f}",
        f"touch_while_core_on: {len(touched_core_on)}",
        f"touch_while_core_off: {len(touched_core_off)}",
        f"no_exact_touch_after_activation: {len(no_touch)}",
        f"median_bars_activation_to_touch: {(median(touch_bars) if touch_bars else 0):.6f}",
        f"median_nearest_distance_pct_after_activation: {(median(nearest_vals) if nearest_vals else 0):.6f}",
        "",
        "NO-TOUCH NEAREST-DISTANCE DIAGNOSTIC ONLY:",
    ]

    for threshold, count in near_counts.items():
        lines.append(f"<= {threshold:.2f}% : {count}")

    lines += [
        "",
        "V1.2 EVENT RULE:",
        "- one stock/date has one continuous RS20 event.",
        "- event activates at the first intraday numeric-core satisfaction.",
        "- the activation bar itself is excluded from subsequent pullback detection.",
        "- later CORE OFF/ON changes are recorded but DO NOT reset the event.",
        "- the first exact Reverse-38 touch after activation is recorded once only.",
        "",
        "NOT SOURCE RULES / NOT USED AS FILTERS:",
        "- the distance thresholds printed above are diagnostic distributions only.",
        "- no numeric definition of '38선 부근' is invented.",
        "- no minimum wave-rise %, time limit, or CORE re-entry rule is invented.",
        "",
        "UNRESOLVED SOURCE ITEMS:",
        "- 세력주 / 수급세력주 mechanical classification",
        "- 3파 chart mechanical definition",
        "- 신규상장 exclusion period",
        "",
        "NO Kiwoom API / NO orders.",
    ]

    (base / OUT_TXT).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 90)
    print("COMPLETE")
    print(f"ANALYZED                     : {len(summary_rows):,} / {len(candidates):,}")
    print(f"LOCAL CACHE UNAVAILABLE      : {len(unavailable_rows):,}")
    print(f"EVENT ACTIVATED              : {len(activated):,}")
    print(f"CORE EVER OFF AFTER EVENT    : {len(ever_off):,}")
    print(f"CORE REENTRY SAME EVENT      : {len(reentered):,}")
    print(f"FIRST EXACT 38 AFTER EVENT   : {len(touched):,}")
    print(f"  - TOUCH WHILE CORE ON      : {len(touched_core_on):,}")
    print(f"  - TOUCH WHILE CORE OFF     : {len(touched_core_off):,}")
    print(f"NO EXACT TOUCH               : {len(no_touch):,}")
    print(f"CANDIDATE SUMMARY            : {OUT_SUMMARY}")
    print(f"EVENT DETAIL                 : {OUT_EVENTS}")
    print(f"UNAVAILABLE                  : {OUT_UNAVAILABLE}")
    print(f"SUMMARY TXT                  : {OUT_TXT}")
    print("=" * 90)


if __name__ == "__main__":
    main()

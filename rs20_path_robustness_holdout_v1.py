# -*- coding: utf-8 -*-
"""
RS20 PATH ROBUSTNESS / HOLDOUT v1
=================================

Purpose
- Evaluate whether the post-entry rebound structure observed in
  rs20_post_entry_path_diagnostic_v1.csv is stable across time and segments.
- NO Kiwoom API.
- NO order API.
- NO optimization of take-profit / stop-loss thresholds.
- Diagnostic robustness only.

Input
- rs20_post_entry_path_diagnostic_v1.csv

Outputs
- rs20_path_robustness_holdout_v1.csv
- rs20_path_robustness_monthly_v1.csv
- rs20_path_robustness_summary_v1.txt
"""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

INPUT_FILE = "rs20_post_entry_path_diagnostic_v1.csv"

OUT_SPLIT = "rs20_path_robustness_holdout_v1.csv"
OUT_MONTHLY = "rs20_path_robustness_monthly_v1.csv"
OUT_SUMMARY = "rs20_path_robustness_summary_v1.txt"

UP_COLS = [1, 2, 3, 4, 5, 7, 10]
DN_COLS = [1, 2, 3, 4, 5, 7, 10]


def sf(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def parse_date(s):
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d")
    return None


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def pct(n, d):
    return n / d * 100.0 if d else 0.0


def summarize(rows, label, split_order):
    n = len(rows)
    mfes = [sf(r.get("mfe_pct")) for r in rows if sf(r.get("mfe_pct")) is not None]
    maes = [sf(r.get("mae_pct")) for r in rows if sf(r.get("mae_pct")) is not None]
    eods = [sf(r.get("eod_return_pct")) for r in rows if sf(r.get("eod_return_pct")) is not None]

    out = {
        "split_order": split_order,
        "segment": label,
        "n": n,
        "date_start": min((r["trade_date"] for r in rows), default=""),
        "date_end": max((r["trade_date"] for r in rows), default=""),
        "median_mfe_pct": round(median(mfes), 6) if mfes else "",
        "median_mae_pct": round(median(maes), 6) if maes else "",
        "median_eod_return_pct": round(median(eods), 6) if eods else "",
        "eod_positive_n": sum(1 for x in eods if x > 0),
        "eod_positive_pct": round(pct(sum(1 for x in eods if x > 0), len(eods)), 4) if eods else "",
    }

    for x in UP_COLS:
        c = sum(1 for r in rows if str(r.get(f"hit_plus_{x}pct", "")).upper() == "Y")
        out[f"plus_{x}_n"] = c
        out[f"plus_{x}_pct"] = round(pct(c, n), 4) if n else ""

    for x in DN_COLS:
        c = sum(1 for r in rows if str(r.get(f"hit_minus_{x}pct", "")).upper() == "Y")
        out[f"minus_{x}_n"] = c
        out[f"minus_{x}_pct"] = round(pct(c, n), 4) if n else ""

    for p in [1, 2, 3]:
        key = f"first_direction_{p}pct"
        up = sum(1 for r in rows if r.get(key) == "UP_FIRST")
        dn = sum(1 for r in rows if r.get(key) == "DOWN_FIRST")
        amb = sum(1 for r in rows if r.get(key) == "AMBIGUOUS_INTRABAR")
        none = sum(1 for r in rows if r.get(key) == "NONE")
        out[f"fd_{p}_up"] = up
        out[f"fd_{p}_down"] = dn
        out[f"fd_{p}_ambiguous"] = amb
        out[f"fd_{p}_none"] = none

    return out


def main():
    base = Path(__file__).resolve().parent
    inp = base / INPUT_FILE
    if not inp.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    rows = read_csv(inp)
    rows = [r for r in rows if r.get("diagnostic_status") == "OK"]

    for r in rows:
        r["_dt"] = parse_date(r.get("trade_date"))
        r["_year"] = r["_dt"].strftime("%Y") if r["_dt"] else ""
        r["_month"] = r["_dt"].strftime("%Y-%m") if r["_dt"] else ""

    rows = [r for r in rows if r["_dt"]]
    rows.sort(key=lambda r: (r["_dt"], r.get("stock_code", "")))

    n = len(rows)
    if n == 0:
        raise SystemExit("NO VALID ROWS")

    print("=" * 92)
    print("RS20 PATH ROBUSTNESS / HOLDOUT v1")
    print(f"VALID ROWS : {n:,}")
    print("NO Kiwoom API / NO orders / NO threshold optimization")
    print("=" * 92)

    split_rows = []
    order = 1

    split_rows.append(summarize(rows, "ALL", order)); order += 1

    # Chronological 70/30 holdout
    cut70 = int(n * 0.70)
    train70 = rows[:cut70]
    hold30 = rows[cut70:]
    split_rows.append(summarize(train70, "CHRONO_TRAIN_70", order)); order += 1
    split_rows.append(summarize(hold30, "CHRONO_HOLDOUT_30", order)); order += 1

    # Chronological halves
    cut50 = n // 2
    split_rows.append(summarize(rows[:cut50], "CHRONO_FIRST_HALF", order)); order += 1
    split_rows.append(summarize(rows[cut50:], "CHRONO_SECOND_HALF", order)); order += 1

    # CORE state
    for state in ["ON", "OFF"]:
        g = [r for r in rows if str(r.get("core_state_at_entry", "")).upper() == state]
        split_rows.append(summarize(g, f"CORE_{state}_AT_ENTRY", order)); order += 1

    # Market
    markets = sorted(set(str(r.get("market", "")).strip() for r in rows if str(r.get("market", "")).strip()))
    for m in markets:
        g = [r for r in rows if str(r.get("market", "")).strip() == m]
        split_rows.append(summarize(g, f"MARKET_{m}", order)); order += 1

    # Year
    years = sorted(set(r["_year"] for r in rows if r["_year"]))
    for y in years:
        g = [r for r in rows if r["_year"] == y]
        split_rows.append(summarize(g, f"YEAR_{y}", order)); order += 1

    split_fields = [
        "split_order", "segment", "n", "date_start", "date_end",
        "median_mfe_pct", "median_mae_pct", "median_eod_return_pct",
        "eod_positive_n", "eod_positive_pct",
    ]
    for x in UP_COLS:
        split_fields += [f"plus_{x}_n", f"plus_{x}_pct"]
    for x in DN_COLS:
        split_fields += [f"minus_{x}_n", f"minus_{x}_pct"]
    for p in [1, 2, 3]:
        split_fields += [
            f"fd_{p}_up", f"fd_{p}_down",
            f"fd_{p}_ambiguous", f"fd_{p}_none"
        ]

    write_csv(base / OUT_SPLIT, split_fields, split_rows)

    monthly_rows = []
    for month in sorted(set(r["_month"] for r in rows if r["_month"])):
        g = [r for r in rows if r["_month"] == month]
        s = summarize(g, month, 0)
        monthly_rows.append({
            "month": month,
            "n": s["n"],
            "median_mfe_pct": s["median_mfe_pct"],
            "median_mae_pct": s["median_mae_pct"],
            "median_eod_return_pct": s["median_eod_return_pct"],
            "eod_positive_pct": s["eod_positive_pct"],
            "plus_1_pct": s["plus_1_pct"],
            "plus_2_pct": s["plus_2_pct"],
            "plus_3_pct": s["plus_3_pct"],
            "plus_4_pct": s["plus_4_pct"],
            "plus_5_pct": s["plus_5_pct"],
            "minus_1_pct": s["minus_1_pct"],
            "minus_2_pct": s["minus_2_pct"],
            "minus_3_pct": s["minus_3_pct"],
        })

    write_csv(
        base / OUT_MONTHLY,
        [
            "month", "n",
            "median_mfe_pct", "median_mae_pct", "median_eod_return_pct",
            "eod_positive_pct",
            "plus_1_pct", "plus_2_pct", "plus_3_pct", "plus_4_pct", "plus_5_pct",
            "minus_1_pct", "minus_2_pct", "minus_3_pct",
        ],
        monthly_rows
    )

    seg = {r["segment"]: r for r in split_rows}
    allr = seg["ALL"]
    hold = seg["CHRONO_HOLDOUT_30"]

    lines = [
        "RS20 PATH ROBUSTNESS / HOLDOUT v1",
        "",
        f"valid_rows: {n}",
        f"date_start: {rows[0]['trade_date']}",
        f"date_end: {rows[-1]['trade_date']}",
        "",
        "ALL",
        f"median_mfe_pct: {allr['median_mfe_pct']}",
        f"median_mae_pct: {allr['median_mae_pct']}",
        f"median_eod_return_pct: {allr['median_eod_return_pct']}",
        f"eod_positive_pct: {allr['eod_positive_pct']}",
        f"plus_1_pct: {allr['plus_1_pct']}",
        f"plus_2_pct: {allr['plus_2_pct']}",
        f"plus_3_pct: {allr['plus_3_pct']}",
        f"plus_4_pct: {allr['plus_4_pct']}",
        f"plus_5_pct: {allr['plus_5_pct']}",
        "",
        "CHRONO_HOLDOUT_30",
        f"n: {hold['n']}",
        f"date_start: {hold['date_start']}",
        f"date_end: {hold['date_end']}",
        f"median_mfe_pct: {hold['median_mfe_pct']}",
        f"median_mae_pct: {hold['median_mae_pct']}",
        f"median_eod_return_pct: {hold['median_eod_return_pct']}",
        f"eod_positive_pct: {hold['eod_positive_pct']}",
        f"plus_1_pct: {hold['plus_1_pct']}",
        f"plus_2_pct: {hold['plus_2_pct']}",
        f"plus_3_pct: {hold['plus_3_pct']}",
        f"plus_4_pct: {hold['plus_4_pct']}",
        f"plus_5_pct: {hold['plus_5_pct']}",
        "",
        "INTERPRETATION RULES",
        "- This is robustness diagnostics only.",
        "- No TP/SL threshold is optimized or selected.",
        "- Holdout is chronological, not random.",
        "- Monthly/market/core-state splits are descriptive.",
        "- Do not call any positive-rate statistic a final win rate.",
        "",
        "NO Kiwoom API. NO orders.",
    ]

    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 92)
    print("COMPLETE")
    print(f"VALID ROWS              : {n:,}")
    print(f"TRAIN 70                : {len(train70):,}")
    print(f"HOLDOUT 30              : {len(hold30):,}")
    print(f"MONTH GROUPS            : {len(monthly_rows):,}")
    print(f"SPLIT FILE              : {OUT_SPLIT}")
    print(f"MONTHLY FILE            : {OUT_MONTHLY}")
    print(f"SUMMARY                 : {OUT_SUMMARY}")
    print("=" * 92)


if __name__ == "__main__":
    main()

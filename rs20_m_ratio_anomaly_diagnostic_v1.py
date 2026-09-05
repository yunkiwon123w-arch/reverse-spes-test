# -*- coding: utf-8 -*-
"""
RS20 M-ratio anomaly diagnostic v1

Purpose
- Diagnose historical RS20 rows where M / daily traded value > 100%.
- Compare ka10080 minute data with:
    upd_stkpc_tp=1 (adjusted price)
    upd_stkpc_tp=0 (unadjusted price)
- Uses base_dt=trade_date so only the target-date neighborhood is requested.
- NO ORDER API. Read-only diagnostic only.

Input
- rs20_history_numeric_candidates_v1.csv in the same folder

Output
- rs20_m_ratio_anomaly_diagnostic_v1.csv
- rs20_m_ratio_anomaly_summary_v1.txt
"""

import csv
import getpass
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
CHART_URL = f"{BASE_URL}/api/dostk/chart"
API_MINUTE = "ka10080"

API_MIN_INTERVAL = 0.35
RETRY_DELAYS = [1.5, 3.0, 6.0, 10.0]

INPUT_FILE = "rs20_history_numeric_candidates_v1.csv"
OUTPUT_FILE = "rs20_m_ratio_anomaly_diagnostic_v1.csv"
SUMMARY_FILE = "rs20_m_ratio_anomaly_summary_v1.txt"


class RateLimiter:
    def __init__(self, interval):
        self.interval = interval
        self.last = 0.0

    def wait(self):
        gap = time.monotonic() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic()


RATE = RateLimiter(API_MIN_INTERVAL)


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


def get_token(app, secret):
    last_err = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(
                TOKEN_URL,
                json={
                    "grant_type": "client_credentials",
                    "appkey": app,
                    "secretkey": secret,
                },
                timeout=20,
            )
            r.raise_for_status()
            d = r.json()
            if not d.get("token"):
                raise RuntimeError("TOKEN issue: " + str(d))
            return d["token"]
        except Exception as e:
            last_err = e
            if attempt >= len(RETRY_DELAYS):
                break
            delay = RETRY_DELAYS[attempt]
            print(f"[TOKEN RETRY {attempt+1}] {e} / {delay:.1f}s")
            time.sleep(delay)
    raise last_err


def api_headers(token):
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": "Bearer " + token,
        "api-id": API_MINUTE,
        "Connection": "close",
    }


def post_minute(token, body, label):
    last_err = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            RATE.wait()
            r = requests.post(
                CHART_URL,
                headers=api_headers(token),
                json=body,
                timeout=30,
            )
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                raise requests.HTTPError(
                    f"retryable HTTP {r.status_code}: {r.text[:120]}"
                )
            r.raise_for_status()
            data = r.json()
            if int(data.get("return_code", 0)) != 0:
                raise RuntimeError(str(data))
            return data
        except Exception as e:
            last_err = e
            if attempt >= len(RETRY_DELAYS):
                break
            delay = RETRY_DELAYS[attempt]
            print(f"[RETRY {label} {attempt+1}/{len(RETRY_DELAYS)}] {e} / {delay:.1f}s")
            time.sleep(delay)
    raise last_err


def parse_minute_row(x):
    tm = str(x.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    o = af(x.get("open_pric"))
    h = af(x.get("high_pric"))
    l = af(x.get("low_pric"))
    c = af(x.get("cur_prc"))
    v = af(x.get("trde_qty"), 0.0)

    if None in (o, h, l, c):
        return None
    return tm, o, h, l, c, v or 0.0


def calc_target_day(token, code, trade_date, adjusted):
    body = {
        "stk_cd": code,
        "tic_scope": "1",
        "upd_stkpc_tp": "1" if adjusted else "0",
        "base_dt": trade_date,
    }
    data = post_minute(
        token,
        body,
        f"{code}-{trade_date}-{'ADJ' if adjusted else 'RAW'}",
    )
    rows = data.get("stk_min_pole_chart_qry") or []

    signed_m = 0.0
    approx_turnover = 0.0
    total_volume = 0.0
    count = 0
    first_tm = None
    last_tm = None
    day_low = None
    day_high = None

    for x in rows:
        p = parse_minute_row(x)
        if not p:
            continue
        tm, o, h, l, c, v = p
        if tm[:8] != trade_date:
            continue

        typical = (h + o + l + c) / 4.0
        val_eok = typical * v / 100000000.0

        if c > o:
            signed_m += val_eok
        elif c < o:
            signed_m -= val_eok

        approx_turnover += val_eok
        total_volume += v
        count += 1
        first_tm = tm if first_tm is None else min(first_tm, tm)
        last_tm = tm if last_tm is None else max(last_tm, tm)
        day_low = l if day_low is None else min(day_low, l)
        day_high = h if day_high is None else max(day_high, h)

    return {
        "bars": count,
        "m_eok": signed_m,
        "approx_turnover_eok": approx_turnover,
        "volume": total_volume,
        "first_tm": first_tm or "",
        "last_tm": last_tm or "",
        "low": day_low,
        "high": day_high,
    }


def main():
    base = Path(__file__).resolve().parent
    input_path = base / INPUT_FILE
    output_path = base / OUTPUT_FILE
    summary_path = base / SUMMARY_FILE

    if not input_path.exists():
        raise SystemExit(f"INPUT NOT FOUND: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    anomalies = []
    for r in rows:
        ratio = sf(r.get("m_ratio_pct"))
        if ratio is not None and ratio > 100.0:
            anomalies.append(r)

    print("=" * 70)
    print("RS20 M-ratio anomaly diagnostic v1")
    print(f"INPUT rows       : {len(rows):,}")
    print(f"M ratio > 100%   : {len(anomalies):,}")
    print("NO ORDER API")
    print("=" * 70)

    if not anomalies:
        summary_path.write_text(
            "No M-ratio > 100% rows found.\n",
            encoding="utf-8",
        )
        print("No anomaly rows.")
        return

    app = getpass.getpass("Kiwoom App Key: ").strip()
    secret = getpass.getpass("Kiwoom Secret Key: ").strip()
    token = get_token(app, secret)
    print("TOKEN success")

    out = []
    errors = 0

    for i, r in enumerate(anomalies, 1):
        code = str(r["stock_code"]).strip().zfill(6)
        name = r.get("stock_name", "")
        dt = str(r["trade_date"]).strip()
        daily_tv = sf(r.get("traded_value_eok"), 0.0)
        old_m = sf(r.get("m_value_eok"), 0.0)
        old_ratio = sf(r.get("m_ratio_pct"), 0.0)

        try:
            adj = calc_target_day(token, code, dt, True)
            raw = calc_target_day(token, code, dt, False)

            adj_ratio = adj["m_eok"] / daily_tv * 100 if daily_tv else None
            raw_ratio = raw["m_eok"] / daily_tv * 100 if daily_tv else None
            adj_turn_ratio = (
                adj["approx_turnover_eok"] / daily_tv * 100 if daily_tv else None
            )
            raw_turn_ratio = (
                raw["approx_turnover_eok"] / daily_tv * 100 if daily_tv else None
            )

            if raw_ratio is not None and raw_ratio <= 100 and old_ratio > 100:
                diagnosis = "ADJUSTED_PRICE_MISMATCH_SUSPECT"
            elif raw_turn_ratio is not None and 80 <= raw_turn_ratio <= 120:
                diagnosis = "RAW_TURNOVER_ALIGNS"
            else:
                diagnosis = "NEEDS_REVIEW"

            out.append({
                "stock_code": code,
                "stock_name": name,
                "trade_date": dt,
                "daily_traded_value_eok": daily_tv,
                "collector_m_eok": old_m,
                "collector_ratio_pct": old_ratio,
                "adj_bars": adj["bars"],
                "adj_m_eok": round(adj["m_eok"], 6),
                "adj_m_ratio_pct": round(adj_ratio, 6) if adj_ratio is not None else "",
                "adj_approx_turnover_eok": round(adj["approx_turnover_eok"], 6),
                "adj_turnover_vs_daily_pct": round(adj_turn_ratio, 6) if adj_turn_ratio is not None else "",
                "raw_bars": raw["bars"],
                "raw_m_eok": round(raw["m_eok"], 6),
                "raw_m_ratio_pct": round(raw_ratio, 6) if raw_ratio is not None else "",
                "raw_approx_turnover_eok": round(raw["approx_turnover_eok"], 6),
                "raw_turnover_vs_daily_pct": round(raw_turn_ratio, 6) if raw_turn_ratio is not None else "",
                "adj_price_low": adj["low"],
                "adj_price_high": adj["high"],
                "raw_price_low": raw["low"],
                "raw_price_high": raw["high"],
                "adj_volume": adj["volume"],
                "raw_volume": raw["volume"],
                "diagnosis": diagnosis,
                "error": "",
            })

            print(
                f"[{i:02d}/{len(anomalies)}] {code} {name} {dt} | "
                f"old {old_ratio:.1f}% | adj {adj_ratio:.1f}% | raw {raw_ratio:.1f}% | "
                f"{diagnosis}"
            )

        except Exception as e:
            errors += 1
            out.append({
                "stock_code": code,
                "stock_name": name,
                "trade_date": dt,
                "daily_traded_value_eok": daily_tv,
                "collector_m_eok": old_m,
                "collector_ratio_pct": old_ratio,
                "diagnosis": "ERROR",
                "error": repr(e),
            })
            print(f"[{i:02d}/{len(anomalies)}] ERROR {code} {dt}: {e}")

    fields = [
        "stock_code", "stock_name", "trade_date",
        "daily_traded_value_eok", "collector_m_eok", "collector_ratio_pct",
        "adj_bars", "adj_m_eok", "adj_m_ratio_pct",
        "adj_approx_turnover_eok", "adj_turnover_vs_daily_pct",
        "raw_bars", "raw_m_eok", "raw_m_ratio_pct",
        "raw_approx_turnover_eok", "raw_turnover_vs_daily_pct",
        "adj_price_low", "adj_price_high", "raw_price_low", "raw_price_high",
        "adj_volume", "raw_volume", "diagnosis", "error",
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    counts = {}
    for r in out:
        k = r.get("diagnosis", "")
        counts[k] = counts.get(k, 0) + 1

    lines = [
        "RS20 M-ratio anomaly diagnostic v1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        f"input_rows: {len(rows)}",
        f"anomaly_rows_gt_100pct: {len(anomalies)}",
        f"processed_rows: {len(out)}",
        f"errors: {errors}",
        "",
        "[diagnosis counts]",
    ]
    for k in sorted(counts):
        lines.append(f"{k}: {counts[k]}")
    lines += [
        "",
        "NOTE:",
        "- This diagnostic does NOT modify the original candidate CSV.",
        "- It does NOT send any order.",
        "- Final rule correction must be decided after reviewing this output.",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 70)
    print(f"OUTPUT : {output_path.name}")
    print(f"SUMMARY: {summary_path.name}")
    print(f"ERRORS : {errors}")
    print("=" * 70)


if __name__ == "__main__":
    main()

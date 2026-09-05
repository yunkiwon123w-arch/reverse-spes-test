# -*- coding: utf-8 -*-
"""
RS20 Numeric Revalidation v1
============================

Purpose
- Revalidate ALL 1,267 rows in rs20_history_numeric_candidates_v1.csv.
- Request the target date directly with ka10080 instead of historical pagination.
- Deduplicate 1-minute bars by exact timestamp before calculating M.
- Save the actual target-date 1-minute OHLCV into a reusable local cache.
- Resume safely after Ctrl+C / restart.
- NO ORDER API.

Important
- This validates the existing 1,267 candidate rows for false positives.
- It does NOT yet prove that the old collector created no false negatives.
  That check is a separate stage after this revalidation finishes.

Source M formula
    typical = (H + O + L + C) / 4
    signed value =
        + typical * volume / 1e8, if C > O
        - typical * volume / 1e8, if C < O
        0,                         if C == O
    M = sum(signed value for the trading day)

Strict RS20 numeric core
    M >= 200 eok
    M / daily traded value >= 20%
"""

import csv
import getpass
import gzip
import json
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
CHART_URL = f"{BASE_URL}/api/dostk/chart"
API_ID = "ka10080"

API_MIN_INTERVAL = 0.35
RETRY_DELAYS = [1.5, 3.0, 6.0, 10.0]

INPUT_FILE = "rs20_history_numeric_candidates_v1.csv"
PROGRESS_FILE = "rs20_numeric_revalidation_progress_v1.csv"
PASS_FILE = "rs20_numeric_candidates_corrected_v1.csv"
FAIL_FILE = "rs20_numeric_candidates_removed_v1.csv"
SUMMARY_FILE = "rs20_numeric_revalidation_summary_v1.txt"
MANIFEST_FILE = "common_market_data/minute_1m_manifest_v1.csv"
CACHE_ROOT = "common_market_data/minute_1m"

PROGRESS_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "old_m_value_eok", "old_traded_value_eok", "old_m_ratio_pct",
    "new_m_value_eok", "new_traded_value_eok", "new_m_ratio_pct",
    "approx_minute_turnover_eok", "turnover_vs_daily_pct",
    "bar_count", "duplicate_bar_count",
    "first_minute", "last_minute",
    "day_open", "day_high", "day_low", "day_close", "day_volume",
    "numeric_pass",
    "m_pass", "ratio_pass",
    "status", "error", "validated_at",
]

CACHE_FIELDS = [
    "cntr_tm", "open_pric", "high_pric", "low_pric", "cur_prc", "trde_qty"
]

MANIFEST_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "bar_count", "first_minute", "last_minute",
    "cache_file", "saved_at"
]


class RateLimiter:
    def __init__(self, interval):
        self.interval = interval
        self.last = 0.0

    def wait(self):
        elapsed = time.monotonic() - self.last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
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
    if x is None:
        return default
    return abs(x)


def norm_code(v):
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def get_token(appkey, secretkey):
    last_err = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(
                TOKEN_URL,
                json={
                    "grant_type": "client_credentials",
                    "appkey": appkey,
                    "secretkey": secretkey,
                },
                timeout=20,
            )
            r.raise_for_status()
            d = r.json()
            token = d.get("token")
            if not token:
                raise RuntimeError("TOKEN issue: " + str(d))
            return token
        except Exception as e:
            last_err = e
            if attempt >= len(RETRY_DELAYS):
                break
            delay = RETRY_DELAYS[attempt]
            print(f"[TOKEN RETRY {attempt+1}/{len(RETRY_DELAYS)}] {e} / {delay:.1f}s")
            time.sleep(delay)
    raise last_err


def request_target_date(token, code, trade_date):
    """
    One direct target-date request.
    1 trading day is normally well below the response size used by this TR,
    so pagination is intentionally NOT used here.
    """
    body = {
        "stk_cd": code,
        "tic_scope": "1",
        # Use unadjusted price for price*volume / actual daily traded-value consistency.
        "upd_stkpc_tp": "0",
        "base_dt": trade_date,
    }

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": "Bearer " + token,
        "api-id": API_ID,
        "Connection": "close",
    }

    last_err = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            RATE.wait()
            r = requests.post(
                CHART_URL,
                headers=headers,
                json=body,
                timeout=30,
            )
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                raise requests.HTTPError(
                    f"retryable HTTP {r.status_code}: {r.text[:160]}"
                )
            r.raise_for_status()
            d = r.json()

            if int(d.get("return_code", 0)) != 0:
                raise RuntimeError(str(d))

            return d.get("stk_min_pole_chart_qry") or []

        except Exception as e:
            last_err = e
            if attempt >= len(RETRY_DELAYS):
                break
            delay = RETRY_DELAYS[attempt]
            print(
                f"[RETRY {code} {trade_date} {attempt+1}/{len(RETRY_DELAYS)}] "
                f"{e} / {delay:.1f}s"
            )
            time.sleep(delay)

    raise last_err


def normalize_target_bars(raw_rows, trade_date):
    """
    Returns exact target-date bars deduplicated by cntr_tm.
    If duplicate timestamps exist inside the response, the first parsed row wins.
    """
    by_tm = {}
    duplicate_count = 0

    for r in raw_rows:
        tm = str(r.get("cntr_tm", "")).strip()
        if len(tm) != 14 or not tm.isdigit():
            continue
        if tm[:8] != trade_date:
            continue

        o = af(r.get("open_pric"))
        h = af(r.get("high_pric"))
        l = af(r.get("low_pric"))
        c = af(r.get("cur_prc"))
        v = af(r.get("trde_qty"), 0.0)

        if None in (o, h, l, c):
            continue

        if tm in by_tm:
            duplicate_count += 1
            continue

        by_tm[tm] = {
            "cntr_tm": tm,
            "open_pric": o,
            "high_pric": h,
            "low_pric": l,
            "cur_prc": c,
            "trde_qty": v or 0.0,
        }

    bars = [by_tm[k] for k in sorted(by_tm)]
    return bars, duplicate_count


def calculate_day(bars):
    if not bars:
        raise ValueError("No target-date minute bars")

    m = 0.0
    approx_turnover = 0.0
    total_volume = 0.0

    for b in bars:
        o = b["open_pric"]
        h = b["high_pric"]
        l = b["low_pric"]
        c = b["cur_prc"]
        v = b["trde_qty"]

        typical = (h + o + l + c) / 4.0
        value_eok = typical * v / 100000000.0

        if c > o:
            m += value_eok
        elif c < o:
            m -= value_eok

        approx_turnover += value_eok
        total_volume += v

    return {
        "m": m,
        "approx_turnover": approx_turnover,
        "volume": total_volume,
        "open": bars[0]["open_pric"],
        "high": max(x["high_pric"] for x in bars),
        "low": min(x["low_pric"] for x in bars),
        "close": bars[-1]["cur_prc"],
        "first_minute": bars[0]["cntr_tm"],
        "last_minute": bars[-1]["cntr_tm"],
        "bar_count": len(bars),
    }


def cache_path(base, code, trade_date):
    year = trade_date[:4]
    month = trade_date[4:6]
    return base / CACHE_ROOT / year / month / f"{code}_{trade_date}.csv.gz"


def save_cache(path, bars):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    with gzip.open(tmp, "wt", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CACHE_FIELDS)
        w.writeheader()
        w.writerows(bars)

    tmp.replace(path)


def load_cache(path, trade_date):
    if not path.exists():
        return None

    try:
        rows = []
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows.append(r)

        bars, _ = normalize_target_bars(rows, trade_date)
        if bars:
            return bars
    except Exception:
        return None

    return None


def read_csv_rows(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_all(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def append_row(path, fields, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    base = Path(__file__).resolve().parent
    input_path = base / INPUT_FILE
    progress_path = base / PROGRESS_FILE
    pass_path = base / PASS_FILE
    fail_path = base / FAIL_FILE
    summary_path = base / SUMMARY_FILE
    manifest_path = base / MANIFEST_FILE

    if not input_path.exists():
        raise SystemExit(f"INPUT NOT FOUND: {input_path}")

    original = read_csv_rows(input_path)

    # Normalize and keep only unique stock/date input rows.
    unique = {}
    for r in original:
        code = norm_code(r.get("stock_code", ""))
        dt = str(r.get("trade_date", "")).strip()
        if len(dt) != 8 or not dt.isdigit():
            continue
        r = dict(r)
        r["stock_code"] = code
        unique[(code, dt)] = r

    targets = list(unique.values())

    existing_progress = read_csv_rows(progress_path)
    done = {
        (norm_code(r.get("stock_code", "")), str(r.get("trade_date", "")).strip())
        for r in existing_progress
        if str(r.get("status", "")).strip() == "DONE"
    }

    print("=" * 74)
    print("RS20 Numeric Revalidation v1")
    print(f"Input rows             : {len(original):,}")
    print(f"Unique stock/date      : {len(targets):,}")
    print(f"Already DONE           : {len(done):,}")
    print(f"Remaining              : {len(targets)-len(done):,}")
    print("Target-date direct query + timestamp dedup + minute cache")
    print("NO ORDER API")
    print("=" * 74)

    if len(done) == len(targets):
        print("All rows already DONE. Rebuilding final outputs...")
    else:
        app = getpass.getpass("Kiwoom App Key: ").strip()
        secret = getpass.getpass("Kiwoom Secret Key: ").strip()
        token = get_token(app, secret)
        print("TOKEN success")

        remaining_index = 0

        try:
            for idx, r in enumerate(targets, 1):
                code = norm_code(r["stock_code"])
                dt = str(r["trade_date"]).strip()
                key = (code, dt)

                if key in done:
                    continue

                remaining_index += 1
                name = r.get("stock_name", "")
                market = r.get("market", "")
                daily_tv = sf(r.get("traded_value_eok"), 0.0)
                old_m = sf(r.get("m_value_eok"), 0.0)
                old_ratio = sf(r.get("m_ratio_pct"), 0.0)

                try:
                    cp = cache_path(base, code, dt)
                    bars = load_cache(cp, dt)
                    duplicate_count = 0
                    source = "CACHE"

                    if not bars:
                        raw = request_target_date(token, code, dt)
                        bars, duplicate_count = normalize_target_bars(raw, dt)
                        if not bars:
                            raise ValueError("No target-date minute bars returned")
                        save_cache(cp, bars)
                        source = "API"

                    d = calculate_day(bars)
                    new_m = d["m"]
                    new_ratio = (new_m / daily_tv * 100.0) if daily_tv else None
                    turn_ratio = (
                        d["approx_turnover"] / daily_tv * 100.0
                        if daily_tv else None
                    )

                    m_pass = new_m >= 200.0
                    ratio_pass = new_ratio is not None and new_ratio >= 20.0
                    numeric_pass = m_pass and ratio_pass

                    row = {
                        "stock_code": code,
                        "stock_name": name,
                        "market": market,
                        "trade_date": dt,
                        "old_m_value_eok": old_m,
                        "old_traded_value_eok": daily_tv,
                        "old_m_ratio_pct": old_ratio,
                        "new_m_value_eok": round(new_m, 6),
                        "new_traded_value_eok": daily_tv,
                        "new_m_ratio_pct": round(new_ratio, 6) if new_ratio is not None else "",
                        "approx_minute_turnover_eok": round(d["approx_turnover"], 6),
                        "turnover_vs_daily_pct": round(turn_ratio, 6) if turn_ratio is not None else "",
                        "bar_count": d["bar_count"],
                        "duplicate_bar_count": duplicate_count,
                        "first_minute": d["first_minute"],
                        "last_minute": d["last_minute"],
                        "day_open": d["open"],
                        "day_high": d["high"],
                        "day_low": d["low"],
                        "day_close": d["close"],
                        "day_volume": d["volume"],
                        "numeric_pass": "Y" if numeric_pass else "N",
                        "m_pass": "Y" if m_pass else "N",
                        "ratio_pass": "Y" if ratio_pass else "N",
                        "status": "DONE",
                        "error": "",
                        "validated_at": datetime.now().strftime("%Y%m%d%H%M%S"),
                    }
                    append_row(progress_path, PROGRESS_FIELDS, row)

                    manifest_row = {
                        "stock_code": code,
                        "stock_name": name,
                        "market": market,
                        "trade_date": dt,
                        "bar_count": d["bar_count"],
                        "first_minute": d["first_minute"],
                        "last_minute": d["last_minute"],
                        "cache_file": str(cp.relative_to(base)).replace("\\", "/"),
                        "saved_at": datetime.now().strftime("%Y%m%d%H%M%S"),
                    }
                    append_row(manifest_path, MANIFEST_FIELDS, manifest_row)

                    verdict = "PASS" if numeric_pass else "REMOVE"
                    print(
                        f"[{idx:04d}/{len(targets)}] {code} {name} {dt} | "
                        f"old {old_m:.1f}/{old_ratio:.1f}% -> "
                        f"new {new_m:.1f}/{new_ratio:.1f}% | "
                        f"bars {d['bar_count']} | {source} | {verdict}"
                    )

                except Exception as e:
                    row = {
                        "stock_code": code,
                        "stock_name": name,
                        "market": market,
                        "trade_date": dt,
                        "old_m_value_eok": old_m,
                        "old_traded_value_eok": daily_tv,
                        "old_m_ratio_pct": old_ratio,
                        "status": "ERROR",
                        "error": repr(e),
                        "validated_at": datetime.now().strftime("%Y%m%d%H%M%S"),
                    }
                    append_row(progress_path, PROGRESS_FIELDS, row)
                    print(f"[ERROR] {code} {name} {dt}: {e}")

        except KeyboardInterrupt:
            print()
            print("Ctrl+C detected.")
            print("Completed rows and minute cache are already saved.")
            print("Run the same BAT later to resume.")
            return

    # Rebuild final outputs from latest DONE row per stock/date.
    progress = read_csv_rows(progress_path)
    latest = {}
    for r in progress:
        key = (norm_code(r.get("stock_code", "")), str(r.get("trade_date", "")).strip())
        if str(r.get("status", "")).strip() == "DONE":
            latest[key] = r

    passed = []
    removed = []

    for key, r in latest.items():
        if r.get("numeric_pass") == "Y":
            passed.append(r)
        else:
            removed.append(r)

    passed.sort(key=lambda x: (x["trade_date"], x["stock_code"]))
    removed.sort(key=lambda x: (x["trade_date"], x["stock_code"]))

    write_all(pass_path, PROGRESS_FIELDS, passed)
    write_all(fail_path, PROGRESS_FIELDS, removed)

    done_count = len(latest)
    errors = sum(
        1 for r in progress
        if str(r.get("status", "")).strip() == "ERROR"
        and (norm_code(r.get("stock_code", "")), str(r.get("trade_date", "")).strip()) not in latest
    )

    lines = [
        "RS20 Numeric Revalidation v1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        f"original_input_rows: {len(original)}",
        f"unique_input_stock_dates: {len(targets)}",
        f"done_stock_dates: {done_count}",
        f"corrected_numeric_pass: {len(passed)}",
        f"removed_from_old_candidates: {len(removed)}",
        f"unresolved_errors: {errors}",
        "",
        "RULE:",
        "M >= 200 eok AND M/daily_traded_value >= 20%",
        "",
        "METHOD:",
        "- ka10080 direct target-date request",
        "- 1-minute bars",
        "- upd_stkpc_tp=0",
        "- exact cntr_tm timestamp dedup before M calculation",
        "- target-date minute OHLCV cached as gzip CSV",
        "",
        "IMPORTANT:",
        "- This stage checks false positives inside the old 1,267 candidates.",
        "- It does NOT yet certify that the old historical collector had zero false negatives.",
        "- After this stage, run the separate old-collector false-negative audit before freezing the final RS20 numeric universe.",
        "- NO ORDER API.",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 74)
    print("REVALIDATION COMPLETE")
    print(f"DONE       : {done_count:,} / {len(targets):,}")
    print(f"PASS       : {len(passed):,}")
    print(f"REMOVED    : {len(removed):,}")
    print(f"UNRES ERROR: {errors:,}")
    print(f"PASS FILE  : {PASS_FILE}")
    print(f"REMOVED    : {FAIL_FILE}")
    print(f"SUMMARY    : {SUMMARY_FILE}")
    print(f"CACHE ROOT : {CACHE_ROOT}")
    print("=" * 74)


if __name__ == "__main__":
    main()

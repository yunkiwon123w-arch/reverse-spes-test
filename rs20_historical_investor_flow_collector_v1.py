# -*- coding: utf-8 -*-
"""
RS20 HISTORICAL INVESTOR FLOW COLLECTOR v1
==========================================

Purpose
- Attach historical investor-flow data to the frozen RS20 1,174 numeric candidates.
- Collect by STOCK, not by candidate row, so multiple target dates for one stock
  reuse the same historical API pages.
- Save raw historical investor rows for future strategy reuse.
- Do NOT classify 세력주/수급주/수급세력주 yet.

Official Kiwoom REST API
- API ID : ka10060
- URL    : POST https://api.kiwoom.com/api/dostk/chart
- Request:
    dt          YYYYMMDD
    stk_cd      stock code
    amt_qty_tp  1 = amount
    trde_tp     0 = net buy
    unit_tp     1000
- Response list:
    stk_invsr_orgn_chart

Safety
- NO order endpoint.
- App Key / Secret are entered locally with getpass.
- Resume-safe.
- Retry/backoff.
- Conservative request interval.
"""

import csv
import getpass
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

INPUT_FILE = "rs20_numeric_candidates_final_audited_v1.csv"

RAW_DIR = Path("common_market_data/investor_flow_daily_v1")
PROGRESS_FILE = "rs20_investor_flow_progress_v1.csv"
MATCHED_FILE = "rs20_investor_flow_candidates_v1.csv"
MISSING_FILE = "rs20_investor_flow_missing_v1.csv"
ERROR_FILE = "rs20_investor_flow_errors_v1.csv"
SUMMARY_FILE = "rs20_investor_flow_summary_v1.txt"

TOKEN_URL = "https://api.kiwoom.com/oauth2/token"
API_URL = "https://api.kiwoom.com/api/dostk/chart"
API_ID = "ka10060"

REQUEST_INTERVAL = 0.32
MAX_RETRIES = 5
MAX_PAGES_PER_STOCK = 100

INVESTOR_FIELDS = [
    "dt", "cur_prc", "pred_pre", "acc_trde_prica",
    "ind_invsr", "frgnr_invsr", "orgn",
    "fnnc_invt", "insrnc", "invtrt", "etc_fnnc",
    "bank", "penfnd_etc", "samo_fund", "natn",
    "etc_corp", "natfor"
]

PROGRESS_FIELDS = [
    "stock_code", "stock_name", "target_date_count",
    "newest_target_date", "oldest_target_date",
    "status", "pages", "rows_saved",
    "matched_target_dates", "missing_target_dates",
    "updated_at", "message"
]

MATCHED_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "eod_traded_value_eok", "eod_m_value_eok", "eod_m_ratio_pct"
] + INVESTOR_FIELDS

MISSING_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date", "reason"
]

ERROR_FIELDS = [
    "stock_code", "stock_name", "phase", "attempt",
    "error_type", "message", "time"
]


def norm_code(v):
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def read_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def append_csv(path, fields, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


class RateLimiter:
    def __init__(self, interval):
        self.interval = interval
        self.last = 0.0

    def wait(self):
        now = time.monotonic()
        gap = now - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic()


def get_token(session, appkey, secretkey):
    body = {
        "grant_type": "client_credentials",
        "appkey": appkey,
        "secretkey": secretkey,
    }
    r = session.post(TOKEN_URL, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"TOKEN FAILED: {data}")
    return token


def api_page(session, limiter, token, code, date_str, cont_yn=None, next_key=None):
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": API_ID,
        "Connection": "close",
    }
    if cont_yn:
        headers["cont-yn"] = cont_yn
    if next_key:
        headers["next-key"] = next_key

    body = {
        "dt": date_str,
        "stk_cd": code,
        "amt_qty_tp": "1",
        "trde_tp": "0",
        "unit_tp": "1000",
    }

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            limiter.wait()
            r = session.post(API_URL, headers=headers, json=body, timeout=40)

            if r.status_code == 429 or 500 <= r.status_code < 600:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

            r.raise_for_status()
            data = r.json()

            if data.get("return_code") not in (None, 0):
                raise RuntimeError(
                    f"API return_code={data.get('return_code')} "
                    f"msg={data.get('return_msg')}"
                )

            return (
                data,
                r.headers.get("cont-yn", ""),
                r.headers.get("next-key", ""),
                attempt
            )

        except Exception as e:
            last_exc = e
            if attempt >= MAX_RETRIES:
                break
            time.sleep([1.5, 3.0, 6.0, 10.0][min(attempt - 1, 3)])

    raise last_exc


def load_raw_stock(path):
    rows = read_csv(path)
    return {str(r.get("dt", "")).strip(): r for r in rows if r.get("dt")}


def save_raw_stock(path, rows_by_date):
    rows = list(rows_by_date.values())
    rows.sort(key=lambda r: str(r.get("dt", "")), reverse=True)
    write_csv_atomic(path, INVESTOR_FIELDS, rows)


def main():
    base = Path(__file__).resolve().parent
    input_path = base / INPUT_FILE
    raw_root = base / RAW_DIR
    raw_root.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    candidates = read_csv(input_path)
    if not candidates:
        raise SystemExit("INPUT CSV IS EMPTY")

    by_stock = defaultdict(list)
    for r in candidates:
        code = norm_code(r.get("stock_code", ""))
        by_stock[code].append(r)

    # Existing DONE stock progress is reusable.
    progress_path = base / PROGRESS_FILE
    old_progress = read_csv(progress_path)
    progress_map = {
        norm_code(r.get("stock_code", "")): r
        for r in old_progress
        if str(r.get("status", "")).upper() == "DONE"
    }

    print("=" * 92)
    print("RS20 HISTORICAL INVESTOR FLOW COLLECTOR v1")
    print(f"CANDIDATE ROWS       : {len(candidates):,}")
    print(f"UNIQUE STOCKS        : {len(by_stock):,}")
    print(f"RESUME DONE STOCKS   : {len(progress_map):,}")
    print("API                  : ka10060")
    print("MODE                 : historical investor NET-BUY AMOUNT")
    print("NO ORDER API")
    print("=" * 92)

    appkey = getpass.getpass("KIWOOM APP KEY (hidden): ").strip()
    secretkey = getpass.getpass("KIWOOM SECRET KEY (hidden): ").strip()

    session = requests.Session()
    session.headers.update({"User-Agent": "rs20-investor-flow-v1"})
    token = get_token(session, appkey, secretkey)
    print("TOKEN OK")

    limiter = RateLimiter(REQUEST_INTERVAL)
    errors = []

    stock_items = sorted(by_stock.items())
    done_count = 0

    for idx, (code, items) in enumerate(stock_items, 1):
        name = items[0].get("stock_name", "")
        target_dates = sorted(
            {str(r.get("trade_date", "")).strip() for r in items if r.get("trade_date")},
            reverse=True
        )
        newest = max(target_dates)
        oldest = min(target_dates)

        raw_path = raw_root / f"{code}.csv"
        raw_map = load_raw_stock(raw_path)

        already_all = all(d in raw_map for d in target_dates)
        if code in progress_map and already_all:
            done_count += 1
            if idx % 25 == 0 or idx == len(stock_items):
                print(f"[{idx:03d}/{len(stock_items)}] DONE {done_count:,} / cached {code} {name}")
            continue

        pages = 0
        message = ""
        status = "ERROR"

        try:
            # If target dates are already all cached, no API call.
            if not already_all:
                query_date = newest
                cont_yn = None
                next_key = None
                seen_page_keys = set()

                for page_no in range(1, MAX_PAGES_PER_STOCK + 1):
                    data, next_cont, next_k, attempt_used = api_page(
                        session, limiter, token, code, query_date, cont_yn, next_key
                    )
                    pages += 1

                    rows = data.get("stk_invsr_orgn_chart", []) or []
                    for row in rows:
                        dt = str(row.get("dt", "")).strip()
                        if not dt:
                            continue
                        raw_map[dt] = {k: row.get(k, "") for k in INVESTOR_FIELDS}

                    save_raw_stock(raw_path, raw_map)

                    if all(d in raw_map for d in target_dates):
                        break

                    if not rows:
                        break

                    oldest_returned = min(
                        [str(r.get("dt", "")).strip() for r in rows if r.get("dt")] or ["99999999"]
                    )

                    # If API has already traversed older than our oldest target date,
                    # further pages cannot recover a missing date inside the traversed range.
                    if oldest_returned < oldest:
                        break

                    if str(next_cont).upper() != "Y" or not next_k:
                        break

                    page_key = (str(next_cont), str(next_k))
                    if page_key in seen_page_keys:
                        raise RuntimeError("CONTINUATION KEY LOOP DETECTED")
                    seen_page_keys.add(page_key)

                    cont_yn = next_cont
                    next_key = next_k

            matched = sum(1 for d in target_dates if d in raw_map)
            missing = len(target_dates) - matched
            status = "DONE"
            message = "ALL_TARGET_DATES_FOUND" if missing == 0 else "DONE_WITH_MISSING_TARGET_DATES"
            done_count += 1

        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            errors.append({
                "stock_code": code,
                "stock_name": name,
                "phase": "KA10060",
                "attempt": MAX_RETRIES,
                "error_type": type(e).__name__,
                "message": str(e),
                "time": datetime.now().isoformat(timespec="seconds"),
            })
            matched = sum(1 for d in target_dates if d in raw_map)
            missing = len(target_dates) - matched

        progress_map[code] = {
            "stock_code": code,
            "stock_name": name,
            "target_date_count": len(target_dates),
            "newest_target_date": newest,
            "oldest_target_date": oldest,
            "status": status,
            "pages": pages,
            "rows_saved": len(raw_map),
            "matched_target_dates": matched,
            "missing_target_dates": missing,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "message": message,
        }

        write_csv_atomic(
            progress_path,
            PROGRESS_FIELDS,
            sorted(progress_map.values(), key=lambda r: r["stock_code"])
        )

        if errors:
            write_csv_atomic(base / ERROR_FILE, ERROR_FIELDS, errors)

        print(
            f"[{idx:03d}/{len(stock_items)}] {status:<5} "
            f"{code} {name} | target {len(target_dates)} | "
            f"matched {matched} | missing {missing} | pages {pages}"
        )

    # Build candidate-level matched and missing outputs from reusable raw cache.
    matched_rows = []
    missing_rows = []

    for cand in candidates:
        code = norm_code(cand.get("stock_code", ""))
        dt = str(cand.get("trade_date", "")).strip()
        raw_path = raw_root / f"{code}.csv"
        raw_map = load_raw_stock(raw_path)

        if dt in raw_map:
            row = {
                "stock_code": code,
                "stock_name": cand.get("stock_name", ""),
                "market": cand.get("market", ""),
                "trade_date": dt,
                "eod_traded_value_eok": cand.get("traded_value_eok", ""),
                "eod_m_value_eok": cand.get("m_value_eok", ""),
                "eod_m_ratio_pct": cand.get("m_ratio_pct", ""),
            }
            row.update(raw_map[dt])
            matched_rows.append(row)
        else:
            missing_rows.append({
                "stock_code": code,
                "stock_name": cand.get("stock_name", ""),
                "market": cand.get("market", ""),
                "trade_date": dt,
                "reason": "TARGET_DATE_NOT_RETURNED_BY_KA10060",
            })

    matched_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))
    missing_rows.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    write_csv_atomic(base / MATCHED_FILE, MATCHED_FIELDS, matched_rows)
    write_csv_atomic(base / MISSING_FILE, MISSING_FIELDS, missing_rows)

    final_progress = list(progress_map.values())
    unresolved_stocks = sum(1 for r in final_progress if r.get("status") != "DONE")

    lines = [
        "RS20 HISTORICAL INVESTOR FLOW COLLECTOR v1",
        f"run_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"candidate_rows: {len(candidates)}",
        f"unique_stocks: {len(by_stock)}",
        f"done_stocks: {sum(1 for r in final_progress if r.get('status') == 'DONE')}",
        f"unresolved_error_stocks: {unresolved_stocks}",
        f"matched_candidate_dates: {len(matched_rows)}",
        f"missing_candidate_dates: {len(missing_rows)}",
        "",
        "API: ka10060 /api/dostk/chart",
        "REQUEST: amount(1), net-buy(0), unit(1000)",
        "",
        "IMPORTANT:",
        "- raw investor rows are cached per stock for reuse.",
        "- no 세력주/수급주/수급세력주 classification is performed.",
        "- no source rule is invented.",
        "- no order API is used.",
    ]
    (base / SUMMARY_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 92)
    print("COMPLETE")
    print(f"DONE STOCKS             : {sum(1 for r in final_progress if r.get('status') == 'DONE'):,} / {len(by_stock):,}")
    print(f"UNRES ERROR STOCKS      : {unresolved_stocks:,}")
    print(f"MATCHED CANDIDATE DATES : {len(matched_rows):,} / {len(candidates):,}")
    print(f"MISSING CANDIDATE DATES : {len(missing_rows):,}")
    print(f"MATCHED FILE            : {MATCHED_FILE}")
    print(f"MISSING FILE            : {MISSING_FILE}")
    print(f"PROGRESS                : {PROGRESS_FILE}")
    print(f"RAW CACHE ROOT          : {RAW_DIR}")
    print(f"SUMMARY                 : {SUMMARY_FILE}")
    print("=" * 92)


if __name__ == "__main__":
    main()

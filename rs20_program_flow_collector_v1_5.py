# -*- coding: utf-8 -*-
"""
RS20 PROGRAM_FLOW COLLECTOR v1.5
==============================

Collect Kiwoom ka90008 stock-by-time program-trading data ONLY for the
RS20 v1.2 exact-touch stock/date events.

Official ka90008:
POST https://api.kiwoom.com/api/dostk/mrkcond
Headers: authorization, api-id=ka90008, cont-yn, next-key
Body:
  amt_qty_tp: "1"  # amount, million KRW
  stk_cd: stock code
  date: YYYYMMDD
Response list:
  stk_tm_prm_trde_trnsn

Safety / design:
- No order API.
- Event-only collection; no whole-market scan.
- One stock/date is cached independently.
- Resume-safe: existing valid cache files are skipped.
- Rate-limited conservatively below Kiwoom domestic query ceiling.
- Pagination supported and timestamp-deduplicated.
- Credentials are resolved safely in this order:
  literal auth-file constants -> Windows env -> local hidden getpass input.
- Existing auth_test.py files that themselves use getpass() are NOT executed.
- Access Token is issued automatically through Kiwoom OAuth and kept only
  in memory; credentials and token are never written by this script.
- If historical ka90008 data are unavailable for an old event date, the
  event is recorded as NO_DATA rather than silently treated as zero flow.
"""

import ast
import csv
import gzip
from getpass import getpass
import json
import os
import time
from pathlib import Path

import requests

INPUT_FILE = "rs20_source_event_state_machine_candidate_summary_v1_2.csv"

API_URL = "https://api.kiwoom.com/api/dostk/mrkcond"
API_ID = "ka90008"
RESPONSE_KEY = "stk_tm_prm_trde_trnsn"

CACHE_ROOT = Path("common_market_data/program_flow_ka90008_v1")

OUT_MATCHED = "rs20_program_flow_collection_status_v1_5.csv"
OUT_MISSING = "rs20_program_flow_missing_v1_5.csv"
OUT_PROGRESS = "rs20_program_flow_progress_v1_5.csv"
OUT_SUMMARY = "rs20_program_flow_collection_summary_v1_5.txt"

# Conservative. Do not run another Kiwoom-heavy collector at the same time.
MIN_REQUEST_INTERVAL_SEC = 0.30
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 5
MAX_PAGES_PER_EVENT = 100


# Request pacing state
_last_request_ts = 0.0

# Raw ka90008 cache columns
RAW_FIELDS = [
    "stock_code", "stock_name", "trade_date",
    "event_activation_time", "event_touch_time",
    "tm", "cur_prc", "pre_sig", "pred_pre", "flu_rt", "trde_qty",
    "prm_sell_amt", "prm_buy_amt", "prm_netprps_amt",
    "prm_netprps_amt_irds",
    "prm_sell_qty", "prm_buy_qty", "prm_netprps_qty",
    "prm_netprps_qty_irds",
    "base_pric_tm", "dbrt_trde_rpy_sum", "remn_rcvord_sum", "stex_tp",
]

# Collection-status columns
STATUS_FIELDS = [
    "stock_code", "stock_name", "trade_date",
    "event_activation_time", "event_touch_time",
    "status", "row_count", "page_count", "cache_file", "message",
]


TOKEN_URL = "https://api.kiwoom.com/oauth2/token"

# Preferred source: the already-working local authentication test file.
# We PARSE it with ast and NEVER import/execute it.
AUTH_FILE_CANDIDATES = [
    Path("src/kiwoom_auth_test.py"),
    Path("kiwoom_auth_test.py"),
]

APP_KEY_NAMES = ["APP_KEY", "APPKEY", "KIWOOM_APP_KEY"]
APP_SECRET_NAMES = ["APP_SECRET", "SECRET_KEY", "SECRETKEY", "KIWOOM_APP_SECRET"]

# Fallback environment-variable aliases.
APPKEY_ENV_NAMES = [
    "KIWOOM_APP_KEY",
    "KIWOOM_APPKEY",
    "KIWOOM_REST_APP_KEY",
    "KIWOOM_API_KEY",
]
SECRET_ENV_NAMES = [
    "KIWOOM_APP_SECRET",
    "KIWOOM_SECRET_KEY",
    "KIWOOM_SECRETKEY",
    "KIWOOM_REST_APP_SECRET",
    "KIWOOM_API_SECRET",
]


def read_string_constants_from_py(path):
    """
    Safely parse top-level string assignments without executing the file.
    Returns {variable_name: value}.
    """
    text = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text, filename=str(path))
    out = {}

    for node in tree.body:
        targets = []
        value_node = None

        if isinstance(node, ast.Assign):
            targets = node.targets
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value_node = node.value
        else:
            continue

        if value_node is None:
            continue

        try:
            value = ast.literal_eval(value_node)
        except Exception:
            continue

        if not isinstance(value, str) or not value.strip():
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = value.strip()

    return out


def first_env(names):
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return name, value.strip()
    return None, None


def first_named_value(mapping, names):
    for name in names:
        value = mapping.get(name)
        if value and str(value).strip():
            return name, str(value).strip()
    return None, None


def load_credentials(base):
    # 1) Prefer existing auth file ONLY if it contains literal string constants.
    for rel in AUTH_FILE_CANDIDATES:
        path = base / rel
        if not path.exists():
            continue

        try:
            constants = read_string_constants_from_py(path)
        except Exception as e:
            print(f"AUTH FILE PARSE WARNING   : {rel} | {e}")
            continue

        app_name, appkey = first_named_value(constants, APP_KEY_NAMES)
        sec_name, secretkey = first_named_value(constants, APP_SECRET_NAMES)

        if appkey and secretkey:
            return {
                "source": f"FILE:{rel}",
                "app_name": app_name,
                "sec_name": sec_name,
                "appkey": appkey,
                "secretkey": secretkey,
            }

    # 2) Fallback to environment variables if present.
    app_name, appkey = first_env(APPKEY_ENV_NAMES)
    sec_name, secretkey = first_env(SECRET_ENV_NAMES)

    if appkey and secretkey:
        return {
            "source": "WINDOWS_ENV",
            "app_name": app_name,
            "sec_name": sec_name,
            "appkey": appkey,
            "secretkey": secretkey,
        }

    # 3) Existing auth_test.py in this project uses getpass(), so if no stored
    # credential source exists we securely ask for App Key / Secret locally.
    print()
    print("Stored Kiwoom credentials were not found.")
    print("Your existing auth test appears to use secure getpass input.")
    print("Enter App Key / Secret locally. Input will NOT be shown or saved.")
    print()

    appkey = getpass("Kiwoom APP KEY (hidden): ").strip()
    secretkey = getpass("Kiwoom APP SECRET (hidden): ").strip()

    if not appkey or not secretkey:
        raise SystemExit("APP KEY or APP SECRET is empty.")

    return {
        "source": "LOCAL_GETPASS",
        "app_name": "APP_KEY",
        "sec_name": "APP_SECRET",
        "appkey": appkey,
        "secretkey": secretkey,
    }


def issue_access_token(session, base):
    cred = load_credentials(base)

    if not cred:
        print()
        print("KIWOOM credentials were not found safely.")
        print("Checked auth files:")
        for p in AUTH_FILE_CANDIDATES:
            print(f"  - {p}")
        print()
        print("Expected variable names inside auth file:")
        print("  App Key   :", ", ".join(APP_KEY_NAMES))
        print("  App Secret:", ", ".join(APP_SECRET_NAMES))
        print()
        print("No credential value was printed.")
        print("Do NOT paste App Key / Secret into ChatGPT.")
        raise SystemExit(2)

    print(f"AUTH SOURCE             : {cred['source']}")
    print(f"AUTH VARIABLE NAMES     : {cred['app_name']} / {cred['sec_name']}")
    print("ACCESS TOKEN            : issuing automatically...")

    resp = session.post(
        TOKEN_URL,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={
            "grant_type": "client_credentials",
            "appkey": cred["appkey"],
            "secretkey": cred["secretkey"],
        },
        timeout=REQUEST_TIMEOUT_SEC,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"TOKEN HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        body = resp.json()
    except Exception:
        raise RuntimeError("Token response was not valid JSON")

    token = str(body.get("token", "")).strip()
    if not token:
        msg = (
            body.get("return_msg")
            or body.get("message")
            or body.get("msg")
            or str(body)[:500]
        )
        raise RuntimeError(f"Access token was not returned: {msg}")

    expires_dt = str(body.get("expires_dt", "")).strip()
    print("ACCESS TOKEN            : OK")
    if expires_dt:
        print(f"TOKEN EXPIRES           : {expires_dt}")

    return token


def norm_code(v):
    s = str(v or "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def read_csv(path):
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


def write_gzip_csv_atomic(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def cache_path(base, code, dt):
    return base / CACHE_ROOT / dt[:4] / dt[4:6] / f"{code}_{dt}.csv.gz"


def cache_is_valid(path):
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames is not None
    except Exception:
        return False


def rate_limit():
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    if elapsed < MIN_REQUEST_INTERVAL_SEC:
        time.sleep(MIN_REQUEST_INTERVAL_SEC - elapsed)


def post_page(session, token, payload, cont_yn="N", next_key=""):
    global _last_request_ts

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": API_ID,
        "cont-yn": cont_yn,
        "next-key": next_key,
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rate_limit()
            resp = session.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT_SEC,
            )
            _last_request_ts = time.monotonic()

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except Exception:
                    raise RuntimeError("HTTP 200 but response was not valid JSON")

                # Kiwoom error responses may still arrive as JSON.
                return resp, body

            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"

            # Retry transient failures only.
            if resp.status_code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(last_error)

        except Exception as e:
            last_error = str(e)

        if attempt < MAX_RETRIES:
            time.sleep(min(2 ** (attempt - 1), 8))

    raise RuntimeError(last_error or "request failed")


def normalize_tm(tm, dt):
    s = str(tm or "").strip()

    # Official ka90008 normally returns HHMMSS.
    if len(s) == 6 and s.isdigit():
        return s

    # Be tolerant if a full timestamp is ever returned.
    if len(s) == 14 and s.isdigit():
        if s[:8] == dt:
            return s[8:]
        return s[8:]

    return s


def collect_event(session, token, event):
    code = event["stock_code"]
    dt = event["trade_date"]

    payload = {
        "amt_qty_tp": "1",  # amount; official unit: million KRW
        "stk_cd": code,
        "date": dt,
    }

    all_rows = {}
    cont_yn = "N"
    next_key = ""
    page_count = 0

    while True:
        page_count += 1
        if page_count > MAX_PAGES_PER_EVENT:
            raise RuntimeError("MAX_PAGES_PER_EVENT exceeded")

        resp, body = post_page(
            session=session,
            token=token,
            payload=payload,
            cont_yn=cont_yn,
            next_key=next_key,
        )

        data = body.get(RESPONSE_KEY, [])
        if data is None:
            data = []

        if not isinstance(data, list):
            # Preserve a useful error message without assuming an undocumented schema.
            msg = body.get("return_msg") or body.get("message") or body.get("msg") or str(body)[:500]
            raise RuntimeError(f"{RESPONSE_KEY} is not a list: {msg}")

        for r in data:
            if not isinstance(r, dict):
                continue

            tm = normalize_tm(r.get("tm"), dt)
            key = tm or json.dumps(r, ensure_ascii=False, sort_keys=True)

            out = {
                "stock_code": code,
                "stock_name": event["stock_name"],
                "trade_date": dt,
                "event_activation_time": event["event_activation_time"],
                "event_touch_time": event["event_touch_time"],
            }
            for f in RAW_FIELDS:
                if f in out:
                    continue
                out[f] = r.get(f, "")
            out["tm"] = tm
            all_rows[key] = out

        h_cont = str(resp.headers.get("cont-yn", "")).upper()
        h_next = str(resp.headers.get("next-key", ""))

        if h_cont != "Y" or not h_next:
            break

        cont_yn = "Y"
        next_key = h_next

    rows = sorted(all_rows.values(), key=lambda r: str(r.get("tm", "")))
    return rows, page_count


def main():
    base = Path(__file__).resolve().parent
    inp = base / INPUT_FILE

    if not inp.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    src = read_csv(inp)

    exact = []
    seen = set()

    for r in src:
        if str(r.get("has_exact_touch_after_activation", "")).upper() != "Y":
            continue

        code = norm_code(r.get("stock_code"))
        dt = str(r.get("trade_date", "")).strip()
        if not code or len(dt) != 8 or not dt.isdigit():
            continue

        key = (code, dt)
        if key in seen:
            continue
        seen.add(key)

        exact.append({
            "stock_code": code,
            "stock_name": str(r.get("stock_name", "")).strip(),
            "trade_date": dt,
            "event_activation_time": str(r.get("event_activation_time", "")).strip(),
            "event_touch_time": str(r.get("first_exact_touch_after_activation_time", "")).strip(),
        })

    exact.sort(key=lambda r: (r["trade_date"], r["stock_code"]))

    print("=" * 94)
    print("RS20 PROGRAM_FLOW COLLECTOR v1.5")
    print(f"EXACT-TOUCH STOCK/DATES : {len(exact):,}")
    print("API                     : ka90008")
    print("SCOPE                   : RS20 exact-touch events only")
    print("RESUME                  : ON")
    print("ORDER API               : NONE")
    print("=" * 94)
    print("IMPORTANT: Do NOT run another Kiwoom-heavy collector at the same time.")
    print()

    session = requests.Session()

    try:
        token = issue_access_token(session, base)
    except Exception as e:
        session.close()
        raise SystemExit(f"KIWOOM AUTH FAILED: {e}")

    print()

    statuses = []
    missing = []
    done = 0
    cached = 0
    no_data = 0
    errors = 0
    total_rows = 0

    progress_path = base / OUT_PROGRESS

    try:
        for idx, ev in enumerate(exact, 1):
            code = ev["stock_code"]
            dt = ev["trade_date"]
            cp = cache_path(base, code, dt)
            rel_cp = str(cp.relative_to(base))

            if cache_is_valid(cp):
                cached += 1
                done += 1
                statuses.append({
                    **ev,
                    "status": "CACHED",
                    "row_count": "",
                    "page_count": "",
                    "cache_file": rel_cp,
                    "message": "",
                })
                print(f"[{idx:03d}/{len(exact)}] CACHED  {code} {dt}")
                write_csv_atomic(progress_path, STATUS_FIELDS, statuses)
                continue

            try:
                rows, pages = collect_event(session, token, ev)

                if rows:
                    write_gzip_csv_atomic(cp, RAW_FIELDS, rows)
                    done += 1
                    total_rows += len(rows)
                    statuses.append({
                        **ev,
                        "status": "COLLECTED",
                        "row_count": len(rows),
                        "page_count": pages,
                        "cache_file": rel_cp,
                        "message": "",
                    })
                    print(
                        f"[{idx:03d}/{len(exact)}] COLLECTED {code} {dt} "
                        f"| rows={len(rows):,} pages={pages}"
                    )
                else:
                    # Do NOT create an empty "valid" cache. A future rerun may recover it.
                    no_data += 1
                    statuses.append({
                        **ev,
                        "status": "NO_DATA",
                        "row_count": 0,
                        "page_count": pages,
                        "cache_file": "",
                        "message": "ka90008 returned no rows for this historical stock/date",
                    })
                    missing.append(statuses[-1])
                    print(f"[{idx:03d}/{len(exact)}] NO_DATA  {code} {dt}")

            except KeyboardInterrupt:
                print("\nSTOP REQUESTED. Progress is already saved; rerun to resume.")
                break
            except Exception as e:
                errors += 1
                statuses.append({
                    **ev,
                    "status": "ERROR",
                    "row_count": 0,
                    "page_count": "",
                    "cache_file": "",
                    "message": str(e)[:500],
                })
                missing.append(statuses[-1])
                print(f"[{idx:03d}/{len(exact)}] ERROR    {code} {dt} | {str(e)[:180]}")

            write_csv_atomic(progress_path, STATUS_FIELDS, statuses)

    finally:
        session.close()

    # Final files from this run.
    write_csv_atomic(base / OUT_MATCHED, STATUS_FIELDS, statuses)
    write_csv_atomic(base / OUT_MISSING, STATUS_FIELDS, missing)

    summary = [
        "RS20 PROGRAM_FLOW COLLECTOR v1.5",
        "",
        f"target_exact_touch_stock_dates: {len(exact)}",
        f"status_rows_this_run: {len(statuses)}",
        f"done_collected_this_run: {done}",
        f"cached_existing: {cached}",
        f"no_data: {no_data}",
        f"errors: {errors}",
        f"new_program_flow_rows: {total_rows}",
        f"cache_root: {CACHE_ROOT}",
        "",
        "IMPORTANT",
        "- ka90008 amount mode (amt_qty_tp=1) was requested.",
        "- official amount unit is million KRW.",
        "- NO_DATA is not interpreted as zero program flow.",
        "- existing valid stock/date cache is skipped on rerun.",
        "- do not run another Kiwoom-heavy collector concurrently.",
        "- no order API is used.",
    ]
    (base / OUT_SUMMARY).write_text("\n".join(summary) + "\n", encoding="utf-8")

    print("=" * 94)
    print("COMPLETE / STOPPED SAFELY")
    print(f"TARGET STOCK/DATES       : {len(exact):,}")
    print(f"STATUS ROWS              : {len(statuses):,}")
    print(f"COLLECTED/CACHED DONE    : {done:,}")
    print(f"EXISTING CACHE           : {cached:,}")
    print(f"NO DATA                  : {no_data:,}")
    print(f"ERRORS                   : {errors:,}")
    print(f"NEW RAW ROWS             : {total_rows:,}")
    print(f"CACHE ROOT               : {CACHE_ROOT}")
    print(f"STATUS FILE              : {OUT_MATCHED}")
    print(f"MISSING FILE             : {OUT_MISSING}")
    print(f"PROGRESS FILE            : {OUT_PROGRESS}")
    print(f"SUMMARY                  : {OUT_SUMMARY}")
    print("=" * 94)


if __name__ == "__main__":
    main()

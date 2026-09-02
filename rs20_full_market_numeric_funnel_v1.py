# -*- coding: utf-8 -*-
"""
Reverse SPES - RS20 Full Market Numeric Funnel v1

원칙
- RS20 원문에서 기계적으로 확정 가능한 조건만 자동 판정한다.
- 실제 주문 기능은 없다.
- 세력/수급세력주, '38선 부근' 허용폭, 3파, 신규상장 기간은 임의 정의하지 않는다.

자동 판정:
1) M지표 >= 200억원
2) M지표 / 거래대금 >= 20%

진단만 수행:
- 당일(최신 거래일) running high/low 기준 Reverse Fibonacci 38선
- 각 1분봉 시점의 running fib38과 가격구간 간 거리
- 정확한 fib38 터치 여부/최초 시각
  ※ '부근' 허용폭은 원문 미정의이므로 이 값으로 PASS/FAIL 하지 않음.

Kiwoom REST:
- ka10099 전종목
- ka10080 1분봉
- ka10081 일봉 거래대금
"""

import csv
import getpass
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests


BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
STOCKINFO_URL = f"{BASE_URL}/api/dostk/stkinfo"
CHART_URL = f"{BASE_URL}/api/dostk/chart"

API_STOCK_LIST = "ka10099"
API_MINUTE = "ka10080"
API_DAILY = "ka10081"

API_MIN_INTERVAL = 0.24  # 국내 조회 5/sec보다 보수적
M_MIN_EOK = 200.0
M_RATIO_MIN = 0.20

CACHE_DIR = "rs20_funnel_cache_v1"
OUTPUT_FILE = "rs20_full_market_numeric_candidates_v1.csv"
PROGRESS_FILE = "rs20_full_market_numeric_progress_v1.csv"
ERROR_FILE = "rs20_full_market_numeric_errors_v1.csv"
SUMMARY_FILE = "rs20_full_market_numeric_summary_v1.txt"

PROGRESS_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "status", "m_value_eok", "traded_value_eok", "m_ratio_pct",
    "day_high", "day_low", "fib38_current",
    "first_exact_touch_time", "min_running_fib38_distance_pct",
    "scanned_at"
]

CANDIDATE_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "m_value_eok", "traded_value_eok", "m_ratio_pct",
    "day_high", "day_low", "fib38_current",
    "first_exact_touch_time", "min_running_fib38_distance_pct",
    "is_force_or_supply_stock",
    "is_three_wave_chart",
    "is_new_listing",
    "fib38_near_review",
    "review_status",
    "scanned_at"
]


class RateLimiter:
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.last = 0.0

    def wait(self):
        now_m = time.monotonic()
        gap = now_m - self.last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self.last = time.monotonic()


RATE = RateLimiter(API_MIN_INTERVAL)


def now():
    return datetime.now()


def ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)


def normalize_code(value):
    s = str(value or "").strip().upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if len(s) == 6 and s.isalnum():
        return s
    if s.isdigit():
        return s.zfill(6)
    return s


def safe_float(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return default


def abs_float(v, default=None):
    x = safe_float(v, default)
    return abs(x) if x is not None else default


def request_post(url, headers, body, timeout=30):
    RATE.wait()
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r


def get_token(appkey, secretkey):
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
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"TOKEN 발급 실패: {data}")
    return token


def auth_headers(token, api_id):
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": api_id,
    }


def fetch_stock_list(token, market_type):
    r = request_post(
        STOCKINFO_URL,
        auth_headers(token, API_STOCK_LIST),
        {"mrkt_tp": str(market_type)},
    )
    data = r.json()
    rows = data.get("list") or []

    out = []
    for x in rows:
        code = normalize_code(
            x.get("code")
            or x.get("stk_cd")
            or x.get("stock_code")
            or x.get("종목코드")
        )
        name = str(
            x.get("name")
            or x.get("stk_nm")
            or x.get("stock_name")
            or x.get("종목명")
            or ""
        ).strip()

        if code:
            out.append({
                "stock_code": code,
                "stock_name": name,
                "market": "KOSPI" if str(market_type) == "0" else "KOSDAQ",
            })
    return out


def universe_cache_path():
    return os.path.join(CACHE_DIR, f"rs20_universe_{now():%Y%m%d}.csv")


def load_or_fetch_universe(token):
    ensure_dirs()
    path = universe_cache_path()

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            return rows

    kospi = fetch_stock_list(token, "0")
    kosdaq = fetch_stock_list(token, "10")

    uniq = {}
    for r in kospi + kosdaq:
        uniq[r["stock_code"]] = r
    rows = list(uniq.values())

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["stock_code", "stock_name", "market"]
        )
        w.writeheader()
        w.writerows(rows)

    return rows


def parse_bar(raw):
    tm = str(raw.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    o = abs_float(raw.get("open_pric"))
    h = abs_float(raw.get("high_pric"))
    l = abs_float(raw.get("low_pric"))
    c = abs_float(raw.get("cur_prc"))
    v = abs_float(raw.get("trde_qty"), 0.0)

    if None in (o, h, l, c):
        return None

    return {
        "dt": datetime.strptime(tm, "%Y%m%d%H%M%S"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v or 0.0,
    }


def fetch_latest_day_bars(token, code):
    """
    ka10080 1회 응답(최대 900개 범위)에서 가장 최신 거래일의 1분봉만 사용.
    하루 1분봉은 통상 이 범위 안에 들어오므로 전종목 1차 Funnel에서는
    continuation을 사용하지 않는다.
    """
    r = request_post(
        CHART_URL,
        auth_headers(token, API_MINUTE),
        {
            "stk_cd": code,
            "tic_scope": "1",
            "upd_stkpc_tp": "1",
        },
    )
    data = r.json()
    raw = data.get("stk_min_pole_chart_qry") or []

    bars = [parse_bar(x) for x in raw]
    bars = [x for x in bars if x]
    if not bars:
        return None, []

    latest_date = max(b["dt"].strftime("%Y%m%d") for b in bars)
    bars = [b for b in bars if b["dt"].strftime("%Y%m%d") == latest_date]

    uniq = {b["dt"]: b for b in bars}
    bars = [uniq[k] for k in sorted(uniq)]
    return latest_date, bars


def fetch_daily_trade_value(token, code, trade_date):
    r = request_post(
        CHART_URL,
        auth_headers(token, API_DAILY),
        {
            "stk_cd": code,
            "base_dt": trade_date,
            "upd_stkpc_tp": "1",
        },
    )
    data = r.json()
    rows = data.get("stk_dt_pole_chart_qry") or []
    if not rows:
        return None

    chosen = None
    for x in rows:
        dt = str(
            x.get("dt")
            or x.get("date")
            or x.get("base_dt")
            or ""
        ).strip()
        if dt == trade_date:
            chosen = x
            break
    if chosen is None:
        chosen = rows[0]

    traded_raw = abs_float(
        chosen.get("trde_prica")
        or chosen.get("trading_value")
        or chosen.get("거래대금")
    )
    if traded_raw is None:
        return None

    # 기존 프로젝트 검증 기준: ka10081 trde_prica = 백만원 단위
    return traded_raw / 100.0


def m_indicator_eok(bars):
    """
    강의 M지표:
    양봉 +(H+O+L+C)/4 * V / 1e8
    음봉 -(H+O+L+C)/4 * V / 1e8
    보합 0
    """
    total = 0.0
    for b in bars:
        typical = (
            b["high"] + b["open"] + b["low"] + b["close"]
        ) / 4.0
        value_eok = typical * b["volume"] / 100000000.0

        if b["close"] > b["open"]:
            total += value_eok
        elif b["close"] < b["open"]:
            total -= value_eok

    return total


def reverse_fib38(high_price, low_price):
    # 강의 명명법: 38선 = K*0.618 + daylow
    return (high_price - low_price) * 0.618 + low_price


def distance_bar_to_level_pct(bar, level):
    if not level or level <= 0:
        return None
    if bar["low"] <= level <= bar["high"]:
        return 0.0
    if level < bar["low"]:
        return (bar["low"] - level) / level * 100.0
    return (level - bar["high"]) / level * 100.0


def fib38_diagnostics(bars):
    """
    허용폭을 만들지 않고 '측정'만 한다.
    각 시점 running high/low로 해당 시점 fib38을 계산한다.
    """
    if not bars:
        return {
            "day_high": None,
            "day_low": None,
            "fib38_current": None,
            "first_exact_touch_time": "",
            "min_running_fib38_distance_pct": None,
        }

    running_high = None
    running_low = None
    first_touch = None
    min_dist = None

    for b in bars:
        running_high = b["high"] if running_high is None else max(running_high, b["high"])
        running_low = b["low"] if running_low is None else min(running_low, b["low"])

        if running_high <= running_low:
            continue

        fib38 = reverse_fib38(running_high, running_low)
        dist = distance_bar_to_level_pct(b, fib38)

        if dist is not None:
            if min_dist is None or dist < min_dist:
                min_dist = dist

        if first_touch is None and dist == 0.0:
            first_touch = b["dt"].strftime("%Y%m%d%H%M%S")

    day_high = max(b["high"] for b in bars)
    day_low = min(b["low"] for b in bars)
    current = reverse_fib38(day_high, day_low) if day_high > day_low else None

    return {
        "day_high": day_high,
        "day_low": day_low,
        "fib38_current": current,
        "first_exact_touch_time": first_touch or "",
        "min_running_fib38_distance_pct": min_dist,
    }


def read_existing_candidates():
    result = {}
    if not os.path.exists(OUTPUT_FILE):
        return result
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                code = normalize_code(r.get("stock_code"))
                if code:
                    result[code] = r
    except Exception:
        return {}
    return result


def write_candidates(rows):
    existing = read_existing_candidates()
    manual_fields = [
        "is_force_or_supply_stock",
        "is_three_wave_chart",
        "is_new_listing",
        "fib38_near_review",
    ]

    for r in rows:
        code = normalize_code(r["stock_code"])
        old = existing.get(code, {})
        out = dict(r)
        for field in manual_fields:
            out[field] = old.get(field, "")
        out["review_status"] = "PENDING_REVIEW"
        existing[code] = out

    final_rows = sorted(
        existing.values(),
        key=lambda x: (
            -safe_float(x.get("m_ratio_pct"), 0.0),
            -safe_float(x.get("m_value_eok"), 0.0),
            x.get("stock_code", ""),
        )
    )

    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANDIDATE_FIELDS)
        w.writeheader()
        for r in final_rows:
            w.writerow({k: r.get(k, "") for k in CANDIDATE_FIELDS})
    os.replace(tmp, OUTPUT_FILE)


def load_done_codes():
    done = set()
    if not os.path.exists(PROGRESS_FILE):
        return done

    with open(PROGRESS_FILE, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = normalize_code(r.get("stock_code"))
            if code:
                done.add(code)
    return done


def append_progress(row):
    exists = os.path.exists(PROGRESS_FILE) and os.path.getsize(PROGRESS_FILE) > 0
    with open(PROGRESS_FILE, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PROGRESS_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in PROGRESS_FIELDS})


def append_error(code, name, error):
    fields = ["time", "stock_code", "stock_name", "error"]
    exists = os.path.exists(ERROR_FILE) and os.path.getsize(ERROR_FILE) > 0
    with open(ERROR_FILE, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({
            "time": now().strftime("%Y%m%d%H%M%S"),
            "stock_code": code,
            "stock_name": name,
            "error": str(error),
        })


def write_summary(total, already_done, processed_now, m200_count, numeric_count, error_count):
    text = f"""Reverse SPES - RS20 Full Market Numeric Funnel v1
실제 주문 기능: 없음

전종목 Universe       : {total:,}
시작 전 완료/재개    : {already_done:,}
이번 실행 처리       : {processed_now:,}
M >= 200억           : {m200_count:,}
M/거래대금 >= 20%    : {numeric_count:,}
오류                 : {error_count:,}

후보 파일:
{OUTPUT_FILE}

진행 파일:
{PROGRESS_FILE}

주의:
- 세력/수급세력주, 3파, 신규상장 기간은 자동판정하지 않음.
- '38선 부근' 허용폭을 임의로 만들지 않음.
- fib38 관련 값은 분포/원문 사례 대조용 진단값이며 매수 PASS 기준이 아님.
"""
    Path(SUMMARY_FILE).write_text(text, encoding="utf-8")


def main():
    print("=" * 78)
    print("Reverse SPES - RS20 Full Market Numeric Funnel v1")
    print("M>=200 + M/TradingValue>=20% / no real orders")
    print("=" * 78)
    print()
    print("주의: 실제 주문 기능은 없습니다.")
    print("중단 후 다시 실행하면 progress CSV 기준으로 이어서 진행합니다.")
    print()

    appkey = getpass.getpass("Kiwoom App Key: ")
    secret = getpass.getpass("Kiwoom Secret Key: ")

    print("\nTOKEN 발급 중...")
    token = get_token(appkey, secret)
    print("TOKEN 발급 성공")

    universe = load_or_fetch_universe(token)
    total = len(universe)
    done = load_done_codes()
    already_done = len(done)

    print(f"\n전종목 Universe: {total:,}종목")
    print(f"이미 처리된 종목: {already_done:,}")
    print("스캔 시작...")
    print("종료/중단: Ctrl+C")
    print()

    processed_now = 0
    m200_count = 0
    numeric_count = 0
    error_count = 0
    candidate_buffer = []

    try:
        for idx, stock in enumerate(universe, start=1):
            code = normalize_code(stock["stock_code"])
            name = stock.get("stock_name", "")
            market = stock.get("market", "")

            if code in done:
                continue

            try:
                trade_date, bars = fetch_latest_day_bars(token, code)

                if not bars:
                    append_progress({
                        "stock_code": code,
                        "stock_name": name,
                        "market": market,
                        "trade_date": trade_date or "",
                        "status": "NO_MINUTE_DATA",
                        "scanned_at": now().strftime("%Y%m%d%H%M%S"),
                    })
                    processed_now += 1
                    continue

                m_value = m_indicator_eok(bars)
                diag = fib38_diagnostics(bars)

                base_row = {
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "trade_date": trade_date,
                    "m_value_eok": round(m_value, 4),
                    "day_high": round(diag["day_high"], 4) if diag["day_high"] is not None else "",
                    "day_low": round(diag["day_low"], 4) if diag["day_low"] is not None else "",
                    "fib38_current": round(diag["fib38_current"], 4) if diag["fib38_current"] is not None else "",
                    "first_exact_touch_time": diag["first_exact_touch_time"],
                    "min_running_fib38_distance_pct": (
                        round(diag["min_running_fib38_distance_pct"], 6)
                        if diag["min_running_fib38_distance_pct"] is not None
                        else ""
                    ),
                    "scanned_at": now().strftime("%Y%m%d%H%M%S"),
                }

                if m_value < M_MIN_EOK:
                    progress = dict(base_row)
                    progress["status"] = "FAIL_M_LT_200"
                    progress["traded_value_eok"] = ""
                    progress["m_ratio_pct"] = ""
                    append_progress(progress)
                    processed_now += 1

                else:
                    m200_count += 1
                    traded_value = fetch_daily_trade_value(token, code, trade_date)

                    if traded_value is None or traded_value <= 0:
                        progress = dict(base_row)
                        progress["status"] = "NO_DAILY_TRADE_VALUE"
                        progress["traded_value_eok"] = ""
                        progress["m_ratio_pct"] = ""
                        append_progress(progress)
                        processed_now += 1
                    else:
                        ratio = m_value / traded_value
                        ratio_pct = ratio * 100.0

                        progress = dict(base_row)
                        progress["traded_value_eok"] = round(traded_value, 4)
                        progress["m_ratio_pct"] = round(ratio_pct, 4)

                        if ratio >= M_RATIO_MIN:
                            numeric_count += 1
                            progress["status"] = "PASS_NUMERIC_CORE"

                            candidate_buffer.append({
                                **base_row,
                                "traded_value_eok": round(traded_value, 4),
                                "m_ratio_pct": round(ratio_pct, 4),
                            })
                        else:
                            progress["status"] = "FAIL_M_RATIO_LT_20PCT"

                        append_progress(progress)
                        processed_now += 1

                if len(candidate_buffer) >= 10:
                    write_candidates(candidate_buffer)
                    candidate_buffer = []

                if processed_now % 100 == 0:
                    if candidate_buffer:
                        write_candidates(candidate_buffer)
                        candidate_buffer = []
                    print(
                        f"[{idx:,}/{total:,}] 이번처리 {processed_now:,} / "
                        f"M200 {m200_count:,} / 숫자후보 {numeric_count:,} / 오류 {error_count:,}"
                    )
                    write_summary(
                        total, already_done, processed_now,
                        m200_count, numeric_count, error_count
                    )

            except Exception as e:
                error_count += 1
                processed_now += 1
                append_error(code, name, e)
                append_progress({
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "trade_date": "",
                    "status": "ERROR",
                    "scanned_at": now().strftime("%Y%m%d%H%M%S"),
                })
                print(f"[ERROR] {code} {name}: {e}")

    except KeyboardInterrupt:
        print("\n사용자 중단 요청 - 현재까지 결과를 저장합니다.")

    finally:
        if candidate_buffer:
            write_candidates(candidate_buffer)

        write_summary(
            total, already_done, processed_now,
            m200_count, numeric_count, error_count
        )

        print()
        print("=" * 78)
        print("RS20 Full Market Numeric Funnel v1 종료")
        print(f"이번 실행 처리      : {processed_now:,}")
        print(f"M >= 200억          : {m200_count:,}")
        print(f"숫자 핵심조건 후보  : {numeric_count:,}")
        print(f"오류                : {error_count:,}")
        print(f"후보파일            : {OUTPUT_FILE}")
        print(f"진행파일            : {PROGRESS_FILE}")
        print(f"요약파일            : {SUMMARY_FILE}")
        print("실제 주문은 전혀 전송하지 않았습니다.")
        print("=" * 78)


if __name__ == "__main__":
    main()

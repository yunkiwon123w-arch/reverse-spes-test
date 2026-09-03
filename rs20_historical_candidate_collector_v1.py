# -*- coding: utf-8 -*-
"""
Reverse SPES - RS20 Historical Candidate Collector v1

목적
- 하루 1개 표본으로 '상승파동/첫 눌림'을 정의하지 않기 위해 과거 RS20 숫자조건 표본을 확보한다.
- 실제 주문 기능 없음.
- 원문 미정의 조건(세력/수급세력주, 38선 부근 허용폭, 3파, 신규상장 기간)은 적용하지 않는다.

핵심 숫자조건
- M지표 >= 200억원
- M지표 / 거래대금 >= 20%

수집 방식
PHASE A: ka10081 일봉으로 과거 거래대금 >= 200억원 날짜를 먼저 찾는다.
         M은 절대값 기준으로 그 날 전체 거래대금보다 클 수 없으므로,
         거래대금 < 200억원은 M>=200 조건을 만족할 수 없어 안전하게 사전 제외한다.
PHASE B: PHASE A에서 후보 날짜가 있는 종목만 ka10080 1분봉을 continuation으로 과거까지 내려가며
         날짜별 M지표를 계산한다.
         목표 날짜들을 모두 확보하면 해당 종목 pagination을 즉시 중단한다.

주의
- ka10080/ka10081의 현재 응답 보존 범위 안에서만 수집된다.
- API가 더 오래된 날짜를 제공하지 않으면 그 밖의 기간은 만들거나 추정하지 않는다.
- 중단 후 재실행 가능.
"""

import csv
import getpass
import json
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
STOCKINFO_URL = f"{BASE_URL}/api/dostk/stkinfo"
CHART_URL = f"{BASE_URL}/api/dostk/chart"

API_STOCK_LIST = "ka10099"
API_DAILY = "ka10081"
API_MINUTE = "ka10080"

API_MIN_INTERVAL = 0.24
TRADE_VALUE_PREFILTER_EOK = 200.0
M_MIN_EOK = 200.0
M_RATIO_MIN = 0.20

CACHE_DIR = "rs20_history_cache_v1"
UNIVERSE_FILE = os.path.join(CACHE_DIR, "universe.csv")
DAILY_PREFILTER_FILE = "rs20_history_daily_prefilter_v1.csv"
DAILY_STOCK_DONE_FILE = "rs20_history_daily_stock_done_v1.csv"
MINUTE_STOCK_DONE_FILE = "rs20_history_minute_stock_done_v1.csv"
CANDIDATE_FILE = "rs20_history_numeric_candidates_v1.csv"
ERROR_FILE = "rs20_history_errors_v1.csv"
SUMMARY_FILE = "rs20_history_summary_v1.txt"

# 일봉은 API가 제공하는 continuation을 따라가되 너무 오래된 데이터까지 무한히 내려가지 않도록
# 사용자가 원하는 시작일을 실행 시 입력받는다. 빈 입력이면 20250801.
DEFAULT_START_DATE = "20250801"


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


def nowstr():
    return datetime.now().strftime("%Y%m%d%H%M%S")


def ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


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


def norm_code(v):
    s = str(v or "").strip().upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if len(s) == 6 and s.isalnum():
        return s
    if s.isdigit():
        return s.zfill(6)
    return s


def get_token(app, secret):
    r = requests.post(
        TOKEN_URL,
        json={"grant_type":"client_credentials","appkey":app,"secretkey":secret},
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()
    if not d.get("token"):
        raise RuntimeError("TOKEN 발급 실패: " + str(d))
    return d["token"]


def headers(token, api_id, cont_yn=None, next_key=None):
    h = {
        "Content-Type":"application/json;charset=UTF-8",
        "authorization":"Bearer " + token,
        "api-id":api_id,
    }
    if cont_yn:
        h["cont-yn"] = cont_yn
    if next_key:
        h["next-key"] = next_key
    return h


def post(url, token, api_id, body, cont_yn=None, next_key=None, timeout=30):
    RATE.wait()
    r = requests.post(
        url, headers=headers(token, api_id, cont_yn, next_key),
        json=body, timeout=timeout
    )
    r.raise_for_status()
    return r


def response_cont(r):
    # Kiwoom REST continuation headers
    cont = (r.headers.get("cont-yn") or r.headers.get("Cont-Yn") or "").strip().upper()
    key = (r.headers.get("next-key") or r.headers.get("Next-Key") or "").strip()
    return cont, key


def fetch_stock_list(token, market_type):
    r = post(
        STOCKINFO_URL, token, API_STOCK_LIST,
        {"mrkt_tp": str(market_type)}
    )
    rows = r.json().get("list") or []
    out = []
    for x in rows:
        code = norm_code(x.get("code") or x.get("stk_cd") or x.get("stock_code") or x.get("종목코드"))
        name = str(x.get("name") or x.get("stk_nm") or x.get("stock_name") or x.get("종목명") or "").strip()
        if code:
            out.append({
                "stock_code": code,
                "stock_name": name,
                "market": "KOSPI" if str(market_type) == "0" else "KOSDAQ",
            })
    return out


def load_universe(token):
    ensure_dir()
    if os.path.exists(UNIVERSE_FILE):
        with open(UNIVERSE_FILE, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            return rows

    rows = fetch_stock_list(token, "0") + fetch_stock_list(token, "10")
    uniq = {r["stock_code"]: r for r in rows}
    rows = list(uniq.values())
    with open(UNIVERSE_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stock_code","stock_name","market"])
        w.writeheader()
        w.writerows(rows)
    return rows


def append_csv(path, row, fields):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({k:row.get(k,"") for k in fields})


def done_codes(path):
    s = set()
    if not os.path.exists(path):
        return s
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c = norm_code(r.get("stock_code"))
            if c:
                s.add(c)
    return s


def log_error(stage, code, name, err):
    append_csv(
        ERROR_FILE,
        {"time":nowstr(),"stage":stage,"stock_code":code,"stock_name":name,"error":str(err)},
        ["time","stage","stock_code","stock_name","error"]
    )


def daily_rows_from_json(data):
    return data.get("stk_dt_pole_chart_qry") or []


def parse_daily_row(x):
    dt = str(x.get("dt") or x.get("date") or x.get("base_dt") or "").strip()
    raw = af(x.get("trde_prica") or x.get("trading_value") or x.get("거래대금"))
    if len(dt) != 8 or not dt.isdigit() or raw is None:
        return None
    # 기존 프로젝트 실측 기준: 백만원 -> 억원 /100
    return dt, raw / 100.0


def scan_daily_stock(token, stock, start_date):
    code = stock["stock_code"]
    body = {"stk_cd":code, "base_dt":datetime.now().strftime("%Y%m%d"), "upd_stkpc_tp":"1"}
    cont = next_key = None
    hits = []
    pages = 0
    oldest = None

    while True:
        r = post(CHART_URL, token, API_DAILY, body, cont, next_key)
        pages += 1
        rows = daily_rows_from_json(r.json())
        parsed = [parse_daily_row(x) for x in rows]
        parsed = [x for x in parsed if x]
        if not parsed:
            break

        for dt, tv in parsed:
            oldest = dt if oldest is None else min(oldest, dt)
            if dt >= start_date and tv >= TRADE_VALUE_PREFILTER_EOK:
                hits.append((dt, tv))

        # 목표 시작일에 도달했으면 더 내려갈 필요 없음
        if oldest and oldest <= start_date:
            break

        c, k = response_cont(r)
        if c != "Y" or not k:
            break
        cont, next_key = "Y", k

    return hits, pages, oldest


def phase_a_daily(token, universe, start_date):
    fields = ["stock_code","stock_name","market","trade_date","traded_value_eok","scanned_at"]
    done_fields = ["stock_code","stock_name","status","hit_dates","pages","oldest_date","finished_at"]

    done = done_codes(DAILY_STOCK_DONE_FILE)
    total = len(universe)
    print(f"\n[PHASE A] 일봉 사전필터 시작 / 완료종목 {len(done):,}/{total:,}")

    for i, st in enumerate(universe, 1):
        code = st["stock_code"]
        if code in done:
            continue
        try:
            hits, pages, oldest = scan_daily_stock(token, st, start_date)
            for dt, tv in hits:
                append_csv(
                    DAILY_PREFILTER_FILE,
                    {
                        "stock_code":code,"stock_name":st.get("stock_name",""),
                        "market":st.get("market",""),"trade_date":dt,
                        "traded_value_eok":round(tv,4),"scanned_at":nowstr()
                    },
                    fields
                )
            append_csv(
                DAILY_STOCK_DONE_FILE,
                {
                    "stock_code":code,"stock_name":st.get("stock_name",""),
                    "status":"DONE","hit_dates":len(hits),"pages":pages,
                    "oldest_date":oldest or "","finished_at":nowstr()
                },
                done_fields
            )
            if i % 100 == 0 or hits:
                print(f"[A {i:,}/{total:,}] {code} {st.get('stock_name','')} / >=200억 날짜 {len(hits)} / pages {pages}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log_error("PHASE_A", code, st.get("stock_name",""), e)
            append_csv(
                DAILY_STOCK_DONE_FILE,
                {
                    "stock_code":code,"stock_name":st.get("stock_name",""),
                    "status":"ERROR","hit_dates":0,"pages":0,
                    "oldest_date":"","finished_at":nowstr()
                },
                done_fields
            )
            print(f"[A ERROR] {code} {st.get('stock_name','')}: {e}")


def load_prefilter_targets():
    targets = defaultdict(dict)
    meta = {}
    if not os.path.exists(DAILY_PREFILTER_FILE):
        return targets, meta
    with open(DAILY_PREFILTER_FILE, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = norm_code(r.get("stock_code"))
            dt = str(r.get("trade_date","")).strip()
            tv = sf(r.get("traded_value_eok"))
            if code and len(dt)==8 and tv is not None:
                targets[code][dt] = tv
                meta[code] = {
                    "stock_name":r.get("stock_name",""),
                    "market":r.get("market","")
                }
    return targets, meta


def parse_minute_row(x):
    tm = str(x.get("cntr_tm","")).strip()
    if len(tm)!=14 or not tm.isdigit():
        return None
    o,h,l,c = af(x.get("open_pric")),af(x.get("high_pric")),af(x.get("low_pric")),af(x.get("cur_prc"))
    v = af(x.get("trde_qty"),0.0)
    if None in (o,h,l,c):
        return None
    return tm, o,h,l,c,v or 0.0


def m_add(o,h,l,c,v):
    typical = (h+o+l+c)/4.0
    val = typical*v/100000000.0
    if c > o:
        return val
    if c < o:
        return -val
    return 0.0


def scan_minute_targets(token, code, wanted_dates):
    body = {"stk_cd":code,"tic_scope":"1","upd_stkpc_tp":"1"}
    cont = next_key = None
    sums = defaultdict(float)
    seen_dates = set()
    pages = 0
    oldest = None
    min_wanted = min(wanted_dates)

    while True:
        r = post(CHART_URL, token, API_MINUTE, body, cont, next_key)
        pages += 1
        rows = r.json().get("stk_min_pole_chart_qry") or []
        parsed = [parse_minute_row(x) for x in rows]
        parsed = [x for x in parsed if x]
        if not parsed:
            break

        for tm,o,h,l,c,v in parsed:
            dt = tm[:8]
            oldest = dt if oldest is None else min(oldest, dt)
            if dt in wanted_dates:
                sums[dt] += m_add(o,h,l,c,v)
                seen_dates.add(dt)

        # 모든 목표 날짜보다 과거까지 내려왔다면 해당 목표일의 모든 분봉을 지나온 상태
        if oldest and oldest < min_wanted:
            break

        cflag, key = response_cont(r)
        if cflag != "Y" or not key:
            break
        cont, next_key = "Y", key

    return sums, seen_dates, pages, oldest


def phase_b_minute(token):
    targets, meta = load_prefilter_targets()
    codes = sorted(targets)
    done = done_codes(MINUTE_STOCK_DONE_FILE)

    print(f"\n[PHASE B] 분봉 M 계산 대상종목 {len(codes):,} / 완료 {len(done):,}")

    cand_fields = [
        "stock_code","stock_name","market","trade_date",
        "m_value_eok","traded_value_eok","m_ratio_pct",
        "source_status","scanned_at"
    ]
    done_fields = [
        "stock_code","stock_name","status","target_dates","seen_dates",
        "numeric_candidates","pages","oldest_date","finished_at"
    ]

    for i, code in enumerate(codes,1):
        if code in done:
            continue
        name = meta.get(code,{}).get("stock_name","")
        market = meta.get(code,{}).get("market","")
        wanted = set(targets[code].keys())
        try:
            sums, seen, pages, oldest = scan_minute_targets(token, code, wanted)
            found = 0
            for dt in sorted(wanted):
                if dt not in seen:
                    continue
                m = sums[dt]
                tv = targets[code][dt]
                ratio = m/tv if tv > 0 else None
                if m >= M_MIN_EOK and ratio is not None and ratio >= M_RATIO_MIN:
                    found += 1
                    append_csv(
                        CANDIDATE_FILE,
                        {
                            "stock_code":code,"stock_name":name,"market":market,
                            "trade_date":dt,
                            "m_value_eok":round(m,4),
                            "traded_value_eok":round(tv,4),
                            "m_ratio_pct":round(ratio*100.0,4),
                            "source_status":"PASS_NUMERIC_CORE",
                            "scanned_at":nowstr()
                        },
                        cand_fields
                    )

            append_csv(
                MINUTE_STOCK_DONE_FILE,
                {
                    "stock_code":code,"stock_name":name,"status":"DONE",
                    "target_dates":len(wanted),"seen_dates":len(seen),
                    "numeric_candidates":found,"pages":pages,
                    "oldest_date":oldest or "","finished_at":nowstr()
                },
                done_fields
            )
            print(f"[B {i:,}/{len(codes):,}] {code} {name} / target {len(wanted)} / seen {len(seen)} / RS20숫자후보 {found} / pages {pages}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log_error("PHASE_B", code, name, e)
            append_csv(
                MINUTE_STOCK_DONE_FILE,
                {
                    "stock_code":code,"stock_name":name,"status":"ERROR",
                    "target_dates":len(wanted),"seen_dates":0,
                    "numeric_candidates":0,"pages":0,
                    "oldest_date":"","finished_at":nowstr()
                },
                done_fields
            )
            print(f"[B ERROR] {code} {name}: {e}")


def count_rows(path):
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def write_summary(start_date, universe_count):
    text = f"""Reverse SPES - RS20 Historical Candidate Collector v1
실제 주문 기능: 없음

수집 시작일: {start_date}
Universe: {universe_count:,}

PHASE A 일봉 >=200억 날짜수: {count_rows(DAILY_PREFILTER_FILE):,}
PHASE A 완료종목: {count_rows(DAILY_STOCK_DONE_FILE):,}
PHASE B 완료종목: {count_rows(MINUTE_STOCK_DONE_FILE):,}
RS20 숫자 핵심조건 후보: {count_rows(CANDIDATE_FILE):,}
오류 기록: {count_rows(ERROR_FILE):,}

후보:
{CANDIDATE_FILE}

주의:
- 원문 미정의 조건은 적용하지 않았음.
- 현재 Kiwoom API가 실제로 반환하는 보존기간 안에서만 수집됨.
- 없는 과거 데이터를 추정/보간하지 않음.
"""
    Path(SUMMARY_FILE).write_text(text, encoding="utf-8")


def main():
    print("="*82)
    print("Reverse SPES - RS20 Historical Candidate Collector v1")
    print("Daily prefilter -> historical minute M -> numeric RS20 candidates")
    print("NO REAL ORDERS")
    print("="*82)
    print()
    print("중요: 전체 과거 수집은 오래 걸릴 수 있습니다.")
    print("Ctrl+C로 중단 가능하며, 재실행하면 완료 종목을 건너뜁니다.")
    print()

    start_date = input(f"수집 시작일 YYYYMMDD [기본 {DEFAULT_START_DATE}]: ").strip() or DEFAULT_START_DATE
    if len(start_date)!=8 or not start_date.isdigit():
        raise ValueError("시작일은 YYYYMMDD 형식이어야 합니다.")

    app = getpass.getpass("Kiwoom App Key: ")
    sec = getpass.getpass("Kiwoom Secret Key: ")
    print("\nTOKEN 발급 중...")
    tok = get_token(app, sec)
    print("TOKEN 발급 성공")

    universe = load_universe(tok)
    print(f"Universe: {len(universe):,}종목")

    try:
        phase_a_daily(tok, universe, start_date)
        phase_b_minute(tok)
    except KeyboardInterrupt:
        print("\n사용자 중단 요청 - 현재까지 진행상황을 저장했습니다.")
    finally:
        write_summary(start_date, len(universe))
        print()
        print("="*82)
        print("현재 실행 종료")
        print(f"PHASE A 날짜수       : {count_rows(DAILY_PREFILTER_FILE):,}")
        print(f"PHASE A 완료종목     : {count_rows(DAILY_STOCK_DONE_FILE):,}")
        print(f"PHASE B 완료종목     : {count_rows(MINUTE_STOCK_DONE_FILE):,}")
        print(f"RS20 숫자후보        : {count_rows(CANDIDATE_FILE):,}")
        print(f"오류                 : {count_rows(ERROR_FILE):,}")
        print(f"요약파일             : {SUMMARY_FILE}")
        print("실제 주문은 전혀 전송하지 않았습니다.")
        print("="*82)


if __name__ == "__main__":
    main()

import csv
import getpass
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
MINUTE_URL = f"{BASE_URL}/api/dostk/chart"

INPUT_FILE = "rs3_structure_analysis_v2.csv"
CACHE_DIR = "minute_cache"
MANIFEST_FILE = "minute_cache_manifest.csv"
ERROR_FILE = "minute_cache_errors.csv"

REQUEST_INTERVAL = 0.30
MAX_PAGES_PER_STOCK = 500


def normalize_code(value):
    s = str(value or "").strip().upper()
    if not s:
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if len(s) == 6 and s.isalnum():
        return s
    if s.isdigit():
        return s.zfill(6)
    return s


def safe_float(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return abs(float(str(v).replace(",", "").strip()))
    except Exception:
        return None


def safe_int(v):
    if v is None or str(v).strip() == "":
        return 0
    try:
        return abs(int(float(str(v).replace(",", "").strip())))
    except Exception:
        return 0


def cache_path(code):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{normalize_code(code)}_minute.csv")


def parse_cache_dt(s):
    s = str(s or "").strip()
    if len(s) == 14 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d%H%M%S")
    return None


def load_cache(code):
    path = cache_path(code)
    if not os.path.exists(path):
        return []

    bars = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_cache_dt(row.get("cntr_tm"))
            if not dt:
                continue
            bars.append({
                "dt": dt,
                "open": safe_float(row.get("open")),
                "high": safe_float(row.get("high")),
                "low": safe_float(row.get("low")),
                "close": safe_float(row.get("close")),
                "volume": safe_int(row.get("volume")),
            })

    uniq = {x["dt"]: x for x in bars}
    return [uniq[k] for k in sorted(uniq)]


def save_cache(code, bars):
    path = cache_path(code)
    uniq = {x["dt"]: x for x in bars}
    ordered = [uniq[k] for k in sorted(uniq)]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["cntr_tm", "open", "high", "low", "close", "volume"]
        )
        w.writeheader()
        for b in ordered:
            w.writerow({
                "cntr_tm": b["dt"].strftime("%Y%m%d%H%M%S"),
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b["volume"],
            })
    return len(ordered)


def get_token(appkey, secretkey):
    payload = {
        "grant_type": "client_credentials",
        "appkey": appkey,
        "secretkey": secretkey,
    }
    r = requests.post(TOKEN_URL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"TOKEN 발급 실패: {data}")
    return token


def request_page(token, code, cont_yn="", next_key=""):
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10080",
    }
    if cont_yn:
        headers["cont-yn"] = cont_yn
    if next_key:
        headers["next-key"] = next_key

    body = {
        "stk_cd": code,
        "tic_scope": "1",
        "upd_stkpc_tp": "1",
    }

    r = requests.post(MINUTE_URL, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    bars = data.get("stk_min_pole_chart_qry") or []
    return bars, r.headers.get("cont-yn", ""), r.headers.get("next-key", "")


def parse_api_bar(raw):
    tm = str(raw.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    o = safe_float(raw.get("open_pric"))
    h = safe_float(raw.get("high_pric"))
    l = safe_float(raw.get("low_pric"))
    c = safe_float(raw.get("cur_prc"))

    if None in (o, h, l, c):
        return None

    return {
        "dt": datetime.strptime(tm, "%Y%m%d%H%M%S"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": safe_int(raw.get("trde_qty")),
    }


def cache_covers(bars, required_oldest_date):
    if not bars:
        return False
    oldest = min(x["dt"].strftime("%Y%m%d") for x in bars)
    return oldest <= required_oldest_date


def append_row(path, fieldnames, row):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    print("=" * 76)
    print("Reverse SPES - RS3 분봉 CACHE 구축 v2")
    print("분석 규칙 변경 없음 / 데이터 재조회 방지용 로컬 캐시")
    print("=" * 76)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    grouped = defaultdict(list)
    for row in rows:
        code = normalize_code(row.get("stock_code"))
        if code:
            grouped[code].append(row)

    print(f"입력 후보: {len(rows)}건")
    print(f"대상 종목: {len(grouped)}개")
    print(f"캐시 폴더: {CACHE_DIR}")
    print()

    # 먼저 PC 캐시만 검사한다. 모든 종목이 충분하면 Kiwoom 인증조차 하지 않는다.
    need_api = []
    cache_ok = []

    for code, items in grouped.items():
        oldest_required = min(str(x.get("date", "")).strip() for x in items)
        cached = load_cache(code)
        if cache_covers(cached, oldest_required):
            cache_ok.append((code, items, cached, oldest_required))
        else:
            need_api.append((code, items, cached, oldest_required))

    print(f"이미 CACHE 충분: {len(cache_ok)}종목")
    print(f"API 추가 조회 필요: {len(need_api)}종목")
    print()

    manifest_fields = [
        "stock_code", "stock_name", "required_oldest_date",
        "cache_oldest", "cache_newest", "bar_count", "status"
    ]

    # 충분한 기존 캐시 기록
    for code, items, cached, oldest_required in cache_ok:
        append_row(
            MANIFEST_FILE,
            manifest_fields,
            {
                "stock_code": code,
                "stock_name": items[0].get("stock_name", ""),
                "required_oldest_date": oldest_required,
                "cache_oldest": min(x["dt"].strftime("%Y%m%d") for x in cached),
                "cache_newest": max(x["dt"].strftime("%Y%m%d") for x in cached),
                "bar_count": len(cached),
                "status": "CACHE_OK",
            }
        )

    if not need_api:
        print("모든 대상 종목의 캐시가 이미 충분합니다.")
        print("Kiwoom TOKEN 발급 및 API 조회를 하지 않았습니다.")
        print(f"결과: {MANIFEST_FILE}")
        return

    print("처음 CACHE를 구축하는 종목만 Kiwoom 인증이 필요합니다.")
    appkey = getpass.getpass("Kiwoom App Key: ")
    secret = getpass.getpass("Kiwoom Secret Key: ")

    print("\nTOKEN 발급 중...")
    token = get_token(appkey, secret)
    print("TOKEN 발급 성공\n")

    success = 0
    errors = 0

    for i, (code, items, cached, oldest_required) in enumerate(need_api, start=1):
        name = items[0].get("stock_name", "")
        print(f"[{i}/{len(need_api)}] {code} {name} / 필요 최저일 {oldest_required}")

        try:
            all_bars = list(cached)
            cont_yn = ""
            next_key = ""
            reached = False

            for page in range(1, MAX_PAGES_PER_STOCK + 1):
                raw, cont_yn, next_key = request_page(
                    token, code, cont_yn, next_key
                )

                parsed = [parse_api_bar(x) for x in raw]
                parsed = [x for x in parsed if x]
                all_bars.extend(parsed)

                if parsed:
                    oldest_seen = min(
                        x["dt"].strftime("%Y%m%d") for x in parsed
                    )
                    if oldest_seen <= oldest_required:
                        reached = True
                        break

                if str(cont_yn).upper() != "Y" or not next_key:
                    break

                time.sleep(REQUEST_INTERVAL)

            count = save_cache(code, all_bars)
            final_bars = load_cache(code)

            oldest = (
                min(x["dt"].strftime("%Y%m%d") for x in final_bars)
                if final_bars else ""
            )
            newest = (
                max(x["dt"].strftime("%Y%m%d") for x in final_bars)
                if final_bars else ""
            )

            status = "CACHE_BUILT" if reached else "CACHE_PARTIAL"
            append_row(
                MANIFEST_FILE,
                manifest_fields,
                {
                    "stock_code": code,
                    "stock_name": name,
                    "required_oldest_date": oldest_required,
                    "cache_oldest": oldest,
                    "cache_newest": newest,
                    "bar_count": count,
                    "status": status,
                }
            )

            success += 1
            print(f"  {status} / 저장 {count:,}분봉 / {oldest} ~ {newest}")

        except Exception as e:
            append_row(
                ERROR_FILE,
                ["stock_code", "stock_name", "required_oldest_date", "error"],
                {
                    "stock_code": code,
                    "stock_name": name,
                    "required_oldest_date": oldest_required,
                    "error": str(e),
                }
            )
            errors += 1
            print(f"  ERROR: {e}")

        time.sleep(REQUEST_INTERVAL)

    print()
    print("=" * 76)
    print("RS3 분봉 CACHE 구축 종료")
    print(f"성공/기록: {success}종목")
    print(f"오류: {errors}종목")
    print(f"캐시 폴더: {CACHE_DIR}")
    print(f"현황 파일: {MANIFEST_FILE}")
    print(f"오류 파일: {ERROR_FILE}")
    print()
    print("앞으로 같은 과거 분봉은 minute_cache에서 우선 읽도록 연결합니다.")
    print("=" * 76)


if __name__ == "__main__":
    main()

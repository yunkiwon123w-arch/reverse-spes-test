import csv
import getpass
import time
from datetime import datetime

import requests


BASE_URL = "https://api.kiwoom.com"

# RS3 원문 1차 조건
MIN_RISE_RATE = 0.20

# 키움 API 과호출 방지
REQUEST_INTERVAL = 0.30

# 현재 단계에서는 전체 종목 일봉 1회 조회
BASE_DATE = datetime.now().strftime("%Y%m%d")

OUTPUT_FILE = "rs3_market_candidates.csv"
ERROR_FILE = "rs3_market_scan_errors.csv"


def get_token(app_key, secret_key):
    url = BASE_URL + "/oauth2/token"

    headers = {
        "Content-Type": "application/json;charset=UTF-8"
    }

    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    data = response.json()

    if data.get("return_code") != 0 or not data.get("token"):
        raise RuntimeError(
            f"토큰 발급 실패: {data.get('return_msg')}"
        )

    return data["token"]


def clean_number(value):
    if value is None:
        return None

    text = str(value).replace(",", "").strip()

    if not text:
        return None

    try:
        return abs(int(float(text)))
    except ValueError:
        return None


def get_stock_list(token, market_type):
    url = BASE_URL + "/api/dostk/stkinfo"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10099"
    }

    body = {
        "mrkt_tp": market_type
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    data = response.json()

    if response.status_code != 200:
        raise RuntimeError(
            f"종목리스트 HTTP 오류: {response.status_code}"
        )

    if data.get("return_code") not in (None, 0):
        raise RuntimeError(
            f"종목리스트 API 오류: {data.get('return_msg')}"
        )

    return data.get("list", [])


def get_daily_chart(token, stock_code):
    url = BASE_URL + "/api/dostk/chart"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10081"
    }

    body = {
        "stk_cd": stock_code,
        "base_dt": BASE_DATE,
        "upd_stkpc_tp": "1"
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    return response


def find_rs3_candidates(rows, stock_code, stock_name, market_name):
    results = []

    for row in rows:
        date = str(row.get("dt", "")).strip()

        open_price = clean_number(
            row.get("open_pric")
        )

        high_price = clean_number(
            row.get("high_pric")
        )

        traded_value = clean_number(
            row.get("trde_prica")
        )

        if not date:
            continue

        if not open_price or not high_price:
            continue

        if open_price <= 0:
            continue

        rise_rate = (
            (high_price - open_price)
            / open_price
        )

        # RS3 원문:
        # 시가 대비 당일 고가 +20% 이상
        if rise_rate < MIN_RISE_RATE:
            continue

        results.append({
            "stock_code": stock_code,
            "stock_name": stock_name,
            "market": market_name,
            "date": date,
            "open": open_price,
            "high": high_price,
            "rise_pct": round(
                rise_rate * 100,
                2
            ),
            "traded_value_raw": traded_value
        })

    return results


def save_candidates(rows):
    fields = [
        "stock_code",
        "stock_name",
        "market",
        "date",
        "open",
        "high",
        "rise_pct",
        "traded_value_raw"
    ]

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(rows)


def save_errors(rows):
    fields = [
        "stock_code",
        "stock_name",
        "market",
        "error"
    ]

    with open(
        ERROR_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(rows)


print("=" * 70)
print("Reverse SPES RS3 - 전체시장 1차 후보 스캔")
print("조건 : 시가 대비 당일 고가 +20% 이상")
print("=" * 70)

app_key = getpass.getpass(
    "App Key 입력: "
)

secret_key = getpass.getpass(
    "Secret Key 입력: "
)

try:
    print()
    print("1. TOKEN 발급 중...")

    token = get_token(
        app_key,
        secret_key
    )

    print("✅ TOKEN 발급 성공")

    print()
    print("2. 코스피/코스닥 종목리스트 조회...")

    kospi = get_stock_list(
        token,
        "0"
    )

    kosdaq = get_stock_list(
        token,
        "10"
    )

    stocks = []

    for row in kospi:
        stocks.append({
            "code": row.get("code"),
            "name": row.get("name"),
            "market": "KOSPI"
        })

    for row in kosdaq:
        stocks.append({
            "code": row.get("code"),
            "name": row.get("name"),
            "market": "KOSDAQ"
        })

    print(
        "전체 조회 대상 :",
        len(stocks),
        "종목"
    )

    print()
    print("3. 전체시장 일봉 스캔 시작")
    print()

    candidates = []
    errors = []

    total = len(stocks)

    for index, stock in enumerate(
        stocks,
        start=1
    ):

        code = stock["code"]
        name = stock["name"]
        market = stock["market"]

        if not code:
            continue

        try:
            response = get_daily_chart(
                token,
                code
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"HTTP {response.status_code}"
                )

            data = response.json()

            if data.get(
                "return_code"
            ) not in (None, 0):

                raise RuntimeError(
                    data.get(
                        "return_msg",
                        "API 오류"
                    )
                )

            rows = data.get(
                "stk_dt_pole_chart_qry",
                []
            )

            found = find_rs3_candidates(
                rows,
                code,
                name,
                market
            )

            if found:
                candidates.extend(found)

                print(
                    f"★ {code} {name} "
                    f"/ 후보 {len(found)}건"
                )

            # 50종목마다 진행상황 + 중간저장
            if index % 50 == 0:

                print(
                    f"[{index:,}/{total:,}] "
                    f"후보 누적 {len(candidates):,}건 "
                    f"/ 오류 {len(errors):,}건"
                )

                save_candidates(
                    candidates
                )

                save_errors(
                    errors
                )

            time.sleep(
                REQUEST_INTERVAL
            )

        except Exception as e:

            errors.append({
                "stock_code": code,
                "stock_name": name,
                "market": market,
                "error": str(e)
            })

            print(
                f"⚠ {code} {name} 오류:",
                str(e)
            )

            time.sleep(
                REQUEST_INTERVAL
            )

    # 최종 저장
    save_candidates(
        candidates
    )

    save_errors(
        errors
    )

    print()
    print("=" * 70)
    print("4. 전체시장 스캔 완료")
    print("=" * 70)

    print(
        "전체 종목 :",
        total
    )

    print(
        "RS3 +20% 후보 :",
        len(candidates)
    )

    print(
        "오류 종목 :",
        len(errors)
    )

    print()
    print(
        "후보 CSV :",
        OUTPUT_FILE
    )

    print(
        "오류 CSV :",
        ERROR_FILE
    )

    print()
    print("✅ 전체시장 1차 스캔 완료")

except KeyboardInterrupt:

    print()
    print("⚠ 사용자가 중단했습니다.")

except Exception as e:

    print()
    print(
        "❌ 오류 :",
        type(e).__name__,
        str(e)
    )

print()
input("Enter를 누르면 종료합니다...")

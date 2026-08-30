import csv
import getpass
import os
import time
import requests


BASE_URL = "https://api.kiwoom.com"

INPUT_FILE = "rs3_candidates_minute_period.csv"

MAX_PAGES = 20
REQUEST_INTERVAL = 0.30


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


def load_latest_candidate():
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(
            f"{INPUT_FILE} 파일이 없습니다."
        )

    rows = []

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:
            rows.append(row)

    if not rows:
        raise RuntimeError(
            "후보 CSV에 데이터가 없습니다."
        )

    rows.sort(
        key=lambda x: x.get("date", ""),
        reverse=True
    )

    return rows[0]


def request_minute_page(
    token,
    stock_code,
    cont_yn=None,
    next_key=None
):
    url = BASE_URL + "/api/dostk/chart"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10080"
    }

    if cont_yn == "Y" and next_key:
        headers["cont-yn"] = "Y"
        headers["next-key"] = next_key

    body = {
        "stk_cd": stock_code,
        "tic_scope": "1",
        "upd_stkpc_tp": "1"
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    return response


def load_target_day_minutes(
    token,
    stock_code,
    target_date
):
    all_rows = []

    cont_yn = None
    next_key = None

    page = 0

    while page < MAX_PAGES:

        response = request_minute_page(
            token,
            stock_code,
            cont_yn,
            next_key
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP 오류: {response.status_code}"
            )

        data = response.json()

        if data.get("return_code") not in (None, 0):
            raise RuntimeError(
                data.get(
                    "return_msg",
                    "분봉 API 오류"
                )
            )

        rows = data.get(
            "stk_min_pole_chart_qry",
            []
        )

        page += 1

        oldest_date = None

        for row in rows:

            tm = str(
                row.get("cntr_tm", "")
            ).strip()

            if len(tm) < 8:
                continue

            row_date = tm[:8]

            if oldest_date is None:
                oldest_date = row_date
            elif row_date < oldest_date:
                oldest_date = row_date

            if row_date == target_date:
                all_rows.append(row)

        print(
            f"[{page}페이지] "
            f"목표일 분봉 누적 {len(all_rows)}개"
        )

        if oldest_date and oldest_date < target_date:
            break

        new_cont_yn = response.headers.get(
            "cont-yn",
            ""
        )

        new_next_key = response.headers.get(
            "next-key",
            ""
        )

        if new_cont_yn != "Y" or not new_next_key:
            break

        cont_yn = new_cont_yn
        next_key = new_next_key

        time.sleep(
            REQUEST_INTERVAL
        )

    return all_rows


def analyze_rs3_day(
    rows,
    daily_open
):
    bars = []

    for row in rows:

        tm = str(
            row.get("cntr_tm", "")
        ).strip()

        if len(tm) < 14:
            continue

        cur = clean_number(
            row.get("cur_prc")
        )

        high = clean_number(
            row.get("high_pric")
        )

        low = clean_number(
            row.get("low_pric")
        )

        if cur is None or high is None or low is None:
            continue

        bars.append({
            "time": tm,
            "cur": cur,
            "high": high,
            "low": low
        })

    bars.sort(
        key=lambda x: x["time"]
    )

    if not bars:
        return None

    running_high = None
    running_low = None

    trigger_time = None

    # +20% 최초 발생 순간에 고정할 값
    fixed_high = None
    fixed_low = None

    fib50 = None
    fib618 = None
    fib70 = None

    before_1430_touch_50 = False
    first_after_1430_touch = None

    diagnostic_rows = []

    for bar in bars:

        tm = bar["time"]
        hhmm = tm[8:12]

        high = bar["high"]
        low = bar["low"]

        if running_high is None:
            running_high = high
        else:
            running_high = max(
                running_high,
                high
            )

        if running_low is None:
            running_low = low
        else:
            running_low = min(
                running_low,
                low
            )

        rise_rate = (
            (running_high - daily_open)
            / daily_open
        )

        # +20% 최초 발생 순간
        if (
            trigger_time is None
            and rise_rate >= 0.20
        ):
            trigger_time = tm

            # 이 순간의 A, B 고정
            fixed_high = running_high
            fixed_low = running_low

            diff = (
                fixed_high
                - fixed_low
            )

            fib50 = (
                fixed_high
                - diff * 0.5
            )

            fib618 = (
                fixed_high
                - diff * 0.618
            )

            fib70 = (
                fixed_high
                - diff * 0.7
            )

        if trigger_time is None:
            continue

        # 고정된 피보나치 가격 사용
        touched_50 = (
            low <= fib50 <= high
        )

        if hhmm < "1430" and touched_50:
            before_1430_touch_50 = True

        if (
            hhmm >= "1430"
            and touched_50
            and first_after_1430_touch is None
        ):
            first_after_1430_touch = {
                "time": tm,
                "fib50": fib50,
                "fib618": fib618,
                "fib70": fib70
            }

        if (
            hhmm in (
                "1400",
                "1430",
                "1500",
                "1530"
            )
        ):
            diagnostic_rows.append({
                "time": tm,
                "fib50": fib50,
                "fib618": fib618,
                "fib70": fib70
            })

    return {
        "bars": bars,
        "trigger_time": trigger_time,
        "fixed_high": fixed_high,
        "fixed_low": fixed_low,
        "fib50": fib50,
        "fib618": fib618,
        "fib70": fib70,
        "before_1430_touch_50": before_1430_touch_50,
        "first_after_1430_touch": first_after_1430_touch,
        "diagnostic_rows": diagnostic_rows
    }


print("=" * 70)
print("Reverse SPES RS3 - 1분봉 진입 진단")
print("피보나치 A/B : +20% 최초 발생 시점 고정")
print("=" * 70)

try:
    candidate = load_latest_candidate()

    stock_code = candidate.get(
        "stock_code"
    )

    stock_name = candidate.get(
        "stock_name"
    )

    target_date = candidate.get(
        "date"
    )

    daily_open = clean_number(
        candidate.get("open")
    )

    daily_high = clean_number(
        candidate.get("high")
    )

    print()
    print("진단 대상")
    print(
        "종목 :",
        stock_code,
        stock_name
    )
    print(
        "일자 :",
        target_date
    )
    print(
        "일봉 시가 :",
        daily_open
    )
    print(
        "일봉 고가 :",
        daily_high
    )
    print(
        "일봉 상승률 :",
        candidate.get("rise_pct"),
        "%"
    )
    print(
        "거래대금 :",
        candidate.get(
            "traded_value_eok"
        ),
        "억원"
    )

    print()

    app_key = getpass.getpass(
        "App Key 입력: "
    )

    secret_key = getpass.getpass(
        "Secret Key 입력: "
    )

    print()
    print("TOKEN 발급 중...")

    token = get_token(
        app_key,
        secret_key
    )

    print("✅ TOKEN 발급 성공")

    print()
    print("목표일 1분봉 조회 중...")

    minute_rows = load_target_day_minutes(
        token,
        stock_code,
        target_date
    )

    print()
    print(
        "목표일 받은 1분봉 :",
        len(minute_rows)
    )

    result = analyze_rs3_day(
        minute_rows,
        daily_open
    )

    print()
    print("=" * 70)
    print("RS3 분봉 진단 결과")
    print("=" * 70)

    if result is None:
        print("❌ 분석 가능한 분봉이 없습니다.")

    else:

        trigger_time = result[
            "trigger_time"
        ]

        if trigger_time:

            print(
                "+20% 최초 발생 :",
                trigger_time
            )

            print(
                "고정 A(고가) :",
                result["fixed_high"]
            )

            print(
                "고정 B(저가) :",
                result["fixed_low"]
            )

            print()
            print(
                "고정 50선 :",
                round(
                    result["fib50"],
                    2
                )
            )

            print(
                "고정 61.8선 :",
                round(
                    result["fib618"],
                    2
                )
            )

            print(
                "고정 70선 :",
                round(
                    result["fib70"],
                    2
                )
            )

        else:

            print(
                "❌ 분봉상 +20% 발생을 찾지 못했습니다."
            )

        print()
        print(
            "14:30 이전 50선 터치 :",
            "YES"
            if result[
                "before_1430_touch_50"
            ]
            else "NO"
        )

        after_touch = result[
            "first_after_1430_touch"
        ]

        if after_touch:

            print(
                "14:30 이후 첫 50선 터치 :",
                after_touch["time"]
            )

        else:

            print(
                "14:30 이후 50선 터치 : 없음"
            )

        print()
        print("=" * 70)
        print("주요 시점 고정 피보나치")
        print("=" * 70)

        for row in result[
            "diagnostic_rows"
        ]:

            print(
                row["time"],
                "/ 50",
                round(row["fib50"], 2),
                "/ 61.8",
                round(row["fib618"], 2),
                "/ 70",
                round(row["fib70"], 2)
            )

        print()
        print("✅ 1분봉 진단 완료")

except Exception as e:

    print()
    print(
        "❌ 오류 :",
        type(e).__name__,
        str(e)
    )

print()
input("Enter를 누르면 종료합니다...")

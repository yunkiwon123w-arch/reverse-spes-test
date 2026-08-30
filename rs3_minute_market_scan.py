import csv
import getpass
import os
import time
from collections import defaultdict

import requests


BASE_URL = "https://api.kiwoom.com"

INPUT_FILE = "rs3_candidates_minute_period.csv"

OUTPUT_FILE = "rs3_minute_entry_scan.csv"
ERROR_FILE = "rs3_minute_entry_errors.csv"

REQUEST_INTERVAL = 0.30

# 한 종목당 비정상 무한조회 방지
MAX_PAGES_PER_STOCK = 500


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


def load_candidates():
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

    return rows


def load_completed_keys():
    completed = set()

    if not os.path.exists(OUTPUT_FILE):
        return completed

    with open(
        OUTPUT_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:
            code = str(
                row.get("stock_code", "")
            ).strip()

            date = str(
                row.get("date", "")
            ).strip()

            if code and date:
                completed.add(
                    (code, date)
                )

    return completed


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

    return requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )


def load_stock_minutes(
    token,
    stock_code,
    oldest_target_date
):
    all_rows = []

    cont_yn = None
    next_key = None

    seen_next_keys = set()

    page = 0

    while page < MAX_PAGES_PER_STOCK:

        response = request_minute_page(
            token,
            stock_code,
            cont_yn,
            next_key
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP {response.status_code}"
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

        oldest_page_date = None

        for row in rows:

            tm = str(
                row.get("cntr_tm", "")
            ).strip()

            if len(tm) < 8:
                continue

            row_date = tm[:8]

            if (
                oldest_page_date is None
                or row_date < oldest_page_date
            ):
                oldest_page_date = row_date

            # 가장 오래된 후보 날짜보다
            # 더 최신 데이터만 저장
            if row_date >= oldest_target_date:
                all_rows.append(row)

        # 필요한 가장 오래된 날짜보다
        # 더 과거까지 도달했으면 종료
        if (
            oldest_page_date
            and oldest_page_date < oldest_target_date
        ):
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

        if new_next_key in seen_next_keys:
            break

        seen_next_keys.add(
            new_next_key
        )

        cont_yn = new_cont_yn
        next_key = new_next_key

        time.sleep(
            REQUEST_INTERVAL
        )

    return all_rows, page


def split_by_date(rows):
    by_date = defaultdict(list)

    for row in rows:

        tm = str(
            row.get("cntr_tm", "")
        ).strip()

        if len(tm) < 14:
            continue

        by_date[tm[:8]].append(row)

    return by_date


def analyze_day(
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

        high = clean_number(
            row.get("high_pric")
        )

        low = clean_number(
            row.get("low_pric")
        )

        cur = clean_number(
            row.get("cur_prc")
        )

        if (
            high is None
            or low is None
            or cur is None
        ):
            continue

        bars.append({
            "time": tm,
            "high": high,
            "low": low,
            "cur": cur
        })

    bars.sort(
        key=lambda x: x["time"]
    )

    if not bars:
        return {
            "status": "NO_MINUTE_DATA"
        }

    running_high = None
    running_low = None

    trigger_time = None

    fixed_high = None
    fixed_low = None

    fib50 = None
    fib618 = None
    fib70 = None

    before_1430_touch = False
    first_after_1430_touch = None

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

        # RS3:
        # 시가 대비 당일 고가 +20%
        # 최초 성립 시점의 A/B 고정
        if (
            trigger_time is None
            and rise_rate >= 0.20
        ):
            trigger_time = tm

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

        touched_50 = (
            low <= fib50 <= high
        )

        # 강의 제외조건:
        # 14:30 이전 50선 터치
        if (
            hhmm < "1430"
            and touched_50
        ):
            before_1430_touch = True

        # 14:30 이후 첫 50선 터치
        if (
            hhmm >= "1430"
            and touched_50
            and first_after_1430_touch is None
        ):
            first_after_1430_touch = tm

    if trigger_time is None:
        status = "NO_20_TRIGGER"

    elif before_1430_touch:
        status = "EXCLUDED_BEFORE_1430_TOUCH"

    elif first_after_1430_touch is None:
        status = "NO_AFTER_1430_TOUCH"

    else:
        status = "ENTRY_1_CANDIDATE"

    return {
        "status": status,
        "trigger_time": trigger_time,
        "fixed_high": fixed_high,
        "fixed_low": fixed_low,
        "fib50": fib50,
        "fib618": fib618,
        "fib70": fib70,
        "before_1430_touch": before_1430_touch,
        "entry1_time": first_after_1430_touch
    }


OUTPUT_FIELDS = [
    "stock_code",
    "stock_name",
    "market",
    "date",
    "daily_open",
    "daily_high",
    "rise_pct",
    "traded_value_eok",
    "trigger_time",
    "fixed_high",
    "fixed_low",
    "fib50",
    "fib618",
    "fib70",
    "before_1430_touch",
    "entry1_time",
    "status"
]


def append_result(row):
    exists = os.path.exists(
        OUTPUT_FILE
    )

    with open(
        OUTPUT_FILE,
        "a",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=OUTPUT_FIELDS
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)


def append_error(
    code,
    name,
    error
):
    exists = os.path.exists(
        ERROR_FILE
    )

    fields = [
        "stock_code",
        "stock_name",
        "error"
    ]

    with open(
        ERROR_FILE,
        "a",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        if not exists:
            writer.writeheader()

        writer.writerow({
            "stock_code": code,
            "stock_name": name,
            "error": error
        })


print("=" * 72)
print("Reverse SPES RS3 - 전체 1분봉 진입 스캔")
print("완료 데이터 자동 건너뛰기 / 중간저장 적용")
print("=" * 72)


try:
    candidates = load_candidates()

    completed = load_completed_keys()

    print()
    print(
        "전체 후보 :",
        f"{len(candidates):,}건"
    )

    print(
        "이미 완료 :",
        f"{len(completed):,}건"
    )

    pending = []

    for row in candidates:

        key = (
            str(
                row.get(
                    "stock_code",
                    ""
                )
            ).strip(),
            str(
                row.get(
                    "date",
                    ""
                )
            ).strip()
        )

        if key not in completed:
            pending.append(row)

    print(
        "남은 후보 :",
        f"{len(pending):,}건"
    )

    if not pending:
        print()
        print("✅ 이미 전체 스캔 완료")
        input(
            "Enter를 누르면 종료합니다..."
        )
        raise SystemExit

    grouped = defaultdict(list)

    for row in pending:

        code = str(
            row.get("stock_code", "")
        ).strip()

        if code:
            grouped[code].append(row)

    print(
        "조회할 종목 :",
        f"{len(grouped):,}개"
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

    total_groups = len(grouped)

    processed_candidates = 0

    count_entry = 0
    count_before = 0
    count_no_touch = 0
    count_no_trigger = 0
    count_no_data = 0
    error_count = 0

    for stock_index, (
        stock_code,
        stock_candidates
    ) in enumerate(
        grouped.items(),
        start=1
    ):

        stock_name = stock_candidates[0].get(
            "stock_name",
            ""
        )

        dates = [
            str(
                x.get("date", "")
            ).strip()
            for x in stock_candidates
        ]

        dates = [
            x for x in dates if x
        ]

        if not dates:
            continue

        oldest_target_date = min(
            dates
        )

        print(
            f"[{stock_index:,}/{total_groups:,}] "
            f"{stock_code} {stock_name} "
            f"/ 후보 {len(stock_candidates)}건"
        )

        try:
            minute_rows, pages = (
                load_stock_minutes(
                    token,
                    stock_code,
                    oldest_target_date
                )
            )

            by_date = split_by_date(
                minute_rows
            )

            for candidate in stock_candidates:

                target_date = str(
                    candidate.get(
                        "date",
                        ""
                    )
                ).strip()

                daily_open = clean_number(
                    candidate.get("open")
                )

                daily_high = clean_number(
                    candidate.get("high")
                )

                day_rows = by_date.get(
                    target_date,
                    []
                )

                result = analyze_day(
                    day_rows,
                    daily_open
                )

                status = result.get(
                    "status"
                )

                if status == "ENTRY_1_CANDIDATE":
                    count_entry += 1

                elif status == "EXCLUDED_BEFORE_1430_TOUCH":
                    count_before += 1

                elif status == "NO_AFTER_1430_TOUCH":
                    count_no_touch += 1

                elif status == "NO_20_TRIGGER":
                    count_no_trigger += 1

                elif status == "NO_MINUTE_DATA":
                    count_no_data += 1

                append_result({
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "market": candidate.get(
                        "market",
                        ""
                    ),
                    "date": target_date,
                    "daily_open": daily_open,
                    "daily_high": daily_high,
                    "rise_pct": candidate.get(
                        "rise_pct",
                        ""
                    ),
                    "traded_value_eok": candidate.get(
                        "traded_value_eok",
                        ""
                    ),
                    "trigger_time": result.get(
                        "trigger_time",
                        ""
                    ),
                    "fixed_high": result.get(
                        "fixed_high",
                        ""
                    ),
                    "fixed_low": result.get(
                        "fixed_low",
                        ""
                    ),
                    "fib50": result.get(
                        "fib50",
                        ""
                    ),
                    "fib618": result.get(
                        "fib618",
                        ""
                    ),
                    "fib70": result.get(
                        "fib70",
                        ""
                    ),
                    "before_1430_touch": result.get(
                        "before_1430_touch",
                        ""
                    ),
                    "entry1_time": result.get(
                        "entry1_time",
                        ""
                    ),
                    "status": status
                })

                processed_candidates += 1

            print(
                f"   분봉 {len(minute_rows):,}개 "
                f"/ {pages}페이지 "
                f"/ 완료 {processed_candidates:,}건"
            )

        except Exception as e:

            error_count += 1

            append_error(
                stock_code,
                stock_name,
                str(e)
            )

            print(
                "   ⚠ 오류 :",
                str(e)
            )

        # 종목별 호출 사이 여유
        time.sleep(
            REQUEST_INTERVAL
        )

        if stock_index % 10 == 0:
            print()
            print(
                "   ---- 중간 현황 ----"
            )

            print(
                "   1차매수 후보 :",
                count_entry
            )

            print(
                "   14:30 전 터치 제외 :",
                count_before
            )

            print(
                "   14:30 후 미터치 :",
                count_no_touch
            )

            print(
                "   +20% 분봉 불일치 :",
                count_no_trigger
            )

            print(
                "   분봉 없음 :",
                count_no_data
            )

            print(
                "   오류 종목 :",
                error_count
            )

            print()

    print()
    print("=" * 72)
    print("전체 1분봉 진입 스캔 완료")
    print("=" * 72)

    print(
        "이번 실행 처리 후보 :",
        processed_candidates
    )

    print(
        "1차매수 후보 :",
        count_entry
    )

    print(
        "14:30 이전 50선 터치 제외 :",
        count_before
    )

    print(
        "14:30 이후 50선 미터치 :",
        count_no_touch
    )

    print(
        "+20% 분봉 불일치 :",
        count_no_trigger
    )

    print(
        "분봉 데이터 없음 :",
        count_no_data
    )

    print(
        "오류 종목 :",
        error_count
    )

    print()
    print(
        "결과 파일 :",
        OUTPUT_FILE
    )

    print(
        "오류 파일 :",
        ERROR_FILE
    )

    print()
    print(
        "✅ 결과는 후보 1건마다 즉시 저장됩니다."
    )

    print(
        "중간에 종료 후 다시 실행해도 완료 건은 건너뜁니다."
    )


except KeyboardInterrupt:

    print()
    print()
    print("⚠ 사용자가 실행을 중단했습니다.")
    print(
        "지금까지 완료된 결과는 CSV에 저장되어 있습니다."
    )
    print(
        "다시 실행하면 완료된 후보는 자동으로 건너뜁니다."
    )


except Exception as e:

    print()
    print(
        "❌ 오류 :",
        type(e).__name__,
        str(e)
    )


print()
input("Enter를 누르면 종료합니다...")

import getpass
import requests

BASE_URL = "https://api.kiwoom.com"

# 우선 구조 검증용 종목 몇 개
# 전체시장 종목코드 자동수집은 다음 단계에서 붙임
TEST_CODES = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "035420",  # NAVER
    "035720",  # 카카오
]


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

    value = str(value).replace(",", "").strip()

    if not value:
        return None

    try:
        return abs(int(value))
    except ValueError:
        return None


def request_daily_chart(token, stock_code):
    url = BASE_URL + "/api/dostk/chart"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10081"
    }

    body = {
        "stk_cd": stock_code,
        "base_dt": "20260828",
        "upd_stkpc_tp": "1"
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    return response


def find_rs3_daily_candidates(rows):
    candidates = []

    for row in rows:
        date = str(row.get("dt", "")).strip()

        open_price = clean_number(row.get("open_pric"))
        high_price = clean_number(row.get("high_pric"))

        if not date or not open_price or not high_price:
            continue

        if open_price <= 0:
            continue

        rise_rate = (
            (high_price - open_price)
            / open_price
        )

        # RS3 원문:
        # 시가 대비 당일 고가 상승률 20% 이상
        if rise_rate >= 0.20:
            candidates.append({
                "date": date,
                "open": open_price,
                "high": high_price,
                "rise_pct": rise_rate * 100
            })

    return candidates


print("=" * 65)
print("RS3 일봉 1차 후보 선별 테스트")
print("조건 : 시가 대비 당일 고가 +20% 이상")
print("=" * 65)

app_key = getpass.getpass("App Key 입력: ")
secret_key = getpass.getpass("Secret Key 입력: ")

try:
    token = get_token(app_key, secret_key)

    print()
    print("✅ TOKEN 발급 성공")
    print()

    total_candidates = 0

    for stock_code in TEST_CODES:

        response = request_daily_chart(
            token,
            stock_code
        )

        data = response.json()

        print("-" * 65)
        print("종목 :", stock_code)

        if response.status_code != 200:
            print("HTTP 오류 :", response.status_code)
            continue

        if data.get("return_code") != 0:
            print(
                "API 오류 :",
                data.get("return_msg")
            )
            continue

        rows = data.get(
            "stk_dt_pole_chart_qry",
            []
        )

        print("받은 일봉 :", len(rows))

        candidates = find_rs3_daily_candidates(
            rows
        )

        print(
            "RS3 +20% 후보 :",
            len(candidates)
        )

        total_candidates += len(candidates)

        for candidate in candidates[:20]:
            print(
                candidate["date"],
                "/ 시가", candidate["open"],
                "/ 고가", candidate["high"],
                "/ 상승률",
                f'{candidate["rise_pct"]:.2f}%'
            )

    print()
    print("=" * 65)
    print(
        "전체 테스트 후보 수 :",
        total_candidates
    )
    print("=" * 65)

except Exception as e:
    print()
    print(
        "❌ 오류 :",
        type(e).__name__,
        str(e)
    )

print()
input("Enter를 누르면 종료합니다...")

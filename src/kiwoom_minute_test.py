import getpass
import requests
from datetime import datetime

BASE_URL = "https://api.kiwoom.com"


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


def get_minute_data(token):
    url = BASE_URL + "/api/dostk/chart"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10080"
    }

    body = {
        "stk_cd": "005930",
        "tic_scope": "1",
        "upd_stkpc_tp": "1",
        "base_dt": datetime.now().strftime("%Y%m%d")
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    return response


print("=" * 55)
print("키움 REST API - 삼성전자 1분봉 조회 테스트")
print("=" * 55)

app_key = getpass.getpass("App Key 입력: ")
secret_key = getpass.getpass("Secret Key 입력: ")

try:
    print()
    print("1. 토큰 발급 중...")
    token = get_token(app_key, secret_key)
    print("   TOKEN 발급 성공")

    print()
    print("2. 삼성전자(005930) 1분봉 조회 중...")

    response = get_minute_data(token)

    print("   HTTP STATUS :", response.status_code)

    data = response.json()

    print("   RETURN CODE :", data.get("return_code"))
    print("   RETURN MSG  :", data.get("return_msg"))

    rows = data.get("stk_min_pole_chart_qry", [])

    print()
    print("3. 조회 결과")
    print("   받은 분봉 개수 :", len(rows))
    print("   연속조회 여부 :", response.headers.get("cont-yn"))
    print("   Next-Key 존재 :", bool(response.headers.get("next-key")))

    if rows:
        print()
        print("   첫 번째 데이터 :", rows[0])
        print("   마지막 데이터 :", rows[-1])

        dates = [
            str(x.get("cntr_tm", ""))
            for x in rows
            if x.get("cntr_tm")
        ]

        if dates:
            print()
            print("   최신 시각 :", max(dates))
            print("   가장 오래된 시각 :", min(dates))

    print()
    if data.get("return_code") == 0 and rows:
        print("✅ 1분봉 조회 성공")
    else:
        print("❌ 1분봉 조회 실패")

except Exception as e:
    print()
    print("❌ 오류 :", type(e).__name__, str(e))

print()
input("Enter를 누르면 종료합니다...")

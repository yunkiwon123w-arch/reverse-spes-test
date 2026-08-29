import getpass
import requests

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
            f"HTTP 오류: {response.status_code}"
        )

    if data.get("return_code") not in (None, 0):
        raise RuntimeError(
            f"API 오류: {data.get('return_msg')}"
        )

    rows = data.get("list", [])

    return rows


print("=" * 65)
print("키움 REST API - 코스피/코스닥 종목리스트 테스트")
print("=" * 65)

app_key = getpass.getpass("App Key 입력: ")
secret_key = getpass.getpass("Secret Key 입력: ")

try:
    token = get_token(app_key, secret_key)

    print()
    print("✅ TOKEN 발급 성공")
    print()

    kospi = get_stock_list(token, "0")
    kosdaq = get_stock_list(token, "10")

    print("코스피 종목 수 :", len(kospi))
    print("코스닥 종목 수 :", len(kosdaq))
    print("전체 종목 수   :", len(kospi) + len(kosdaq))

    print()
    print("=" * 65)
    print("코스피 앞 5개")
    print("=" * 65)

    for row in kospi[:5]:
        print(
            row.get("code"),
            "/",
            row.get("name"),
            "/",
            row.get("marketName"),
            "/ 상태:",
            row.get("state")
        )

    print()
    print("=" * 65)
    print("코스닥 앞 5개")
    print("=" * 65)

    for row in kosdaq[:5]:
        print(
            row.get("code"),
            "/",
            row.get("name"),
            "/",
            row.get("marketName"),
            "/ 상태:",
            row.get("state")
        )

    print()
    print("✅ 전체 종목리스트 조회 성공")

except Exception as e:
    print()
    print(
        "❌ 오류 :",
        type(e).__name__,
        str(e)
    )

print()
input("Enter를 누르면 종료합니다...")

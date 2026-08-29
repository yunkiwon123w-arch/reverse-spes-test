import os
import requests

APP_KEY = os.environ.get("KIWOOM_APP_KEY")
SECRET_KEY = os.environ.get("KIWOOM_SECRET_KEY")

if not APP_KEY or not SECRET_KEY:
    print("ERROR: App Key / Secret Key 환경변수가 없습니다.")
    raise SystemExit(1)

url = "https://api.kiwoom.com/oauth2/token"

headers = {
    "Content-Type": "application/json;charset=UTF-8"
}

payload = {
    "grant_type": "client_credentials",
    "appkey": APP_KEY,
    "secretkey": SECRET_KEY
}

try:
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=20
    )

    print("HTTP STATUS:", response.status_code)

    data = response.json()

    print("RETURN CODE:", data.get("return_code"))
    print("RETURN MSG :", data.get("return_msg"))
    print("EXPIRES    :", data.get("expires_dt"))

    if data.get("token"):
        print("TOKEN      : 발급 성공")
    else:
        print("TOKEN      : 발급 실패")

except Exception as e:
    print("ERROR:", type(e).__name__, str(e))

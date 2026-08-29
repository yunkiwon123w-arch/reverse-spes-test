import getpass
import requests

print("=" * 50)
print("키움 REST API 인증 테스트")
print("=" * 50)

app_key = getpass.getpass("App Key 입력: ")
secret_key = getpass.getpass("Secret Key 입력: ")

url = "https://api.kiwoom.com/oauth2/token"

headers = {
    "Content-Type": "application/json;charset=UTF-8"
}

payload = {
    "grant_type": "client_credentials",
    "appkey": app_key,
    "secretkey": secret_key
}

try:
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=20
    )

    print()
    print("HTTP STATUS :", response.status_code)

    data = response.json()

    print("RETURN CODE :", data.get("return_code"))
    print("RETURN MSG  :", data.get("return_msg"))
    print("EXPIRES     :", data.get("expires_dt"))

    if data.get("token"):
        print()
        print("✅ TOKEN 발급 성공")
    else:
        print()
        print("❌ TOKEN 발급 실패")

except Exception as e:
    print()
    print("❌ 오류 발생:", type(e).__name__, str(e))

print()
input("Enter를 누르면 종료합니다...")

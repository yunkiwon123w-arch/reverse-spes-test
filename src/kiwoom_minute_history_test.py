import getpass
import time
import requests

BASE_URL = "https://api.kiwoom.com"
STOCK_CODE = "005930"     # 삼성전자
TIC_SCOPE = "1"           # 1분봉

# 비정상적인 무한 반복 방지용.
# 실제 데이터가 끝나면 이 값에 도달하기 전에 자동 종료됨.
MAX_PAGES = 3000


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


def request_minute_page(token, cont_yn=None, next_key=None):
    url = BASE_URL + "/api/dostk/chart"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10080"
    }

    # 두 번째 요청부터 연속조회 헤더 사용
    if cont_yn == "Y" and next_key:
        headers["cont-yn"] = "Y"
        headers["next-key"] = next_key

    body = {
        "stk_cd": STOCK_CODE,
        "tic_scope": TIC_SCOPE,
        "upd_stkpc_tp": "1"
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20
    )

    return response


print("=" * 65)
print("키움 REST API - 1분봉 최대 과거 조회범위 테스트")
print("종목 : 삼성전자(005930)")
print("=" * 65)

app_key = getpass.getpass("App Key 입력: ")
secret_key = getpass.getpass("Secret Key 입력: ")

try:
    print()
    print("1. 토큰 발급 중...")
    token = get_token(app_key, secret_key)
    print("   ✅ TOKEN 발급 성공")

    print()
    print("2. 1분봉 연속조회 시작")
    print("   데이터가 더 이상 없을 때까지 자동 조회합니다.")
    print()

    page = 0
    total_rows = 0

    newest_time = None
    oldest_time = None

    cont_yn = None
    next_key = None

    seen_next_keys = set()

    while page < MAX_PAGES:

        response = request_minute_page(
            token=token,
            cont_yn=cont_yn,
            next_key=next_key
        )

        if response.status_code != 200:
            print()
            print("❌ HTTP 오류 :", response.status_code)
            print(response.text)
            break

        data = response.json()

        if data.get("return_code") != 0:
            print()
            print("❌ API 오류")
            print("RETURN CODE :", data.get("return_code"))
            print("RETURN MSG  :", data.get("return_msg"))
            break

        rows = data.get("stk_min_pole_chart_qry", [])

        page += 1
        total_rows += len(rows)

        # 현재 페이지 시간 범위 확인
        times = []

        for row in rows:
            tm = str(row.get("cntr_tm", "")).strip()

            if tm:
                times.append(tm)

        if times:
            page_newest = max(times)
            page_oldest = min(times)

            if newest_time is None or page_newest > newest_time:
                newest_time = page_newest

            if oldest_time is None or page_oldest < oldest_time:
                oldest_time = page_oldest

        new_cont_yn = response.headers.get("cont-yn", "")
        new_next_key = response.headers.get("next-key", "")

        # 진행상황 출력
        if page == 1 or page % 10 == 0:
            print(
                f"[{page:4d} 페이지] "
                f"누적 {total_rows:,}개 / "
                f"현재 최과거 {oldest_time}"
            )

        # 더 이상 연속조회가 없으면 종료
        if new_cont_yn != "Y" or not new_next_key:
            print()
            print("✅ 더 이상 연속조회 데이터가 없습니다.")
            break

        # 같은 next-key 반복 방지
        if new_next_key in seen_next_keys:
            print()
            print("⚠ 동일 Next-Key가 반복되어 안전 종료합니다.")
            break

        seen_next_keys.add(new_next_key)

        cont_yn = new_cont_yn
        next_key = new_next_key

        # 키움 호출 제한을 넘지 않도록 여유 있게 대기
        time.sleep(0.30)

    print()
    print("=" * 65)
    print("3. 최종 결과")
    print("=" * 65)

    print("총 조회 페이지 :", page)
    print("총 받은 분봉   :", f"{total_rows:,}개")
    print("가장 최신 분봉 :", newest_time)
    print("가장 과거 분봉 :", oldest_time)

    if page >= MAX_PAGES:
        print()
        print(
            f"⚠ 안전제한 {MAX_PAGES}페이지에 도달했습니다."
        )
        print(
            "아직 데이터가 남아 있을 수 있습니다."
        )

    elif oldest_time:
        print()
        print("✅ 키움 1분봉 과거 조회범위 확인 완료")

except KeyboardInterrupt:
    print()
    print("사용자가 조회를 중단했습니다.")

except Exception as e:
    print()
    print("❌ 오류 발생")
    print(type(e).__name__, str(e))

print()
input("Enter를 누르면 종료합니다...")

RS20 PROGRAM_FLOW COLLECTOR v1.3

변경점
- 기존 kiwoom_auth_test.py가
    app_key = getpass(...)
    secret_key = getpass(...)
  형태인 경우를 지원합니다.
- auth_test.py 자체를 실행/import하지 않습니다.
- 저장된 키가 없으면 프로그램이 App Key / App Secret을 직접
  숨김 입력(getpass)으로 받습니다.
- 입력값은 화면에 표시되지 않고 파일에도 저장하지 않습니다.
- 입력받은 App Key / Secret으로 Access Token을 자동 발급합니다.

인증 우선순위
1. 기존 auth 파일의 literal 문자열 상수
2. Windows 환경변수
3. 로컬 getpass 입력

실행
run_rs20_program_flow_collector_v1_3.bat

정상 흐름
Stored Kiwoom credentials were not found.
Kiwoom APP KEY (hidden):
Kiwoom APP SECRET (hidden):
AUTH SOURCE             : LOCAL_GETPASS
ACCESS TOKEN            : issuing automatically...
ACCESS TOKEN            : OK
[001/555] ...

주의
- APP KEY와 APP SECRET은 채팅에 올리지 마세요.
- 입력할 때 화면에 글자나 별표가 안 보여도 정상입니다.
- 다른 키움 대량수집 프로그램과 동시에 실행하지 마세요.
- 주문 API는 사용하지 않습니다.

출력
- rs20_program_flow_collection_status_v1_3.csv
- rs20_program_flow_missing_v1_3.csv
- rs20_program_flow_progress_v1_3.csv
- rs20_program_flow_collection_summary_v1_3.txt

캐시
common_market_data\program_flow_ka90008_v1\YYYY\MM\<stock>_<date>.csv.gz

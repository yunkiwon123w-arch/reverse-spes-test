RS20 PROGRAM_FLOW COLLECTOR v1.4

버그 수정
- v1.3의 AUTH FAILED: name 'first_env' is not defined 오류 수정.
- 인증 우선순위는 그대로 유지:
  1) 기존 auth 파일의 literal 문자열
  2) Windows 환경변수
  3) 로컬 숨김 입력(getpass)

현재 사용자 환경에서는 기존 kiwoom_auth_test.py가 getpass 방식이므로,
정상 실행 시 아래처럼 진행됩니다.

Kiwoom APP KEY (hidden):
Kiwoom APP SECRET (hidden):
AUTH SOURCE             : LOCAL_GETPASS
ACCESS TOKEN            : issuing automatically...
ACCESS TOKEN            : OK

그 후:
[001/555] COLLECTED ...

주의
- 입력 중 글자나 별표가 안 보여도 정상입니다.
- App Key / Secret 값은 채팅에 올리지 마세요.
- 다른 키움 대량수집 프로그램과 동시에 실행하지 마세요.
- 주문 API는 사용하지 않습니다.

실행
run_rs20_program_flow_collector_v1_4.bat

출력
- rs20_program_flow_collection_status_v1_4.csv
- rs20_program_flow_missing_v1_4.csv
- rs20_program_flow_progress_v1_4.csv
- rs20_program_flow_collection_summary_v1_4.txt

캐시는 기존 v1 경로를 그대로 재사용합니다:
common_market_data\program_flow_ka90008_v1\YYYY\MM\<stock>_<date>.csv.gz

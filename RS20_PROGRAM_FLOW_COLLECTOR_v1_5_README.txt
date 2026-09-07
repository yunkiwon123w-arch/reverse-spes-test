RS20 PROGRAM_FLOW COLLECTOR v1.5

수정 내용
- v1.4에서 누락된 _last_request_ts 전역 상태 복구
- v1.4에서 누락된 RAW_FIELDS 복구
- v1.4에서 누락된 STATUS_FIELDS 복구
- Python 문법 컴파일 검증 완료
- 기존 인증 성공 방식(getpass -> Access Token 자동발급)은 그대로 유지
- 기존 ka90008 수집 범위, RESUME 캐시, 주문 없음 구조도 그대로 유지

이번 실행
1) 기존 프로젝트 루트에 아래 2개 파일을 넣습니다.
   rs20_program_flow_collector_v1_5.py
   run_rs20_program_flow_collector_v1_5.bat

2) run_rs20_program_flow_collector_v1_5.bat 더블클릭

3) App Key / App Secret을 PC에서만 숨김 입력

정상 흐름
ACCESS TOKEN            : OK
[001/555] COLLECTED ... 또는 NO_DATA ...
[002/555] ...

주의
- App Key / App Secret 값은 채팅에 올리지 마세요.
- 다른 키움 대량수집 프로그램과 동시에 실행하지 마세요.
- 주문 API는 사용하지 않습니다.
- 기존 v1 캐시는 그대로 재사용합니다.

출력
rs20_program_flow_collection_status_v1_5.csv
rs20_program_flow_missing_v1_5.csv
rs20_program_flow_progress_v1_5.csv
rs20_program_flow_collection_summary_v1_5.txt

캐시
common_market_data\program_flow_ka90008_v1\YYYY\MM\<stock>_<date>.csv.gz

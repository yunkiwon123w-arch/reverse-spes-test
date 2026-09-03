Reverse SPES - RS20 Historical Candidate Collector v1.1

교체 목적
- v1에서 반복된 ConnectionResetError(10054) 대응
- 기존 정상 진행 결과는 그대로 이어서 사용

v1.1 핵심
1. ConnectionReset / Timeout / 429 / 5xx 자동 재시도
2. 재시도 대기 1.5초 -> 3초 -> 6초 -> 10초
3. API 간격 0.32초로 완화
4. DONE인 종목만 재실행 시 건너뜀
5. ERROR인 종목은 다시 시도
6. 기존 v1의 CSV 파일명 그대로 사용
7. 이미 저장된 (종목코드, 날짜)는 중복 저장하지 않음
8. 실제 주문 없음

교체 방법
- 기존 rs20_historical_candidate_collector_v1.py는 삭제하지 않아도 됩니다.
- 새 3개 파일을 기존 프로젝트 루트에 넣습니다.
- 이제부터 run_rs20_historical_candidate_collector_v1_1.bat만 실행합니다.
- 시작일은 이전과 동일하게 그냥 Enter -> 20250801
- App Key / Secret Key 입력

중요
기존 아래 파일은 절대 삭제하지 마세요.
- rs20_history_daily_prefilter_v1.csv
- rs20_history_daily_stock_done_v1.csv
- rs20_history_minute_stock_done_v1.csv
- rs20_history_numeric_candidates_v1.csv
- rs20_history_errors_v1.csv
- rs20_history_cache_v1/

기존 ERROR 줄이 daily/minute done CSV에 남아 있어도 괜찮습니다.
v1.1은 status=DONE인 종목만 완료 처리하므로 ERROR 종목은 다시 조회합니다.

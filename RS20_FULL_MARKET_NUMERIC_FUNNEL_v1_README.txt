Reverse SPES - RS20 Full Market Numeric Funnel v1

목적
- Kiwoom 전종목을 대상으로 RS20의 원문상 숫자 핵심조건만 검사합니다.
- 실제 주문 기능은 없습니다.

자동 판정
1. M지표 >= 200억원
2. M지표 / 거래대금 >= 20%

진단 기록
- 최신 거래일 day high / day low
- Reverse Fibonacci 38선
- running fib38 정확 터치 최초 시각
- running fib38까지 최소 거리(%)

자동 판정하지 않는 원문 미정의 항목
- 세력주 / 수급세력주
- '38선 부근'의 허용범위
- 3파 차트의 기계적 정의
- 신규상장의 기간 정의

실행
1. 이 파일과 rs20_full_market_numeric_funnel_v1.py를 기존 프로젝트 루트에 넣습니다.
2. run_rs20_full_market_numeric_funnel_v1.bat 더블클릭
3. Kiwoom App Key / Secret Key를 화면에 입력합니다.
4. 중단은 Ctrl+C
5. 재실행하면 progress CSV 기준으로 완료 종목은 건너뜁니다.

생성 파일
- rs20_full_market_numeric_candidates_v1.csv
- rs20_full_market_numeric_progress_v1.csv
- rs20_full_market_numeric_errors_v1.csv (오류가 있을 때)
- rs20_full_market_numeric_summary_v1.txt
- rs20_funnel_cache_v1/ (Universe 캐시)

중요
이 단계의 후보는 RS20 최종 매매후보가 아닙니다.
원문 미정의 조건을 통과시키지 않았기 때문에 '숫자 핵심조건 후보'입니다.

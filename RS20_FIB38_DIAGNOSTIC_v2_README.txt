RS20 38선 첫 눌림 진단 v2

필요 파일:
- rs20_fib38_first_pullback_diagnostic_v2.py
- run_rs20_fib38_first_pullback_diagnostic_v2.bat
- 기존 rs20_full_market_numeric_candidates_v1.csv

v2 수정:
- anchor 고점 봉 자체를 38선 터치로 세지 않음
- anchor 고점 이후 봉에서만 눌림 측정
- 38선 부근 허용폭, 상승률 threshold를 임의 생성하지 않음
- 가능한 running-high anchor를 모두 보존
- 실제 주문 없음

생성:
- rs20_fib38_first_pullback_diagnostic_v2.csv
- rs20_fib38_anchor_detail_v2.csv
- rs20_fib38_minute_bars_v2.csv
- rs20_fib38_diagnostic_v2_result_note.txt

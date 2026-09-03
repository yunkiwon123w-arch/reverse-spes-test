Reverse SPES - RS20 Historical Candidate Collector v1

목적:
과거 여러 거래일의 RS20 숫자 핵심조건 표본을 확보합니다.

자동 조건:
- M >= 200억원
- M / 거래대금 >= 20%

PHASE A:
- ka10081 과거 일봉에서 거래대금 >= 200억원 날짜만 사전선별
- 거래대금 < 200억원은 M>=200이 불가능하므로 안전한 필요조건 필터

PHASE B:
- PHASE A 대상 종목만 ka10080 과거 1분봉 pagination
- 목표 날짜별 M 계산
- M>=200 + M/거래대금>=20% 통과 날짜 저장
- 목표 날짜보다 과거까지 도달하면 그 종목 API pagination 종료

중단/재개:
Ctrl+C 가능.
다시 실행하면 완료 종목 CSV를 기준으로 이어서 진행합니다.

기본 시작일:
20250801
이 날짜는 이전 프로젝트에서 확인된 Kiwoom 분봉 보존 실측 시작점과 맞춘 작업 기본값일 뿐,
API의 영구 보존기간을 의미하지 않습니다.

생성 파일:
- rs20_history_daily_prefilter_v1.csv
- rs20_history_daily_stock_done_v1.csv
- rs20_history_minute_stock_done_v1.csv
- rs20_history_numeric_candidates_v1.csv
- rs20_history_errors_v1.csv
- rs20_history_summary_v1.txt
- rs20_history_cache_v1/

중요:
- 세력/수급세력주 자동분류 안 함
- 38선 부근 허용폭 안 만듦
- 3파 자동정의 안 함
- 신규상장 기간 임의 정의 안 함
- 실제 주문 없음

RS3 PAPER Forward Engine v1

목적
- 실제 주문을 전혀 보내지 않는 PAPER 전용 엔진
- RS3 원문판의 진입/익절/손절 구조를 실시간 기록
- 별도로 연구동결 후보 STAGE2 v1 방어 신호를 기록
- Forward Test용 로그 축적

후보 CSV
파일명: rs3_paper_candidates.csv

필수 열:
stock_code
stock_name
traded_value_eok
is_force_stock
is_new_listing
is_tusang_or_higher
is_short_overheat_today

Y/N이 비어 있으면 해당 종목은 PENDING_REVIEW 상태로 두고 PAPER 진입하지 않음.
원문에서 정확히 자동화 정의가 확정되지 않은 항목을 프로그램이 임의 추정하지 않기 위한 조치.

중요
- traded_value_eok는 당일 500억원 이상 후보를 사전 선별하는 입력값.
- M>=200은 RS3 필수진입 조건이 아니며 probability-up 주석으로만 기록.
- 오후 2:30 이전 50선 터치 종목은 원문 제외조건으로 처리.
- 61.8선 "근처" 반등, 투상 이상 등의 정확한 자동판정 정의는 원문 확정 전 임의 생성하지 않음.
- 실제 주문 API 호출 코드는 포함하지 않음.

STAGE2 v1
원문 RS3가 아니라 개선 연구판.
현재 연구동결 후보 조건을 그대로 사용하며 PAPER 로그에서 원문 흐름과 구분해서 기록.

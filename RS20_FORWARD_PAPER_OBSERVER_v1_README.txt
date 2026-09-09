RS20 FORWARD PAPER OBSERVER v1

이 단계의 목적
과거 데이터를 더 튜닝하지 않고, 앞으로 새로 들어오는 실시간 표본에서
RS20 원문 숫자구조와 Reverse-38 진입, 체결 가능성, PROGRAM_FLOW 보조지표를
관측합니다.

중요
- 실제 주문 없음
- PROGRAM_FLOW는 필터가 아니라 관측값
- pf_net_amt_0도 매매 차단 조건으로 사용하지 않음
- 38선 '부근' 허용폭을 임의로 만들지 않음
- 세력주/수급세력주 자동분류 없음
- 3파/신규상장 기계적 제외 규칙 발명 없음
- 해당 항목들은 SOURCE_REVIEW_REQUIRED로 기록

원문 수치조건
- M >= 200억원
- M / 누적거래대금 >= 20%

M지표
1분봉 기준:
(H+O+L+C)/4 * Volume / 1억원
Close > Open : +
Close < Open : -
Close = Open : 0
당일 누적

Reverse Fibonacci
dayhigh = DayHigh()
daylow = DayLow()
K = dayhigh-daylow
강의의 0.382선 = K*0.618 + daylow

실시간 데이터
- 0B 주식체결: 전체 KOSPI/KOSDAQ 감시
- 0w 종목프로그램매매: RS20 numeric event가 활성화된 종목만 추가 구독
키움 공식 WebSocket:
wss://api.kiwoom.com:10000/api/dostk/websocket

프로그램 수급
0w field 212 = 순매수금액
기록만 합니다. 진입 필터 아님.

Forward PAPER 연구청산
과거 검증의 plateau를 새 데이터에서 병렬 관측하기 위해:
- 5% / 3%
- 7% / 4%
- 10% / 5%
- 미도달 시 EOD
이 값들은 원문 규칙이 아닙니다.

실행 전
Python websockets 패키지가 없으면 한 번만:
python -m pip install websockets

실행
run_rs20_forward_paper_observer_v1.bat

매우 중요
첫날에는 반드시 장 시작 전(09:00 이전)에 실행하세요.
M지표는 장 시작부터 누적해야 하기 때문입니다.

같은 날 프로그램을 재시작할 때는
forward_paper/rs20_v1/rs20_forward_state_v1.json
상태를 자동 복원합니다.

출력
forward_paper/rs20_v1/
- rs20_forward_state_v1.json
- rs20_forward_events_v1.csv
- rs20_forward_minutes_v1.csv
- rs20_forward_errors_v1.csv

중단
Ctrl+C
상태 저장 후 종료합니다.

주의
전체 KOSPI/KOSDAQ 0B WebSocket 등록을 사용하므로,
첫 실전 실행은 수신 안정성과 등록 응답을 먼저 확인합니다.
주문 API는 사용하지 않습니다.

RS3 PAPER 통합 v2

1. 목적
- 실제 주문 없이 Forward PAPER 테스트
- KOSPI/KOSDAQ 전 종목 자동 스캔
- 당일 고가가 시가 대비 +20% 이상
- 거래대금 500억원 이상
- 후보를 rs3_paper_candidates_auto.csv에 자동 등록
- 등록 후보의 1분봉을 60초 주기로 감시
- 원문 RS3 PAPER와 STAGE2 v1 개선신호 기록

2. 실행시간
- 09:00 이전: 09:00까지 대기
- 09:00~15:30: 스캐너 + 모니터 동작
- 15:30 이후: 반복 API 호출 없이 자동 종료

3. 전종목 스캔
- ka10099로 KOSPI/KOSDAQ 종목목록
- ka10081 일봉으로 +20% / 500억 조건 검사
- API 제한을 고려해 약 4회/초 이하로 호출
- 전시장 한 번 스캔에는 시간이 걸릴 수 있음
- 스캔 완료 후 10분 쉬고 다시 전시장 스캔

4. 후보 자동파일
rs3_paper_candidates_auto.csv

자동 입력:
stock_code, stock_name, market, scan_time,
open_price, day_high, rise_pct, traded_value_eok

수동검토:
is_force_stock
is_new_listing
is_tusang_or_higher
is_short_overheat_today

원문에서 정확한 기계적 정의가 확정되지 않은 항목이므로
프로그램이 임의 판정하지 않는다.
비어 있으면 PENDING_REVIEW.
Y/N 입력 후 다음 모니터 주기부터 반영.

5. 원문 RS3
- +20% 첫 도달 시 A/B 고정
- 거래대금 500억 이상
- 오후 2:30 이후
- 14:30 이전 50선 터치 제외
- 50선 1차 PAPER
- 61.8선 2차 PAPER
- 각각 +4% 익절
- 70선 손절
- M>=200은 필수진입이 아니라 probability-up 주석

6. STAGE2 v1
- 원문이 아닌 개선 연구판
- 현재 동결한 조건을 변경하지 않고 병렬 기록
- 해당 시 1차 방어 / 2차 취소로 PAPER 기록

7. 실제 주문
- 없음
- 주문 endpoint 호출 코드 자체가 없음

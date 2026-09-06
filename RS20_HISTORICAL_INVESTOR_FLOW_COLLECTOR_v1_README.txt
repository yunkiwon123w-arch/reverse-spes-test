RS20 HISTORICAL INVESTOR FLOW COLLECTOR v1

PURPOSE
Collect historical investor-flow data for the frozen 1,174 RS20 numeric
candidate stock-dates.

OFFICIAL KIWOOM REST API
- ka10060
- POST /api/dostk/chart
- 종목별투자자기관별차트요청

EFFICIENCY
The collector works by UNIQUE STOCK, not by all 1,174 candidate rows.
If one stock has several candidate dates, historical pages are reused.

DATA SAVED
- 개인
- 외국인
- 기관계
- 금융투자
- 보험
- 투신
- 기타금융
- 은행
- 연기금등
- 사모펀드
- 국가
- 기타법인
- 내외국인
plus date/current price/cumulative traded amount where returned.

RAW CACHE
common_market_data/investor_flow_daily_v1/<stock_code>.csv

REQUIRED INPUT
rs20_numeric_candidates_final_audited_v1.csv

RUN
Double-click:
run_rs20_historical_investor_flow_collector_v1.bat

The program asks locally for:
- KIWOOM APP KEY
- KIWOOM SECRET KEY
They are hidden while typed and are NOT saved in the output files.

OUTPUT
- rs20_investor_flow_progress_v1.csv
- rs20_investor_flow_candidates_v1.csv
- rs20_investor_flow_missing_v1.csv
- rs20_investor_flow_errors_v1.csv (only if errors occur)
- rs20_investor_flow_summary_v1.txt
- common_market_data/investor_flow_daily_v1/

IMPORTANT
This collector DOES NOT classify:
- 세력주
- 수급주
- 수급세력주

That classification will be studied only after the historical investor data is
collected and compared with the lecture examples. No source rule is invented.

NO ORDER API.

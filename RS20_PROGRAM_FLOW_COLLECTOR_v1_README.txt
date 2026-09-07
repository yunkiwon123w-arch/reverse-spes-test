RS20 PROGRAM_FLOW COLLECTOR v1

PURPOSE
Collect historical stock-by-time program-trading data only for the frozen
RS20 v1.2 FIRST EXACT Reverse-38 stock/date events.

KIWOOM API
ka90008 - 종목시간별프로그램매매추이요청

REQUEST
POST /api/dostk/mrkcond

Body:
- amt_qty_tp = 1 (amount; official unit million KRW)
- stk_cd
- date = YYYYMMDD

INPUT
rs20_source_event_state_machine_candidate_summary_v1_2.csv

SCOPE
Only rows with has_exact_touch_after_activation = Y.
No whole-market scan.

CACHE
common_market_data/program_flow_ka90008_v1/YYYY/MM/<stock>_<date>.csv.gz

RESUME
Existing valid cache files are skipped.
Ctrl+C is safe; rerun the BAT to continue.

IMPORTANT
Do not run another Kiwoom-heavy collector at the same time.

NO_DATA
If Kiwoom does not return historical ka90008 rows for a stock/date,
the collector records NO_DATA.
NO_DATA is never converted to zero program flow.

OUTPUT
- rs20_program_flow_collection_status_v1.csv
- rs20_program_flow_missing_v1.csv
- rs20_program_flow_progress_v1.csv
- rs20_program_flow_collection_summary_v1.txt

RUN
run_rs20_program_flow_collector_v1.bat

ACCESS TOKEN
Entered locally with hidden input.
The token is not written to disk.

NO ORDER API.

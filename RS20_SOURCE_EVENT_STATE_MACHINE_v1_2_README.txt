RS20 SOURCE EVENT STATE MACHINE v1.2

CHANGE FROM v1.1
v1.1 treated every CORE_ON -> CORE_OFF -> CORE_ON segment as a separate
first-pullback search segment.

v1.2 uses ONE continuous RS20 event per stock/date.

EVENT FLOW
1. Wait until the intraday numeric core is first satisfied:
   - M >= 200 eok
   - M / cumulative reconstructed traded value >= 20%

2. Activate the RS20 event ONCE.

3. The activation bar itself is not counted as a later pullback.

4. From the next 1-minute bar through EOD:
   - keep dynamic DayHigh / DayLow / Reverse Fib38
   - CORE OFF/ON changes are logged only
   - CORE re-entry does NOT create a new first-pullback opportunity
   - record the FIRST exact Fib38 touch once
   - if there is no exact touch, preserve the nearest Fib38 distance

IMPORTANT
The source says "38선 부근".
Exact touch is therefore diagnostic, not the final definition of entry.

NO invented:
- 38-line tolerance
- minimum wave rise %
- time limit
- CORE re-entry requirement

Still unresolved:
- 세력주 / 수급세력주 mechanical classification
- 3파 mechanical definition
- 신규상장 exclusion period

REQUIRED
- rs20_numeric_candidates_final_audited_v1.csv
- common_market_data/minute_1m_stock_v1/
  (date-level common_market_data/minute_1m fallback supported)

RUN
Double-click:
run_rs20_source_event_state_machine_v1_2.bat

OUTPUT
- rs20_source_event_state_machine_candidate_summary_v1_2.csv
- rs20_source_event_state_machine_events_v1_2.csv
- rs20_source_event_state_machine_unavailable_v1_2.csv
- rs20_source_event_state_machine_summary_v1_2.txt

NO Kiwoom API.
NO order API.

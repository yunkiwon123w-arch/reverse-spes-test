RS20 SOURCE EVENT STATE MACHINE v1

PURPOSE
This stage combines only the mechanically confirmed RS20 source rules on the
intraday 1-minute path.

SOURCE RULES USED
1. M >= 200 eok
2. M / cumulative traded value >= 20%
3. Dynamic Reverse Fib38:
   DayLow + (DayHigh-DayLow)*0.618

WHY THIS IS DIFFERENT
Earlier dynamic-Fib diagnostics showed that 38 touches by themselves are too
common. This version asks a more source-faithful question:

"When the RS20 numeric core is actually satisfied intraday, where is the active
Reverse-38 line and what does the first pullback toward it look like?"

NO extra wave %, no waiting minutes, and no 38-line tolerance are added.

REQUIRED
- rs20_numeric_candidates_final_audited_v1.csv
- common_market_data/minute_1m_stock_v1/
  (date-level minute_1m fallback is also supported)

RUN
Double-click:
run_rs20_source_event_state_machine_v1.bat

OUTPUT
- rs20_source_event_state_machine_candidate_summary_v1.csv
- rs20_source_event_state_machine_events_v1.csv
- rs20_source_event_state_machine_core_minutes_v1.csv
- rs20_source_event_state_machine_unavailable_v1.csv
- rs20_source_event_state_machine_summary_v1.txt

IMPORTANT
- The source's "38선 부근" tolerance is still unresolved.
- 세력주/수급세력주, 3파, 신규상장 are not mechanically decided here.
- The end-of-day 1,174 set remains the frozen numeric candidate universe.
- This is diagnostic only, not a final trade list.
- NO Kiwoom API.
- NO order API.

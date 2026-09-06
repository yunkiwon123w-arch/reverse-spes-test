RS20 SOURCE EVENT STATE MACHINE v1.1

MAIN FIX
v1 allowed the same 1-minute bar to be both:
1) the bar where the numeric CORE first turns ON, and
2) the first Reverse-38 pullback bar.

v1.1 removes that causal overlap.

RULE
For every CORE_ON segment:
- the CORE_ON transition bar defines the start of the segment;
- that exact bar is NOT evaluated as a later pullback;
- pullback diagnostics begin from the NEXT 1-minute bar;
- if CORE turns OFF and later turns ON again, a new segment starts and the same
  causal rule is applied again.

This is NOT a new "wait one minute" source condition.
It is only temporal ordering.

REQUIRED
- rs20_numeric_candidates_final_audited_v1.csv
- common_market_data/minute_1m_stock_v1/
  (date-level minute_1m fallback is supported)

RUN
Double-click:
run_rs20_source_event_state_machine_v1_1.bat

OUTPUT
- rs20_source_event_state_machine_candidate_summary_v1_1.csv
- rs20_source_event_state_machine_segments_v1_1.csv
- rs20_source_event_state_machine_events_v1_1.csv
- rs20_source_event_state_machine_unavailable_v1_1.csv
- rs20_source_event_state_machine_summary_v1_1.txt

STILL UNRESOLVED FROM SOURCE
- numeric definition of "38선 부근"
- 세력주 / 수급세력주 classification
- 3파 chart mechanical definition
- 신규상장 exclusion period

NO Kiwoom API.
NO order API.

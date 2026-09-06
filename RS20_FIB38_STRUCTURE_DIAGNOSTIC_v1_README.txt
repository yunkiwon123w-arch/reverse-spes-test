RS20 Reverse-38 Structure Diagnostic v1

PURPOSE
Use the frozen RS20 numeric candidate set and the local 1-minute cache to
diagnose the source concept:
- rising wave
- Reverse Fibonacci 38 line
- first pullback after an anchor

REQUIRED EXISTING FILE
- rs20_numeric_candidates_final_audited_v1.csv

REQUIRED LOCAL CACHE
Primary:
- common_market_data/minute_1m_stock_v1/<stock_code>.csv.gz

Fallback:
- common_market_data/minute_1m/YYYY/MM/<stock_code>_<YYYYMMDD>.csv.gz

FILES TO ADD TO PROJECT ROOT
- rs20_fib38_structure_diagnostic_v1.py
- run_rs20_fib38_structure_diagnostic_v1.bat

RUN
Double-click:
run_rs20_fib38_structure_diagnostic_v1.bat

OUTPUT
- rs20_fib38_structure_candidate_summary_v1.csv
- rs20_fib38_structure_anchors_v1.csv
- rs20_fib38_structure_unavailable_v1.csv
- rs20_fib38_structure_summary_v1.txt

IMPORTANT SOURCE-FIDELITY RULES
This diagnostic does NOT invent:
- minimum wave rise %
- tolerance for "near 38"
- automatic source-wave finalization
- mechanical 세력주/수급세력주 classification
- mechanical 3-wave definition
- new-listing exclusion period

Every new running day-high is preserved as an anchor candidate.
For each anchor, the reverse 38 line is:
    low + (high - low) * 0.618

The anchor bar itself is never counted as a pullback touch.
The first later 1-minute bar whose low/high range contains the line is
recorded as the first exact touch.

The day's final running-high anchor is also summarized, but it is only a
diagnostic reference and is NOT declared to be the lecture's true wave.

NO Kiwoom API calls.
NO order API.

RS20 Dynamic Reverse-Fib38 First-Pullback Diagnostic v1

WHY THIS VERSION EXISTS
High-resolution re-check of the lecture formula confirmed that the Fibonacci
indicator itself uses:
    a = dayhigh()
    b = daylow()
    k = a - b
    lecture 38 line = b + k*0.618

So we do NOT invent a separate local swing/wave selector.

WHAT THIS VERSION FIXES
The previous anchor diagnostic preserved every running-high anchor and searched
far into the future. That was useful for exploration but is not faithful to a
dynamic DayHigh/DayLow indicator because an old line stops being active as soon
as DayHigh or DayLow changes.

This version:
1. Reconstructs running DayHigh/DayLow minute by minute.
2. Opens a new ACTIVE interval whenever DayHigh or DayLow changes.
3. Ends the old interval immediately at the next range revision.
4. Checks pullback behavior only while that Fibonacci line is actually active.
5. Never counts the revision bar itself as its own pullback.
6. Records exact touch AND nearest distance.
7. Does not invent a +/-N% definition for '38선 부근'.

REQUIRED
- rs20_numeric_candidates_final_audited_v1.csv
- common_market_data/minute_1m_stock_v1/
  or the date-level fallback cache under common_market_data/minute_1m/

RUN
Double-click:
run_rs20_dynamic_fib38_first_pullback_diagnostic_v1.bat

OUTPUT
- rs20_dynamic_fib38_candidate_summary_v1.csv
- rs20_dynamic_fib38_active_intervals_v1.csv
- rs20_dynamic_fib38_unavailable_v1.csv
- rs20_dynamic_fib38_summary_v1.txt

NO Kiwoom API.
NO order API.

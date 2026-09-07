RS20 POST-ENTRY PATH DIAGNOSTIC v1

PURPOSE
Extract the price path after the frozen v1.2 FIRST exact Reverse-38 touch.

IMPORTANT
This is NOT yet final P&L. The current frozen RS20 source-rule set does not
contain a sufficiently explicit mechanical take-profit / stop-loss formula,
so this program does not invent one.

ENTRY REFERENCE
- v1.2 first exact Reverse-38 touch
- diagnostic entry price = Fib38 at that touch
- subsequent path starts from the NEXT 1-minute bar

DIAGNOSTICS
- EOD return
- MFE / MAE
- +1/+2/+3/+4/+5/+7/+10/+15/+20% hit
- -1/-2/-3/-4/-5/-7/-10% hit
- +1/-1, +2/-2, +3/-3 first-direction

All percentage levels are diagnostics only, NOT source rules.

REQUIRED
rs20_source_event_state_machine_candidate_summary_v1_2.csv

LOCAL CACHE
common_market_data/minute_1m_stock_v1/
with date-level fallback.

RUN
run_rs20_post_entry_path_diagnostic_v1.bat

OUTPUT
- rs20_post_entry_path_diagnostic_v1.csv
- rs20_post_entry_path_unavailable_v1.csv
- rs20_post_entry_path_summary_v1.txt

NO Kiwoom API.
NO order API.

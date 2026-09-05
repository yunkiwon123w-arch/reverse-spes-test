RS20 Numeric Revalidation v1

PURPOSE
Recalculate all 1,267 old RS20 numeric candidates using a direct target-date
1-minute request. Exact timestamps are deduplicated before M is calculated.

FILES TO PLACE IN PROJECT ROOT
- rs20_numeric_revalidation_v1.py
- run_rs20_numeric_revalidation_v1.bat

REQUIRED EXISTING FILE
- rs20_history_numeric_candidates_v1.csv

RUN
Double-click:
run_rs20_numeric_revalidation_v1.bat

OUTPUTS
- rs20_numeric_revalidation_progress_v1.csv
- rs20_numeric_candidates_corrected_v1.csv
- rs20_numeric_candidates_removed_v1.csv
- rs20_numeric_revalidation_summary_v1.txt

NEW REUSABLE DATA CACHE
- common_market_data/minute_1m/YYYY/MM/<stock>_<date>.csv.gz
- common_market_data/minute_1m_manifest_v1.csv

SAFETY
- Read-only market-data API only.
- No order API.
- Ctrl+C is safe. Run the same BAT again to resume.
- Existing rs20_history_numeric_candidates_v1.csv is never modified.

IMPORTANT
This stage removes false positives from the old 1,267 candidates.
A separate false-negative audit is still required before the RS20 numeric
candidate universe is finally frozen.

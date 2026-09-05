RS20 False-Negative Audit v1

PURPOSE
Rebuild the RS20 historical numeric universe from the PHASE A daily prefilter
with corrected minute pagination and exact timestamp deduplication.

REQUIRED EXISTING FILES IN PROJECT ROOT
- rs20_history_daily_prefilter_v1.csv
- rs20_numeric_candidates_corrected_v1.csv

FILES TO ADD
- rs20_false_negative_audit_v1.py
- run_rs20_false_negative_audit_v1.bat

RUN
Double-click:
run_rs20_false_negative_audit_v1.bat

RESUME
Ctrl+C is safe. Completed stocks are preserved and skipped next run.

OUTPUTS
- rs20_false_negative_audit_all_dates_v1.csv
- rs20_numeric_candidates_final_audited_v1.csv
- rs20_false_negative_new_candidates_v1.csv
- rs20_false_negative_missing_dates_v1.csv
- rs20_false_negative_audit_summary_v1.txt

REUSABLE 1-MINUTE CACHE
- common_market_data/minute_1m_stock_v1/<stock_code>.csv.gz
- common_market_data/minute_1m_stock_manifest_v1.csv

IMPORTANT
- This can take a long time because all PHASE A target dates are re-audited.
- Missing dates are NOT treated as non-candidates.
- No order API is used.

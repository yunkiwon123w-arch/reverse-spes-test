RS20 PATH ROBUSTNESS / HOLDOUT v1

PURPOSE
Test whether the post-entry rebound structure is stable across time and
subgroups.

INPUT
rs20_post_entry_path_diagnostic_v1.csv

ANALYSIS
- ALL rows
- chronological 70/30 split
- chronological first half / second half
- CORE ON vs OFF at entry
- market split
- year split
- month-by-month summary

NO OPTIMIZATION
This script does NOT choose the best take-profit or stop-loss threshold.
All +X/-X hit rates are descriptive diagnostics only.

OUTPUT
- rs20_path_robustness_holdout_v1.csv
- rs20_path_robustness_monthly_v1.csv
- rs20_path_robustness_summary_v1.txt

RUN
run_rs20_path_robustness_holdout_v1.bat

NO Kiwoom API.
NO order API.

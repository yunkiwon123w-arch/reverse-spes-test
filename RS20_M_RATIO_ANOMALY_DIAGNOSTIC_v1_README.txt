RS20 M-ratio anomaly diagnostic v1

1. Put these files in the same folder as rs20_history_numeric_candidates_v1.csv
   - rs20_m_ratio_anomaly_diagnostic_v1.py
   - run_rs20_m_ratio_anomaly_diagnostic_v1.bat

2. Double-click:
   run_rs20_m_ratio_anomaly_diagnostic_v1.bat

3. Enter Kiwoom App Key / Secret Key when prompted.

4. Outputs:
   - rs20_m_ratio_anomaly_diagnostic_v1.csv
   - rs20_m_ratio_anomaly_summary_v1.txt

Purpose:
Compare adjusted-price and unadjusted-price 1-minute data only for the 48 rows
where M / daily traded value exceeded 100%.

No order API is used.
The original candidate CSV is never modified.

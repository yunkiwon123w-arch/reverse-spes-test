RS20 PROGRAM_FLOW COLLECTOR v1.1

CHANGE FROM v1
- No manual Access Token input.
- Reads the existing Kiwoom App Key / App Secret from Windows environment variables.
- Automatically requests a fresh Access Token through:
  POST https://api.kiwoom.com/oauth2/token
- Token and credentials are not written to disk by this script.

SUPPORTED ENVIRONMENT VARIABLE NAMES

App Key:
- KIWOOM_APP_KEY
- KIWOOM_APPKEY
- KIWOOM_REST_APP_KEY
- KIWOOM_API_KEY

App Secret:
- KIWOOM_APP_SECRET
- KIWOOM_SECRET_KEY
- KIWOOM_SECRETKEY
- KIWOOM_REST_APP_SECRET
- KIWOOM_API_SECRET

If the existing project used different names, the program will stop safely
and print ONLY the names it checked. Do not paste credential values into ChatGPT.

DATA COLLECTION
Same as v1:
- Kiwoom ka90008
- RS20 exact-touch stock/date events only
- resume-safe cache
- no whole-market scan
- no order API

INPUT
rs20_source_event_state_machine_candidate_summary_v1_2.csv

CACHE
common_market_data/program_flow_ka90008_v1/YYYY/MM/<stock>_<date>.csv.gz

RUN
run_rs20_program_flow_collector_v1_1.bat

OUTPUT
- rs20_program_flow_collection_status_v1_1.csv
- rs20_program_flow_missing_v1_1.csv
- rs20_program_flow_progress_v1_1.csv
- rs20_program_flow_collection_summary_v1_1.txt

IMPORTANT
Do not run another Kiwoom-heavy collector at the same time.

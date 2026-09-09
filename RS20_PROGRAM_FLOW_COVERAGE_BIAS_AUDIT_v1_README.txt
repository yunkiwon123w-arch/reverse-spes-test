RS20 PROGRAM_FLOW Coverage / Bias Audit v1

목적
ka90008 데이터가 있는 290건과 NO_DATA 265건의 표본 차이를 먼저 확인합니다.
PROGRAM_FLOW 예측력 연구 전에 대표성/선택편향을 점검하는 단계입니다.

추가 Kiwoom API: 없음
주문 API: 없음

필수 입력
rs20_program_flow_collection_status_v1_5.csv

가능하면 함께 있어야 하는 기존 파일
- rs20_post_entry_path_diagnostic_v1.csv
- rs20_source_event_state_machine_candidate_summary_v1_2.csv
- rs20_numeric_candidates_final_audited_v1.csv

검사
- 전체 Coverage
- 월별 Coverage
- 종목별 NO_DATA 집중
- COVERED vs NO_DATA의 MFE/MAE/EOD 차이
- +3/+5/+10%, -1/-2/-3%, EOD positive 차이
- 가능한 경우 M값/거래대금/M비율 차이
- 연속형 변수의 SMD(설명용)

실행
run_rs20_program_flow_coverage_bias_audit_v1.bat

출력
- rs20_program_flow_coverage_bias_event_level_v1.csv
- rs20_program_flow_coverage_bias_group_summary_v1.csv
- rs20_program_flow_coverage_bias_metric_comparison_v1.csv
- rs20_program_flow_coverage_bias_monthly_v1.csv
- rs20_program_flow_coverage_bias_stock_concentration_v1.csv
- rs20_program_flow_coverage_bias_summary_v1.txt

원칙
- NO_DATA를 0으로 처리하지 않음
- 원문 RS20 조건 변경 없음
- 임계값 발명 없음
- PROGRAM_FLOW는 독립 연구 모듈

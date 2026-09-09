RS20 PROGRAM_FLOW Alignment / Predictive Study v1

목적
기존에 수집 완료된 ka90008 프로그램매매 데이터를
RS20 첫 exact Reverse-38 진입시각에 정렬하고,
실제 진입 전에 알 수 있었던 정보가 사후 성과를 구분하는지 검증합니다.

추가 Kiwoom API
없음.

필수 입력
- rs20_program_flow_coverage_bias_event_level_v1.csv
- rs20_post_entry_path_diagnostic_v1.csv
- common_market_data\program_flow_ka90008_v1\YYYY\MM\<stock>_<date>.csv.gz

선택 입력
- rs20_source_event_state_machine_candidate_summary_v1_2.csv
  exact-touch 시간이 다른 파일에 없을 때 보조로 사용합니다.

시장 분리
- ALL
- KOSPI
- KOSDAQ

시간 분리
각 시장별로 날짜순:
- TRAIN70
- HOLDOUT30

진입 예측에 사용 가능한 시간
-30 / -10 / -5 / -3 / -1 / 0분

진입 후 별도 기록
+1 / +3 / +5 / +10 / +30분
이 값들은 진입 예측력 주장에 절대 사용하지 않고,
POST_ENTRY_DESCRIPTIVE_ONLY로 별도 출력합니다.

사전 고정 causal feature
- 진입시점 프로그램 순매수금액
- 진입시점 프로그램 imbalance
- -30->0 / -10->0 / -5->0 순매수 변화량
- -30->0 / -10->0 / -5->0 imbalance 변화량
- 직전 5분 prm_netprps_amt_irds 합

검증 방식
1. TRAIN70에서 Spearman 방향성 확인
2. TRAIN70 feature quartile 경계(Q1/Q2/Q3)를 계산
3. 그 경계를 그대로 HOLDOUT30에 적용
4. 각 quartile의:
   - MFE
   - MAE
   - EOD return
   - +3/+5/+10% 도달률
   - -1/-2/-3% 도달률
   - EOD positive
   를 비교

중요
- 임계값 최적화 없음
- 최고 성과 quartile을 원문 조건으로 추가하지 않음
- ALL 결과가 좋아도 KOSPI/KOSDAQ 분리 재현성을 확인
- 특히 KOSDAQ 자체의 높은 기본 변동성을 PROGRAM_FLOW 효과로 오인하지 않음
- 원문 RS20 변경 없음

실행
run_rs20_program_flow_alignment_predictive_study_v1.bat

출력
- rs20_program_flow_aligned_features_v1.csv
- rs20_program_flow_predictive_feature_study_v1.csv
- rs20_program_flow_predictive_holdout_v1.csv
- rs20_program_flow_post_entry_descriptive_v1.csv
- rs20_program_flow_alignment_predictive_summary_v1.txt

주문 API 없음.

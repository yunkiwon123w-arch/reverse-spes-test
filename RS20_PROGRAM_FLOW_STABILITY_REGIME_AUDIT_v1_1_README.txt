RS20 PROGRAM_FLOW v1.1 Stability / Regime Audit

목적
v1에서 보인 PROGRAM_FLOW 관계가 특정 월/시장/종목/거래대금/변동성에만
의존하는지 검사합니다.

이번 단계에서 새 임계값을 찾지 않습니다.
v1에서 이미 고정된 TRAIN quartile 경계를 그대로 재사용합니다.

필수 입력
- rs20_program_flow_aligned_features_v1.csv
- rs20_program_flow_predictive_holdout_v1.csv
- rs20_program_flow_coverage_bias_event_level_v1.csv

로컬 선택 데이터
- common_market_data\minute_1m_stock_v1\<stock>.csv.gz
  있으면 진입 전 30분 가격범위(변동성)를 계산합니다.
  추가 Kiwoom API는 사용하지 않습니다.

핵심 검사
1. 월별 안정성
   - Spearman 방향
   - Q1 vs Q4 MFE
   - Q1 vs Q4 EOD
   - Q1 vs Q4 +5% 도달률

2. 시장별
   - ALL / KOSPI / KOSDAQ
   - TRAIN70 / HOLDOUT30 유지

3. 거래대금 regime
   - TRAIN에서 거래대금 quartile을 고정
   - HOLDOUT에 그대로 적용

4. 진입 전 변동성 regime
   - exact-touch 전 30분 high-low range
   - TRAIN quartile을 고정 후 HOLDOUT 적용

5. 종목 집중도
   - pf_net_amt_0 Q1 효과가 몇 개 종목에 몰리는지
   - top1/top3/top5 stock share 계산

주요 feature
- pf_net_amt_0
- pf_irds_sum_m5_0
- pf_net_amt_delta_m10_0
- pf_net_amt_delta_m5_0

출력
- rs20_program_flow_stability_enriched_events_v1_1.csv
- rs20_program_flow_stability_monthly_v1_1.csv
- rs20_program_flow_stability_regime_v1_1.csv
- rs20_program_flow_stability_stock_concentration_v1_1.csv
- rs20_program_flow_stability_scorecard_v1_1.csv
- rs20_program_flow_stability_summary_v1_1.txt

실행
run_rs20_program_flow_stability_regime_audit_v1_1.bat

원칙
- 원문 RS20 변경 없음
- 새 최적 임계값 탐색 없음
- 추가 Kiwoom API 없음
- 주문 API 없음

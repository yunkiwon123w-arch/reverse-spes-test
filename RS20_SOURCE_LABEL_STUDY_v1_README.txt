RS20 SOURCE LABEL STUDY v1

PURPOSE
Freeze the stock examples shown in Lecture 1 Chapter 02 as source labels,
then cross-match them against the already collected 1,174 RS20 candidate-day
investor-flow dataset.

SOURCE LABELS
세력주 (pp.9-14)
- 오리엔트정공
- 범양건영
- 화성밸브
- 대동기어
- 이랜시스
- 씨씨에스

수급주 (pp.15-21)
- 두산에너빌리티
- 카카오
- HD현대중공업
- 더존비즈온
- JYP Ent.
- 크래프톤
- HD현대일렉트릭

수급세력주 (pp.22-27)
- 한국가스공사
- 루닛
- 한화오션
- 유한양행
- 레인보우로보틱스
- 알테오젠

REQUIRED
rs20_investor_flow_candidates_v1.csv

RUN
run_rs20_source_label_study_v1.bat

OUTPUT
- rs20_source_stock_labels_v1.csv
- rs20_source_label_candidate_matches_v1.csv
- rs20_source_label_study_summary_v1.txt

IMPORTANT
The candidate-day data are later dates than the lecture examples.
Therefore this is an OUT-OF-SAMPLE CONSISTENCY STUDY, not proof of the
lecture's exact stock-classification formula.

No numeric threshold is invented.
No Kiwoom API.
No order API.

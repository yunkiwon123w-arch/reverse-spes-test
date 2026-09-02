# -*- coding: utf-8 -*-
"""
Reverse SPES - RS20 원문판 후보 Funnel v1

목적
- 원문에서 기계적으로 확정 가능한 조건만 적용해 RS20 후보를 추적한다.
- 원문 미정의 조건은 임의 수치화하지 않고 REVIEW/PENDING 상태로 보존한다.
- 실제 주문 기능 없음.

원문 기반 핵심 조건
1) 세력주 / 수급세력주                 -> 자동 정의 미확정
2) 피보나치 38선 부근 첫 눌림          -> '부근' 허용폭 미확정
3) M지표 최소 200억원 이상             -> 자동 판정
4) 거래대금 대비 M지표 20% 이상        -> 자동 판정

제외/검토
- 3파 차트                              -> 자동 정의 미확정
- 신규상장                              -> '신규' 기간 미확정
"""

from dataclasses import dataclass, asdict
from typing import Optional, Iterable
import csv
import math


SOURCE_VERSION = "RS20_SOURCE_FUNNEL_V1"
M_MIN_EOK = 200.0
M_RATIO_MIN = 0.20


@dataclass
class RS20Input:
    code: str
    name: str
    trade_date: str
    traded_value_eok: float
    m_value_eok: float

    # 피보나치 계산에 필요한 기준 고가/저가.
    # 어떤 파동을 기준으로 잡는지 자체가 후보 생성 단계에서 확정되어 있어야 한다.
    wave_high: Optional[float] = None
    wave_low: Optional[float] = None

    # 첫 눌림 관찰값. '부근' 허용폭은 원문 미정의이므로 자동 PASS에 쓰지 않는다.
    first_pullback_low: Optional[float] = None

    # 원문 미정의/수동 검토 필드
    is_force_or_supply_stock: Optional[bool] = None
    is_three_wave_chart: Optional[bool] = None
    is_new_listing: Optional[bool] = None


def reverse_fib38(wave_high: float, wave_low: float) -> float:
    """
    강의의 Reverse Fibonacci 명명법 보존:
    '38선' = (high-low)*0.618 + low
    """
    return (wave_high - wave_low) * 0.618 + wave_low


def safe_ratio(numerator: float, denominator: float) -> Optional[float]:
    if denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def bool_review(v: Optional[bool], true_label="YES", false_label="NO") -> str:
    if v is None:
        return "PENDING_REVIEW"
    return true_label if v else false_label


def evaluate_rs20(row: RS20Input) -> dict:
    ratio = safe_ratio(row.m_value_eok, row.traded_value_eok)

    m200_pass = row.m_value_eok >= M_MIN_EOK
    ratio20_pass = ratio is not None and ratio >= M_RATIO_MIN
    numeric_core_pass = m200_pass and ratio20_pass

    fib38 = None
    pullback_distance_pct = None
    fib_status = "PENDING_SOURCE_DEFINITION"

    if (
        row.wave_high is not None
        and row.wave_low is not None
        and row.wave_high > row.wave_low
    ):
        fib38 = reverse_fib38(row.wave_high, row.wave_low)

        if row.first_pullback_low is not None and fib38 > 0:
            pullback_distance_pct = (
                (row.first_pullback_low - fib38) / fib38 * 100.0
            )
            # 중요:
            # 원문은 '38선 부근'이라고만 하므로 임의의 ±N%를 PASS 기준으로 만들지 않는다.
            fib_status = "MEASURED_REVIEW_REQUIRED"
        else:
            fib_status = "FIB38_CALCULATED_PULLBACK_MISSING"

    force_status = bool_review(row.is_force_or_supply_stock)
    three_wave_status = bool_review(row.is_three_wave_chart)
    new_listing_status = bool_review(row.is_new_listing)

    # 자동 확정 가능한 숫자 조건까지만 Funnel PASS.
    if not m200_pass:
        funnel_stage = "FAIL_M_LT_200"
    elif not ratio20_pass:
        funnel_stage = "FAIL_M_RATIO_LT_20PCT"
    else:
        funnel_stage = "PASS_NUMERIC_CORE"

    # 원문 최종 RS20 확정은 미정의 항목 때문에 자동으로 선언하지 않는다.
    unresolved = []
    if row.is_force_or_supply_stock is None:
        unresolved.append("FORCE_OR_SUPPLY_STOCK")
    if row.is_three_wave_chart is None:
        unresolved.append("THREE_WAVE_CHART")
    if row.is_new_listing is None:
        unresolved.append("NEW_LISTING")
    if fib_status != "MEASURED_REVIEW_REQUIRED":
        unresolved.append("FIB38_FIRST_PULLBACK_DATA")
    else:
        unresolved.append("FIB38_NEAR_TOLERANCE")

    # 수동 정보가 명백히 원문 제외와 충돌하면 표시한다.
    manual_exclusion = False
    exclusion_reasons = []
    if row.is_force_or_supply_stock is False:
        manual_exclusion = True
        exclusion_reasons.append("NOT_FORCE_OR_SUPPLY_STOCK")
    if row.is_three_wave_chart is True:
        manual_exclusion = True
        exclusion_reasons.append("THREE_WAVE_CHART")
    if row.is_new_listing is True:
        manual_exclusion = True
        exclusion_reasons.append("NEW_LISTING")

    if not numeric_core_pass:
        final_status = "NUMERIC_FAIL"
    elif manual_exclusion:
        final_status = "SOURCE_EXCLUSION"
    else:
        final_status = "RS20_CANDIDATE_REVIEW"

    return {
        "source_version": SOURCE_VERSION,
        **asdict(row),
        "m_ratio": ratio,
        "m_ratio_pct": None if ratio is None else ratio * 100.0,
        "m200_pass": m200_pass,
        "m_ratio20_pass": ratio20_pass,
        "numeric_core_pass": numeric_core_pass,
        "fib38": fib38,
        "first_pullback_distance_pct": pullback_distance_pct,
        "fib_status": fib_status,
        "force_stock_review": force_status,
        "three_wave_review": three_wave_status,
        "new_listing_review": new_listing_status,
        "funnel_stage": funnel_stage,
        "manual_exclusion": manual_exclusion,
        "exclusion_reasons": "|".join(exclusion_reasons),
        "unresolved_source_fields": "|".join(unresolved),
        "final_status": final_status,
    }


def run_funnel(rows: Iterable[RS20Input]) -> list[dict]:
    return [evaluate_rs20(r) for r in rows]


def save_csv(results: list[dict], output_path: str) -> None:
    if not results:
        print("저장할 결과가 없습니다.")
        return

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)


def print_summary(results: list[dict]) -> None:
    total = len(results)
    m200 = sum(bool(r["m200_pass"]) for r in results)
    ratio20 = sum(bool(r["m_ratio20_pass"]) for r in results)
    numeric = sum(bool(r["numeric_core_pass"]) for r in results)
    review = sum(r["final_status"] == "RS20_CANDIDATE_REVIEW" for r in results)
    excluded = sum(r["final_status"] == "SOURCE_EXCLUSION" for r in results)

    print("=" * 64)
    print("Reverse SPES - RS20 원문판 후보 Funnel v1")
    print("실제 주문 기능: 없음")
    print("=" * 64)
    print(f"입력                : {total:,}")
    print(f"M >= 200억          : {m200:,}")
    print(f"M/거래대금 >= 20%   : {ratio20:,}")
    print(f"숫자 핵심조건 통과  : {numeric:,}")
    print(f"RS20 검토 후보      : {review:,}")
    print(f"원문 제외 표시      : {excluded:,}")
    print()
    print("주의: '38선 부근', 세력/수급세력주, 3파, 신규상장의")
    print("기계적 정의는 원문에서 확정되지 않아 임의 자동판정하지 않습니다.")


if __name__ == "__main__":
    # 파일 자체의 동작 검증용 샘플.
    # 실제 전종목 Kiwoom 데이터 연결은 다음 단계에서 붙인다.
    sample = [
        RS20Input(
            code="SAMPLE1",
            name="원문 O 예시형",
            trade_date="20260902",
            traded_value_eok=1000,
            m_value_eok=300,
            wave_high=12000,
            wave_low=10000,
            first_pullback_low=11200,
        ),
        RS20Input(
            code="SAMPLE2",
            name="M 200억 미만 예시",
            trade_date="20260902",
            traded_value_eok=500,
            m_value_eok=150,
            wave_high=12000,
            wave_low=10000,
            first_pullback_low=11200,
        ),
        RS20Input(
            code="SAMPLE3",
            name="비율 20% 미만 예시",
            trade_date="20260902",
            traded_value_eok=2000,
            m_value_eok=300,
            wave_high=12000,
            wave_low=10000,
            first_pullback_low=11200,
        ),
    ]

    results = run_funnel(sample)
    out = "rs20_source_funnel_v1_sample.csv"
    save_csv(results, out)
    print_summary(results)
    print(f"\n샘플 결과 저장: {out}")

"""
Reverse SPES - RS3 Strategy Integration Test
강의 원문 기준 RS3 독립전략 연결 테스트

목적
- RS3 진입조건 검증
- RS3 제외조건 검증
- RS3 청산조건 검증
- rs3_strategy 통합 연결 검증

주의
RS3는 RS20과 분리된 독립 전략이다.
따라서 fib_line, m_ratio, first_touch 등의
RS20 계열 인자는 사용하지 않는다.
"""

from datetime import time

from rs3_strategy import check_rs3_candidate


def run_tests():

    print("===== Reverse SPES RS3 TEST START =====")

    # -------------------------------------------------
    # TEST 1
    # 모든 RS3 진입조건 충족
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 1] 정상 RS3 후보")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is True


    # -------------------------------------------------
    # TEST 2
    # 당일 고가 상승률 부족
    # 시가 대비 +20% 미만
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=11500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 2] 고가 상승률 부족")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 3
    # 거래대금 부족
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=400,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 3] 거래대금 부족")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 4
    # 14:30 이전
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 20),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 4] 14:30 이전")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 5
    # 세력/수급세력주 아님
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=False,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 5] 세력주 조건 불충족")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 6
    # 신규상장 제외
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=True,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 6] 신규상장 제외")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 7
    # 14:30 이전 50선 터치 종목 제외
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=True,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 7] 14:30 이전 50선 터치")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 8
    # 50선 근처 강한 반등 종목 제외
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=True,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    print("\n[TEST 8] 50선 근처 강한 반등")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 9
    # 투상 이상 제외
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=True,
        short_term_overheat_today=False
    )

    print("\n[TEST 9] 투상 이상")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    # -------------------------------------------------
    # TEST 10
    # 당일 단기과열 발동 종목 제외
    # -------------------------------------------------

    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=True
    )

    print("\n[TEST 10] 당일 단기과열 발동")
    print("candidate =", candidate)
    print("result =", result)

    assert candidate is False


    print("\n====================================")
    print("ALL RS3 TESTS PASSED")
    print("====================================")


if __name__ == "__main__":
    run_tests()

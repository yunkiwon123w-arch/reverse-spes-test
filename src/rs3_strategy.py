"""
Reverse SPES - RS3 Strategy Integration Test
강의 원문 기준 RS3 독립전략 연결 테스트

확인 항목
1. 정상 매수후보
2. 시가 대비 당일 고가 +20% 미달
3. 거래대금 500억원 미달
4. 14:30 이전
5. 제외조건 작동
6. M지표 200억 이상 보너스
7. M지표 200억 미만이어도 필수조건 통과
8. +4% 익절
9. 피보나치 70선 손절
10. 2일 기간손절
11. HOLD
"""

from datetime import time

from rs3_strategy import (
    check_rs3_candidate,
    check_rs3_position_exit,
)


def run_tests():

    print("===== Reverse SPES RS3 TEST START =====")

    # --------------------------------------------------
    # TEST 1
    # 정상 매수후보
    # --------------------------------------------------
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

    assert candidate is True
    assert result["m_indicator_200_bonus"] is True

    print("TEST 1 PASS - 정상 매수후보")


    # --------------------------------------------------
    # TEST 2
    # 당일 고가 +20% 미달
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=11900,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250
    )

    assert candidate is False
    assert result["stage"] == "rs3_entry"

    print("TEST 2 PASS - +20% 미달 탈락")


    # --------------------------------------------------
    # TEST 3
    # 거래대금 500억원 미달
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=499,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250
    )

    assert candidate is False
    assert result["stage"] == "rs3_entry"

    print("TEST 3 PASS - 거래대금 미달 탈락")


    # --------------------------------------------------
    # TEST 4
    # 오후 2시 30분 이전
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 29),
        is_force_stock=True,
        m_value=250
    )

    assert candidate is False
    assert result["stage"] == "rs3_entry"

    print("TEST 4 PASS - 14:30 이전 탈락")


    # --------------------------------------------------
    # TEST 5
    # 제외조건 작동
    # 신규상장 종목
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=250,
        is_new_listing=True
    )

    assert candidate is False
    assert result["stage"] == "rs3_exclusion"

    print("TEST 5 PASS - 제외조건 작동")


    # --------------------------------------------------
    # TEST 6
    # M지표 200억원 이상
    # 확률 UP 표시
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=200
    )

    assert candidate is True
    assert result["m_indicator_200_bonus"] is True

    print("TEST 6 PASS - M지표 200억 확률 UP")


    # --------------------------------------------------
    # TEST 7
    # M지표 200억 미만
    # RS3 필수조건은 아니므로 후보 유지
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,
        m_value=150
    )

    assert candidate is True
    assert result["m_indicator_200_bonus"] is False

    print("TEST 7 PASS - M지표 미달이어도 RS3 후보 유지")


    # --------------------------------------------------
    # TEST 8
    # +4% 익절
    # --------------------------------------------------
    result = check_rs3_position_exit(
        buy_price=10000,
        current_price=10400,
        fibonacci_70_touched=False,
        holding_days=0,
        rebound_within_2days=True
    )

    assert result["exit"] is True
    assert result["reason"] == "profit_target_4pct"

    print("TEST 8 PASS - +4% 익절")


    # --------------------------------------------------
    # TEST 9
    # 피보나치 70선 손절
    # --------------------------------------------------
    result = check_rs3_position_exit(
        buy_price=10000,
        current_price=9800,
        fibonacci_70_touched=True,
        holding_days=0,
        rebound_within_2days=True
    )

    assert result["exit"] is True
    assert result["reason"] == "fibonacci_70_stop"

    print("TEST 9 PASS - 피보나치 70선 손절")


    # --------------------------------------------------
    # TEST 10
    # 2일 기간손절
    # --------------------------------------------------
    result = check_rs3_position_exit(
        buy_price=10000,
        current_price=9900,
        fibonacci_70_touched=False,
        holding_days=2,
        rebound_within_2days=False
    )

    assert result["exit"] is True
    assert result["reason"] == "two_day_time_stop"

    print("TEST 10 PASS - 2일 기간손절")


    # --------------------------------------------------
    # TEST 11
    # HOLD
    # --------------------------------------------------
    result = check_rs3_position_exit(
        buy_price=10000,
        current_price=10100,
        fibonacci_70_touched=False,
        holding_days=1,
        rebound_within_2days=True
    )

    assert result["exit"] is False
    assert result["reason"] == "hold"

    print("TEST 11 PASS - HOLD")

    print("===== ALL RS3 TESTS PASS =====")


if __name__ == "__main__":
    run_tests()

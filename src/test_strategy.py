"""
Reverse SPES - RS3 Strategy Integration Test

목적
- 각 모듈이 정상적으로 연결되는지 확인
- 매매전략을 변경하거나 새로운 조건을 추가하지 않음
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
    # 정상 매수후보 통과
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        fib_line=38,
        m_value=250,
        m_ratio=0.25,
        first_touch=True,

        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,

        is_new_listing=False,
        touched_50_before_1430=False,
        strong_rebound_near_50=False,
        is_tusang_or_higher=False,
        short_term_overheat_today=False
    )

    assert candidate is True
    print("TEST 1 PASS - 정상 매수후보")


    # --------------------------------------------------
    # TEST 2
    # 피보나치 조건 탈락
    # 38선이 아닌 경우
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        fib_line=50,
        m_value=250,
        m_ratio=0.25,
        first_touch=True,

        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True
    )

    assert candidate is False
    assert result["stage"] == "fibonacci_rs20"

    print("TEST 2 PASS - 피보나치 조건 탈락")


    # --------------------------------------------------
    # TEST 3
    # RS3 제외조건 작동 확인
    # 신규상장 종목
    # --------------------------------------------------
    candidate, result = check_rs3_candidate(
        fib_line=38,
        m_value=250,
        m_ratio=0.25,
        first_touch=True,

        open_price=10000,
        day_high=12500,
        traded_value_eok=600,
        current_time=time(14, 40),
        is_force_stock=True,

        is_new_listing=True
    )

    assert candidate is False
    assert result["stage"] == "rs3_exclusion"

    print("TEST 3 PASS - 제외조건 작동")


    # --------------------------------------------------
    # TEST 4
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

    print("TEST 4 PASS - +4% 익절")


    # --------------------------------------------------
    # TEST 5
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

    print("TEST 5 PASS - 피보나치 70선 손절")


    # --------------------------------------------------
    # TEST 6
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

    print("TEST 6 PASS - 2일 기간손절")


    # --------------------------------------------------
    # TEST 7
    # 아무 청산조건도 없는 경우
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

    print("TEST 7 PASS - HOLD")


    print("===== ALL TESTS PASS =====")


if __name__ == "__main__":
    run_tests()

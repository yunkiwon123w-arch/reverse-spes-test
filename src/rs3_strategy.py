"""
Reverse SPES - RS3 Strategy Integration
강의 원문 기준

중요
- RS20과 RS3는 별도 전략이다.
- RS3 진입에 RS20 피보나치 38선 조건을 강제하지 않는다.
- RS3의 M지표 200억 이상은 필수조건이 아니라 '확률 UP' 요소다.
"""

from m_indicator import calculate_m_indicator
from rs3_entry import check_rs3_entry
from rs3_exclusion import check_rs3_exclusion
from rs3_exit import check_rs3_exit


def check_rs3_candidate(
    open_price,
    day_high,
    traded_value_eok,
    current_time,
    is_force_stock,
    m_value=None,
    is_new_listing=False,
    touched_50_before_1430=False,
    strong_rebound_near_50=False,
    is_tusang_or_higher=False,
    short_term_overheat_today=False
):
    """
    RS3 신규 매수 후보 통합 판정
    """

    # 1. RS3 기본 매수조건
    entry_ok = check_rs3_entry(
        open_price=open_price,
        day_high=day_high,
        traded_value_eok=traded_value_eok,
        current_time=current_time,
        is_force_stock=is_force_stock
    )

    if not entry_ok:
        return False, {
            "candidate": False,
            "stage": "rs3_entry",
            "reason": "entry_condition_failed"
        }

    # 2. RS3 제외조건
    excluded, exclusion_reasons = check_rs3_exclusion(
        is_new_listing=is_new_listing,
        touched_50_before_1430=touched_50_before_1430,
        strong_rebound_near_50=strong_rebound_near_50,
        is_tusang_or_higher=is_tusang_or_higher,
        short_term_overheat_today=short_term_overheat_today
    )

    if excluded:
        return False, {
            "candidate": False,
            "stage": "rs3_exclusion",
            "reason": "excluded",
            "exclusion_reasons": exclusion_reasons
        }

    # 3. M지표 200억 이상 = 확률 UP
    # 필수 매수조건은 아님
    m_indicator_bonus = (
        m_value is not None
        and m_value >= 200
    )

    return True, {
        "candidate": True,
        "stage": "passed",
        "reason": "all_required_conditions_passed",
        "m_indicator_200_bonus": m_indicator_bonus
    }


def check_rs3_position_exit(
    buy_price,
    current_price,
    fibonacci_70_touched=False,
    holding_days=0,
    rebound_within_2days=True
):
    """
    RS3 보유 종목 청산 판정
    """

    exit_signal, reason = check_rs3_exit(
        buy_price=buy_price,
        current_price=current_price,
        fibonacci_70_touched=fibonacci_70_touched,
        holding_days=holding_days,
        rebound_within_2days=rebound_within_2days
    )

    return {
        "exit": exit_signal,
        "reason": reason
    }


def prepare_m_indicator(df):
    """
    OHLCV 데이터에 강의 원문 M지표 계산
    """

    return calculate_m_indicator(df)

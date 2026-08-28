"""
Reverse SPES - RS3 Strategy Integration

현재까지 구현한 강의 원문 기반 모듈을 연결한다.

연결 모듈
1. Fibonacci RS20
2. M Indicator
3. RS3 Entry
4. RS3 Exclusion
5. RS3 Exit

주의
- 새로운 매매조건을 임의로 추가하지 않는다.
- 원문에서 수치가 확정되지 않은 조건은 외부 판정값을 사용한다.
"""

from fibonacci import check_fibonacci_rs20
from m_indicator import calculate_m_indicator
from rs3_entry import check_rs3_entry
from rs3_exclusion import check_rs3_exclusion
from rs3_exit import check_rs3_exit


def check_rs3_candidate(
    fib_line,
    m_value,
    m_ratio,
    first_touch,
    open_price,
    day_high,
    traded_value_eok,
    current_time,
    is_force_stock,
    is_new_listing=False,
    touched_50_before_1430=False,
    strong_rebound_near_50=False,
    is_tusang_or_higher=False,
    short_term_overheat_today=False
):
    """
    RS3 신규 매수 후보 통합 판정

    Returns
    -------
    tuple
        (candidate, result)

        candidate : bool
            최종 매수후보 여부

        result : dict
            각 조건별 판정 결과
    """

    # ---------------------------------
    # 1. Fibonacci RS20
    # ---------------------------------
    fibonacci_ok = check_fibonacci_rs20(
        fib_line=fib_line,
        m_value=m_value,
        m_ratio=m_ratio,
        first_touch=first_touch
    )

    if not fibonacci_ok:
        return False, {
            "candidate": False,
            "stage": "fibonacci_rs20",
            "reason": "fibonacci_condition_failed"
        }

    # ---------------------------------
    # 2. RS3 기본 매수조건
    # ---------------------------------
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

    # ---------------------------------
    # 3. RS3 제외조건
    # ---------------------------------
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

    # ---------------------------------
    # 모든 진입조건 통과
    # ---------------------------------
    return True, {
        "candidate": True,
        "stage": "passed",
        "reason": "all_entry_conditions_passed"
    }


def check_rs3_position_exit(
    buy_price,
    current_price,
    fibonacci_70_touched=False,
    holding_days=0,
    rebound_within_2days=True
):
    """
    보유 종목 RS3 청산 판정
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
    원시 OHLCV 데이터에 M지표를 계산한다.

    실제 데이터 로딩/백테스트 단계에서 사용한다.
    """

    return calculate_m_indicator(df)

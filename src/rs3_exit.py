"""
Reverse SPES - RS3 Exit Conditions
강의 원문 기준 청산조건 구현

청산 기준

1. 익절
   - 매수가 대비 +4% 도달 시 익절

2. 가격 손절
   - 당일 피보나치 70선 터치 시 손절

3. 기간 손절
   - 매수 후 2일 안에 반등이 나오지 않으면 손절

주의
- 강의 원문에서 확인되지 않은 추가 손절률은 사용하지 않는다.
- '반등'의 세부 수치 기준은 임의로 만들지 않는다.
- 따라서 기간손절의 반등 여부는 외부에서
  rebound_within_2days=True/False 로 입력받는다.
"""


PROFIT_TARGET_RATE = 0.04


def check_rs3_exit(
    buy_price,
    current_price,
    fibonacci_70_touched=False,
    holding_days=0,
    rebound_within_2days=True
):
    """
    RS3 청산조건 판정

    Parameters
    ----------
    buy_price : float
        매수가

    current_price : float
        현재가

    fibonacci_70_touched : bool
        당일 피보나치 70선 터치 여부

    holding_days : int
        매수 후 경과 일수

    rebound_within_2days : bool
        2일 안에 반등이 발생했는지 여부

    Returns
    -------
    tuple
        (exit_signal, reason)

        exit_signal : bool
            청산조건 발생 여부

        reason : str
            청산 사유
    """

    # 잘못된 매수가 데이터 방지
    if buy_price <= 0:
        return False, "invalid_buy_price"

    # ---------------------------------
    # 1. +4% 익절
    # ---------------------------------
    profit_rate = (
        (current_price - buy_price)
        / buy_price
    )

    if profit_rate >= PROFIT_TARGET_RATE:
        return True, "profit_target_4pct"

    # ---------------------------------
    # 2. 당일 피보나치 70선 터치 손절
    # ---------------------------------
    if fibonacci_70_touched:
        return True, "fibonacci_70_stop"

    # ---------------------------------
    # 3. 2일 기간손절
    # ---------------------------------
    if holding_days >= 2 and not rebound_within_2days:
        return True, "two_day_time_stop"

    # 청산조건 없음
    return False, "hold"

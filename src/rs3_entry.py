"""
Reverse SPES - RS3 Entry Conditions
강의 원문 기준 매수조건 구현

매수조건
- 세력 / 수급세력주
- 시가 대비 상승률 20% 이상
- 거래대금 최소 500억원 이상
- 오후 2시 30분 이후
"""


from datetime import time


def check_rs3_entry(
    open_price,
    current_price,
    traded_value_eok,
    current_time,
    is_force_stock=True
):
    """
    RS3 매수 기본조건 판정

    Parameters
    ----------
    open_price : float
        당일 시가

    current_price : float
        현재가

    traded_value_eok : float
        거래대금 (억원)

    current_time : datetime.time
        현재 시각

    is_force_stock : bool
        세력 / 수급세력주 여부

    Returns
    -------
    bool
        모든 조건 충족 시 True
    """

    # 세력 / 수급세력주 조건
    if not is_force_stock:
        return False

    # 잘못된 시가 데이터 방지
    if open_price <= 0:
        return False

    # 시가 대비 상승률
    rise_rate = (
        (current_price - open_price)
        / open_price
    )

    # 시가 대비 +20% 이상
    if rise_rate < 0.20:
        return False

    # 거래대금 500억원 이상
    if traded_value_eok < 500:
        return False

    # 오후 2시 30분 이후
    if current_time < time(14, 30):
        return False

    return True

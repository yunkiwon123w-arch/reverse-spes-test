"""
Reverse SPES - Fibonacci RS20
강의 원문 기준 구현

핵심 기준
- 피보나치 첫 터치선: 38선
- M지표 최소값: 200
- M지표 비율 최소값: 20%
"""


def check_fibonacci_rs20(
    fib_line,
    m_value,
    m_ratio,
    first_touch=True
):
    """
    피보나치 RS20 기본 조건 판정

    Parameters
    ----------
    fib_line : float
        피보나치 터치선

    m_value : float
        M지표 값

    m_ratio : float
        M지표 비율 (예: 0.20 = 20%)

    first_touch : bool
        해당 피보나치선을 처음 터치했는지 여부

    Returns
    -------
    bool
        모든 조건 충족 시 True
    """

    if not first_touch:
        return False

    if fib_line != 38:
        return False

    if m_value < 200:
        return False

    if m_ratio < 0.20:
        return False

    return True

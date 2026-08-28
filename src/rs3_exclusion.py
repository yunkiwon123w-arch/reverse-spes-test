"""
Reverse SPES - RS3 Exclusion Conditions
강의 원문 기준 제외조건 구현

원문 제외조건
1. 신규상장 종목
2. 오후 2시 30분 이전에 50선을 이미 한번이라도 터치한 종목
3. 50선 근처까지 왔다가 크게 반등 나온 종목
4. 투상 이상 제외
5. 당일 단기과열 발동 종목

주의
- '50선 근처', '크게 반등', '투상 이상'의 세부 자동판정 기준은
  강의 원문에서 수치가 확정되기 전까지 임의로 만들지 않는다.
- 따라서 현재는 각 조건의 판정 결과를 True/False로 입력받는다.
"""


def check_rs3_exclusion(
    is_new_listing=False,
    touched_50_before_1430=False,
    strong_rebound_near_50=False,
    is_tusang_or_higher=False,
    short_term_overheat_today=False,
):
    """
    RS3 제외조건 판정.

    Returns
    -------
    excluded : bool
        하나라도 제외조건에 해당하면 True

    reasons : list[str]
        해당된 제외사유 목록
    """

    reasons = []

    if is_new_listing:
        reasons.append("신규상장 종목")

    if touched_50_before_1430:
        reasons.append(
            "오후 2시 30분 이전에 50선을 이미 한번이라도 터치한 종목"
        )

    if strong_rebound_near_50:
        reasons.append(
            "50선 근처까지 왔다가 크게 반등 나온 종목"
        )

    if is_tusang_or_higher:
        reasons.append("투상 이상 제외")

    if short_term_overheat_today:
        reasons.append("당일 단기과열 발동 종목")

    excluded = len(reasons) > 0

    return excluded, reasons

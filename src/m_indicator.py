"""
Reverse SPES - M Indicator
강의 원문 M지표 수식 구현

원문:
B = sum(
    if(c > o,
       (H+O+L+C)/4*V/100000000,
       if(c < o,
          -(H+O+L+C)/4*V/100000000,
          0
       )
    )
)

M지표 = B - B2

Python 백테스트에서는 날짜별로 누적값을 초기화하여
해당 거래일의 M지표 값을 계산한다.
"""

import pandas as pd


def calculate_m_indicator(df):
    """
    Reverse SPES 강의 원문 기준 M지표 계산.

    필요한 컬럼
    -----------
    Open
    High
    Low
    Close
    Volume

    인덱스
    ------
    DatetimeIndex

    반환
    ----
    원본 DataFrame 복사본에 아래 컬럼 추가:
    - M_flow_eok : 각 봉의 수급금액(억원)
    - M_indicator : 당일 누적 M지표(억원)
    """

    required = ["Open", "High", "Low", "Close", "Volume"]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            f"M지표 계산에 필요한 컬럼이 없습니다: {missing}"
        )

    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError(
            "M지표 계산에는 DatetimeIndex가 필요합니다."
        )

    data = df.copy()

    # 원문: (H + O + L + C) / 4
    average_price = (
        data["High"]
        + data["Open"]
        + data["Low"]
        + data["Close"]
    ) / 4.0

    # 억원 단위
    traded_value_eok = (
        average_price * data["Volume"]
    ) / 100000000.0

    # 원문 조건
    # c > o : +
    # c < o : -
    # c == o : 0
    data["M_flow_eok"] = 0.0

    bullish = data["Close"] > data["Open"]
    bearish = data["Close"] < data["Open"]

    data.loc[bullish, "M_flow_eok"] = (
        traded_value_eok[bullish]
    )

    data.loc[bearish, "M_flow_eok"] = (
        -traded_value_eok[bearish]
    )

    # B - B2와 동일한 의미:
    # 거래일별 누적 M지표
    trade_date = data.index.normalize()

    data["M_indicator"] = (
        data["M_flow_eok"]
        .groupby(trade_date)
        .cumsum()
    )

    return data

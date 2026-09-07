RS20 PORTFOLIO / CAPITAL STRESS v1

PURPOSE
Move from isolated trade statistics to account-level capital constraints.

REQUIRED
rs20_execution_trade_results_v1.csv

REPRESENTATIVE RESEARCH CONFIGS
These are NOT source rules and NOT final selections.
They sample low/mid/high points from the broad EOD plateau found in the
previous execution/P&L research:

- P5_S3_EOD
- P7_S4_EOD
- P10_S5_EOD

CAPITAL FRACTIONS
- 10%
- 20%
- 25%
- 33%

No leverage.
If free cash is insufficient, the signal is skipped.

COST SCENARIOS
- ILLUSTRATIVE_BASE
- ILLUSTRATIVE_STRESS

SAME-MINUTE TIE STRESS
When several signals arrive in the same minute and capital is limited:
- CODE_ASC
- CODE_DESC

Both are tested to measure sensitivity to arbitrary ordering.

METRICS
- total signals
- accepted signals
- skipped signals
- acceptance rate
- maximum simultaneous positions
- maximum / average same-day signal count
- ending equity
- portfolio return
- diagnostic mark-to-market MDD
- maximum cash utilization
- minimum cash
- realized trade win rate
- average net trade return
- maximum consecutive losses

MARK-TO-MARKET
At each entry/exit event time, open positions are marked using the latest
available 1-minute close. Estimated liquidation cost/slippage is applied.

LIMITATIONS
- event-time MTM is not a continuous every-minute account curve.
- fractional shares are allowed to isolate capital effects.
- actual broker fee/tax schedule is not yet fixed.
- exact-touch fillability must still be checked in Forward PAPER.
- unresolved source filters remain unresolved.

LOCAL CACHE
common_market_data/minute_1m_stock_v1/
with date-level fallback.

RUN
run_rs20_portfolio_capital_stress_v1.bat

OUTPUT
- rs20_portfolio_capital_stress_runs_v1.csv
- rs20_portfolio_capital_stress_events_v1.csv
- rs20_portfolio_capital_stress_daily_signal_counts_v1.csv
- rs20_portfolio_capital_stress_summary_v1.txt

NO Kiwoom API.
NO order API.

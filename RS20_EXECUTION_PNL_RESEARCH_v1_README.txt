RS20 EXECUTION / P&L RESEARCH v1

PURPOSE
Research many execution / exit structures after the frozen RS20 v1.2
first exact Reverse-38 touch.

THIS IS NOT THE SOURCE STRATEGY.
The lecture does not currently provide a sufficiently explicit mechanical
RS20 take-profit / stop-loss / maximum-hold rule, so this program does NOT
write any tested TP/SL back into the source version.

RESEARCH GRID
TP:
1, 2, 3, 4, 5, 7, 10 percent

SL:
1, 2, 3, 4, 5 percent

MAXIMUM HOLD:
30 / 60 / 120 one-minute bars / EOD

EXECUTION
- Entry reference: v1.2 first exact Reverse-38 touch price
- Exit evaluation starts from the NEXT 1-minute bar
- If TP and SL are both touched inside the same 1-minute bar:
  CONSERVATIVE SL_FIRST
- Time exit: close of final permitted bar
- EOD exit: final one-minute close

COSTS
Four research scenarios are produced:
- GROSS_0
- ILLUSTRATIVE_LOW
- ILLUSTRATIVE_BASE
- ILLUSTRATIVE_STRESS

The fee/tax/slippage numbers in those scenarios are RESEARCH ASSUMPTIONS,
not a statement of the user's actual broker schedule.
They are separated in the source code and can later be replaced with the
actual fixed assumptions.

HOLDOUT
Every configuration is reported separately for:
- ALL
- chronological TRAIN70
- chronological HOLDOUT30

METRICS
- win rate
- mean / median gross return
- mean / median net return
- average win
- average loss
- payoff ratio
- expectancy
- diagnostic compounded return
- diagnostic MDD
- maximum consecutive losses
- median holding bars
- TP/SL/TIME/EOD exit counts
- ambiguous intrabar count

IMPORTANT LIMITATION
The compounded return and MDD treat trades sequentially at equal 1x sizing.
They do NOT model simultaneous signals, overlapping positions, capital limits,
or portfolio allocation yet. Therefore they are diagnostic, not production
portfolio results.

REQUIRED
rs20_source_event_state_machine_candidate_summary_v1_2.csv

LOCAL CACHE
common_market_data/minute_1m_stock_v1/
with date-level fallback.

RUN
run_rs20_execution_pnl_research_v1.bat

OUTPUT
- rs20_execution_trade_results_v1.csv
- rs20_execution_pnl_grid_v1.csv
- rs20_execution_pnl_unavailable_v1.csv
- rs20_execution_pnl_summary_v1.txt

NO Kiwoom API.
NO order API.

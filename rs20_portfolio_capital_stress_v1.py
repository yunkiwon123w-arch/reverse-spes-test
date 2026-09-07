# -*- coding: utf-8 -*-
"""
RS20 PORTFOLIO / CAPITAL STRESS v1
==================================

PURPOSE
- Move from per-trade diagnostics to account-level capital constraints.
- Use the already-generated RS20 execution trade grid.
- Test representative TP/SL/EOD research configurations across several
  fixed position-size fractions.
- Measure:
    * accepted / skipped signals
    * maximum simultaneous positions
    * same-day signal crowding
    * portfolio return
    * mark-to-market diagnostic MDD
    * cash utilization
    * tie-order sensitivity

IMPORTANT
- This is RESEARCH ONLY.
- The representative TP/SL settings are NOT source rules.
- Position-size fractions are NOT recommendations.
- No Kiwoom API.
- No orders.

REQUIRED
- rs20_execution_trade_results_v1.csv
- local 1-minute cache:
    common_market_data/minute_1m_stock_v1/<stock>.csv.gz
  with date-level fallback support.

WHY REPRESENTATIVE CONFIGS?
The previous P&L grid showed a broad EOD plateau rather than one isolated
optimum. v1 therefore samples low/mid/high points from that plateau instead
of selecting a single "winner":
    P5_S3_EOD
    P7_S4_EOD
    P10_S5_EOD

COST SCENARIOS
- ILLUSTRATIVE_BASE
- ILLUSTRATIVE_STRESS

CAPITAL FRACTIONS
- 10%, 20%, 25%, 33%
No leverage. A signal is skipped when free cash is insufficient.

TIE HANDLING
When multiple signals occur at the exact same minute and capital is limited,
two deterministic tie orders are tested:
- CODE_ASC
- CODE_DESC
This checks whether results are sensitive to arbitrary same-minute ordering.
"""

import csv
import gzip
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from pathlib import Path

INPUT_FILE = "rs20_execution_trade_results_v1.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_RUNS = "rs20_portfolio_capital_stress_runs_v1.csv"
OUT_EVENTS = "rs20_portfolio_capital_stress_events_v1.csv"
OUT_DAILY = "rs20_portfolio_capital_stress_daily_signal_counts_v1.csv"
OUT_SUMMARY = "rs20_portfolio_capital_stress_summary_v1.txt"

REPRESENTATIVE_CONFIGS = [
    {"name": "P5_S3_EOD", "tp_pct": 5.0, "sl_pct": 3.0, "max_hold_bars": "EOD"},
    {"name": "P7_S4_EOD", "tp_pct": 7.0, "sl_pct": 4.0, "max_hold_bars": "EOD"},
    {"name": "P10_S5_EOD", "tp_pct": 10.0, "sl_pct": 5.0, "max_hold_bars": "EOD"},
]

POSITION_FRACTIONS = [0.10, 0.20, 0.25, 0.33]
TIE_ORDERS = ["CODE_ASC", "CODE_DESC"]

COST_SCENARIOS = {
    "ILLUSTRATIVE_BASE": {
        "buy_commission_pct": 0.015,
        "sell_commission_pct": 0.015,
        "sell_tax_pct": 0.200,
        "buy_slippage_pct": 0.050,
        "sell_slippage_pct": 0.050,
    },
    "ILLUSTRATIVE_STRESS": {
        "buy_commission_pct": 0.030,
        "sell_commission_pct": 0.030,
        "sell_tax_pct": 0.250,
        "buy_slippage_pct": 0.100,
        "sell_slippage_pct": 0.100,
    },
}

INITIAL_EQUITY = 100_000_000.0  # research normalization only

RUN_FIELDS = [
    "config_name", "cost_scenario", "position_fraction", "tie_order",
    "signal_count", "accepted_count", "skipped_cash_count",
    "acceptance_rate_pct",
    "max_simultaneous_positions",
    "max_same_day_signals",
    "mean_same_day_signals",
    "ending_equity",
    "portfolio_return_pct",
    "diagnostic_mtm_mdd_pct",
    "max_cash_utilization_pct",
    "min_cash",
    "realized_trade_win_rate_pct",
    "avg_net_trade_return_pct",
    "max_consecutive_portfolio_losses",
]

EVENT_FIELDS = [
    "config_name", "cost_scenario", "position_fraction", "tie_order",
    "event_time", "event_type",
    "stock_code", "stock_name", "trade_date",
    "entry_time", "exit_time",
    "free_cash_before", "free_cash_after",
    "portfolio_equity_after",
    "open_positions_after",
    "position_notional",
    "net_trade_return_pct",
    "skip_reason",
]

DAILY_FIELDS = [
    "config_name", "trade_date", "signal_count"
]


def norm_code(v):
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(6)


def sf(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def load_bar_series(path):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            tm = str(r.get("cntr_tm", "")).strip()
            if len(tm) != 14 or not tm.isdigit():
                continue
            try:
                close = abs(float(str(r.get("cur_prc", "")).replace(",", "").replace("+", "")))
            except Exception:
                continue
            rows.append((tm, close))
    rows.sort()
    return rows


def find_date_cache(base, code, dt):
    yyyy, mm = dt[:4], dt[4:6]
    candidates = [
        base / DATE_CACHE_ROOT / yyyy / mm / f"{code}_{dt}.csv.gz",
        base / DATE_CACHE_ROOT / f"{code}_{dt}.csv.gz",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


class PriceCache:
    def __init__(self, base):
        self.base = base
        self.stock_series = {}
        self.date_series = {}

    def _load_stock(self, code):
        if code in self.stock_series:
            return self.stock_series[code]
        p = self.base / STOCK_CACHE_ROOT / f"{code}.csv.gz"
        if p.exists():
            try:
                series = load_bar_series(p)
            except Exception:
                series = []
        else:
            series = []
        self.stock_series[code] = series
        return series

    def _load_date(self, code, dt):
        key = (code, dt)
        if key in self.date_series:
            return self.date_series[key]
        p = find_date_cache(self.base, code, dt)
        if p:
            try:
                series = load_bar_series(p)
            except Exception:
                series = []
        else:
            series = []
        self.date_series[key] = series
        return series

    def price_at_or_before(self, code, timestamp):
        dt = timestamp[:8]

        series = self._load_stock(code)
        if series:
            times = [x[0] for x in series]
            idx = bisect_right(times, timestamp) - 1
            if idx >= 0 and series[idx][0].startswith(dt):
                return series[idx][1]

        series = self._load_date(code, dt)
        if series:
            times = [x[0] for x in series]
            idx = bisect_right(times, timestamp) - 1
            if idx >= 0 and series[idx][0].startswith(dt):
                return series[idx][1]

        return None


def cost_adjusted_buy_price(entry_price, cost):
    return entry_price * (1.0 + cost["buy_slippage_pct"] / 100.0)


def cost_adjusted_sell_price(exit_price, cost):
    return exit_price * (1.0 - cost["sell_slippage_pct"] / 100.0)


def buy_cash_required(market_value, cost):
    return market_value * (1.0 + cost["buy_commission_pct"] / 100.0)


def sell_cash_received(market_value, cost):
    return market_value * (
        1.0
        - cost["sell_commission_pct"] / 100.0
        - cost["sell_tax_pct"] / 100.0
    )


def liquidation_value_for_open_position(pos, mark_price, cost):
    sell_fill = cost_adjusted_sell_price(mark_price, cost)
    market_value = pos["shares"] * sell_fill
    return sell_cash_received(market_value, cost)


def current_equity(cash, open_positions, timestamp, price_cache, cost):
    equity = cash
    for pos in open_positions.values():
        px = price_cache.price_at_or_before(pos["stock_code"], timestamp)
        if px is None:
            px = pos["entry_price_raw"]
        equity += liquidation_value_for_open_position(pos, px, cost)
    return equity


def consecutive_losses(net_returns):
    best = 0
    cur = 0
    for r in net_returns:
        if r < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def filter_config(rows, cfg):
    out = []
    for r in rows:
        tp = sf(r.get("tp_pct"))
        sl = sf(r.get("sl_pct"))
        hold = str(r.get("max_hold_bars", "")).strip()

        if tp == cfg["tp_pct"] and sl == cfg["sl_pct"] and hold == str(cfg["max_hold_bars"]):
            rr = dict(r)
            rr["stock_code"] = norm_code(rr.get("stock_code", ""))
            rr["entry_price"] = sf(rr.get("entry_price"))
            rr["exit_price"] = sf(rr.get("exit_price"))
            rr["entry_time"] = str(rr.get("entry_time", "")).strip()
            rr["exit_time"] = str(rr.get("exit_time", "")).strip()
            if rr["entry_price"] and rr["exit_price"] and rr["entry_time"] and rr["exit_time"]:
                out.append(rr)

    return out


def same_day_stats(trades):
    d = defaultdict(int)
    for t in trades:
        d[t["trade_date"]] += 1
    vals = list(d.values())
    if not vals:
        return 0, 0.0, d
    return max(vals), sum(vals) / len(vals), d


def run_portfolio(trades, cfg_name, cost_name, cost, position_fraction, tie_order, price_cache):
    # Build entry and exit events.
    # Exits are processed before entries at the same timestamp so capital freed
    # at that minute can be reused.
    events = []

    for t in trades:
        events.append({
            "ts": t["entry_time"],
            "kind": "ENTRY",
            "trade": t,
        })
        events.append({
            "ts": t["exit_time"],
            "kind": "EXIT",
            "trade": t,
        })

    def code_key(ev):
        code = ev["trade"]["stock_code"]
        if tie_order == "CODE_ASC":
            return code
        return "".join(chr(255 - ord(c)) for c in code)

    events.sort(key=lambda ev: (
        ev["ts"],
        0 if ev["kind"] == "EXIT" else 1,
        code_key(ev),
    ))

    cash = INITIAL_EQUITY
    open_positions = {}
    accepted_trade_ids = set()

    peak_equity = INITIAL_EQUITY
    min_dd = 0.0
    max_open = 0
    max_cash_util = 0.0
    min_cash = cash

    event_rows = []
    realized_returns = []

    # trade identity
    def tid(t):
        return (
            t["stock_code"],
            t["trade_date"],
            t["entry_time"],
            t["exit_time"],
            str(t["tp_pct"]),
            str(t["sl_pct"]),
            str(t["max_hold_bars"]),
        )

    for ev in events:
        ts = ev["ts"]
        t = ev["trade"]
        trade_id = tid(t)

        # mark-to-market before event
        eq_before = current_equity(cash, open_positions, ts, price_cache, cost)
        free_before = cash

        if ev["kind"] == "EXIT":
            if trade_id not in accepted_trade_ids:
                continue
            pos = open_positions.pop(trade_id)

            sell_fill = cost_adjusted_sell_price(t["exit_price"], cost)
            sell_mv = pos["shares"] * sell_fill
            cash_in = sell_cash_received(sell_mv, cost)
            cash += cash_in

            net_ret = (cash_in / pos["cash_out"] - 1.0) * 100.0
            realized_returns.append(net_ret)

            eq_after = current_equity(cash, open_positions, ts, price_cache, cost)

            event_rows.append({
                "config_name": cfg_name,
                "cost_scenario": cost_name,
                "position_fraction": position_fraction,
                "tie_order": tie_order,
                "event_time": ts,
                "event_type": "EXIT",
                "stock_code": t["stock_code"],
                "stock_name": t.get("stock_name", ""),
                "trade_date": t["trade_date"],
                "entry_time": t["entry_time"],
                "exit_time": t["exit_time"],
                "free_cash_before": round(free_before, 2),
                "free_cash_after": round(cash, 2),
                "portfolio_equity_after": round(eq_after, 2),
                "open_positions_after": len(open_positions),
                "position_notional": round(pos["position_notional"], 2),
                "net_trade_return_pct": round(net_ret, 6),
                "skip_reason": "",
            })

        else:
            # account equity marked immediately before admission decision
            eq_now = eq_before
            desired_notional = eq_now * position_fraction

            buy_fill = cost_adjusted_buy_price(t["entry_price"], cost)
            if buy_fill <= 0:
                continue

            # fractional shares are allowed intentionally in this research model
            # to isolate capital effects from lot-size effects.
            shares = desired_notional / buy_fill
            market_value = shares * buy_fill
            cash_out = buy_cash_required(market_value, cost)

            if cash_out > cash + 1e-9:
                event_rows.append({
                    "config_name": cfg_name,
                    "cost_scenario": cost_name,
                    "position_fraction": position_fraction,
                    "tie_order": tie_order,
                    "event_time": ts,
                    "event_type": "SKIP",
                    "stock_code": t["stock_code"],
                    "stock_name": t.get("stock_name", ""),
                    "trade_date": t["trade_date"],
                    "entry_time": t["entry_time"],
                    "exit_time": t["exit_time"],
                    "free_cash_before": round(free_before, 2),
                    "free_cash_after": round(cash, 2),
                    "portfolio_equity_after": round(eq_now, 2),
                    "open_positions_after": len(open_positions),
                    "position_notional": round(desired_notional, 2),
                    "net_trade_return_pct": "",
                    "skip_reason": "INSUFFICIENT_FREE_CASH",
                })
            else:
                cash -= cash_out
                accepted_trade_ids.add(trade_id)
                open_positions[trade_id] = {
                    "stock_code": t["stock_code"],
                    "entry_price_raw": t["entry_price"],
                    "shares": shares,
                    "cash_out": cash_out,
                    "position_notional": desired_notional,
                }

                eq_after = current_equity(cash, open_positions, ts, price_cache, cost)

                event_rows.append({
                    "config_name": cfg_name,
                    "cost_scenario": cost_name,
                    "position_fraction": position_fraction,
                    "tie_order": tie_order,
                    "event_time": ts,
                    "event_type": "ENTRY",
                    "stock_code": t["stock_code"],
                    "stock_name": t.get("stock_name", ""),
                    "trade_date": t["trade_date"],
                    "entry_time": t["entry_time"],
                    "exit_time": t["exit_time"],
                    "free_cash_before": round(free_before, 2),
                    "free_cash_after": round(cash, 2),
                    "portfolio_equity_after": round(eq_after, 2),
                    "open_positions_after": len(open_positions),
                    "position_notional": round(desired_notional, 2),
                    "net_trade_return_pct": "",
                    "skip_reason": "",
                })

        # update MTM risk metrics after each accepted entry / realized exit
        eq = current_equity(cash, open_positions, ts, price_cache, cost)
        peak_equity = max(peak_equity, eq)
        if peak_equity > 0:
            dd = (eq / peak_equity - 1.0) * 100.0
            min_dd = min(min_dd, dd)

        max_open = max(max_open, len(open_positions))
        min_cash = min(min_cash, cash)

        if eq > 0:
            utilization = (eq - cash) / eq * 100.0
            max_cash_util = max(max_cash_util, utilization)

    # Final equity after all exits.
    final_ts = max((t["exit_time"] for t in trades), default="")
    ending_equity = current_equity(cash, open_positions, final_ts, price_cache, cost) if final_ts else cash

    signal_count = len(trades)
    accepted_count = len(accepted_trade_ids)
    skipped = signal_count - accepted_count

    max_same, mean_same, _ = same_day_stats(trades)

    wins = sum(1 for r in realized_returns if r > 0)

    run_row = {
        "config_name": cfg_name,
        "cost_scenario": cost_name,
        "position_fraction": position_fraction,
        "tie_order": tie_order,
        "signal_count": signal_count,
        "accepted_count": accepted_count,
        "skipped_cash_count": skipped,
        "acceptance_rate_pct": round(accepted_count / signal_count * 100.0, 6) if signal_count else 0.0,
        "max_simultaneous_positions": max_open,
        "max_same_day_signals": max_same,
        "mean_same_day_signals": round(mean_same, 6),
        "ending_equity": round(ending_equity, 2),
        "portfolio_return_pct": round((ending_equity / INITIAL_EQUITY - 1.0) * 100.0, 6),
        "diagnostic_mtm_mdd_pct": round(min_dd, 6),
        "max_cash_utilization_pct": round(max_cash_util, 6),
        "min_cash": round(min_cash, 2),
        "realized_trade_win_rate_pct": round(wins / len(realized_returns) * 100.0, 6) if realized_returns else "",
        "avg_net_trade_return_pct": round(sum(realized_returns) / len(realized_returns), 6) if realized_returns else "",
        "max_consecutive_portfolio_losses": consecutive_losses(realized_returns),
    }

    return run_row, event_rows


def main():
    base = Path(__file__).resolve().parent
    inp = base / INPUT_FILE

    if not inp.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    rows = read_csv(inp)

    print("=" * 98)
    print("RS20 PORTFOLIO / CAPITAL STRESS v1")
    print(f"INPUT TRADE GRID ROWS    : {len(rows):,}")
    print(f"REPRESENTATIVE CONFIGS   : {[c['name'] for c in REPRESENTATIVE_CONFIGS]}")
    print(f"POSITION FRACTIONS       : {POSITION_FRACTIONS}")
    print(f"COST SCENARIOS           : {list(COST_SCENARIOS.keys())}")
    print(f"TIE ORDERS               : {TIE_ORDERS}")
    print("NO Kiwoom API / NO order API")
    print("=" * 98)

    price_cache = PriceCache(base)
    all_run_rows = []
    all_event_rows = []
    daily_rows = []

    for cfg in REPRESENTATIVE_CONFIGS:
        trades = filter_config(rows, cfg)
        trades.sort(key=lambda t: (t["entry_time"], t["stock_code"]))

        max_same, mean_same, day_counts = same_day_stats(trades)

        for d, c in sorted(day_counts.items()):
            daily_rows.append({
                "config_name": cfg["name"],
                "trade_date": d,
                "signal_count": c,
            })

        print(
            f"{cfg['name']}: {len(trades):,} signals | "
            f"max same-day {max_same} | mean same-day {mean_same:.2f}"
        )

        for cost_name, cost in COST_SCENARIOS.items():
            for frac in POSITION_FRACTIONS:
                for tie in TIE_ORDERS:
                    run_row, event_rows = run_portfolio(
                        trades=trades,
                        cfg_name=cfg["name"],
                        cost_name=cost_name,
                        cost=cost,
                        position_fraction=frac,
                        tie_order=tie,
                        price_cache=price_cache,
                    )
                    all_run_rows.append(run_row)
                    all_event_rows.extend(event_rows)

                    print(
                        f"  {cost_name:<20} frac={frac:.2f} {tie:<9} | "
                        f"accepted={run_row['accepted_count']:>3}/{run_row['signal_count']} | "
                        f"ret={run_row['portfolio_return_pct']:>9.3f}% | "
                        f"MDD={run_row['diagnostic_mtm_mdd_pct']:>8.3f}%"
                    )

    write_csv(base / OUT_RUNS, RUN_FIELDS, all_run_rows)
    write_csv(base / OUT_EVENTS, EVENT_FIELDS, all_event_rows)
    write_csv(base / OUT_DAILY, DAILY_FIELDS, daily_rows)

    # Summary without selecting a winner.
    lines = [
        "RS20 PORTFOLIO / CAPITAL STRESS v1",
        "",
        f"initial_equity_normalization: {INITIAL_EQUITY:.0f}",
        f"representative_configs: {[c['name'] for c in REPRESENTATIVE_CONFIGS]}",
        f"position_fractions: {POSITION_FRACTIONS}",
        f"cost_scenarios: {list(COST_SCENARIOS.keys())}",
        f"tie_orders: {TIE_ORDERS}",
        f"portfolio_runs: {len(all_run_rows)}",
        "",
        "INTERPRETATION",
        "- representative configs are research samples from the broad EOD plateau.",
        "- no config is selected as a source-rule winner.",
        "- fixed position fractions are capital-stress assumptions only.",
        "- no leverage.",
        "- insufficient free cash causes the signal to be skipped.",
        "- same-minute tie order is tested both ascending and descending by stock code.",
        "- fractional shares are allowed to isolate capital effects from lot-size effects.",
        "- diagnostic MDD marks open positions to latest available 1-minute close at each event.",
        "- open-position liquidation value includes the selected sell cost/slippage assumptions.",
        "",
        "LIMITATIONS",
        "- event-time MTM is not a continuous every-minute account curve.",
        "- actual broker fees/taxes are not yet fixed.",
        "- exact-touch fillability still requires Forward PAPER.",
        "- unresolved source filters remain unresolved.",
        "",
        "NO Kiwoom API. NO orders.",
    ]

    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 98)
    print("COMPLETE")
    print(f"PORTFOLIO RUNS          : {len(all_run_rows):,}")
    print(f"EVENT ROWS              : {len(all_event_rows):,}")
    print(f"DAILY SIGNAL ROWS       : {len(daily_rows):,}")
    print(f"RUN FILE                : {OUT_RUNS}")
    print(f"EVENT FILE              : {OUT_EVENTS}")
    print(f"DAILY FILE              : {OUT_DAILY}")
    print(f"SUMMARY                 : {OUT_SUMMARY}")
    print("=" * 98)


if __name__ == "__main__":
    main()

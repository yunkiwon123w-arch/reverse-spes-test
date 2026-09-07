# -*- coding: utf-8 -*-
"""
RS20 EXECUTION / P&L RESEARCH v1
================================

PURPOSE
- Research execution outcomes AFTER the frozen RS20 v1.2 first exact Reverse-38 touch.
- Compare many TP / SL / maximum-hold combinations WITHOUT turning any of them
  into a source rule.
- Apply transaction-cost scenarios separately from the price-path rule.
- Produce chronological 70/30 holdout statistics for every configuration.

IMPORTANT
- This is RESEARCH ONLY, not the frozen source strategy.
- TP/SL/holding rules below are NOT in the RS20 source material.
- Cost scenarios are ILLUSTRATIVE research assumptions, NOT a claim about the
  user's actual broker fee/tax schedule.
- Intrabar TP+SL collision is handled CONSERVATIVELY as SL_FIRST.
- No Kiwoom API. No orders.

REQUIRED
- rs20_source_event_state_machine_candidate_summary_v1_2.csv
- local 1-minute cache:
    common_market_data/minute_1m_stock_v1/<stock>.csv.gz
  with date-level fallback:
    common_market_data/minute_1m/YYYY/MM/<stock>_<date>.csv.gz
"""

import csv
import gzip
from collections import defaultdict
from pathlib import Path
from statistics import median

INPUT_FILE = "rs20_source_event_state_machine_candidate_summary_v1_2.csv"

STOCK_CACHE_ROOT = Path("common_market_data/minute_1m_stock_v1")
DATE_CACHE_ROOT = Path("common_market_data/minute_1m")

OUT_TRADES = "rs20_execution_trade_results_v1.csv"
OUT_GRID = "rs20_execution_pnl_grid_v1.csv"
OUT_UNAVAILABLE = "rs20_execution_pnl_unavailable_v1.csv"
OUT_SUMMARY = "rs20_execution_pnl_summary_v1.txt"

# ---------------------------------------------------------------------
# RESEARCH GRID ONLY — NOT SOURCE RULES
# ---------------------------------------------------------------------
TP_LEVELS_PCT = [1, 2, 3, 4, 5, 7, 10]
SL_LEVELS_PCT = [1, 2, 3, 4, 5]
MAX_HOLD_BARS = [30, 60, 120, "EOD"]

# ILLUSTRATIVE cost scenarios.
# All values are percent of traded value.
# Change only if/when the actual broker/tax assumptions are intentionally fixed.
COST_SCENARIOS = {
    "GROSS_0": {
        "buy_commission_pct": 0.000,
        "sell_commission_pct": 0.000,
        "sell_tax_pct": 0.000,
        "buy_slippage_pct": 0.000,
        "sell_slippage_pct": 0.000,
    },
    "ILLUSTRATIVE_LOW": {
        "buy_commission_pct": 0.015,
        "sell_commission_pct": 0.015,
        "sell_tax_pct": 0.150,
        "buy_slippage_pct": 0.025,
        "sell_slippage_pct": 0.025,
    },
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

TRADE_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date",
    "entry_time", "entry_price",
    "core_state_at_entry",
    "tp_pct", "sl_pct", "max_hold_bars",
    "exit_time", "exit_price",
    "gross_return_pct",
    "exit_reason",
    "holding_bars",
    "ambiguous_intrabar",
    "split_70_30",
]

GRID_FIELDS = [
    "split",
    "tp_pct", "sl_pct", "max_hold_bars",
    "cost_scenario",
    "n",
    "win_n", "loss_n", "flat_n",
    "win_rate_pct",
    "mean_gross_return_pct",
    "median_gross_return_pct",
    "mean_net_return_pct",
    "median_net_return_pct",
    "avg_win_net_pct",
    "avg_loss_net_pct",
    "payoff_ratio",
    "expectancy_net_pct",
    "diagnostic_compounded_return_pct",
    "diagnostic_mdd_pct",
    "max_consecutive_losses",
    "median_holding_bars",
    "tp_exit_n", "sl_exit_n", "time_exit_n", "eod_exit_n",
    "ambiguous_intrabar_n",
    "buy_commission_pct",
    "sell_commission_pct",
    "sell_tax_pct",
    "buy_slippage_pct",
    "sell_slippage_pct",
]

UNAVAILABLE_FIELDS = [
    "stock_code", "stock_name", "market", "trade_date", "reason"
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
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return default


def af(v, default=None):
    x = sf(v, default)
    return abs(x) if x is not None else default


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


def parse_bar(r):
    tm = str(r.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    o = af(r.get("open_pric"))
    h = af(r.get("high_pric"))
    l = af(r.get("low_pric"))
    c = af(r.get("cur_prc"))

    if None in (o, h, l, c):
        return None

    return {
        "cntr_tm": tm,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
    }


def load_gzip_bars(path):
    bars = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            b = parse_bar(r)
            if b:
                bars[b["cntr_tm"]] = b
    return bars


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


def simulate_trade(daybars, entry_time, entry_price, tp_pct, sl_pct, max_hold_bars):
    idx = None
    for i, b in enumerate(daybars):
        if b["cntr_tm"] == entry_time:
            idx = i
            break

    if idx is None:
        return None

    # Entry touch occurs inside the entry bar.
    # Exit-path evaluation starts from the NEXT 1-minute bar.
    path = daybars[idx + 1:]

    if not path:
        return {
            "exit_time": entry_time,
            "exit_price": entry_price,
            "gross_return_pct": 0.0,
            "exit_reason": "NO_POST_ENTRY_BAR",
            "holding_bars": 0,
            "ambiguous_intrabar": "N",
        }

    if max_hold_bars == "EOD":
        eval_path = path
    else:
        eval_path = path[:int(max_hold_bars)]

    tp_price = entry_price * (1.0 + tp_pct / 100.0)
    sl_price = entry_price * (1.0 - sl_pct / 100.0)

    for j, b in enumerate(eval_path, start=1):
        hit_tp = b["high"] >= tp_price
        hit_sl = b["low"] <= sl_price

        if hit_tp and hit_sl:
            # Conservative convention.
            return {
                "exit_time": b["cntr_tm"],
                "exit_price": sl_price,
                "gross_return_pct": -float(sl_pct),
                "exit_reason": "AMBIGUOUS_SL_FIRST",
                "holding_bars": j,
                "ambiguous_intrabar": "Y",
            }

        if hit_sl:
            return {
                "exit_time": b["cntr_tm"],
                "exit_price": sl_price,
                "gross_return_pct": -float(sl_pct),
                "exit_reason": "SL",
                "holding_bars": j,
                "ambiguous_intrabar": "N",
            }

        if hit_tp:
            return {
                "exit_time": b["cntr_tm"],
                "exit_price": tp_price,
                "gross_return_pct": float(tp_pct),
                "exit_reason": "TP",
                "holding_bars": j,
                "ambiguous_intrabar": "N",
            }

    # No TP/SL before time limit.
    last = eval_path[-1]
    reason = "EOD" if max_hold_bars == "EOD" or len(path) <= len(eval_path) else "TIME"
    gross_ret = (last["close"] / entry_price - 1.0) * 100.0

    return {
        "exit_time": last["cntr_tm"],
        "exit_price": last["close"],
        "gross_return_pct": gross_ret,
        "exit_reason": reason,
        "holding_bars": len(eval_path),
        "ambiguous_intrabar": "N",
    }


def net_return_pct(entry_price, exit_price, cost):
    buy_comm = cost["buy_commission_pct"] / 100.0
    sell_comm = cost["sell_commission_pct"] / 100.0
    sell_tax = cost["sell_tax_pct"] / 100.0
    buy_slip = cost["buy_slippage_pct"] / 100.0
    sell_slip = cost["sell_slippage_pct"] / 100.0

    buy_fill = entry_price * (1.0 + buy_slip)
    sell_fill = exit_price * (1.0 - sell_slip)

    cash_out = buy_fill * (1.0 + buy_comm)
    cash_in = sell_fill * (1.0 - sell_comm - sell_tax)

    return (cash_in / cash_out - 1.0) * 100.0


def max_consecutive_losses(returns):
    best = 0
    cur = 0
    for r in returns:
        if r < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def compounded_return_and_mdd(returns_pct):
    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    for r in returns_pct:
        equity *= (1.0 + r / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            dd = (equity / peak - 1.0) * 100.0
            max_dd = min(max_dd, dd)

    return (equity - 1.0) * 100.0, max_dd


def median_safe(vals):
    vals = [v for v in vals if v is not None]
    return median(vals) if vals else None


def aggregate_config(trades, split_name, tp, sl, hold, scenario_name, cost):
    subset = [
        t for t in trades
        if t["tp_pct"] == tp
        and t["sl_pct"] == sl
        and t["max_hold_bars"] == hold
        and (split_name == "ALL" or t["split_70_30"] == split_name)
    ]

    n = len(subset)
    if n == 0:
        return None

    gross = [float(t["gross_return_pct"]) for t in subset]
    net = [net_return_pct(float(t["entry_price"]), float(t["exit_price"]), cost) for t in subset]

    wins = [r for r in net if r > 0]
    losses = [r for r in net if r < 0]
    flats = [r for r in net if r == 0]

    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss not in (None, 0) else None
    expectancy = sum(net) / n

    comp, mdd = compounded_return_and_mdd(net)

    return {
        "split": split_name,
        "tp_pct": tp,
        "sl_pct": sl,
        "max_hold_bars": hold,
        "cost_scenario": scenario_name,
        "n": n,
        "win_n": len(wins),
        "loss_n": len(losses),
        "flat_n": len(flats),
        "win_rate_pct": round(len(wins) / n * 100.0, 6),
        "mean_gross_return_pct": round(sum(gross) / n, 6),
        "median_gross_return_pct": round(median(gross), 6),
        "mean_net_return_pct": round(sum(net) / n, 6),
        "median_net_return_pct": round(median(net), 6),
        "avg_win_net_pct": round(avg_win, 6) if avg_win is not None else "",
        "avg_loss_net_pct": round(avg_loss, 6) if avg_loss is not None else "",
        "payoff_ratio": round(payoff, 6) if payoff is not None else "",
        "expectancy_net_pct": round(expectancy, 6),
        "diagnostic_compounded_return_pct": round(comp, 6),
        "diagnostic_mdd_pct": round(mdd, 6),
        "max_consecutive_losses": max_consecutive_losses(net),
        "median_holding_bars": round(median_safe([int(t["holding_bars"]) for t in subset]), 6),
        "tp_exit_n": sum(1 for t in subset if t["exit_reason"] == "TP"),
        "sl_exit_n": sum(1 for t in subset if t["exit_reason"] == "SL"),
        "time_exit_n": sum(1 for t in subset if t["exit_reason"] == "TIME"),
        "eod_exit_n": sum(1 for t in subset if t["exit_reason"] == "EOD"),
        "ambiguous_intrabar_n": sum(1 for t in subset if t["ambiguous_intrabar"] == "Y"),
        "buy_commission_pct": cost["buy_commission_pct"],
        "sell_commission_pct": cost["sell_commission_pct"],
        "sell_tax_pct": cost["sell_tax_pct"],
        "buy_slippage_pct": cost["buy_slippage_pct"],
        "sell_slippage_pct": cost["sell_slippage_pct"],
    }


def main():
    base = Path(__file__).resolve().parent
    inp = base / INPUT_FILE

    if not inp.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    rows = read_csv(inp)
    exact = [
        r for r in rows
        if str(r.get("has_exact_touch_after_activation", "")).upper() == "Y"
    ]
    exact.sort(key=lambda r: (
        str(r.get("trade_date", "")),
        str(r.get("first_exact_touch_after_activation_time", "")),
        norm_code(r.get("stock_code", "")),
    ))

    n_exact = len(exact)
    cut70 = int(n_exact * 0.70)

    print("=" * 94)
    print("RS20 EXECUTION / P&L RESEARCH v1")
    print(f"EXACT-TOUCH INPUT        : {n_exact:,}")
    print(f"CHRONO TRAIN 70          : {cut70:,}")
    print(f"CHRONO HOLDOUT 30        : {n_exact - cut70:,}")
    print(f"TP LEVELS                : {TP_LEVELS_PCT}")
    print(f"SL LEVELS                : {SL_LEVELS_PCT}")
    print(f"MAX HOLD                 : {MAX_HOLD_BARS}")
    print(f"COST SCENARIOS           : {list(COST_SCENARIOS.keys())}")
    print("LOCAL CACHE ONLY / NO Kiwoom API / NO ORDER API")
    print("=" * 94)

    stock_cache = {}
    unavailable = []
    trade_rows = []

    for i, r in enumerate(exact):
        code = norm_code(r.get("stock_code", ""))
        dt = str(r.get("trade_date", "")).strip()
        entry_time = str(r.get("first_exact_touch_after_activation_time", "")).strip()
        entry_price = sf(r.get("first_exact_touch_after_activation_fib38"))

        if not entry_time or entry_price is None or entry_price <= 0:
            unavailable.append({
                "stock_code": code,
                "stock_name": r.get("stock_name", ""),
                "market": r.get("market", ""),
                "trade_date": dt,
                "reason": "INVALID_ENTRY_REFERENCE",
            })
            continue

        if code not in stock_cache:
            p = base / STOCK_CACHE_ROOT / f"{code}.csv.gz"
            if p.exists():
                try:
                    stock_cache[code] = load_gzip_bars(p)
                except Exception:
                    stock_cache[code] = None
            else:
                stock_cache[code] = None

        bars_map = stock_cache.get(code)

        if bars_map is None or not any(tm.startswith(dt) for tm in bars_map):
            p = find_date_cache(base, code, dt)
            if p:
                try:
                    bars_map = load_gzip_bars(p)
                except Exception:
                    bars_map = None

        if not bars_map:
            unavailable.append({
                "stock_code": code,
                "stock_name": r.get("stock_name", ""),
                "market": r.get("market", ""),
                "trade_date": dt,
                "reason": "LOCAL_1M_CACHE_NOT_FOUND_FOR_DATE",
            })
            continue

        daybars = sorted(
            [b for tm, b in bars_map.items() if tm.startswith(dt)],
            key=lambda x: x["cntr_tm"]
        )

        split = "TRAIN70" if i < cut70 else "HOLDOUT30"

        for tp in TP_LEVELS_PCT:
            for sl in SL_LEVELS_PCT:
                for hold in MAX_HOLD_BARS:
                    result = simulate_trade(daybars, entry_time, entry_price, tp, sl, hold)

                    if result is None:
                        continue

                    trade_rows.append({
                        "stock_code": code,
                        "stock_name": r.get("stock_name", ""),
                        "market": r.get("market", ""),
                        "trade_date": dt,
                        "entry_time": entry_time,
                        "entry_price": round(entry_price, 6),
                        "core_state_at_entry": r.get("core_state_at_first_exact_touch", ""),
                        "tp_pct": tp,
                        "sl_pct": sl,
                        "max_hold_bars": hold,
                        "exit_time": result["exit_time"],
                        "exit_price": round(float(result["exit_price"]), 6),
                        "gross_return_pct": round(float(result["gross_return_pct"]), 6),
                        "exit_reason": result["exit_reason"],
                        "holding_bars": result["holding_bars"],
                        "ambiguous_intrabar": result["ambiguous_intrabar"],
                        "split_70_30": split,
                    })

        if (i + 1) % 50 == 0 or (i + 1) == n_exact:
            print(
                f"[{i+1:03d}/{n_exact}] "
                f"trade-grid rows {len(trade_rows):,} / unavailable {len(unavailable):,}"
            )

    write_csv(base / OUT_TRADES, TRADE_FIELDS, trade_rows)
    write_csv(base / OUT_UNAVAILABLE, UNAVAILABLE_FIELDS, unavailable)

    grid_rows = []
    for tp in TP_LEVELS_PCT:
        for sl in SL_LEVELS_PCT:
            for hold in MAX_HOLD_BARS:
                for scenario_name, cost in COST_SCENARIOS.items():
                    for split_name in ["ALL", "TRAIN70", "HOLDOUT30"]:
                        row = aggregate_config(
                            trade_rows, split_name, tp, sl, hold, scenario_name, cost
                        )
                        if row:
                            grid_rows.append(row)

    write_csv(base / OUT_GRID, GRID_FIELDS, grid_rows)

    unique_trades = len(exact) - len(unavailable)
    same_day = defaultdict(int)
    for r in exact:
        same_day[str(r.get("trade_date", "")).strip()] += 1
    max_signals_same_day = max(same_day.values()) if same_day else 0

    lines = [
        "RS20 EXECUTION / P&L RESEARCH v1",
        "",
        f"exact_touch_input: {n_exact}",
        f"usable_entry_paths: {unique_trades}",
        f"unavailable: {len(unavailable)}",
        f"trade_grid_rows: {len(trade_rows)}",
        f"pnl_grid_rows: {len(grid_rows)}",
        f"chrono_train70: {cut70}",
        f"chrono_holdout30: {n_exact - cut70}",
        f"max_exact_touch_signals_same_day: {max_signals_same_day}",
        "",
        "RESEARCH GRID — NOT SOURCE RULES",
        f"TP_LEVELS_PCT: {TP_LEVELS_PCT}",
        f"SL_LEVELS_PCT: {SL_LEVELS_PCT}",
        f"MAX_HOLD_BARS: {MAX_HOLD_BARS}",
        "",
        "COST SCENARIOS — ILLUSTRATIVE ONLY",
    ]

    for name, c in COST_SCENARIOS.items():
        lines.append(
            f"{name}: buy_comm={c['buy_commission_pct']}%, "
            f"sell_comm={c['sell_commission_pct']}%, "
            f"sell_tax={c['sell_tax_pct']}%, "
            f"buy_slip={c['buy_slippage_pct']}%, "
            f"sell_slip={c['sell_slippage_pct']}%"
        )

    lines += [
        "",
        "EXECUTION CONVENTIONS",
        "- entry reference = v1.2 first exact Reverse-38 touch price.",
        "- exit search starts from the next 1-minute bar.",
        "- if TP and SL are both touched in one bar, SL_FIRST is assumed.",
        "- time-limit exit uses the close of the final allowed 1-minute bar.",
        "- EOD exit uses the last available 1-minute close.",
        "",
        "STATISTICS",
        "- expectancy = mean per-trade net return.",
        "- diagnostic compounded return and MDD use sequential equal-1x trades.",
        "- overlapping/simultaneous capital constraints are NOT modeled yet.",
        "- therefore diagnostic compounded return/MDD are NOT production portfolio P&L.",
        "",
        "NO CONFIGURATION IS SELECTED AS THE WINNER IN THIS SCRIPT.",
        "NO Kiwoom API. NO orders.",
    ]

    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 94)
    print("COMPLETE")
    print(f"EXACT TOUCH INPUT       : {n_exact:,}")
    print(f"USABLE ENTRY PATHS      : {unique_trades:,}")
    print(f"UNAVAILABLE             : {len(unavailable):,}")
    print(f"TRADE GRID ROWS         : {len(trade_rows):,}")
    print(f"P&L GRID ROWS           : {len(grid_rows):,}")
    print(f"TRADE RESULTS           : {OUT_TRADES}")
    print(f"P&L GRID                : {OUT_GRID}")
    print(f"SUMMARY                 : {OUT_SUMMARY}")
    print("=" * 94)


if __name__ == "__main__":
    main()

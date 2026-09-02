import csv
import glob
import os
import sys
from datetime import datetime

CACHE_DIR = "minute_cache"
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

OUTPUT_SUMMARY = os.path.join(
    CACHE_DIR, f"rs3_stage2_cost_weight_stress_summary_v1_{RUN_TAG}.csv"
)
OUTPUT_CASES = os.path.join(
    CACHE_DIR, f"rs3_stage2_cost_weight_stress_cases_v1_{RUN_TAG}.csv"
)
OUTPUT_ERRORS = os.path.join(
    CACHE_DIR, f"rs3_stage2_cost_weight_stress_errors_v1_{RUN_TAG}.csv"
)

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"
DEV_RATIO = 0.70

# ------------------------------------------------------------
# 연구용 자금/비용 가정
# 실제 증권사 수수료·세금의 확정값이 아님.
# 목적: STAGE2가 거래비용과 비중 변화에도 살아남는지 스트레스 테스트.
# ------------------------------------------------------------

WEIGHT_SCHEMES = [
    ("W50_50", 0.50, 0.50),
    ("W60_40", 0.60, 0.40),
    ("W70_30", 0.70, 0.30),
]

# fee_side_pct: 매수/매도 각각 적용되는 연구용 수수료
# sell_tax_pct: 매도 시에만 적용되는 연구용 세금/부담
# slippage_side_pct: 매수/매도 각각 적용되는 연구용 체결 불리함
COST_SCENARIOS = [
    ("COST_0", 0.00, 0.00, 0.00),
    ("COST_LOW", 0.01, 0.18, 0.05),
    ("COST_MID", 0.015, 0.20, 0.10),
    ("COST_HIGH", 0.02, 0.23, 0.20),
]


def num(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def normalize_code(value):
    s = str(value or "").strip().upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if len(s) == 6 and s.isalnum():
        return s
    if s.isdigit():
        return s.zfill(6)
    return s


def parse_dt(v):
    s = str(v or "").strip()
    if not s:
        return None
    if len(s) == 14 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d%H%M%S")
    return None


def parse_date(v):
    return datetime.strptime(str(v or "").strip(), "%Y%m%d")


def pct(n, d):
    return round(n / d * 100.0, 2) if d else ""


def find_latest_corrected_file():
    candidates = []
    candidates += glob.glob(
        os.path.join(CACHE_DIR, "rs3_trading_time_corrected_v1_*.csv")
    )
    candidates += glob.glob("rs3_trading_time_corrected_v1_*.csv")
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def load_cache(code):
    path = os.path.join(CACHE_DIR, f"{normalize_code(code)}_minute.csv")
    if not os.path.exists(path):
        return []

    bars = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_dt(row.get("cntr_tm"))
            if not dt:
                continue
            try:
                bars.append({
                    "dt": dt,
                    "open": abs(float(row["open"])),
                    "high": abs(float(row["high"])),
                    "low": abs(float(row["low"])),
                    "close": abs(float(row["close"])),
                    "volume": abs(float(row.get("volume", 0) or 0)),
                })
            except Exception:
                continue
    bars.sort(key=lambda x: x["dt"])
    return bars


def clean_class(row):
    g = str(row.get("path_group", "")).strip()
    if g in SUCCESS_GROUPS:
        return "SUCCESS"
    if g == FAIL_GROUP:
        return "FAIL"
    return None


def early_risk_3m(row):
    low3 = num(row.get("w3_low_pct"))
    down3 = num(row.get("w3_down_ratio"))
    return (
        low3 is not None and down3 is not None
        and low3 <= -1.5 and down3 >= 0.65
    )


def early_risk_5m(row):
    high5 = num(row.get("w5_high_pct"))
    low5 = num(row.get("w5_low_pct"))
    close5 = num(row.get("w5_close_pct"))
    down5 = num(row.get("w5_down_ratio"))
    vol5 = num(row.get("w5_volume_avg_vs_pre30"))

    score = 0
    if high5 is not None and high5 < 1.0:
        score += 1
    if low5 is not None and low5 <= -1.0:
        score += 1
    if close5 is not None and close5 < 0:
        score += 1
    if down5 is not None and down5 >= 0.70:
        score += 1
    if vol5 is not None and vol5 >= 1.25:
        score += 1

    return score >= 4


def stage2_risk(row):
    mins = num(row.get("trading_minutes_buy1_to_buy2"))
    vol = num(row.get("vol_50_to_618_avg_vs_pre30"))
    if mins is None or vol is None:
        return None
    return mins <= 5 or vol >= 1.0


def stage2_action(row):
    buy2_dt = parse_dt(row.get("buy2_time"))
    return (
        buy2_dt is not None
        and (early_risk_3m(row) or early_risk_5m(row))
        and stage2_risk(row) is True
    )


def horizon_bars(bars, candidate_date, buy1_dt):
    dates = sorted({
        b["dt"].strftime("%Y%m%d")
        for b in bars
        if b["dt"] >= buy1_dt
    })
    dates = [d for d in dates if d >= candidate_date][:3]
    allowed = set(dates)

    return [
        b for b in bars
        if b["dt"] >= buy1_dt
        and b["dt"].strftime("%Y%m%d") in allowed
    ]


def simulate_tranche(bars, entry_dt, entry_price, tp_price, stop_price):
    active = [b for b in bars if b["dt"] >= entry_dt]

    for b in active:
        hit_tp = b["high"] >= tp_price
        hit_stop = b["low"] <= stop_price

        if hit_tp and hit_stop:
            return {
                "status": "AMBIGUOUS",
                "exit_dt": b["dt"],
                "exit_price": None,
            }
        if hit_tp:
            return {
                "status": "TP",
                "exit_dt": b["dt"],
                "exit_price": tp_price,
            }
        if hit_stop:
            return {
                "status": "STOP",
                "exit_dt": b["dt"],
                "exit_price": stop_price,
            }

    if active:
        return {
            "status": "MTM_END_D2",
            "exit_dt": active[-1]["dt"],
            "exit_price": active[-1]["close"],
        }

    return {
        "status": "NO_DATA",
        "exit_dt": None,
        "exit_price": None,
    }


def gross_return_pct(entry_price, exit_price):
    return (exit_price / entry_price - 1.0) * 100.0


def net_return_pct(
    entry_price,
    exit_price,
    fee_side_pct,
    sell_tax_pct,
    slippage_side_pct
):
    """
    매수/매도 각각 체결불리함과 수수료를 반영한 연구용 순수익률.
    - 매수 실제비용: entry * (1 + slippage) + fee
    - 매도 실제수취: exit * (1 - slippage) - fee - sell tax
    단순 비율 근사.
    """
    buy_cost_rate = (fee_side_pct + slippage_side_pct) / 100.0
    sell_cost_rate = (
        fee_side_pct + sell_tax_pct + slippage_side_pct
    ) / 100.0

    effective_buy = entry_price * (1.0 + buy_cost_rate)
    effective_sell = exit_price * (1.0 - sell_cost_rate)

    return (effective_sell / effective_buy - 1.0) * 100.0


def baseline_trade(row, bars):
    buy1_dt = parse_dt(row.get("buy1_time"))
    buy2_dt = parse_dt(row.get("buy2_time"))
    buy1 = num(row.get("buy1_price"))
    buy2 = num(row.get("buy2_price"))
    stop70 = num(row.get("stop70_price"))

    if not buy1_dt or not buy1 or not stop70:
        return None

    hb = horizon_bars(
        bars,
        str(row.get("date", "")).strip(),
        buy1_dt
    )
    if not hb:
        return None

    t1 = simulate_tranche(
        hb, buy1_dt, buy1, buy1 * 1.04, stop70
    )
    if t1["exit_price"] is None:
        return None

    t2 = None
    if buy2_dt and buy2:
        t2 = simulate_tranche(
            hb, buy2_dt, buy2, buy2 * 1.04, stop70
        )
        if t2["exit_price"] is None:
            return None

    return {
        "buy1": buy1,
        "buy2": buy2,
        "t1_exit": t1["exit_price"],
        "t1_status": t1["status"],
        "t2_exit": t2["exit_price"] if t2 else None,
        "t2_status": t2["status"] if t2 else "NOT_FILLED",
        "second_filled": t2 is not None,
    }


def scenario_return(
    row,
    trade,
    w1,
    w2,
    fee_side_pct,
    sell_tax_pct,
    slippage_side_pct,
    scenario
):
    acted = stage2_action(row)

    # STAGE2 defense:
    # 61.8 도달 시 1차를 buy2 가격에서 방어하고 2차 신규매수 취소.
    if scenario == "STAGE2_DEFENSE" and acted:
        exit_price = num(row.get("buy2_price"))
        if not exit_price:
            return None, True

        r1 = net_return_pct(
            trade["buy1"], exit_price,
            fee_side_pct, sell_tax_pct, slippage_side_pct
        )
        # 2차는 미집행: 미사용 자금 수익률 0
        return w1 * r1, True

    # baseline 또는 STAGE2 미개입
    r1 = net_return_pct(
        trade["buy1"], trade["t1_exit"],
        fee_side_pct, sell_tax_pct, slippage_side_pct
    )
    total = w1 * r1

    if trade["second_filled"]:
        r2 = net_return_pct(
            trade["buy2"], trade["t2_exit"],
            fee_side_pct, sell_tax_pct, slippage_side_pct
        )
        total += w2 * r2

    return total, False


def event_mdd(returns):
    equity = 1.0
    peak = 1.0
    worst = 0.0

    for r in returns:
        equity *= 1.0 + r / 100.0
        peak = max(peak, equity)
        dd = equity / peak - 1.0
        worst = min(worst, dd)

    return worst * 100.0, (equity - 1.0) * 100.0


def summarize(rows, segment, scenario, weight_name, cost_name):
    vals = [
        r["net_return_pct"]
        for r in rows
        if r["segment"] == segment
        and r["scenario"] == scenario
        and r["weight_scheme"] == weight_name
        and r["cost_scenario"] == cost_name
    ]

    if not vals:
        return None

    wins = sum(v > 0 for v in vals)
    losses = sum(v < 0 for v in vals)
    mdd, compound = event_mdd(vals)

    acted_rows = [
        r for r in rows
        if r["segment"] == segment
        and r["scenario"] == scenario
        and r["weight_scheme"] == weight_name
        and r["cost_scenario"] == cost_name
        and r["stage2_acted"] == 1
    ]

    fail_acted = [r for r in acted_rows if r["class"] == "FAIL"]
    succ_acted = [r for r in acted_rows if r["class"] == "SUCCESS"]

    return {
        "segment": segment,
        "scenario": scenario,
        "weight_scheme": weight_name,
        "cost_scenario": cost_name,
        "count": len(vals),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": pct(wins, len(vals)),
        "avg_return_pct": round(sum(vals) / len(vals), 4),
        "simple_sum_return_pct": round(sum(vals), 4),
        "event_compound_return_pct": round(compound, 4),
        "event_mdd_pct": round(mdd, 4),
        "stage2_action_count": len(acted_rows),
        "acted_fail_count": len(fail_acted),
        "acted_success_count": len(succ_acted),
    }


def main():
    print("=" * 92)
    print("Reverse SPES - RS3 STAGE2 거래비용·비중 스트레스 테스트 v1")
    print("STAGE2 조건 동결 / 비용·슬리피지·1차/2차 비중 변화 내구성 검증")
    print("=" * 92)

    input_file = find_latest_corrected_file()
    if not input_file:
        print("[ERROR] 교정 입력 파일을 찾지 못했습니다.")
        sys.exit(1)

    print(f"입력: {input_file}")

    with open(input_file, "r", encoding="utf-8-sig", newline="") as f:
        raw_rows = list(csv.DictReader(f))

    clean = [r for r in raw_rows if clean_class(r) is not None]
    clean.sort(
        key=lambda r: (
            parse_date(r.get("date")),
            str(r.get("stock_code", ""))
        )
    )

    split = int(len(clean) * DEV_RATIO)
    dev_keys = {
        (normalize_code(r["stock_code"]), str(r["date"]).strip())
        for r in clean[:split]
    }

    print(f"Primary 표본: {len(clean)}건")
    print(f"개발: {split}건 / 홀드아웃: {len(clean)-split}건")
    print(f"비중 시나리오: {len(WEIGHT_SCHEMES)}개")
    print(f"비용 시나리오: {len(COST_SCENARIOS)}개")
    print()

    cache_map = {}
    trades = []
    errors = []

    for r in clean:
        code = normalize_code(r.get("stock_code"))

        if code not in cache_map:
            cache_map[code] = load_cache(code)

        bars = cache_map[code]
        if not bars:
            errors.append({
                "stock_code": code,
                "stock_name": r.get("stock_name", ""),
                "date": r.get("date", ""),
                "error": "minute_cache 없음",
            })
            continue

        trade = baseline_trade(r, bars)
        if not trade:
            errors.append({
                "stock_code": code,
                "stock_name": r.get("stock_name", ""),
                "date": r.get("date", ""),
                "error": "baseline 거래 재구성 실패/AMBIGUOUS",
            })
            continue

        trades.append((r, trade))

    case_rows = []

    for r, trade in trades:
        key = (
            normalize_code(r["stock_code"]),
            str(r["date"]).strip()
        )
        segment = "DEV" if key in dev_keys else "HOLDOUT"

        for weight_name, w1, w2 in WEIGHT_SCHEMES:
            for cost_name, fee, tax, slip in COST_SCENARIOS:
                for scenario in ("BASELINE", "STAGE2_DEFENSE"):
                    ret, acted = scenario_return(
                        r, trade, w1, w2,
                        fee, tax, slip, scenario
                    )

                    if ret is None:
                        continue

                    case_rows.append({
                        "segment": segment,
                        "stock_code": normalize_code(r.get("stock_code")),
                        "stock_name": r.get("stock_name", ""),
                        "date": r.get("date", ""),
                        "path_group": r.get("path_group", ""),
                        "class": clean_class(r),
                        "scenario": scenario,
                        "weight_scheme": weight_name,
                        "weight1": w1,
                        "weight2": w2,
                        "cost_scenario": cost_name,
                        "fee_side_pct": fee,
                        "sell_tax_pct": tax,
                        "slippage_side_pct": slip,
                        "stage2_acted": int(acted),
                        "second_filled_baseline": int(
                            trade["second_filled"]
                        ),
                        "t1_exit_status": trade["t1_status"],
                        "t2_exit_status": trade["t2_status"],
                        "net_return_pct": round(ret, 4),
                    })

    if errors:
        with open(
            OUTPUT_ERRORS, "w", encoding="utf-8-sig", newline=""
        ) as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "stock_code", "stock_name", "date", "error"
                ]
            )
            w.writeheader()
            w.writerows(errors)

    if not case_rows:
        print("[ERROR] 결과가 없습니다.")
        sys.exit(1)

    case_fields = list(case_rows[0].keys())
    with open(
        OUTPUT_CASES, "w", encoding="utf-8-sig", newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=case_fields)
        w.writeheader()
        w.writerows(case_rows)

    # ALL segment도 요약할 수 있도록 별도 복제 없이 집계
    summary_rows = []

    for weight_name, _, _ in WEIGHT_SCHEMES:
        for cost_name, _, _, _ in COST_SCENARIOS:
            for segment in ("DEV", "HOLDOUT", "ALL"):
                for scenario in ("BASELINE", "STAGE2_DEFENSE"):
                    if segment == "ALL":
                        vals = [
                            r for r in case_rows
                            if r["scenario"] == scenario
                            and r["weight_scheme"] == weight_name
                            and r["cost_scenario"] == cost_name
                        ]
                        # 임시 ALL 요약
                        returns = [r["net_return_pct"] for r in vals]
                        if not returns:
                            continue
                        wins = sum(v > 0 for v in returns)
                        losses = sum(v < 0 for v in returns)
                        dd, compound = event_mdd(returns)
                        acted_rows = [
                            r for r in vals if r["stage2_acted"] == 1
                        ]
                        s = {
                            "segment": "ALL",
                            "scenario": scenario,
                            "weight_scheme": weight_name,
                            "cost_scenario": cost_name,
                            "count": len(returns),
                            "wins": wins,
                            "losses": losses,
                            "win_rate_pct": pct(wins, len(returns)),
                            "avg_return_pct": round(
                                sum(returns)/len(returns), 4
                            ),
                            "simple_sum_return_pct": round(
                                sum(returns), 4
                            ),
                            "event_compound_return_pct": round(
                                compound, 4
                            ),
                            "event_mdd_pct": round(dd, 4),
                            "stage2_action_count": len(acted_rows),
                            "acted_fail_count": sum(
                                r["class"] == "FAIL"
                                for r in acted_rows
                            ),
                            "acted_success_count": sum(
                                r["class"] == "SUCCESS"
                                for r in acted_rows
                            ),
                        }
                    else:
                        s = summarize(
                            case_rows, segment, scenario,
                            weight_name, cost_name
                        )
                    if s:
                        summary_rows.append(s)

    # 같은 segment/weight/cost 내 baseline 대비 STAGE2 변화량
    lookup = {
        (
            r["segment"],
            r["weight_scheme"],
            r["cost_scenario"],
            r["scenario"],
        ): r
        for r in summary_rows
    }

    for r in summary_rows:
        if r["scenario"] == "STAGE2_DEFENSE":
            b = lookup.get((
                r["segment"],
                r["weight_scheme"],
                r["cost_scenario"],
                "BASELINE",
            ))
            if b:
                r["avg_return_delta_pp"] = round(
                    r["avg_return_pct"] - b["avg_return_pct"], 4
                )
                r["sum_return_delta_pp"] = round(
                    r["simple_sum_return_pct"]
                    - b["simple_sum_return_pct"], 4
                )
                r["mdd_delta_pp"] = round(
                    r["event_mdd_pct"] - b["event_mdd_pct"], 4
                )
            else:
                r["avg_return_delta_pp"] = ""
                r["sum_return_delta_pp"] = ""
                r["mdd_delta_pp"] = ""
        else:
            r["avg_return_delta_pp"] = 0.0
            r["sum_return_delta_pp"] = 0.0
            r["mdd_delta_pp"] = 0.0

    summary_fields = [
        "segment", "scenario",
        "weight_scheme", "cost_scenario",
        "count", "wins", "losses", "win_rate_pct",
        "avg_return_pct", "avg_return_delta_pp",
        "simple_sum_return_pct", "sum_return_delta_pp",
        "event_compound_return_pct",
        "event_mdd_pct", "mdd_delta_pp",
        "stage2_action_count",
        "acted_fail_count", "acted_success_count",
    ]

    with open(
        OUTPUT_SUMMARY, "w", encoding="utf-8-sig", newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        for r in summary_rows:
            w.writerow({k: r.get(k, "") for k in summary_fields})

    print("=" * 92)
    print("거래비용·비중 스트레스 테스트 완료")
    print(f"거래 재구성 성공: {len(trades)}건")
    print(f"오류/제외: {len(errors)}건")
    print(f"요약: {OUTPUT_SUMMARY}")
    print(f"케이스: {OUTPUT_CASES}")
    if errors:
        print(f"오류: {OUTPUT_ERRORS}")
    print()
    print("주의:")
    print("- STAGE2 조건은 이번 단계에서 변경하지 않음")
    print("- 비용 숫자는 실제 확정 수수료/세율이 아닌 연구용 스트레스 가정")
    print("- W50/50, W60/40, W70/30 역시 연구용 자금배분 가정")
    print("- 비용/비중이 달라져도 STAGE2의 baseline 대비 개선이 유지되는지 확인")
    print("- 실제 증권사 조건 확정 후 최종 모의매매 단계에서 다시 반영")
    print("=" * 92)


if __name__ == "__main__":
    main()

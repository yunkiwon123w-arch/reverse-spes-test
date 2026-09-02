import csv
import os
import sys
from datetime import datetime

INPUT_FILE = "rs3_trading_time_corrected_v1_20260902_193236.csv"
CACHE_DIR = "minute_cache"

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
CASE_FILE = os.path.join(
    CACHE_DIR, f"rs3_risk_pnl_cases_v1_{RUN_TAG}.csv"
)
SUMMARY_FILE = os.path.join(
    CACHE_DIR, f"rs3_risk_pnl_summary_v1_{RUN_TAG}.csv"
)
ERROR_FILE = os.path.join(
    CACHE_DIR, f"rs3_risk_pnl_errors_v1_{RUN_TAG}.csv"
)

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"

# 연구용 가정: 원문에 1차/2차 비중이 명시되지 않아
# 최대투입자금 기준 1차 50%, 2차 50%를 "비교용 가정"으로만 사용.
TRANCHE1_WEIGHT = 0.50
TRANCHE2_WEIGHT = 0.50


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


def load_cache(code):
    path = os.path.join(CACHE_DIR, f"{normalize_code(code)}_minute.csv")
    if not os.path.exists(path):
        return []

    bars = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            dt = parse_dt(r.get("cntr_tm"))
            if not dt:
                continue
            try:
                bars.append({
                    "dt": dt,
                    "open": abs(float(r["open"])),
                    "high": abs(float(r["high"])),
                    "low": abs(float(r["low"])),
                    "close": abs(float(r["close"])),
                    "volume": abs(float(r.get("volume", 0) or 0)),
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


def early_3m(row):
    low3 = num(row.get("w3_low_pct"))
    down3 = num(row.get("w3_down_ratio"))
    return (
        low3 is not None and down3 is not None
        and low3 <= -1.5 and down3 >= 0.65
    )


def early_5m(row):
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

    return score >= 4, score


def stage2(row):
    mins = num(row.get("trading_minutes_buy1_to_buy2"))
    vol = num(row.get("vol_50_to_618_avg_vs_pre30"))
    if mins is None or vol is None:
        return None
    return mins <= 5 or vol >= 1.0


def bar_at_or_after(bars, dt):
    if dt is None:
        return None
    for b in bars:
        if b["dt"] >= dt:
            return b
    return None


def bar_at_minutes_after(bars, start_dt, trading_minutes):
    """
    실제 존재하는 1분봉 기준으로 start_dt 이후 N번째 봉을 사용.
    N=5이면 진입 이후 실제 5개 분봉이 지난 시점.
    """
    post = [b for b in bars if b["dt"] > start_dt]
    if not post:
        return None
    idx = trading_minutes - 1
    if idx < 0:
        idx = 0
    if idx >= len(post):
        return None
    return post[idx]


def horizon_bars(bars, candidate_date, buy1_dt):
    """
    이벤트 당일 + 다음 2개 거래일(D<3 해석)의 분봉만 사용.
    기간손절의 정확한 체결 규칙은 미확정이므로,
    미청산 포지션은 마지막 종가 MTM으로 별도 표기한다.
    """
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
    """
    TP/STOP 최초 도달을 1분봉으로 판정.
    같은 봉에서 TP와 STOP 모두 닿으면 AMBIGUOUS.
    """
    if not entry_dt or not entry_price:
        return {
            "status": "NOT_FILLED",
            "exit_dt": None,
            "exit_price": None,
            "return_pct": 0.0,
        }

    active = [b for b in bars if b["dt"] >= entry_dt]

    for b in active:
        hit_tp = b["high"] >= tp_price
        hit_stop = b["low"] <= stop_price

        if hit_tp and hit_stop:
            return {
                "status": "AMBIGUOUS",
                "exit_dt": b["dt"],
                "exit_price": None,
                "return_pct": None,
            }

        if hit_tp:
            return {
                "status": "TP",
                "exit_dt": b["dt"],
                "exit_price": tp_price,
                "return_pct": (tp_price / entry_price - 1.0) * 100.0,
            }

        if hit_stop:
            return {
                "status": "STOP",
                "exit_dt": b["dt"],
                "exit_price": stop_price,
                "return_pct": (stop_price / entry_price - 1.0) * 100.0,
            }

    if active:
        last = active[-1]
        return {
            "status": "MTM_END_D2",
            "exit_dt": last["dt"],
            "exit_price": last["close"],
            "return_pct": (last["close"] / entry_price - 1.0) * 100.0,
        }

    return {
        "status": "NO_DATA",
        "exit_dt": None,
        "exit_price": None,
        "return_pct": None,
    }


def weighted_return(r1, r2, second_filled):
    if r1 is None:
        return None

    total = TRANCHE1_WEIGHT * r1

    if second_filled:
        if r2 is None:
            return None
        total += TRANCHE2_WEIGHT * r2

    return total


def baseline_sim(row, bars):
    buy1_dt = parse_dt(row.get("buy1_time"))
    buy2_dt = parse_dt(row.get("buy2_time"))
    buy1 = num(row.get("buy1_price"))
    buy2 = num(row.get("buy2_price"))
    stop = num(row.get("stop70_price"))

    if not buy1_dt or not buy1 or not stop:
        return None

    hb = horizon_bars(bars, str(row.get("date", "")).strip(), buy1_dt)
    if not hb:
        return None

    t1 = simulate_tranche(
        hb,
        buy1_dt,
        buy1,
        buy1 * 1.04,
        stop
    )

    second_filled = bool(buy2_dt and buy2)

    t2 = {
        "status": "NOT_FILLED",
        "return_pct": 0.0,
        "exit_dt": None,
        "exit_price": None,
    }

    if second_filled:
        t2 = simulate_tranche(
            hb,
            buy2_dt,
            buy2,
            buy2 * 1.04,
            stop
        )

    result = weighted_return(
        t1["return_pct"],
        t2["return_pct"],
        second_filled
    )

    return {
        "return_pct": result,
        "t1": t1,
        "t2": t2,
        "second_filled": second_filled,
    }


def defensive_exit_return(row, bars, mode):
    """
    연구용 방어 시나리오.
    원문 RS3 규칙이 아님.

    EARLY_CONFIRM:
      3분 위험 AND 5분 위험 -> 5분 시점 1차 전량 청산, 2차 취소.

    STAGE2_DEFENSE:
      3분 OR 5분 위험 + Stage2 위험 -> 61.8 도달 시
      1차 청산, 2차 매수 취소.

    HYBRID:
      EARLY_CONFIRM 우선, 아니면 STAGE2_DEFENSE 적용.
    """
    buy1_dt = parse_dt(row.get("buy1_time"))
    buy1 = num(row.get("buy1_price"))
    buy2_dt = parse_dt(row.get("buy2_time"))
    buy2 = num(row.get("buy2_price"))

    if not buy1_dt or not buy1:
        return None, "NO_BUY1"

    e3 = early_3m(row)
    e5, _ = early_5m(row)
    s2 = stage2(row)

    if mode in ("EARLY_CONFIRM", "HYBRID") and e3 and e5:
        b5 = bar_at_minutes_after(bars, buy1_dt, 5)
        if not b5:
            return None, "NO_5M_BAR"

        r = (b5["close"] / buy1 - 1.0) * 100.0
        return TRANCHE1_WEIGHT * r, "EXIT_5M_CANCEL_BUY2"

    if mode in ("STAGE2_DEFENSE", "HYBRID"):
        if (e3 or e5) and s2 is True and buy2_dt and buy2:
            # 61.8선 도달시점에서 1차만 청산하고 2차 신규매수는 취소.
            r = (buy2 / buy1 - 1.0) * 100.0
            return TRANCHE1_WEIGHT * r, "EXIT_AT_618_CANCEL_BUY2"

    return None, "NO_ACTION"


def calc_mdd(returns):
    """
    각 거래가 시간순으로 1회씩 순차 반영된다고 가정한
    연구용 event-equity MDD. 동시보유/현금비중은 반영하지 않음.
    """
    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    for r in returns:
        equity *= (1.0 + r / 100.0)
        if equity > peak:
            peak = equity
        dd = equity / peak - 1.0
        if dd < max_dd:
            max_dd = dd

    return max_dd * 100.0, equity


def summarize_scenario(case_rows, scenario):
    vals = [
        r[f"{scenario}_return_pct"]
        for r in case_rows
        if r[f"{scenario}_return_pct"] is not None
    ]

    if not vals:
        return None

    wins = sum(1 for x in vals if x > 0)
    losses = sum(1 for x in vals if x < 0)
    zero = len(vals) - wins - losses

    avg = sum(vals) / len(vals)
    total_simple = sum(vals)
    mdd, final_equity = calc_mdd(vals)

    return {
        "scenario": scenario,
        "count": len(vals),
        "wins": wins,
        "losses": losses,
        "flat": zero,
        "win_rate_pct": pct(wins, len(vals)),
        "avg_return_pct": round(avg, 4),
        "simple_sum_return_pct": round(total_simple, 4),
        "event_compound_return_pct": round((final_equity - 1.0) * 100.0, 4),
        "event_mdd_pct": round(mdd, 4),
    }


def main():
    print("=" * 86)
    print("Reverse SPES - RS3 위험관리 손익 시뮬레이션 v1")
    print("원문판 baseline vs 연구용 방어 시나리오 비교")
    print("=" * 86)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    if not os.path.isdir(CACHE_DIR):
        print(f"[ERROR] minute_cache 없음: {CACHE_DIR}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # A+B vs C 108건만 primary P&L 비교.
    clean = [r for r in rows if clean_class(r) is not None]
    clean.sort(
        key=lambda r: (
            parse_date(r.get("date")),
            str(r.get("stock_code", ""))
        )
    )

    cache_by_code = {}
    case_rows = []
    errors = []

    print(f"입력 전체: {len(rows)}건")
    print(f"Primary 표본(A+B vs C): {len(clean)}건")
    print()
    print("연구용 자금가정: 1차 50% + 2차 50%")
    print("※ 강의 원문에 매수 비중이 명시되지 않아 비교용으로만 사용")
    print()

    for i, row in enumerate(clean, start=1):
        code = normalize_code(row.get("stock_code"))

        if code not in cache_by_code:
            cache_by_code[code] = load_cache(code)

        bars = cache_by_code[code]

        if not bars:
            errors.append({
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "date": row.get("date", ""),
                "error": "minute_cache 없음",
            })
            continue

        base = baseline_sim(row, bars)

        if not base or base["return_pct"] is None:
            errors.append({
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "date": row.get("date", ""),
                "error": "baseline 계산불가/AMBIGUOUS 포함",
            })
            continue

        early_ret, early_action = defensive_exit_return(
            row, bars, "EARLY_CONFIRM"
        )
        stage2_ret, stage2_action = defensive_exit_return(
            row, bars, "STAGE2_DEFENSE"
        )
        hybrid_ret, hybrid_action = defensive_exit_return(
            row, bars, "HYBRID"
        )

        base_ret = base["return_pct"]

        if early_ret is None:
            early_ret = base_ret
        if stage2_ret is None:
            stage2_ret = base_ret
        if hybrid_ret is None:
            hybrid_ret = base_ret

        e5, score5 = early_5m(row)

        case_rows.append({
            "stock_code": code,
            "stock_name": row.get("stock_name", ""),
            "date": row.get("date", ""),
            "path_group": row.get("path_group", ""),
            "class": clean_class(row),
            "early_3m": int(early_3m(row)),
            "early_5m": int(e5),
            "risk_score_5m": score5,
            "stage2_risk": "" if stage2(row) is None else int(stage2(row)),
            "baseline_t1_status": base["t1"]["status"],
            "baseline_t2_status": base["t2"]["status"],
            "baseline_second_filled": int(base["second_filled"]),
            "BASELINE_return_pct": round(base_ret, 4),
            "EARLY_CONFIRM_return_pct": round(early_ret, 4),
            "EARLY_CONFIRM_action": early_action,
            "STAGE2_DEFENSE_return_pct": round(stage2_ret, 4),
            "STAGE2_DEFENSE_action": stage2_action,
            "HYBRID_return_pct": round(hybrid_ret, 4),
            "HYBRID_action": hybrid_action,
            "EARLY_minus_BASE_pp": round(early_ret - base_ret, 4),
            "STAGE2_minus_BASE_pp": round(stage2_ret - base_ret, 4),
            "HYBRID_minus_BASE_pp": round(hybrid_ret - base_ret, 4),
        })

    if errors:
        with open(ERROR_FILE, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["stock_code", "stock_name", "date", "error"]
            )
            w.writeheader()
            w.writerows(errors)

    if not case_rows:
        print("[ERROR] 계산 가능한 케이스가 없습니다.")
        sys.exit(1)

    case_fields = list(case_rows[0].keys())
    with open(CASE_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=case_fields)
        w.writeheader()
        w.writerows(case_rows)

    summaries = []
    for scenario in (
        "BASELINE",
        "EARLY_CONFIRM",
        "STAGE2_DEFENSE",
        "HYBRID",
    ):
        s = summarize_scenario(case_rows, scenario)
        if s:
            summaries.append(s)

    # 손절 C와 성공 A+B에 끼친 영향도 별도 계산
    for s in summaries:
        scenario = s["scenario"]

        succ = [
            r for r in case_rows
            if r["class"] == "SUCCESS"
            and r[f"{scenario}_return_pct"] is not None
        ]
        fail = [
            r for r in case_rows
            if r["class"] == "FAIL"
            and r[f"{scenario}_return_pct"] is not None
        ]

        s["success_group_avg_return_pct"] = round(
            sum(r[f"{scenario}_return_pct"] for r in succ) / len(succ), 4
        ) if succ else ""

        s["fail_group_avg_return_pct"] = round(
            sum(r[f"{scenario}_return_pct"] for r in fail) / len(fail), 4
        ) if fail else ""

        if scenario != "BASELINE":
            acted = [
                r for r in case_rows
                if r[f"{scenario}_action"] != "NO_ACTION"
            ]
            s["action_count"] = len(acted)

            harmed_success = sum(
                1 for r in acted
                if r["class"] == "SUCCESS"
                and r[f"{scenario}_return_pct"] < r["BASELINE_return_pct"]
            )
            helped_fail = sum(
                1 for r in acted
                if r["class"] == "FAIL"
                and r[f"{scenario}_return_pct"] > r["BASELINE_return_pct"]
            )

            s["successful_cases_harmed_count"] = harmed_success
            s["failed_cases_helped_count"] = helped_fail
        else:
            s["action_count"] = 0
            s["successful_cases_harmed_count"] = 0
            s["failed_cases_helped_count"] = 0

    summary_fields = [
        "scenario",
        "count",
        "wins",
        "losses",
        "flat",
        "win_rate_pct",
        "avg_return_pct",
        "simple_sum_return_pct",
        "event_compound_return_pct",
        "event_mdd_pct",
        "success_group_avg_return_pct",
        "fail_group_avg_return_pct",
        "action_count",
        "successful_cases_harmed_count",
        "failed_cases_helped_count",
    ]

    with open(SUMMARY_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        for s in summaries:
            w.writerow({k: s.get(k, "") for k in summary_fields})

    print("=" * 86)
    print("손익 시뮬레이션 완료")
    print(f"계산 성공: {len(case_rows)}건")
    print(f"계산 제외/오류: {len(errors)}건")
    print(f"케이스 결과: {CASE_FILE}")
    print(f"요약 결과: {SUMMARY_FILE}")
    if errors:
        print(f"오류 결과: {ERROR_FILE}")

    print()
    print("주의:")
    print("- 1차/2차 50:50 비중은 강의 원문이 아니라 연구용 비교가정")
    print("- 미청산은 D+2 마지막 종가 MTM이며 원문 기간손절 확정규칙이 아님")
    print("- same-minute TP/STOP ambiguity는 계산에서 제외")
    print("- event MDD는 거래를 날짜순 1회씩 연속 적용한 연구용 지표")
    print("- 실제 동시보유/수수료/세금/슬리피지는 아직 미반영")
    print("- 개선안이 baseline보다 좋아도 즉시 원문판에 편입하지 않음")
    print("=" * 86)


if __name__ == "__main__":
    main()

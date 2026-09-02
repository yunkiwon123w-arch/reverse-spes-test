import csv
import glob
import os
import sys
from datetime import datetime

CACHE_DIR = "minute_cache"
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

OUTPUT_CASES = os.path.join(
    CACHE_DIR, f"rs3_618_rebound_defense_cases_v1_{RUN_TAG}.csv"
)
OUTPUT_SUMMARY = os.path.join(
    CACHE_DIR, f"rs3_618_rebound_defense_summary_v1_{RUN_TAG}.csv"
)
OUTPUT_ERRORS = os.path.join(
    CACHE_DIR, f"rs3_618_rebound_defense_errors_v1_{RUN_TAG}.csv"
)

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"

# 원문/기존 STAGE2 조건 고정
# 연구안: 61.8 도달 후 3분 또는 5분 반등 확인 후 방어
# NOTE: 이 연구안은 원문 RS3 규칙이 아님.


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

    return score >= 4, score


def stage2_risk(row):
    mins = num(row.get("trading_minutes_buy1_to_buy2"))
    vol = num(row.get("vol_50_to_618_avg_vs_pre30"))
    if mins is None or vol is None:
        return None
    return mins <= 5 or vol >= 1.0


def is_stage2_acted(row):
    e3 = early_risk_3m(row)
    e5, _ = early_risk_5m(row)
    s2 = stage2_risk(row)
    buy2_dt = parse_dt(row.get("buy2_time"))
    return (e3 or e5) and s2 is True and buy2_dt is not None


def clean_class(row):
    g = str(row.get("path_group", "")).strip()
    if g in SUCCESS_GROUPS:
        return "SUCCESS"
    if g == FAIL_GROUP:
        return "FAIL"
    return None


def post_bars_from_pivot(bars, pivot_dt, n):
    idx = None
    for i, b in enumerate(bars):
        if b["dt"] >= pivot_dt:
            idx = i
            break
    if idx is None:
        return []
    return bars[idx:min(len(bars), idx + n)]


def defense_return_at_price(buy1_price, exit_price):
    # 연구용 1차 50% 기준. 기존 PnL 시뮬레이션과 동일 가정.
    return 0.5 * ((exit_price / buy1_price) - 1.0) * 100.0


def classify_rebound(post, buy1_price, buy2_price):
    """
    임계값 최적화 금지 원칙을 지키기 위해
    '회복 확인'은 단순하고 해석 가능한 조건만 사용:
    - 해당 관찰창 내 고가가 50선과 61.8선 거리의 50% 이상 회복
    OR
    - 마지막 종가가 61.8선 대비 +1.0% 이상

    둘 다 연구용 고정 가정이며 원문 규칙 아님.
    """
    if not post:
        return None, None, None

    max_high = max(b["high"] for b in post)
    last_close = post[-1]["close"]

    denom = buy1_price - buy2_price
    recovery_pct = None
    if denom > 0:
        recovery_pct = (max_high - buy2_price) / denom * 100.0

    close_pct = (last_close / buy2_price - 1.0) * 100.0

    recovered = (
        (recovery_pct is not None and recovery_pct >= 50.0)
        or close_pct >= 1.0
    )
    return recovered, recovery_pct, close_pct


def simulate_variant(row, bars, minutes):
    buy1_dt = parse_dt(row.get("buy1_time"))
    buy2_dt = parse_dt(row.get("buy2_time"))
    buy1 = num(row.get("buy1_price"))
    buy2 = num(row.get("buy2_price"))
    baseline = num(row.get("BASELINE_return_pct"))

    if not all([buy1_dt, buy2_dt, buy1, buy2]) or baseline is None:
        return None

    post = post_bars_from_pivot(bars, buy2_dt, minutes)
    if not post:
        return None

    recovered, recovery_pct, close_pct = classify_rebound(
        post, buy1, buy2
    )

    if recovered:
        # 성공 가능성을 살리기 위해 baseline 유지
        return {
            "action": f"WAIT_{minutes}M_KEEP_BASELINE",
            "return_pct": baseline,
            "recovered": 1,
            "recovery_pct": recovery_pct,
            "close_pct": close_pct,
            "decision_price": post[-1]["close"],
            "decision_time": post[-1]["dt"].strftime("%Y%m%d%H%M%S"),
        }

    # 회복 실패 시 관찰창 마지막 종가에서 1차 방어, 2차 취소
    exit_price = post[-1]["close"]
    ret = defense_return_at_price(buy1, exit_price)
    return {
        "action": f"EXIT_AFTER_{minutes}M_NO_RECOVERY",
        "return_pct": ret,
        "recovered": 0,
        "recovery_pct": recovery_pct,
        "close_pct": close_pct,
        "decision_price": exit_price,
        "decision_time": post[-1]["dt"].strftime("%Y%m%d%H%M%S"),
    }


def mdd(returns):
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for r in returns:
        equity *= 1.0 + r / 100.0
        peak = max(peak, equity)
        dd = equity / peak - 1.0
        worst = min(worst, dd)
    return worst * 100.0


def summarize(rows, scenario_col):
    vals = [num(r.get(scenario_col)) for r in rows]
    vals = [v for v in vals if v is not None]
    wins = sum(v > 0 for v in vals)
    losses = sum(v < 0 for v in vals)

    return {
        "count": len(vals),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": pct(wins, len(vals)),
        "avg_return_pct": round(sum(vals)/len(vals), 4) if vals else "",
        "simple_sum_return_pct": round(sum(vals), 4) if vals else "",
        "event_mdd_pct": round(mdd(vals), 4) if vals else "",
    }


def main():
    print("=" * 88)
    print("Reverse SPES - RS3 61.8 반등확인형 방어 검증 v1")
    print("기존 STAGE2 즉시방어 vs 3분/5분 반등확인 후 방어 비교")
    print("=" * 88)

    input_file = find_latest_corrected_file()
    if not input_file:
        print("[ERROR] 교정 데이터 파일을 찾지 못했습니다.")
        sys.exit(1)

    pnl_candidates = glob.glob(
        os.path.join(CACHE_DIR, "rs3_risk_pnl_cases_v1_*.csv")
    )
    if not pnl_candidates:
        print("[ERROR] 기존 PnL 케이스 파일을 찾지 못했습니다.")
        sys.exit(1)

    pnl_file = max(pnl_candidates, key=os.path.getmtime)

    print(f"교정 입력: {input_file}")
    print(f"PnL 입력: {pnl_file}")

    with open(input_file, "r", encoding="utf-8-sig", newline="") as f:
        corrected = list(csv.DictReader(f))

    with open(pnl_file, "r", encoding="utf-8-sig", newline="") as f:
        pnl_rows = list(csv.DictReader(f))

    pnl_map = {
        (normalize_code(r.get("stock_code")), str(r.get("date", "")).strip()): r
        for r in pnl_rows
    }

    merged = []
    for r in corrected:
        key = (
            normalize_code(r.get("stock_code")),
            str(r.get("date", "")).strip()
        )
        p = pnl_map.get(key)
        if not p:
            continue
        x = dict(r)
        x.update({
            "BASELINE_return_pct": p.get("BASELINE_return_pct", ""),
            "STAGE2_DEFENSE_return_pct": p.get(
                "STAGE2_DEFENSE_return_pct", ""
            ),
            "STAGE2_DEFENSE_action": p.get(
                "STAGE2_DEFENSE_action", ""
            ),
        })
        merged.append(x)

    acted = [r for r in merged if is_stage2_acted(r)]

    print(f"STAGE2 개입 대상: {len(acted)}건")
    print(
        f"실제 C: {sum(clean_class(r) == 'FAIL' for r in acted)}건 / "
        f"성공 A+B: {sum(clean_class(r) == 'SUCCESS' for r in acted)}건"
    )
    print()

    cache_map = {}
    cases = []
    errors = []

    for r in acted:
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

        v3 = simulate_variant(r, bars, 3)
        v5 = simulate_variant(r, bars, 5)

        if not v3 or not v5:
            errors.append({
                "stock_code": code,
                "stock_name": r.get("stock_name", ""),
                "date": r.get("date", ""),
                "error": "3분/5분 반등확인 계산 불가",
            })
            continue

        base = num(r.get("BASELINE_return_pct"))
        st2 = num(r.get("STAGE2_DEFENSE_return_pct"))

        cases.append({
            "stock_code": code,
            "stock_name": r.get("stock_name", ""),
            "date": r.get("date", ""),
            "path_group": r.get("path_group", ""),
            "class": clean_class(r),
            "BASELINE_return_pct": base,
            "STAGE2_DEFENSE_return_pct": st2,
            "STAGE2_DEFENSE_action": r.get("STAGE2_DEFENSE_action", ""),
            "WAIT3_return_pct": round(v3["return_pct"], 4),
            "WAIT3_action": v3["action"],
            "WAIT3_recovered": v3["recovered"],
            "WAIT3_recovery_pct": (
                round(v3["recovery_pct"], 4)
                if v3["recovery_pct"] is not None else ""
            ),
            "WAIT3_close_pct": round(v3["close_pct"], 4),
            "WAIT3_decision_price": v3["decision_price"],
            "WAIT3_decision_time": v3["decision_time"],
            "WAIT5_return_pct": round(v5["return_pct"], 4),
            "WAIT5_action": v5["action"],
            "WAIT5_recovered": v5["recovered"],
            "WAIT5_recovery_pct": (
                round(v5["recovery_pct"], 4)
                if v5["recovery_pct"] is not None else ""
            ),
            "WAIT5_close_pct": round(v5["close_pct"], 4),
            "WAIT5_decision_price": v5["decision_price"],
            "WAIT5_decision_time": v5["decision_time"],
            "WAIT3_minus_STAGE2_pp": round(
                v3["return_pct"] - st2, 4
            ) if st2 is not None else "",
            "WAIT5_minus_STAGE2_pp": round(
                v5["return_pct"] - st2, 4
            ) if st2 is not None else "",
            "WAIT3_minus_BASE_pp": round(
                v3["return_pct"] - base, 4
            ) if base is not None else "",
            "WAIT5_minus_BASE_pp": round(
                v5["return_pct"] - base, 4
            ) if base is not None else "",
        })

    if errors:
        with open(OUTPUT_ERRORS, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["stock_code", "stock_name", "date", "error"]
            )
            w.writeheader()
            w.writerows(errors)

    if not cases:
        print("[ERROR] 계산 가능한 케이스가 없습니다.")
        sys.exit(1)

    case_fields = list(cases[0].keys())
    with open(OUTPUT_CASES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=case_fields)
        w.writeheader()
        w.writerows(cases)

    # STAGE2 개입 13건 subset 내부 비교
    summary_rows = []

    scenario_map = {
        "BASELINE": "BASELINE_return_pct",
        "STAGE2_DEFENSE": "STAGE2_DEFENSE_return_pct",
        "WAIT3_DEFENSE": "WAIT3_return_pct",
        "WAIT5_DEFENSE": "WAIT5_return_pct",
    }

    for scenario, col in scenario_map.items():
        s = summarize(cases, col)

        fail_rows = [r for r in cases if r["class"] == "FAIL"]
        succ_rows = [r for r in cases if r["class"] == "SUCCESS"]

        fail_vals = [num(r.get(col)) for r in fail_rows]
        fail_vals = [v for v in fail_vals if v is not None]
        succ_vals = [num(r.get(col)) for r in succ_rows]
        succ_vals = [v for v in succ_vals if v is not None]

        summary_rows.append({
            "scenario": scenario,
            **s,
            "fail_group_count": len(fail_vals),
            "fail_group_avg_return_pct": (
                round(sum(fail_vals)/len(fail_vals), 4)
                if fail_vals else ""
            ),
            "success_group_count": len(succ_vals),
            "success_group_avg_return_pct": (
                round(sum(succ_vals)/len(succ_vals), 4)
                if succ_vals else ""
            ),
        })

    summary_fields = list(summary_rows[0].keys())
    with open(OUTPUT_SUMMARY, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary_rows)

    print("=" * 88)
    print("61.8 반등확인형 방어 검증 완료")
    print(f"케이스: {OUTPUT_CASES}")
    print(f"요약: {OUTPUT_SUMMARY}")
    print(f"오류: {len(errors)}건")
    if errors:
        print(f"오류파일: {OUTPUT_ERRORS}")
    print()
    print("주의:")
    print("- WAIT3/WAIT5는 원문 RS3 규칙이 아닌 연구안")
    print("- 회복확인 기준은 50선-61.8선 거리 50% 회복 OR 61.8 대비 종가 +1%")
    print("- 임계값은 이 13건에 맞춰 최적화하지 않음")
    print("- 회복 확인 시 baseline 유지, 실패 시 관찰창 마지막 종가에서 방어")
    print("- 1차/2차 50:50은 기존 연구용 비교가정 유지")
    print("- 결과가 좋아도 즉시 원문판에 편입 금지")
    print("=" * 88)


if __name__ == "__main__":
    main()

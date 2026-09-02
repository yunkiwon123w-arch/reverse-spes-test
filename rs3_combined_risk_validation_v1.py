import csv
import math
import os
import sys
from datetime import datetime

INPUT_FILE = "rs3_structure_analysis_v2.csv"
OUTPUT_DIR = "minute_cache"

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_SUMMARY = os.path.join(
    OUTPUT_DIR, f"rs3_combined_risk_summary_v1_{RUN_TAG}.csv"
)
OUTPUT_RULES = os.path.join(
    OUTPUT_DIR, f"rs3_combined_risk_rules_v1_{RUN_TAG}.csv"
)
OUTPUT_CASES = os.path.join(
    OUTPUT_DIR, f"rs3_combined_risk_cases_v1_{RUN_TAG}.csv"
)

DEV_RATIO = 0.70

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"


def num(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def parse_date(v):
    return datetime.strptime(str(v).strip(), "%Y%m%d")


def pct(n, d):
    return round(n / d * 100.0, 2) if d else ""


def median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    m = n // 2
    if n % 2:
        return vals[m]
    return (vals[m - 1] + vals[m]) / 2.0


def classify_base(row):
    g = str(row.get("path_group", "")).strip()
    if g in SUCCESS_GROUPS:
        return 0
    if g == FAIL_GROUP:
        return 1
    return None


def early_risk_3m(row):
    """
    연구용 3분 조기경보.
    원문 RS3 조건이 아님.
    """
    low3 = num(row.get("w3_low_pct"))
    down3 = num(row.get("w3_down_ratio"))
    if low3 is None or down3 is None:
        return False
    return low3 <= -1.5 and down3 >= 0.65


def early_risk_5m(row):
    """
    연구용 5분 확인 신호.
    """
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


def stage2_618_risk(row):
    """
    61.8선 실제 도달 케이스에서만 평가.
    - 50->61.8 도달 속도
    - 50->61.8 평균거래량 / 진입전30분 평균
    원문 규칙이 아닌 연구용 신호.
    """
    minutes = num(row.get("minutes_buy1_to_buy2"))
    vol_ratio = num(row.get("vol_50_to_618_avg_vs_pre30"))

    if minutes is None or vol_ratio is None:
        return None, ""

    # 넓은 후보 구간. 아래 규칙검증에서 세부 임계값을 따로 검증한다.
    fast = minutes <= 5
    persistent_volume = vol_ratio >= 1.0

    if fast and persistent_volume:
        return True, "FAST_618_AND_VOLUME"
    if fast:
        return True, "FAST_618"
    if persistent_volume:
        return True, "VOLUME_PERSIST"
    return False, "DRY_SLOW"


def stage3_70_risk(row):
    """
    61.8 이후 70선 구간에서 거래량이 계속되는지 확인.
    해당 구간이 존재하는 케이스에만 평가.
    """
    minutes = num(row.get("minutes_buy2_to_stop70"))
    vol_ratio = num(row.get("vol_618_to_70_avg_vs_pre30"))

    if minutes is None or vol_ratio is None:
        return None, ""

    fast = minutes <= 5
    persistent_volume = vol_ratio >= 0.75

    if fast and persistent_volume:
        return True, "FAST_70_AND_VOLUME"
    if fast:
        return True, "FAST_70"
    if persistent_volume:
        return True, "VOLUME_PERSIST"
    return False, "DRY_SLOW"


def evaluate(rows, predicate):
    hit = [r for r in rows if predicate(r)]
    fail = sum(r["_fail"] for r in hit)
    return {
        "support": len(hit),
        "fail": fail,
        "success": len(hit) - fail,
        "fail_rate": fail / len(hit) if hit else None,
    }


def write_rows(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main():
    print("=" * 82)
    print("Reverse SPES - RS3 결합 위험상태 검증 v1")
    print("원문 RS3 규칙 변경 없음 / 3분·5분 + 61.8선 속도·거래량 결합 연구")
    print("=" * 82)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    if not os.path.isdir(OUTPUT_DIR):
        print(f"[ERROR] 결과 저장 폴더 없음: {OUTPUT_DIR}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    clean = []
    excluded = []

    for r in rows:
        c = classify_base(r)
        if c is None:
            excluded.append(r)
            continue
        r["_fail"] = c
        clean.append(r)

    clean.sort(key=lambda r: (parse_date(r["date"]), str(r.get("stock_code", ""))))

    split = int(len(clean) * DEV_RATIO)
    dev = clean[:split]
    hold = clean[split:]

    print(f"전체 입력: {len(rows)}건")
    print(f"Clean 표본(A+B vs C): {len(clean)}건")
    print(f"제외(D/AMB): {len(excluded)}건")
    print(f"개발구간: {len(dev)}건 / 손절 {sum(r['_fail'] for r in dev)}건")
    print(f"검증구간: {len(hold)}건 / 손절 {sum(r['_fail'] for r in hold)}건")
    print()

    # ------------------------------------------------------------
    # 1) 케이스별 단계 상태 생성
    # ------------------------------------------------------------
    case_rows = []

    for r in clean:
        e3 = early_risk_3m(r)
        e5, score5 = early_risk_5m(r)
        s2, s2_label = stage2_618_risk(r)
        s3, s3_label = stage3_70_risk(r)

        combined_score = 0
        if e3:
            combined_score += 1
        if e5:
            combined_score += 1
        if s2 is True:
            combined_score += 1
        if s3 is True:
            combined_score += 1

        if combined_score >= 3:
            state = "HIGH_RISK"
        elif combined_score == 2:
            state = "WATCH"
        else:
            state = "NORMAL"

        case_rows.append({
            "stock_code": r.get("stock_code", ""),
            "stock_name": r.get("stock_name", ""),
            "date": r.get("date", ""),
            "path_group": r.get("path_group", ""),
            "actual_fail": r["_fail"],
            "early_risk_3m": int(e3),
            "risk_score_5m": score5,
            "early_risk_5m": int(e5),
            "minutes_buy1_to_buy2": r.get("minutes_buy1_to_buy2", ""),
            "vol_50_to_618_avg_vs_pre30": r.get("vol_50_to_618_avg_vs_pre30", ""),
            "stage2_618_risk": "" if s2 is None else int(s2),
            "stage2_618_label": s2_label,
            "minutes_buy2_to_stop70": r.get("minutes_buy2_to_stop70", ""),
            "vol_618_to_70_avg_vs_pre30": r.get("vol_618_to_70_avg_vs_pre30", ""),
            "stage3_70_risk": "" if s3 is None else int(s3),
            "stage3_70_label": s3_label,
            "combined_risk_score": combined_score,
            "combined_state": state,
        })

    case_fields = [
        "stock_code", "stock_name", "date", "path_group", "actual_fail",
        "early_risk_3m", "risk_score_5m", "early_risk_5m",
        "minutes_buy1_to_buy2", "vol_50_to_618_avg_vs_pre30",
        "stage2_618_risk", "stage2_618_label",
        "minutes_buy2_to_stop70", "vol_618_to_70_avg_vs_pre30",
        "stage3_70_risk", "stage3_70_label",
        "combined_risk_score", "combined_state",
    ]
    write_rows(OUTPUT_CASES, case_fields, case_rows)

    # ------------------------------------------------------------
    # 2) 고정 조합 시나리오 검증
    # ------------------------------------------------------------
    scenarios = [
        ("3M_ONLY", lambda r: early_risk_3m(r)),
        ("5M_ONLY", lambda r: early_risk_5m(r)[0]),
        ("3M_AND_5M", lambda r: early_risk_3m(r) and early_risk_5m(r)[0]),
        ("3M_OR_5M", lambda r: early_risk_3m(r) or early_risk_5m(r)[0]),
        (
            "3M_AND_STAGE2",
            lambda r: early_risk_3m(r) and stage2_618_risk(r)[0] is True
        ),
        (
            "5M_AND_STAGE2",
            lambda r: early_risk_5m(r)[0] and stage2_618_risk(r)[0] is True
        ),
        (
            "3M_5M_STAGE2_ANY2",
            lambda r: (
                int(early_risk_3m(r))
                + int(early_risk_5m(r)[0])
                + int(stage2_618_risk(r)[0] is True)
            ) >= 2
        ),
        (
            "3M_5M_STAGE2_ALL3",
            lambda r: (
                early_risk_3m(r)
                and early_risk_5m(r)[0]
                and stage2_618_risk(r)[0] is True
            )
        ),
        (
            "STAGE2_AND_STAGE3",
            lambda r: (
                stage2_618_risk(r)[0] is True
                and stage3_70_risk(r)[0] is True
            )
        ),
    ]

    rule_rows = []
    dev_base = sum(r["_fail"] for r in dev) / len(dev)
    hold_base = sum(r["_fail"] for r in hold) / len(hold)

    for name, pred in scenarios:
        de = evaluate(dev, pred)
        ho = evaluate(hold, pred)
        allv = evaluate(clean, pred)

        rule_rows.append({
            "scenario": name,
            "all_support": allv["support"],
            "all_fail": allv["fail"],
            "all_fail_rate_pct": pct(allv["fail"], allv["support"]),
            "dev_support": de["support"],
            "dev_fail": de["fail"],
            "dev_fail_rate_pct": pct(de["fail"], de["support"]),
            "dev_baseline_fail_rate_pct": round(dev_base * 100, 2),
            "dev_lift_pp": (
                round((de["fail_rate"] - dev_base) * 100, 2)
                if de["fail_rate"] is not None else ""
            ),
            "holdout_support": ho["support"],
            "holdout_fail": ho["fail"],
            "holdout_fail_rate_pct": pct(ho["fail"], ho["support"]),
            "holdout_baseline_fail_rate_pct": round(hold_base * 100, 2),
            "holdout_lift_pp": (
                round((ho["fail_rate"] - hold_base) * 100, 2)
                if ho["fail_rate"] is not None else ""
            ),
            "holdout_direction_same": (
                "Y"
                if ho["support"] >= 3
                and ho["fail_rate"] is not None
                and ho["fail_rate"] > hold_base
                else "N"
            ),
        })

    rule_fields = [
        "scenario",
        "all_support", "all_fail", "all_fail_rate_pct",
        "dev_support", "dev_fail", "dev_fail_rate_pct",
        "dev_baseline_fail_rate_pct", "dev_lift_pp",
        "holdout_support", "holdout_fail", "holdout_fail_rate_pct",
        "holdout_baseline_fail_rate_pct", "holdout_lift_pp",
        "holdout_direction_same",
    ]
    write_rows(OUTPUT_RULES, rule_fields, rule_rows)

    # ------------------------------------------------------------
    # 3) Stage 2 / Stage 3 연속변수 중앙값 요약
    # ------------------------------------------------------------
    summary_rows = []

    for label, subset in (
        ("SUCCESS", [r for r in clean if r["_fail"] == 0]),
        ("FAIL", [r for r in clean if r["_fail"] == 1]),
    ):
        buy2_rows = [
            r for r in subset
            if num(r.get("minutes_buy1_to_buy2")) is not None
            and num(r.get("vol_50_to_618_avg_vs_pre30")) is not None
        ]
        stop_rows = [
            r for r in subset
            if num(r.get("minutes_buy2_to_stop70")) is not None
            and num(r.get("vol_618_to_70_avg_vs_pre30")) is not None
        ]

        summary_rows.append({
            "group": label,
            "total_count": len(subset),
            "buy2_stage_count": len(buy2_rows),
            "buy1_to_buy2_minutes_median": (
                round(median([num(r["minutes_buy1_to_buy2"]) for r in buy2_rows]), 4)
                if buy2_rows else ""
            ),
            "vol_50_to_618_vs_pre30_median": (
                round(median([num(r["vol_50_to_618_avg_vs_pre30"]) for r in buy2_rows]), 4)
                if buy2_rows else ""
            ),
            "stage3_count": len(stop_rows),
            "buy2_to_stop70_minutes_median": (
                round(median([num(r["minutes_buy2_to_stop70"]) for r in stop_rows]), 4)
                if stop_rows else ""
            ),
            "vol_618_to_70_vs_pre30_median": (
                round(median([num(r["vol_618_to_70_avg_vs_pre30"]) for r in stop_rows]), 4)
                if stop_rows else ""
            ),
        })

    summary_fields = [
        "group", "total_count",
        "buy2_stage_count",
        "buy1_to_buy2_minutes_median",
        "vol_50_to_618_vs_pre30_median",
        "stage3_count",
        "buy2_to_stop70_minutes_median",
        "vol_618_to_70_vs_pre30_median",
    ]
    write_rows(OUTPUT_SUMMARY, summary_fields, summary_rows)

    print("=" * 82)
    print("결합 위험상태 검증 완료")
    print(f"요약: {OUTPUT_SUMMARY}")
    print(f"규칙 검증: {OUTPUT_RULES}")
    print(f"케이스 결과: {OUTPUT_CASES}")
    print()
    print("주의:")
    print("- 원문 RS3 조건은 변경하지 않음")
    print("- 3분/5분 신호는 진입 후 관찰용")
    print("- 61.8 관련 신호는 실제 61.8선 도달 후에만 사용 가능")
    print("- 70선 관련 신호는 61.8 이후 구간에서만 사용 가능")
    print("- 후행 정보를 진입 전 필터로 사용하지 않음")
    print("- 홀드아웃 표본이 작으면 규칙 확정 금지")
    print("=" * 82)


if __name__ == "__main__":
    main()

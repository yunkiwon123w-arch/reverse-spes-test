import csv
import math
import os
import sys
from datetime import datetime

INPUT_FILE = "rs3_structure_analysis_v2.csv"
OUTPUT_STAGE_FILE = "rs3_risk_stage_summary_v1.csv"
OUTPUT_RULE_FILE = "rs3_risk_rule_validation_v1.csv"
OUTPUT_CASE_FILE = "rs3_risk_case_scores_v1.csv"

STAGES = (1, 3, 5, 10)
DEV_RATIO = 0.70
MIN_DEV_SUPPORT = 8

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"
EXCLUDED_GROUPS = {"D_NO_EXIT_WITHIN_WINDOW", "AMBIGUOUS"}


def f(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def parse_date(v):
    s = str(v or "").strip()
    return datetime.strptime(s, "%Y%m%d")


def pct(n, d):
    return round(n / d * 100.0, 2) if d else None


def median(values):
    vals = sorted(x for x in values if x is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def fmt(v, nd=4):
    if v is None:
        return ""
    return round(v, nd)


def summarize_group(rows, stage, fail_value):
    subset = [r for r in rows if r["_fail"] == fail_value]

    def col(name):
        return [f(r.get(name)) for r in subset]

    return {
        "count": len(subset),
        "high_med": median(col(f"w{stage}_high_pct")),
        "low_med": median(col(f"w{stage}_low_pct")),
        "close_med": median(col(f"w{stage}_close_pct")),
        "down_ratio_med": median(col(f"w{stage}_down_ratio")),
        "volume_vs_pre30_med": median(col(f"w{stage}_volume_avg_vs_pre30")),
    }


def condition_value(row, stage, feature, op, threshold):
    x = f(row.get(f"w{stage}_{feature}"))
    if x is None:
        return False
    if op == "<":
        return x < threshold
    if op == "<=":
        return x <= threshold
    if op == ">=":
        return x >= threshold
    if op == ">":
        return x > threshold
    return False


def rule_mask(row, stage, conditions):
    return all(
        condition_value(row, stage, feature, op, threshold)
        for feature, op, threshold in conditions
    )


def condition_text(stage, conditions):
    labels = {
        "high_pct": "고점반등%",
        "low_pct": "저점%",
        "close_pct": "종가%",
        "down_ratio": "하락봉거래량비중",
        "volume_avg_vs_pre30": "평균거래량/진입전30분",
    }
    parts = []
    for feature, op, threshold in conditions:
        parts.append(f"{stage}분 {labels[feature]} {op} {threshold}")
    return " AND ".join(parts)


def evaluate(rows, stage, conditions):
    hit = [r for r in rows if rule_mask(r, stage, conditions)]
    fail = sum(r["_fail"] for r in hit)
    success = len(hit) - fail
    return {
        "support": len(hit),
        "fail": fail,
        "success": success,
        "fail_rate": fail / len(hit) if hit else None,
    }


def make_candidates():
    high_thresholds = [0.5, 0.75, 1.0, 1.25, 1.5]
    low_thresholds = [-0.5, -0.75, -1.0, -1.25, -1.5, -2.0]
    close_thresholds = [0.0, -0.5, -1.0]
    down_thresholds = [0.55, 0.60, 0.65, 0.70, 0.75]
    vol_thresholds = [1.0, 1.25, 1.5, 2.0]

    rules = []

    # 단일 신호
    for t in high_thresholds:
        rules.append([("high_pct", "<", t)])
    for t in low_thresholds:
        rules.append([("low_pct", "<=", t)])
    for t in close_thresholds:
        rules.append([("close_pct", "<", t)])
    for t in down_thresholds:
        rules.append([("down_ratio", ">=", t)])
    for t in vol_thresholds:
        rules.append([("volume_avg_vs_pre30", ">=", t)])

    # 해석 가능한 2개 결합 신호
    for h in high_thresholds:
        for l in low_thresholds:
            rules.append([
                ("high_pct", "<", h),
                ("low_pct", "<=", l),
            ])

    for h in high_thresholds:
        for d in down_thresholds:
            rules.append([
                ("high_pct", "<", h),
                ("down_ratio", ">=", d),
            ])

    for l in low_thresholds:
        for d in down_thresholds:
            rules.append([
                ("low_pct", "<=", l),
                ("down_ratio", ">=", d),
            ])

    for c in close_thresholds:
        for d in down_thresholds:
            rules.append([
                ("close_pct", "<", c),
                ("down_ratio", ">=", d),
            ])

    for l in low_thresholds:
        for v in vol_thresholds:
            rules.append([
                ("low_pct", "<=", l),
                ("volume_avg_vs_pre30", ">=", v),
            ])

    return rules


def score_rule(dev_eval, dev_baseline):
    if not dev_eval["support"] or dev_eval["fail_rate"] is None:
        return -999
    lift = dev_eval["fail_rate"] - dev_baseline
    support_factor = min(dev_eval["support"] / 20.0, 1.0)
    return lift * (0.65 + 0.35 * support_factor)


def stage_case_score(row, stage):
    """
    연구용 점수.
    원문 RS3 조건이 아니며 매수/매도 규칙으로 사용하지 않는다.
    """
    score = 0
    high = f(row.get(f"w{stage}_high_pct"))
    low = f(row.get(f"w{stage}_low_pct"))
    close = f(row.get(f"w{stage}_close_pct"))
    down = f(row.get(f"w{stage}_down_ratio"))
    vol = f(row.get(f"w{stage}_volume_avg_vs_pre30"))

    if high is not None and high < 1.0:
        score += 1
    if low is not None and low <= -1.0:
        score += 1
    if close is not None and close < 0:
        score += 1
    if down is not None and down >= 0.70:
        score += 1
    if vol is not None and vol >= 1.25:
        score += 1

    return score


def main():
    print("=" * 78)
    print("Reverse SPES - RS3 실시간 위험단계 검증 v1")
    print("원문 RS3 규칙 변경 없음 / 연구용 후행 리스크 신호 검증")
    print("=" * 78)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as fobj:
        rows = list(csv.DictReader(fobj))

    clean = []
    excluded = []

    for r in rows:
        g = str(r.get("path_group", "")).strip()
        if g in SUCCESS_GROUPS:
            r["_fail"] = 0
            clean.append(r)
        elif g == FAIL_GROUP:
            r["_fail"] = 1
            clean.append(r)
        else:
            excluded.append(r)

    clean.sort(key=lambda r: (parse_date(r.get("date")), str(r.get("stock_code", ""))))

    split_idx = int(len(clean) * DEV_RATIO)
    dev = clean[:split_idx]
    holdout = clean[split_idx:]

    dev_fail = sum(r["_fail"] for r in dev)
    hold_fail = sum(r["_fail"] for r in holdout)
    dev_baseline = dev_fail / len(dev)
    hold_baseline = hold_fail / len(holdout)

    print(f"전체 입력: {len(rows)}건")
    print(f"Clean 비교 표본(A+B vs C): {len(clean)}건")
    print(f"제외(D/AMB 등): {len(excluded)}건")
    print(f"개발 구간: {len(dev)}건 / 손절 {dev_fail}건 / {pct(dev_fail, len(dev))}%")
    print(f"검증 구간: {len(holdout)}건 / 손절 {hold_fail}건 / {pct(hold_fail, len(holdout))}%")
    print()

    # 1) 단계별 중앙값 요약
    stage_fields = [
        "stage_min",
        "success_count", "fail_count",
        "success_high_median", "fail_high_median",
        "success_low_median", "fail_low_median",
        "success_close_median", "fail_close_median",
        "success_down_ratio_median", "fail_down_ratio_median",
        "success_volume_vs_pre30_median", "fail_volume_vs_pre30_median",
    ]

    with open(OUTPUT_STAGE_FILE, "w", encoding="utf-8-sig", newline="") as fobj:
        w = csv.DictWriter(fobj, fieldnames=stage_fields)
        w.writeheader()

        for stage in STAGES:
            s = summarize_group(clean, stage, 0)
            c = summarize_group(clean, stage, 1)

            w.writerow({
                "stage_min": stage,
                "success_count": s["count"],
                "fail_count": c["count"],
                "success_high_median": fmt(s["high_med"]),
                "fail_high_median": fmt(c["high_med"]),
                "success_low_median": fmt(s["low_med"]),
                "fail_low_median": fmt(c["low_med"]),
                "success_close_median": fmt(s["close_med"]),
                "fail_close_median": fmt(c["close_med"]),
                "success_down_ratio_median": fmt(s["down_ratio_med"]),
                "fail_down_ratio_median": fmt(c["down_ratio_med"]),
                "success_volume_vs_pre30_median": fmt(s["volume_vs_pre30_med"]),
                "fail_volume_vs_pre30_median": fmt(c["volume_vs_pre30_med"]),
            })

    # 2) 개발구간에서만 규칙 선정 → 홀드아웃은 평가 전용
    candidates = make_candidates()
    all_results = []

    for stage in STAGES:
        for conditions in candidates:
            de = evaluate(dev, stage, conditions)

            if de["support"] < MIN_DEV_SUPPORT:
                continue

            ho = evaluate(holdout, stage, conditions)

            row = {
                "stage_min": stage,
                "rule": condition_text(stage, conditions),
                "condition_count": len(conditions),
                "dev_support": de["support"],
                "dev_fail": de["fail"],
                "dev_success": de["success"],
                "dev_fail_rate_pct": pct(de["fail"], de["support"]),
                "dev_baseline_fail_rate_pct": pct(dev_fail, len(dev)),
                "dev_fail_rate_lift_pp": round(
                    (de["fail_rate"] - dev_baseline) * 100.0, 2
                ),
                "holdout_support": ho["support"],
                "holdout_fail": ho["fail"],
                "holdout_success": ho["success"],
                "holdout_fail_rate_pct": pct(ho["fail"], ho["support"]),
                "holdout_baseline_fail_rate_pct": pct(hold_fail, len(holdout)),
                "holdout_fail_rate_lift_pp": (
                    round((ho["fail_rate"] - hold_baseline) * 100.0, 2)
                    if ho["fail_rate"] is not None else ""
                ),
                "holdout_direction_same": (
                    "Y"
                    if ho["support"] >= 3
                    and ho["fail_rate"] is not None
                    and ho["fail_rate"] > hold_baseline
                    else "N"
                ),
                "_score": score_rule(de, dev_baseline),
            }
            all_results.append(row)

    all_results.sort(
        key=lambda r: (
            -r["_score"],
            -r["dev_support"],
            r["stage_min"],
            r["condition_count"],
        )
    )

    rule_fields = [
        "rank",
        "stage_min",
        "rule",
        "condition_count",
        "dev_support",
        "dev_fail",
        "dev_success",
        "dev_fail_rate_pct",
        "dev_baseline_fail_rate_pct",
        "dev_fail_rate_lift_pp",
        "holdout_support",
        "holdout_fail",
        "holdout_success",
        "holdout_fail_rate_pct",
        "holdout_baseline_fail_rate_pct",
        "holdout_fail_rate_lift_pp",
        "holdout_direction_same",
    ]

    with open(OUTPUT_RULE_FILE, "w", encoding="utf-8-sig", newline="") as fobj:
        w = csv.DictWriter(fobj, fieldnames=rule_fields)
        w.writeheader()

        for rank, r in enumerate(all_results, start=1):
            out = dict(r)
            out.pop("_score", None)
            out["rank"] = rank
            w.writerow({k: out.get(k, "") for k in rule_fields})

    # 3) 각 케이스 1/3/5/10분 연구용 위험점수
    base_fields = [
        "stock_code", "stock_name", "date", "path_group",
        "buy1_time", "buy1_price",
    ]
    case_fields = base_fields[:]
    for stage in STAGES:
        case_fields.extend([
            f"risk_score_{stage}m",
            f"w{stage}_high_pct",
            f"w{stage}_low_pct",
            f"w{stage}_close_pct",
            f"w{stage}_down_ratio",
            f"w{stage}_volume_avg_vs_pre30",
        ])

    with open(OUTPUT_CASE_FILE, "w", encoding="utf-8-sig", newline="") as fobj:
        w = csv.DictWriter(fobj, fieldnames=case_fields)
        w.writeheader()

        for r in clean:
            out = {k: r.get(k, "") for k in base_fields}

            for stage in STAGES:
                out[f"risk_score_{stage}m"] = stage_case_score(r, stage)
                for feature in (
                    "high_pct", "low_pct", "close_pct",
                    "down_ratio", "volume_avg_vs_pre30"
                ):
                    out[f"w{stage}_{feature}"] = r.get(
                        f"w{stage}_{feature}", ""
                    )

            w.writerow(out)

    print("=" * 78)
    print("검증 완료")
    print(f"단계 요약: {OUTPUT_STAGE_FILE}")
    print(f"개발/홀드아웃 규칙검증: {OUTPUT_RULE_FILE}")
    print(f"케이스별 위험점수: {OUTPUT_CASE_FILE}")
    print()
    print("주의:")
    print("- D_NO_EXIT_WITHIN_WINDOW / AMBIGUOUS는 주 비교에서 제외")
    print("- 임계값 선정은 개발구간만 사용")
    print("- 홀드아웃은 방향성 확인용이며 표본이 작으면 규칙 확정 금지")
    print("- 이 결과는 원문 RS3 매매조건이 아니라 개선판 연구자료")
    print("=" * 78)


if __name__ == "__main__":
    main()

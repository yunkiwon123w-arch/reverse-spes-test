import csv
import os
import sys
from datetime import datetime

INPUT_FILE = "rs3_structure_analysis_v2.csv"

RESULT_DIR = "minute_cache"
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

OUTPUT_STAGE_FILE = os.path.join(
    RESULT_DIR, f"rs3_risk_stage_summary_v1_1_{RUN_TAG}.csv"
)
OUTPUT_RULE_FILE = os.path.join(
    RESULT_DIR, f"rs3_risk_rule_validation_v1_1_{RUN_TAG}.csv"
)
OUTPUT_CASE_FILE = os.path.join(
    RESULT_DIR, f"rs3_risk_case_scores_v1_1_{RUN_TAG}.csv"
)

STAGES = (1, 3, 5, 10)
DEV_RATIO = 0.70
MIN_DEV_SUPPORT = 8

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"


def f(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def parse_date(v):
    return datetime.strptime(str(v or "").strip(), "%Y%m%d")


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
    # 연구용 점수. 원문 RS3 규칙이 아님.
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
    print("Reverse SPES - RS3 실시간 위험단계 검증 v1.2")
    print("원문 RS3 규칙 변경 없음 / 검증된 쓰기 가능 폴더 minute_cache에 결과 저장")
    print("=" * 78)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    # minute_cache는 앞선 캐시 구축에서 실제 쓰기 성공이 검증된 폴더다.
    if not os.path.isdir(RESULT_DIR):
        print(f"[ERROR] 쓰기 검증 폴더 없음: {RESULT_DIR}")
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

    clean.sort(
        key=lambda r: (
            parse_date(r.get("date")),
            str(r.get("stock_code", ""))
        )
    )

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
    print(
        f"개발 구간: {len(dev)}건 / 손절 {dev_fail}건 / "
        f"{pct(dev_fail, len(dev))}%"
    )
    print(
        f"검증 구간: {len(holdout)}건 / 손절 {hold_fail}건 / "
        f"{pct(hold_fail, len(holdout))}%"
    )
    print()

    stage_fields = [
        "stage_min",
        "success_count", "fail_count",
        "success_high_median", "fail_high_median",
        "success_low_median", "fail_low_median",
        "success_close_median", "fail_close_median",
        "success_down_ratio_median", "fail_down_ratio_median",
        "success_volume_vs_pre30_median", "fail_volume_vs_pre30_median",
    ]

    with open(
        OUTPUT_STAGE_FILE, "w", encoding="utf-8-sig", newline=""
    ) as fobj:
        writer = csv.DictWriter(fobj, fieldnames=stage_fields)
        writer.writeheader()

        for stage in STAGES:
            success = summarize_group(clean, stage, 0)
            fail = summarize_group(clean, stage, 1)

            writer.writerow({
                "stage_min": stage,
                "success_count": success["count"],
                "fail_count": fail["count"],
                "success_high_median": fmt(success["high_med"]),
                "fail_high_median": fmt(fail["high_med"]),
                "success_low_median": fmt(success["low_med"]),
                "fail_low_median": fmt(fail["low_med"]),
                "success_close_median": fmt(success["close_med"]),
                "fail_close_median": fmt(fail["close_med"]),
                "success_down_ratio_median": fmt(success["down_ratio_med"]),
                "fail_down_ratio_median": fmt(fail["down_ratio_med"]),
                "success_volume_vs_pre30_median": fmt(
                    success["volume_vs_pre30_med"]
                ),
                "fail_volume_vs_pre30_median": fmt(
                    fail["volume_vs_pre30_med"]
                ),
            })

    candidates = make_candidates()
    all_results = []

    for stage in STAGES:
        for conditions in candidates:
            dev_eval = evaluate(dev, stage, conditions)

            if dev_eval["support"] < MIN_DEV_SUPPORT:
                continue

            hold_eval = evaluate(holdout, stage, conditions)

            result = {
                "stage_min": stage,
                "rule": condition_text(stage, conditions),
                "condition_count": len(conditions),
                "dev_support": dev_eval["support"],
                "dev_fail": dev_eval["fail"],
                "dev_success": dev_eval["success"],
                "dev_fail_rate_pct": pct(
                    dev_eval["fail"], dev_eval["support"]
                ),
                "dev_baseline_fail_rate_pct": pct(dev_fail, len(dev)),
                "dev_fail_rate_lift_pp": round(
                    (dev_eval["fail_rate"] - dev_baseline) * 100.0, 2
                ),
                "holdout_support": hold_eval["support"],
                "holdout_fail": hold_eval["fail"],
                "holdout_success": hold_eval["success"],
                "holdout_fail_rate_pct": pct(
                    hold_eval["fail"], hold_eval["support"]
                ),
                "holdout_baseline_fail_rate_pct": pct(
                    hold_fail, len(holdout)
                ),
                "holdout_fail_rate_lift_pp": (
                    round(
                        (hold_eval["fail_rate"] - hold_baseline) * 100.0,
                        2
                    )
                    if hold_eval["fail_rate"] is not None
                    else ""
                ),
                "holdout_direction_same": (
                    "Y"
                    if hold_eval["support"] >= 3
                    and hold_eval["fail_rate"] is not None
                    and hold_eval["fail_rate"] > hold_baseline
                    else "N"
                ),
                "_score": score_rule(dev_eval, dev_baseline),
            }

            all_results.append(result)

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

    with open(
        OUTPUT_RULE_FILE, "w", encoding="utf-8-sig", newline=""
    ) as fobj:
        writer = csv.DictWriter(fobj, fieldnames=rule_fields)
        writer.writeheader()

        for rank, row in enumerate(all_results, start=1):
            out = dict(row)
            out.pop("_score", None)
            out["rank"] = rank
            writer.writerow({k: out.get(k, "") for k in rule_fields})

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

    with open(
        OUTPUT_CASE_FILE, "w", encoding="utf-8-sig", newline=""
    ) as fobj:
        writer = csv.DictWriter(fobj, fieldnames=case_fields)
        writer.writeheader()

        for row in clean:
            out = {k: row.get(k, "") for k in base_fields}

            for stage in STAGES:
                out[f"risk_score_{stage}m"] = stage_case_score(row, stage)

                for feature in (
                    "high_pct",
                    "low_pct",
                    "close_pct",
                    "down_ratio",
                    "volume_avg_vs_pre30",
                ):
                    out[f"w{stage}_{feature}"] = row.get(
                        f"w{stage}_{feature}", ""
                    )

            writer.writerow(out)

    print("=" * 78)
    print("검증 완료")
    print(f"결과 폴더: {RESULT_DIR}")
    print(f"단계 요약: {os.path.basename(OUTPUT_STAGE_FILE)}")
    print(f"규칙 검증: {os.path.basename(OUTPUT_RULE_FILE)}")
    print(f"케이스 점수: {os.path.basename(OUTPUT_CASE_FILE)}")
    print()
    print("이번 버전은 기존에 쓰기 성공한 minute_cache 폴더에 실행시각 파일명으로 저장합니다.")
    print("원문 RS3 조건은 변경하지 않았습니다.")
    print("=" * 78)


if __name__ == "__main__":
    main()

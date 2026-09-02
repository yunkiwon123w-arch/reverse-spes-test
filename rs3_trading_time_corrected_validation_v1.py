import csv
import os
import sys
from datetime import datetime

INPUT_FILE = "rs3_structure_analysis_v2.csv"
CACHE_DIR = "minute_cache"

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
CORRECTED_FILE = os.path.join(
    CACHE_DIR, f"rs3_trading_time_corrected_v1_{RUN_TAG}.csv"
)
RULE_FILE = os.path.join(
    CACHE_DIR, f"rs3_combined_risk_corrected_rules_v1_{RUN_TAG}.csv"
)
SUMMARY_FILE = os.path.join(
    CACHE_DIR, f"rs3_combined_risk_corrected_summary_v1_{RUN_TAG}.csv"
)
ERROR_FILE = os.path.join(
    CACHE_DIR, f"rs3_trading_time_corrected_errors_v1_{RUN_TAG}.csv"
)

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"
DEV_RATIO = 0.70


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


def median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    m = n // 2
    if n % 2:
        return vals[m]
    return (vals[m - 1] + vals[m]) / 2.0


def load_cache(code):
    path = os.path.join(CACHE_DIR, f"{normalize_code(code)}_minute.csv")
    if not os.path.exists(path):
        return []

    bars = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            dt = parse_dt(row.get("cntr_tm"))
            if dt:
                bars.append(dt)

    return sorted(set(bars))


def trading_minutes_between(bar_times, start_dt, end_dt):
    """
    실제 확보된 1분봉 개수로 '장중 경과 분'을 계산한다.
    야간/휴장/주말 시간은 자동으로 제외된다.

    start_dt 봉 이후부터 end_dt 봉까지의 실제 1분봉 수를 센다.
    같은 봉이면 0분.
    """
    if not start_dt or not end_dt:
        return None
    if end_dt < start_dt:
        return None
    if end_dt == start_dt:
        return 0

    return sum(1 for dt in bar_times if start_dt < dt <= end_dt)


def classify(row):
    group = str(row.get("path_group", "")).strip()
    if group in SUCCESS_GROUPS:
        return 0
    if group == FAIL_GROUP:
        return 1
    return None


def early_risk_3m(row):
    low3 = num(row.get("w3_low_pct"))
    down3 = num(row.get("w3_down_ratio"))
    return (
        low3 is not None and
        down3 is not None and
        low3 <= -1.5 and
        down3 >= 0.65
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
    minutes = num(row.get("trading_minutes_buy1_to_buy2"))
    vol_ratio = num(row.get("vol_50_to_618_avg_vs_pre30"))

    if minutes is None or vol_ratio is None:
        return None

    # 기존 연구 가설을 '실제 장중 5분' 기준으로 재검증
    return minutes <= 5 or vol_ratio >= 1.0


def stage3_risk(row):
    minutes = num(row.get("trading_minutes_buy2_to_stop70"))
    vol_ratio = num(row.get("vol_618_to_70_avg_vs_pre30"))

    if minutes is None or vol_ratio is None:
        return None

    return minutes <= 5 or vol_ratio >= 0.75


def evaluate(rows, predicate):
    hit = [r for r in rows if predicate(r)]
    fail = sum(r["_fail"] for r in hit)
    return {
        "support": len(hit),
        "fail": fail,
        "success": len(hit) - fail,
        "fail_rate": fail / len(hit) if hit else None,
    }


def write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def main():
    print("=" * 84)
    print("Reverse SPES - RS3 거래시간 교정 + 결합위험 재검증 v1")
    print("야간/주말/휴장 제외 / 실제 저장된 1분봉 개수로 장중 경과시간 계산")
    print("=" * 84)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    if not os.path.isdir(CACHE_DIR):
        print(f"[ERROR] 캐시 폴더 없음: {CACHE_DIR}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    by_code = {}
    corrected = []
    errors = []

    print(f"입력: {len(rows)}건")

    for idx, row in enumerate(rows, start=1):
        code = normalize_code(row.get("stock_code"))

        if code not in by_code:
            by_code[code] = load_cache(code)

        bars = by_code[code]

        if not bars:
            errors.append({
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "date": row.get("date", ""),
                "error": "minute_cache 없음 또는 비어 있음",
            })
            continue

        buy1 = parse_dt(row.get("buy1_time"))
        buy2 = parse_dt(row.get("buy2_time"))
        stop70 = parse_dt(row.get("stop70_time"))
        first_exit = parse_dt(row.get("first_exit_time"))

        out = dict(row)

        out["wall_minutes_buy1_to_buy2_original"] = row.get(
            "minutes_buy1_to_buy2", ""
        )
        out["wall_minutes_buy2_to_stop70_original"] = row.get(
            "minutes_buy2_to_stop70", ""
        )
        out["wall_minutes_buy1_to_stop70_original"] = row.get(
            "minutes_buy1_to_stop70", ""
        )
        out["wall_minutes_buy1_to_first_exit_original"] = row.get(
            "minutes_buy1_to_first_exit", ""
        )

        out["trading_minutes_buy1_to_buy2"] = (
            trading_minutes_between(bars, buy1, buy2)
            if buy2 else ""
        )
        out["trading_minutes_buy2_to_stop70"] = (
            trading_minutes_between(bars, buy2, stop70)
            if buy2 and stop70 else ""
        )
        out["trading_minutes_buy1_to_stop70"] = (
            trading_minutes_between(bars, buy1, stop70)
            if stop70 else ""
        )
        out["trading_minutes_buy1_to_first_exit"] = (
            trading_minutes_between(bars, buy1, first_exit)
            if first_exit else ""
        )

        corrected.append(out)

    if errors:
        write_csv(
            ERROR_FILE,
            ["stock_code", "stock_name", "date", "error"],
            errors
        )

    if not corrected:
        print("[ERROR] 교정 가능한 데이터가 없습니다.")
        sys.exit(1)

    corrected_fields = list(corrected[0].keys())
    write_csv(CORRECTED_FILE, corrected_fields, corrected)

    clean = []
    excluded = []

    for row in corrected:
        c = classify(row)
        if c is None:
            excluded.append(row)
            continue
        row["_fail"] = c
        clean.append(row)

    clean.sort(
        key=lambda r: (
            parse_date(r.get("date")),
            str(r.get("stock_code", ""))
        )
    )

    split = int(len(clean) * DEV_RATIO)
    dev = clean[:split]
    hold = clean[split:]

    dev_base = sum(r["_fail"] for r in dev) / len(dev)
    hold_base = sum(r["_fail"] for r in hold) / len(hold)

    # 단계별 중앙값
    summary_rows = []
    for label, fail_value in (("SUCCESS", 0), ("FAIL", 1)):
        subset = [r for r in clean if r["_fail"] == fail_value]

        b2 = [
            r for r in subset
            if num(r.get("trading_minutes_buy1_to_buy2")) is not None
        ]
        s70 = [
            r for r in subset
            if num(r.get("trading_minutes_buy2_to_stop70")) is not None
        ]

        summary_rows.append({
            "group": label,
            "total_count": len(subset),
            "buy2_count": len(b2),
            "trading_minutes_buy1_to_buy2_median": (
                median([
                    num(r.get("trading_minutes_buy1_to_buy2"))
                    for r in b2
                ])
                if b2 else ""
            ),
            "vol_50_to_618_avg_vs_pre30_median": (
                median([
                    num(r.get("vol_50_to_618_avg_vs_pre30"))
                    for r in b2
                ])
                if b2 else ""
            ),
            "stop70_after_buy2_count": len(s70),
            "trading_minutes_buy2_to_stop70_median": (
                median([
                    num(r.get("trading_minutes_buy2_to_stop70"))
                    for r in s70
                ])
                if s70 else ""
            ),
            "vol_618_to_70_avg_vs_pre30_median": (
                median([
                    num(r.get("vol_618_to_70_avg_vs_pre30"))
                    for r in s70
                ])
                if s70 else ""
            ),
        })

    write_csv(
        SUMMARY_FILE,
        [
            "group", "total_count", "buy2_count",
            "trading_minutes_buy1_to_buy2_median",
            "vol_50_to_618_avg_vs_pre30_median",
            "stop70_after_buy2_count",
            "trading_minutes_buy2_to_stop70_median",
            "vol_618_to_70_avg_vs_pre30_median",
        ],
        summary_rows
    )

    scenarios = [
        ("3M_ONLY", lambda r: early_risk_3m(r)),
        ("5M_ONLY", lambda r: early_risk_5m(r)[0]),
        (
            "3M_AND_5M",
            lambda r: early_risk_3m(r) and early_risk_5m(r)[0]
        ),
        (
            "3M_OR_5M",
            lambda r: early_risk_3m(r) or early_risk_5m(r)[0]
        ),
        (
            "3M_AND_STAGE2_CORRECTED",
            lambda r: early_risk_3m(r) and stage2_risk(r) is True
        ),
        (
            "5M_AND_STAGE2_CORRECTED",
            lambda r: early_risk_5m(r)[0] and stage2_risk(r) is True
        ),
        (
            "3M_5M_STAGE2_ANY2_CORRECTED",
            lambda r: (
                int(early_risk_3m(r))
                + int(early_risk_5m(r)[0])
                + int(stage2_risk(r) is True)
            ) >= 2
        ),
        (
            "3M_5M_STAGE2_ALL3_CORRECTED",
            lambda r: (
                early_risk_3m(r)
                and early_risk_5m(r)[0]
                and stage2_risk(r) is True
            )
        ),
        (
            "STAGE2_AND_STAGE3_CORRECTED",
            lambda r: (
                stage2_risk(r) is True
                and stage3_risk(r) is True
            )
        ),
    ]

    rule_rows = []

    for name, pred in scenarios:
        allv = evaluate(clean, pred)
        de = evaluate(dev, pred)
        ho = evaluate(hold, pred)

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

    write_csv(
        RULE_FILE,
        [
            "scenario",
            "all_support", "all_fail", "all_fail_rate_pct",
            "dev_support", "dev_fail", "dev_fail_rate_pct",
            "dev_baseline_fail_rate_pct", "dev_lift_pp",
            "holdout_support", "holdout_fail",
            "holdout_fail_rate_pct",
            "holdout_baseline_fail_rate_pct", "holdout_lift_pp",
            "holdout_direction_same",
        ],
        rule_rows
    )

    print()
    print("=" * 84)
    print("거래시간 교정 및 결합위험 재검증 완료")
    print(f"교정 데이터: {CORRECTED_FILE}")
    print(f"요약: {SUMMARY_FILE}")
    print(f"재검증 규칙: {RULE_FILE}")
    print(f"오류: {len(errors)}건")
    if errors:
        print(f"오류 파일: {ERROR_FILE}")
    print()
    print("핵심 교정:")
    print("- 기존 datetime 단순 차이 대신 실제 존재하는 1분봉 수를 계산")
    print("- 장 마감 후 야간, 주말, 휴장 시간은 경과시간에서 제외")
    print("- 원문 RS3 규칙은 변경하지 않음")
    print("- 교정된 속도변수로 Stage2/Stage3 결합신호만 재검증")
    print("=" * 84)


if __name__ == "__main__":
    main()

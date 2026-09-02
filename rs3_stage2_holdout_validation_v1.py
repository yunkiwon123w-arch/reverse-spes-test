import csv
import os
import sys
from datetime import datetime

INPUT_FILE = os.path.join("minute_cache", "rs3_risk_pnl_cases_v1_20260902_195848.csv")
OUTPUT_DIR = "minute_cache"
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

SUMMARY_FILE = os.path.join(
    OUTPUT_DIR, f"rs3_stage2_holdout_validation_v1_{RUN_TAG}.csv"
)
DETAIL_FILE = os.path.join(
    OUTPUT_DIR, f"rs3_stage2_holdout_cases_v1_{RUN_TAG}.csv"
)

DEV_RATIO = 0.70


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


def summarize(rows, segment, scenario_col):
    vals = [num(r.get(scenario_col)) for r in rows]
    vals = [v for v in vals if v is not None]

    wins = sum(v > 0 for v in vals)
    losses = sum(v < 0 for v in vals)

    succ = [r for r in rows if r.get("class") == "SUCCESS"]
    fail = [r for r in rows if r.get("class") == "FAIL"]

    acted = []
    if scenario_col == "STAGE2_DEFENSE_return_pct":
        acted = [
            r for r in rows
            if str(r.get("STAGE2_DEFENSE_action", "")).strip() != "NO_ACTION"
        ]

    helped_fail = [
        r for r in acted
        if r.get("class") == "FAIL"
        and num(r.get("STAGE2_DEFENSE_return_pct")) is not None
        and num(r.get("BASELINE_return_pct")) is not None
        and num(r.get("STAGE2_DEFENSE_return_pct")) > num(r.get("BASELINE_return_pct"))
    ]

    harmed_success = [
        r for r in acted
        if r.get("class") == "SUCCESS"
        and num(r.get("STAGE2_DEFENSE_return_pct")) is not None
        and num(r.get("BASELINE_return_pct")) is not None
        and num(r.get("STAGE2_DEFENSE_return_pct")) < num(r.get("BASELINE_return_pct"))
    ]

    return {
        "segment": segment,
        "scenario": "BASELINE" if scenario_col == "BASELINE_return_pct" else "STAGE2_DEFENSE",
        "count": len(vals),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": pct(wins, len(vals)),
        "avg_return_pct": round(sum(vals) / len(vals), 4) if vals else "",
        "simple_sum_return_pct": round(sum(vals), 4) if vals else "",
        "event_mdd_pct": round(mdd(vals), 4) if vals else "",
        "success_count": len(succ),
        "fail_count": len(fail),
        "action_count": len(acted),
        "failed_cases_helped_count": len(helped_fail),
        "successful_cases_harmed_count": len(harmed_success),
        "helped_fail_total_pp": round(sum(
            num(r["STAGE2_DEFENSE_return_pct"]) - num(r["BASELINE_return_pct"])
            for r in helped_fail
        ), 4) if helped_fail else 0.0,
        "harmed_success_total_pp": round(sum(
            num(r["STAGE2_DEFENSE_return_pct"]) - num(r["BASELINE_return_pct"])
            for r in harmed_success
        ), 4) if harmed_success else 0.0,
    }


def main():
    print("=" * 82)
    print("Reverse SPES - RS3 STAGE2 홀드아웃 손익 검증 v1")
    print("BASELINE vs STAGE2_DEFENSE / 시간순 70:30 재검증")
    print("=" * 82)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    rows.sort(key=lambda r: (parse_date(r["date"]), str(r["stock_code"])))

    split = int(len(rows) * DEV_RATIO)
    dev = rows[:split]
    hold = rows[split:]

    print(f"전체: {len(rows)}건")
    print(f"개발: {len(dev)}건")
    print(f"홀드아웃: {len(hold)}건")
    print()

    out = []
    for name, subset in (("DEV", dev), ("HOLDOUT", hold), ("ALL", rows)):
        out.append(summarize(subset, name, "BASELINE_return_pct"))
        out.append(summarize(subset, name, "STAGE2_DEFENSE_return_pct"))

    # baseline 대비 변화량 추가
    lookup = {(r["segment"], r["scenario"]): r for r in out}
    for r in out:
        if r["scenario"] == "STAGE2_DEFENSE":
            b = lookup[(r["segment"], "BASELINE")]
            r["avg_return_delta_pp"] = round(
                float(r["avg_return_pct"]) - float(b["avg_return_pct"]), 4
            )
            r["simple_sum_delta_pp"] = round(
                float(r["simple_sum_return_pct"]) - float(b["simple_sum_return_pct"]), 4
            )
            r["mdd_delta_pp"] = round(
                float(r["event_mdd_pct"]) - float(b["event_mdd_pct"]), 4
            )
        else:
            r["avg_return_delta_pp"] = 0.0
            r["simple_sum_delta_pp"] = 0.0
            r["mdd_delta_pp"] = 0.0

    fields = [
        "segment", "scenario", "count", "wins", "losses", "win_rate_pct",
        "avg_return_pct", "avg_return_delta_pp",
        "simple_sum_return_pct", "simple_sum_delta_pp",
        "event_mdd_pct", "mdd_delta_pp",
        "success_count", "fail_count",
        "action_count", "failed_cases_helped_count",
        "successful_cases_harmed_count",
        "helped_fail_total_pp", "harmed_success_total_pp",
    ]

    with open(SUMMARY_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)

    detail = []
    for seg, subset in (("DEV", dev), ("HOLDOUT", hold)):
        for r in subset:
            base = num(r.get("BASELINE_return_pct"))
            st2 = num(r.get("STAGE2_DEFENSE_return_pct"))
            detail.append({
                "segment": seg,
                "stock_code": r.get("stock_code", ""),
                "stock_name": r.get("stock_name", ""),
                "date": r.get("date", ""),
                "path_group": r.get("path_group", ""),
                "class": r.get("class", ""),
                "stage2_risk": r.get("stage2_risk", ""),
                "STAGE2_DEFENSE_action": r.get("STAGE2_DEFENSE_action", ""),
                "BASELINE_return_pct": base,
                "STAGE2_DEFENSE_return_pct": st2,
                "delta_pp": round(st2 - base, 4) if base is not None and st2 is not None else "",
            })

    detail_fields = list(detail[0].keys())
    with open(DETAIL_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=detail_fields)
        w.writeheader()
        w.writerows(detail)

    print("=" * 82)
    print("STAGE2 홀드아웃 손익 검증 완료")
    print(f"요약: {SUMMARY_FILE}")
    print(f"케이스: {DETAIL_FILE}")
    print()
    print("판정 원칙:")
    print("- 홀드아웃 평균수익 개선 여부")
    print("- 홀드아웃 MDD 악화 여부")
    print("- 실패경로 개선 vs 성공경로 훼손")
    print("- 홀드아웃에서도 개선이 유지되지 않으면 v1 후보 동결 금지")
    print("=" * 82)


if __name__ == "__main__":
    main()

import csv
import glob
import os
import sys
from datetime import datetime

CACHE_DIR = "minute_cache"
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")

OUTPUT_CASES = os.path.join(
    CACHE_DIR, f"rs3_stage2_precision_cases_v1_{RUN_TAG}.csv"
)
OUTPUT_SUMMARY = os.path.join(
    CACHE_DIR, f"rs3_stage2_precision_summary_v1_{RUN_TAG}.csv"
)
OUTPUT_COMPARE = os.path.join(
    CACHE_DIR, f"rs3_stage2_precision_compare_v1_{RUN_TAG}.csv"
)
OUTPUT_ERRORS = os.path.join(
    CACHE_DIR, f"rs3_stage2_precision_errors_v1_{RUN_TAG}.csv"
)

SUCCESS_GROUPS = {"A_DIRECT_TAKE1", "B_BUY2_RECOVERY"}
FAIL_GROUP = "C_STOP70_FIRST"

PRE_WINDOWS = (1, 3, 5)
POST_WINDOWS = (1, 3, 5)


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


def median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    m = n // 2
    if n % 2:
        return vals[m]
    return (vals[m - 1] + vals[m]) / 2.0


def pct_from(base, value):
    if base in (None, 0) or value is None:
        return None
    return (value / base - 1.0) * 100.0


def ratio(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


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


def signed_volume(bar):
    if bar["close"] > bar["open"]:
        return bar["volume"]
    if bar["close"] < bar["open"]:
        return -bar["volume"]
    return 0.0


def volume_stats(segment):
    if not segment:
        return {
            "count": 0,
            "total": None,
            "avg": None,
            "up": None,
            "down": None,
            "signed": None,
            "down_ratio": None,
        }

    total = sum(b["volume"] for b in segment)
    up = sum(b["volume"] for b in segment if b["close"] > b["open"])
    down = sum(b["volume"] for b in segment if b["close"] < b["open"])
    signed = sum(signed_volume(b) for b in segment)

    return {
        "count": len(segment),
        "total": total,
        "avg": total / len(segment),
        "up": up,
        "down": down,
        "signed": signed,
        "down_ratio": down / total if total else None,
    }


def early_risk_3m(row):
    low3 = num(row.get("w3_low_pct"))
    down3 = num(row.get("w3_down_ratio"))
    return (
        low3 is not None
        and down3 is not None
        and low3 <= -1.5
        and down3 >= 0.65
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

    # 기존 STAGE2 조건 그대로 고정. 이번 진단에서는 임계값 변경 금지.
    return minutes <= 5 or vol_ratio >= 1.0


def path_class(row):
    group = str(row.get("path_group", "")).strip()
    if group == FAIL_GROUP:
        return "TRUE_DEFENSE_C"
    if group in SUCCESS_GROUPS:
        return "FALSE_POSITIVE_SUCCESS"
    return "EXCLUDED"


def get_trade_window(bars, pivot_dt, before_n=0, after_n=0):
    """
    실제 존재하는 1분봉 기준.
    before_n: pivot 직전 N개 봉
    after_n: pivot 포함 이후 N개 봉
    """
    idx = None
    for i, b in enumerate(bars):
        if b["dt"] >= pivot_dt:
            idx = i
            break

    if idx is None:
        return [], []

    pre = bars[max(0, idx - before_n):idx]
    post = bars[idx:min(len(bars), idx + after_n)]
    return pre, post


def summarize_window(segment, ref_price):
    if not segment:
        return {
            "close_pct": None,
            "high_pct": None,
            "low_pct": None,
            "range_pct": None,
            "volume_total": None,
            "volume_avg": None,
            "down_ratio": None,
            "signed_volume": None,
            "first_close_pct": None,
            "last_close_pct": None,
        }

    vs = volume_stats(segment)
    max_high = max(b["high"] for b in segment)
    min_low = min(b["low"] for b in segment)

    return {
        "close_pct": pct_from(ref_price, segment[-1]["close"]),
        "high_pct": pct_from(ref_price, max_high),
        "low_pct": pct_from(ref_price, min_low),
        "range_pct": (
            (max_high - min_low) / ref_price * 100.0
            if ref_price else None
        ),
        "volume_total": vs["total"],
        "volume_avg": vs["avg"],
        "down_ratio": vs["down_ratio"],
        "signed_volume": vs["signed"],
        "first_close_pct": pct_from(ref_price, segment[0]["close"]),
        "last_close_pct": pct_from(ref_price, segment[-1]["close"]),
    }


def write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def main():
    print("=" * 88)
    print("Reverse SPES - RS3 STAGE2 오판 정밀진단 v1")
    print("기존 STAGE2 조건 고정 / 61.8 도달 직전·직후 분봉 구조 비교")
    print("=" * 88)

    if not os.path.isdir(CACHE_DIR):
        print(f"[ERROR] minute_cache 폴더 없음: {CACHE_DIR}")
        sys.exit(1)

    input_file = find_latest_corrected_file()
    if not input_file:
        print("[ERROR] rs3_trading_time_corrected_v1_*.csv 파일을 찾지 못했습니다.")
        sys.exit(1)

    print(f"입력 파일: {input_file}")

    with open(input_file, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    acted = []
    for row in rows:
        group = str(row.get("path_group", "")).strip()
        if group not in SUCCESS_GROUPS and group != FAIL_GROUP:
            continue

        e3 = early_risk_3m(row)
        e5, score5 = early_risk_5m(row)
        s2 = stage2_risk(row)

        # 기존 STAGE2_DEFENSE가 실제 개입하는 조건과 동일
        if (e3 or e5) and s2 is True and parse_dt(row.get("buy2_time")):
            row["_e3"] = int(e3)
            row["_e5"] = int(e5)
            row["_score5"] = score5
            row["_class"] = path_class(row)
            acted.append(row)

    print(f"STAGE2 개입 대상: {len(acted)}건")
    print(
        "  실제 C 방어: "
        f"{sum(r['_class'] == 'TRUE_DEFENSE_C' for r in acted)}건"
    )
    print(
        "  성공 A/B 오판: "
        f"{sum(r['_class'] == 'FALSE_POSITIVE_SUCCESS' for r in acted)}건"
    )
    print()

    cache_by_code = {}
    case_rows = []
    errors = []

    for row in acted:
        code = normalize_code(row.get("stock_code"))
        buy2_dt = parse_dt(row.get("buy2_time"))
        buy2_price = num(row.get("buy2_price"))

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

        if not buy2_dt or not buy2_price:
            errors.append({
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "date": row.get("date", ""),
                "error": "buy2_time 또는 buy2_price 없음",
            })
            continue

        out = {
            "stock_code": code,
            "stock_name": row.get("stock_name", ""),
            "date": row.get("date", ""),
            "path_group": row.get("path_group", ""),
            "diagnosis_class": row["_class"],
            "early_3m": row["_e3"],
            "early_5m": row["_e5"],
            "risk_score_5m": row["_score5"],
            "buy1_time": row.get("buy1_time", ""),
            "buy2_time": row.get("buy2_time", ""),
            "buy1_price": row.get("buy1_price", ""),
            "buy2_price": row.get("buy2_price", ""),
            "trading_minutes_buy1_to_buy2": row.get(
                "trading_minutes_buy1_to_buy2", ""
            ),
            "vol_50_to_618_avg_vs_pre30": row.get(
                "vol_50_to_618_avg_vs_pre30", ""
            ),
        }

        # 61.8 도달 "직전" 정보: 도달 순간까지 실제로 알 수 있는 구조.
        for n in PRE_WINDOWS:
            pre, _ = get_trade_window(bars, buy2_dt, before_n=n, after_n=0)
            s = summarize_window(pre, buy2_price)
            for key, value in s.items():
                out[f"pre{n}_{key}"] = value

        # 61.8 도달 "직후": 오판 원인 연구용.
        # 이 데이터는 61.8 도달 순간 의사결정에는 사용할 수 없음.
        for n in POST_WINDOWS:
            _, post = get_trade_window(bars, buy2_dt, before_n=0, after_n=n)
            s = summarize_window(post, buy2_price)
            for key, value in s.items():
                out[f"post{n}_{key}"] = value

        # 도달 직전 5분 vs 직후 5분 거래량 변화
        pre5, post5 = get_trade_window(bars, buy2_dt, before_n=5, after_n=5)
        pre5v = volume_stats(pre5)
        post5v = volume_stats(post5)
        out["post5_avgvol_vs_pre5"] = ratio(post5v["avg"], pre5v["avg"])

        # 61.8 도달 이후 1/3/5분 내 50선 방향 회복률(연구용 후행)
        buy1_price = num(row.get("buy1_price"))
        for n in POST_WINDOWS:
            _, post = get_trade_window(bars, buy2_dt, before_n=0, after_n=n)
            if post and buy1_price:
                max_high = max(b["high"] for b in post)
                out[f"post{n}_recovery_to_buy1_pct"] = (
                    (max_high - buy2_price)
                    / (buy1_price - buy2_price)
                    * 100.0
                    if buy1_price != buy2_price else None
                )
            else:
                out[f"post{n}_recovery_to_buy1_pct"] = None

        case_rows.append(out)

    if errors:
        write_csv(
            OUTPUT_ERRORS,
            ["stock_code", "stock_name", "date", "error"],
            errors
        )

    if not case_rows:
        print("[ERROR] 정밀진단 가능한 케이스가 없습니다.")
        sys.exit(1)

    case_fields = list(case_rows[0].keys())
    write_csv(OUTPUT_CASES, case_fields, case_rows)

    # ---------------------------------------------------------
    # 그룹 중앙값 비교
    # 임계값 탐색 금지. 단순 기술통계만 생성.
    # ---------------------------------------------------------
    compare_features = [
        "trading_minutes_buy1_to_buy2",
        "vol_50_to_618_avg_vs_pre30",
        "pre1_close_pct", "pre1_low_pct", "pre1_down_ratio",
        "pre3_close_pct", "pre3_low_pct", "pre3_down_ratio",
        "pre5_close_pct", "pre5_low_pct", "pre5_down_ratio",
        "pre5_volume_avg", "pre5_signed_volume",
        "post1_close_pct", "post1_high_pct", "post1_low_pct",
        "post3_close_pct", "post3_high_pct", "post3_low_pct",
        "post5_close_pct", "post5_high_pct", "post5_low_pct",
        "post5_down_ratio", "post5_avgvol_vs_pre5",
        "post1_recovery_to_buy1_pct",
        "post3_recovery_to_buy1_pct",
        "post5_recovery_to_buy1_pct",
    ]

    compare_rows = []

    groups = {
        "TRUE_DEFENSE_C": [
            r for r in case_rows
            if r["diagnosis_class"] == "TRUE_DEFENSE_C"
        ],
        "FALSE_POSITIVE_SUCCESS": [
            r for r in case_rows
            if r["diagnosis_class"] == "FALSE_POSITIVE_SUCCESS"
        ],
    }

    for feature in compare_features:
        fail_vals = [num(r.get(feature)) for r in groups["TRUE_DEFENSE_C"]]
        succ_vals = [
            num(r.get(feature))
            for r in groups["FALSE_POSITIVE_SUCCESS"]
        ]
        fail_vals = [v for v in fail_vals if v is not None]
        succ_vals = [v for v in succ_vals if v is not None]

        compare_rows.append({
            "feature": feature,
            "true_defense_count": len(fail_vals),
            "true_defense_median": median(fail_vals),
            "false_positive_count": len(succ_vals),
            "false_positive_median": median(succ_vals),
            "median_gap_true_minus_false": (
                median(fail_vals) - median(succ_vals)
                if fail_vals and succ_vals else ""
            ),
            "timing_use": (
                "AT_618_AVAILABLE"
                if feature.startswith("pre")
                or feature in {
                    "trading_minutes_buy1_to_buy2",
                    "vol_50_to_618_avg_vs_pre30",
                }
                else "POST_618_RESEARCH_ONLY"
            ),
        })

    compare_fields = list(compare_rows[0].keys())
    write_csv(OUTPUT_COMPARE, compare_fields, compare_rows)

    # ---------------------------------------------------------
    # 요약
    # ---------------------------------------------------------
    summary_rows = []

    for label, group_rows in groups.items():
        summary_rows.append({
            "group": label,
            "count": len(group_rows),
            "trading_minutes_buy1_to_buy2_median": median([
                num(r.get("trading_minutes_buy1_to_buy2"))
                for r in group_rows
            ]),
            "vol_50_to_618_avg_vs_pre30_median": median([
                num(r.get("vol_50_to_618_avg_vs_pre30"))
                for r in group_rows
            ]),
            "pre3_low_pct_median": median([
                num(r.get("pre3_low_pct"))
                for r in group_rows
            ]),
            "pre3_down_ratio_median": median([
                num(r.get("pre3_down_ratio"))
                for r in group_rows
            ]),
            "pre5_close_pct_median": median([
                num(r.get("pre5_close_pct"))
                for r in group_rows
            ]),
            "pre5_down_ratio_median": median([
                num(r.get("pre5_down_ratio"))
                for r in group_rows
            ]),
            "post3_high_pct_median": median([
                num(r.get("post3_high_pct"))
                for r in group_rows
            ]),
            "post3_close_pct_median": median([
                num(r.get("post3_close_pct"))
                for r in group_rows
            ]),
            "post5_recovery_to_buy1_pct_median": median([
                num(r.get("post5_recovery_to_buy1_pct"))
                for r in group_rows
            ]),
        })

    summary_fields = list(summary_rows[0].keys())
    write_csv(OUTPUT_SUMMARY, summary_fields, summary_rows)

    print("=" * 88)
    print("STAGE2 오판 정밀진단 완료")
    print(f"케이스 상세: {OUTPUT_CASES}")
    print(f"그룹 요약: {OUTPUT_SUMMARY}")
    print(f"변수 비교: {OUTPUT_COMPARE}")
    print(f"오류: {len(errors)}건")
    if errors:
        print(f"오류 파일: {OUTPUT_ERRORS}")
    print()
    print("해석 원칙:")
    print("- 기존 STAGE2 임계값/조건은 변경하지 않음")
    print("- pre1/pre3/pre5는 61.8 도달 시점까지 사용 가능한 정보")
    print("- post1/post3/post5는 도달 후 정보이므로 원인연구용")
    print("- post 신호를 61.8 도달 순간 의사결정에 소급 사용 금지")
    print("- 표본이 작으므로 새 임계값 자동탐색/최적화 금지")
    print("=" * 88)


if __name__ == "__main__":
    main()

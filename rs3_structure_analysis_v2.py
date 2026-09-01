import csv
import getpass
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
MINUTE_URL = f"{BASE_URL}/api/dostk/chart"

INPUT_FILE = "rs3_structure_analysis.csv"
OUTPUT_FILE = "rs3_structure_analysis_v2.csv"
ERROR_FILE = "rs3_structure_analysis_v2_errors.csv"

REQUEST_INTERVAL = 0.30
MAX_PAGES_PER_STOCK = 500

WINDOWS = (1, 3, 5, 10, 20, 30)


def normalize_code(value):
    s = str(value or "").strip().upper()
    if not s:
        return ""
    if len(s) == 6 and s.isalnum():
        return s
    if s.isdigit():
        return s.zfill(6)
    return s


def safe_float(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def safe_int(v, default=0):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).replace(",", "").strip()))
    except Exception:
        return default


def parse_dt(value):
    s = str(value or "").strip()
    if not s:
        return None
    return datetime.strptime(s, "%Y%m%d%H%M%S")


def fmt_dt(dt):
    return dt.strftime("%Y%m%d%H%M%S") if dt else ""


def pct(base, value):
    if base in (None, 0) or value is None:
        return ""
    return round((value / base - 1.0) * 100.0, 4)


def ratio(a, b):
    if a in ("", None) or b in ("", None, 0):
        return ""
    return round(float(a) / float(b), 4)


def get_token(appkey, secretkey):
    payload = {
        "grant_type": "client_credentials",
        "appkey": appkey,
        "secretkey": secretkey,
    }
    r = requests.post(TOKEN_URL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"TOKEN 발급 실패: {data}")
    return token


def request_minute_page(token, code, cont_yn="", next_key=""):
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10080",
    }
    if cont_yn:
        headers["cont-yn"] = cont_yn
    if next_key:
        headers["next-key"] = next_key

    body = {
        "stk_cd": code,
        "tic_scope": "1",
        "upd_stkpc_tp": "1",
    }

    r = requests.post(MINUTE_URL, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()

    bars = data.get("stk_min_pole_chart_qry") or []
    return (
        bars,
        r.headers.get("cont-yn", ""),
        r.headers.get("next-key", ""),
    )


def parse_bar(raw):
    tm = str(raw.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    def price(name):
        v = safe_float(raw.get(name), None)
        return abs(v) if v is not None else None

    o = price("open_pric")
    h = price("high_pric")
    l = price("low_pric")
    c = price("cur_prc")
    volume = abs(safe_int(raw.get("trde_qty"), 0))

    if None in (o, h, l, c):
        return None

    return {
        "dt": datetime.strptime(tm, "%Y%m%d%H%M%S"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": volume,
    }


def fetch_history_until(token, code, oldest_date):
    all_bars = []
    cont_yn = ""
    next_key = ""

    for _ in range(MAX_PAGES_PER_STOCK):
        raw_bars, cont_yn, next_key = request_minute_page(
            token, code, cont_yn, next_key
        )

        parsed = [parse_bar(x) for x in raw_bars]
        parsed = [x for x in parsed if x]
        all_bars.extend(parsed)

        if parsed:
            oldest_seen = min(x["dt"].strftime("%Y%m%d") for x in parsed)
            if oldest_seen <= oldest_date:
                break

        if str(cont_yn).upper() != "Y" or not next_key:
            break

        time.sleep(REQUEST_INTERVAL)

    uniq = {}
    for bar in all_bars:
        uniq[bar["dt"]] = bar

    return [uniq[k] for k in sorted(uniq)]


def signed_volume(bar):
    if bar["close"] > bar["open"]:
        return bar["volume"]
    if bar["close"] < bar["open"]:
        return -bar["volume"]
    return 0


def volume_summary(segment):
    if not segment:
        return {
            "total": "",
            "avg": "",
            "up": "",
            "down": "",
            "signed": "",
            "up_ratio": "",
            "down_ratio": "",
        }

    total = sum(x["volume"] for x in segment)
    up = sum(x["volume"] for x in segment if x["close"] > x["open"])
    down = sum(x["volume"] for x in segment if x["close"] < x["open"])
    signed = sum(signed_volume(x) for x in segment)

    return {
        "total": total,
        "avg": round(total / len(segment), 2),
        "up": up,
        "down": down,
        "signed": signed,
        "up_ratio": round(up / total, 4) if total else "",
        "down_ratio": round(down / total, 4) if total else "",
    }


def window_bars(bars, start_dt, minutes):
    end_ts = start_dt.timestamp() + minutes * 60
    return [
        x for x in bars
        if start_dt.timestamp() <= x["dt"].timestamp() <= end_ts
    ]


def analyze_row(row, bars):
    buy1_dt = parse_dt(row.get("buy1_time"))
    buy1_price = safe_float(row.get("buy1_price"))

    if not buy1_dt:
        raise RuntimeError("buy1_time 없음")
    if not buy1_price:
        raise RuntimeError("buy1_price 없음")

    post = [x for x in bars if x["dt"] >= buy1_dt]
    if not post:
        raise RuntimeError("buy1_time 이후 분봉 없음")

    pre_start = buy1_dt.timestamp() - 30 * 60
    pre30 = [
        x for x in bars
        if pre_start <= x["dt"].timestamp() < buy1_dt.timestamp()
    ]
    pre = volume_summary(pre30)
    pre_avg = pre["avg"]

    result = dict(row)

    result["pre30_up_volume"] = pre["up"]
    result["pre30_down_volume"] = pre["down"]
    result["pre30_signed_volume"] = pre["signed"]
    result["pre30_up_ratio"] = pre["up_ratio"]
    result["pre30_down_ratio"] = pre["down_ratio"]

    for minutes in WINDOWS:
        seg = window_bars(post, buy1_dt, minutes)

        if not seg:
            for key in (
                "close_pct", "high_pct", "low_pct",
                "volume_total", "volume_avg_vs_pre30",
                "up_volume", "down_volume", "signed_volume",
                "up_ratio", "down_ratio",
                "min_low_time", "max_high_time",
            ):
                result[f"w{minutes}_{key}"] = ""
            continue

        summary = volume_summary(seg)

        last_close = seg[-1]["close"]
        max_high = max(x["high"] for x in seg)
        min_low = min(x["low"] for x in seg)

        min_bar = next(x for x in seg if x["low"] == min_low)
        max_bar = next(x for x in seg if x["high"] == max_high)

        result[f"w{minutes}_close_pct"] = pct(buy1_price, last_close)
        result[f"w{minutes}_high_pct"] = pct(buy1_price, max_high)
        result[f"w{minutes}_low_pct"] = pct(buy1_price, min_low)

        result[f"w{minutes}_volume_total"] = summary["total"]
        result[f"w{minutes}_volume_avg_vs_pre30"] = ratio(
            summary["avg"], pre_avg
        )

        result[f"w{minutes}_up_volume"] = summary["up"]
        result[f"w{minutes}_down_volume"] = summary["down"]
        result[f"w{minutes}_signed_volume"] = summary["signed"]
        result[f"w{minutes}_up_ratio"] = summary["up_ratio"]
        result[f"w{minutes}_down_ratio"] = summary["down_ratio"]
        result[f"w{minutes}_min_low_time"] = fmt_dt(min_bar["dt"])
        result[f"w{minutes}_max_high_time"] = fmt_dt(max_bar["dt"])

    # 연구용 위험 플래그.
    # 원문 RS3 매매조건이 아니며, 추후 검증용으로만 기록한다.
    h5 = safe_float(result.get("w5_high_pct"))
    l5 = safe_float(result.get("w5_low_pct"))
    c5 = safe_float(result.get("w5_close_pct"))
    vol5 = safe_float(result.get("w5_volume_avg_vs_pre30"))
    down5 = safe_float(result.get("w5_down_ratio"))

    flags = []

    if h5 is not None and h5 < 1.0:
        flags.append("WEAK_REBOUND_5M")
    if l5 is not None and l5 <= -1.0:
        flags.append("DEEP_DROP_5M")
    if c5 is not None and c5 < 0:
        flags.append("NEGATIVE_CLOSE_5M")
    if vol5 is not None and vol5 >= 1.0:
        flags.append("VOLUME_NOT_DRYING_5M")
    if down5 is not None and down5 >= 0.55:
        flags.append("DOWN_VOLUME_DOMINANT_5M")

    result["research_risk_flags_5m"] = "|".join(flags)
    result["research_risk_flag_count_5m"] = len(flags)

    return result


def load_rows():
    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def completed_keys():
    if not os.path.exists(OUTPUT_FILE):
        return set()

    keys = set()
    with open(OUTPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            keys.add((
                normalize_code(row.get("stock_code")),
                str(row.get("date", "")).strip()
            ))
    return keys


def build_fieldnames(input_fields):
    extra = [
        "pre30_up_volume",
        "pre30_down_volume",
        "pre30_signed_volume",
        "pre30_up_ratio",
        "pre30_down_ratio",
    ]

    for minutes in WINDOWS:
        extra.extend([
            f"w{minutes}_close_pct",
            f"w{minutes}_high_pct",
            f"w{minutes}_low_pct",
            f"w{minutes}_volume_total",
            f"w{minutes}_volume_avg_vs_pre30",
            f"w{minutes}_up_volume",
            f"w{minutes}_down_volume",
            f"w{minutes}_signed_volume",
            f"w{minutes}_up_ratio",
            f"w{minutes}_down_ratio",
            f"w{minutes}_min_low_time",
            f"w{minutes}_max_high_time",
        ])

    extra.extend([
        "research_risk_flags_5m",
        "research_risk_flag_count_5m",
    ])

    return list(input_fields) + [x for x in extra if x not in input_fields]


def append_csv(path, fieldnames, row):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    print("=" * 76)
    print("Reverse SPES - RS3 분봉 구조 고도화 분석 v2")
    print("원문 RS3 규칙 변경 없음 / 연구용 진입후 가격·거래량 구조 추가 계측")
    print("=" * 76)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] 입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        input_fields = reader.fieldnames or []
        rows = list(reader)

    fieldnames = build_fieldnames(input_fields)
    done = completed_keys()

    remaining = [
        row for row in rows
        if (
            normalize_code(row.get("stock_code")),
            str(row.get("date", "")).strip()
        ) not in done
    ]

    grouped = defaultdict(list)
    for row in remaining:
        grouped[normalize_code(row.get("stock_code"))].append(row)

    print(f"입력 구조분석 표본: {len(rows)}건")
    print(f"이미 완료: {len(done)}건")
    print(f"이번 실행 대상: {len(remaining)}건")
    print(f"조회 종목: {len(grouped)}개")
    print()
    print("추가 계측:")
    print("  - 진입 후 1/3/5/10/20/30분 종가·고가·저가")
    print("  - 각 구간 평균거래량 / 진입직전 30분 평균거래량")
    print("  - 상승봉 거래량 / 하락봉 거래량 / 방향성 거래량")
    print("  - 저점·고점 형성 시각")
    print("  - 5분 위험플래그(연구용, 원문 조건 아님)")
    print()

    if not remaining:
        print("이미 모두 완료되었습니다.")
        return

    appkey = getpass.getpass("Kiwoom App Key: ")
    secret = getpass.getpass("Kiwoom Secret Key: ")

    print("\nTOKEN 발급 중...")
    token = get_token(appkey, secret)
    print("TOKEN 발급 성공\n")

    completed_now = 0
    error_now = 0

    for idx, (code, candidates) in enumerate(grouped.items(), start=1):
        name = candidates[0].get("stock_name", "")
        oldest_date = min(str(x.get("date", "")).strip() for x in candidates)

        print(f"[{idx}/{len(grouped)}] {code} {name} / 후보 {len(candidates)}건")

        try:
            bars = fetch_history_until(token, code, oldest_date)
            print(f"  분봉 {len(bars):,}개")

            for row in candidates:
                try:
                    result = analyze_row(row, bars)
                    append_csv(OUTPUT_FILE, fieldnames, result)
                    completed_now += 1
                except Exception as e:
                    append_csv(
                        ERROR_FILE,
                        ["stock_code", "stock_name", "date", "error"],
                        {
                            "stock_code": code,
                            "stock_name": row.get("stock_name", ""),
                            "date": row.get("date", ""),
                            "error": str(e),
                        }
                    )
                    error_now += 1
                    print(f"  후보 오류 {row.get('date')}: {e}")

        except Exception as e:
            for row in candidates:
                append_csv(
                    ERROR_FILE,
                    ["stock_code", "stock_name", "date", "error"],
                    {
                        "stock_code": code,
                        "stock_name": row.get("stock_name", ""),
                        "date": row.get("date", ""),
                        "error": str(e),
                    }
                )
                error_now += 1
            print(f"  종목 조회 오류: {e}")

        time.sleep(REQUEST_INTERVAL)

    print()
    print("=" * 76)
    print("RS3 분봉 구조 고도화 분석 v2 완료")
    print(f"이번 실행 완료: {completed_now}건")
    print(f"오류 기록: {error_now}건")
    print(f"결과: {OUTPUT_FILE}")
    print(f"오류: {ERROR_FILE}")
    print()
    print("주의:")
    print("  research_risk_* 항목은 원문 매매조건이 아닙니다.")
    print("  개선판 후보를 검증하기 위한 연구용 변수입니다.")
    print("=" * 76)


if __name__ == "__main__":
    main()

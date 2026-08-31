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

INPUT_FILE = "rs3_trade_validation_v2_1.csv"
OUTPUT_FILE = "rs3_structure_analysis.csv"
ERROR_FILE = "rs3_structure_analysis_errors.csv"

REQUEST_INTERVAL = 0.30
MAX_PAGES_PER_STOCK = 500

# 이번 단계의 목적:
# 원문 RS3 규칙을 변경하지 않고, 이미 확정된 122건의 진입 이후 분봉 구조를 계측한다.
# 특히 50선 -> 61.8선 -> 70선 구간의 속도/거래량/반등 구조를 뽑는다.


def normalize_code(value):
    s = str(value or "").strip().upper()
    if not s:
        return ""
    # 영문 혼합 6자리 종목코드는 그대로 보존
    if len(s) == 6 and s.isalnum():
        return s
    if s.isdigit():
        return s.zfill(6)
    return s


def parse_dt(value):
    s = str(value or "").strip()
    if not s:
        return None
    return datetime.strptime(s, "%Y%m%d%H%M%S")


def fmt_dt(dt):
    return dt.strftime("%Y%m%d%H%M%S") if dt else ""


def minutes_between(a, b):
    if not a or not b:
        return ""
    return round((b - a).total_seconds() / 60.0, 2)


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
    new_cont = r.headers.get("cont-yn", "")
    new_next = r.headers.get("next-key", "")
    return bars, new_cont, new_next


def parse_bar(raw):
    tm = str(raw.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    def p(name):
        v = safe_float(raw.get(name), None)
        return abs(v) if v is not None else None

    o = p("open_pric")
    h = p("high_pric")
    l = p("low_pric")
    c = p("cur_prc")
    vol = safe_int(raw.get("trde_qty"), 0)

    if None in (o, h, l, c):
        return None

    return {
        "dt": datetime.strptime(tm, "%Y%m%d%H%M%S"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": abs(vol),
    }


def fetch_history_until(token, code, oldest_date):
    all_bars = []
    cont_yn = ""
    next_key = ""

    for page in range(1, MAX_PAGES_PER_STOCK + 1):
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

    # 중복 제거 + 시간순 정렬
    uniq = {}
    for b in all_bars:
        uniq[b["dt"]] = b
    return [uniq[k] for k in sorted(uniq)]


def classify_path(row):
    first_exit = str(row.get("first_exit_event", "")).strip()
    buy2 = str(row.get("buy2_filled", "")).upper() == "Y"
    take1 = str(row.get("take1_hit", "")).upper() == "Y"
    ambiguity = str(row.get("intrabar_ambiguity", "")).strip()

    if ambiguity:
        return "AMBIGUOUS"
    if first_exit == "STOP70":
        return "C_STOP70_FIRST"
    if first_exit in ("TAKE1", "TAKE2"):
        if buy2:
            return "B_BUY2_RECOVERY"
        if take1:
            return "A_DIRECT_TAKE1"
        return "B_BUY2_RECOVERY"
    return "D_NO_EXIT_WITHIN_WINDOW"


def bars_between(bars, start_dt, end_dt, include_end=True):
    if not start_dt or not end_dt:
        return []
    if include_end:
        return [b for b in bars if start_dt <= b["dt"] <= end_dt]
    return [b for b in bars if start_dt <= b["dt"] < end_dt]


def volume_stats(segment):
    if not segment:
        return ("", "", "")
    vols = [b["volume"] for b in segment]
    total = sum(vols)
    avg = total / len(vols) if vols else 0
    peak = max(vols) if vols else 0
    return (total, round(avg, 2), peak)


def pct(a, b):
    if a in (None, 0) or b is None:
        return ""
    return round((b / a - 1.0) * 100.0, 4)


def analyze_candidate(row, bars):
    buy1_dt = parse_dt(row.get("buy1_time"))
    buy2_dt = parse_dt(row.get("buy2_time"))
    stop_dt = parse_dt(row.get("stop70_time"))
    first_exit_dt = parse_dt(row.get("first_exit_time"))
    eval_last_dt = parse_dt(row.get("evaluation_last_time"))

    buy1 = safe_float(row.get("buy1_price"))
    buy2 = safe_float(row.get("buy2_price"))
    stop70 = safe_float(row.get("stop70_price"))

    if not buy1_dt:
        raise RuntimeError("buy1_time 없음")

    post = [b for b in bars if b["dt"] >= buy1_dt]
    if eval_last_dt:
        post = [b for b in post if b["dt"] <= eval_last_dt]
    if not post:
        raise RuntimeError("buy1_time 이후 분봉 없음")

    # 진입 직전 30분을 기준 거래량으로 사용.
    pre30_start = buy1_dt.timestamp() - 30 * 60
    pre30 = [
        b for b in bars
        if pre30_start <= b["dt"].timestamp() < buy1_dt.timestamp()
    ]
    pre_total, pre_avg, pre_peak = volume_stats(pre30)

    # 50 -> 61.8
    seg_50_618 = bars_between(post, buy1_dt, buy2_dt) if buy2_dt else []
    v50618_total, v50618_avg, v50618_peak = volume_stats(seg_50_618)

    # 61.8 -> 70
    seg_618_70 = bars_between(post, buy2_dt, stop_dt) if buy2_dt and stop_dt else []
    v61870_total, v61870_avg, v61870_peak = volume_stats(seg_618_70)

    # 50 -> 첫 청산 이벤트
    seg_to_exit = bars_between(post, buy1_dt, first_exit_dt) if first_exit_dt else []
    vexit_total, vexit_avg, vexit_peak = volume_stats(seg_to_exit)

    # 첫 5/10/20/30분의 최저가와 최고가
    early = {}
    for mins in (5, 10, 20, 30):
        end_ts = buy1_dt.timestamp() + mins * 60
        seg = [b for b in post if b["dt"].timestamp() <= end_ts]
        if seg:
            low = min(b["low"] for b in seg)
            high = max(b["high"] for b in seg)
            early[f"low_{mins}m_pct"] = pct(buy1, low)
            early[f"high_{mins}m_pct"] = pct(buy1, high)
        else:
            early[f"low_{mins}m_pct"] = ""
            early[f"high_{mins}m_pct"] = ""

    # 70선 발생 후 회복력
    post_stop = []
    if stop_dt:
        post_stop = [b for b in post if b["dt"] > stop_dt]

    post_stop_max = max((b["high"] for b in post_stop), default=None)
    post_stop_max_dt = None
    if post_stop_max is not None:
        for b in post_stop:
            if b["high"] == post_stop_max:
                post_stop_max_dt = b["dt"]
                break

    recovered_buy1 = bool(post_stop_max is not None and buy1 is not None and post_stop_max >= buy1)
    recovered_plus4 = bool(post_stop_max is not None and buy1 is not None and post_stop_max >= buy1 * 1.04)
    recovered_plus5 = bool(post_stop_max is not None and buy1 is not None and post_stop_max >= buy1 * 1.05)

    # 70선 발생 직전 10분 거래량 vs 진입 직전 30분 평균
    pre_stop_10 = []
    if stop_dt:
        start_ts = stop_dt.timestamp() - 10 * 60
        pre_stop_10 = [
            b for b in post
            if start_ts <= b["dt"].timestamp() <= stop_dt.timestamp()
        ]
    _, pre_stop_avg, pre_stop_peak = volume_stats(pre_stop_10)

    def ratio(x, y):
        if x in ("", None) or y in ("", None, 0):
            return ""
        return round(float(x) / float(y), 4)

    out = {
        "stock_code": normalize_code(row.get("stock_code")),
        "stock_name": row.get("stock_name", ""),
        "market": row.get("market", ""),
        "date": row.get("date", ""),
        "path_group": classify_path(row),
        "first_exit_event": row.get("first_exit_event", ""),
        "intrabar_ambiguity": row.get("intrabar_ambiguity", ""),
        "traded_value_eok": row.get("traded_value_eok", ""),
        "rise_pct": row.get("rise_pct", ""),
        "trigger_time": row.get("trigger_time", ""),
        "buy1_time": row.get("buy1_time", ""),
        "buy2_time": row.get("buy2_time", ""),
        "stop70_time": row.get("stop70_time", ""),
        "first_exit_time": row.get("first_exit_time", ""),
        "buy1_price": row.get("buy1_price", ""),
        "buy2_price": row.get("buy2_price", ""),
        "stop70_price": row.get("stop70_price", ""),
        "minutes_buy1_to_buy2": minutes_between(buy1_dt, buy2_dt),
        "minutes_buy2_to_stop70": minutes_between(buy2_dt, stop_dt),
        "minutes_buy1_to_stop70": minutes_between(buy1_dt, stop_dt),
        "minutes_buy1_to_first_exit": minutes_between(buy1_dt, first_exit_dt),
        "pre30_volume_total": pre_total,
        "pre30_volume_avg": pre_avg,
        "pre30_volume_peak": pre_peak,
        "vol_50_to_618_total": v50618_total,
        "vol_50_to_618_avg": v50618_avg,
        "vol_50_to_618_peak": v50618_peak,
        "vol_50_to_618_avg_vs_pre30": ratio(v50618_avg, pre_avg),
        "vol_618_to_70_total": v61870_total,
        "vol_618_to_70_avg": v61870_avg,
        "vol_618_to_70_peak": v61870_peak,
        "vol_618_to_70_avg_vs_pre30": ratio(v61870_avg, pre_avg),
        "vol_to_first_exit_total": vexit_total,
        "vol_to_first_exit_avg": vexit_avg,
        "vol_to_first_exit_peak": vexit_peak,
        "vol_to_first_exit_avg_vs_pre30": ratio(vexit_avg, pre_avg),
        "pre_stop_10m_volume_avg": pre_stop_avg,
        "pre_stop_10m_volume_peak": pre_stop_peak,
        "pre_stop_10m_avg_vs_pre30": ratio(pre_stop_avg, pre_avg),
        "post_stop_max_price": post_stop_max if post_stop_max is not None else "",
        "post_stop_max_time": fmt_dt(post_stop_max_dt),
        "post_stop_max_pct_from_buy1": pct(buy1, post_stop_max),
        "post_stop_recovered_buy1": "Y" if recovered_buy1 else "N",
        "post_stop_recovered_plus4": "Y" if recovered_plus4 else "N",
        "post_stop_recovered_plus5": "Y" if recovered_plus5 else "N",
        "mfe_pct_from_buy1": row.get("mfe_pct_from_buy1", ""),
        "mae_pct_from_buy1": row.get("mae_pct_from_buy1", ""),
    }
    out.update(early)
    return out


FIELDNAMES = [
    "stock_code","stock_name","market","date","path_group","first_exit_event",
    "intrabar_ambiguity","traded_value_eok","rise_pct","trigger_time",
    "buy1_time","buy2_time","stop70_time","first_exit_time",
    "buy1_price","buy2_price","stop70_price",
    "minutes_buy1_to_buy2","minutes_buy2_to_stop70","minutes_buy1_to_stop70",
    "minutes_buy1_to_first_exit",
    "pre30_volume_total","pre30_volume_avg","pre30_volume_peak",
    "vol_50_to_618_total","vol_50_to_618_avg","vol_50_to_618_peak",
    "vol_50_to_618_avg_vs_pre30",
    "vol_618_to_70_total","vol_618_to_70_avg","vol_618_to_70_peak",
    "vol_618_to_70_avg_vs_pre30",
    "vol_to_first_exit_total","vol_to_first_exit_avg","vol_to_first_exit_peak",
    "vol_to_first_exit_avg_vs_pre30",
    "pre_stop_10m_volume_avg","pre_stop_10m_volume_peak","pre_stop_10m_avg_vs_pre30",
    "low_5m_pct","high_5m_pct","low_10m_pct","high_10m_pct",
    "low_20m_pct","high_20m_pct","low_30m_pct","high_30m_pct",
    "post_stop_max_price","post_stop_max_time","post_stop_max_pct_from_buy1",
    "post_stop_recovered_buy1","post_stop_recovered_plus4","post_stop_recovered_plus5",
    "mfe_pct_from_buy1","mae_pct_from_buy1",
]


def load_input():
    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if str(r.get("status", "")).strip() == "PATH_EXTRACTED"]


def completed_keys():
    if not os.path.exists(OUTPUT_FILE):
        return set()
    keys = set()
    with open(OUTPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            keys.add((normalize_code(r.get("stock_code")), str(r.get("date", "")).strip()))
    return keys


def append_row(path, fieldnames, row):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    print("=" * 72)
    print("Reverse SPES - RS3 성공/실패 분봉 구조 분석 v1")
    print("원문 규칙 변경 없음 / 122건 진입 이후 구조만 계측")
    print("=" * 72)

    if not os.path.exists(INPUT_FILE):
        print(f"입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    rows = load_input()
    done = completed_keys()
    remaining = [
        r for r in rows
        if (normalize_code(r.get("stock_code")), str(r.get("date", "")).strip()) not in done
    ]

    grouped = defaultdict(list)
    for r in remaining:
        grouped[normalize_code(r.get("stock_code"))].append(r)

    print(f"입력 PATH_EXTRACTED: {len(rows)}건")
    print(f"이미 완료: {len(done)}건")
    print(f"이번 실행 대상: {len(remaining)}건")
    print(f"조회 종목: {len(grouped)}개")
    print()
    print("계측: 50->61.8 속도 / 61.8->70 속도 / 구간 거래량 /")
    print("      진입 후 5·10·20·30분 가격경로 / 70선 후 회복력")
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
    error_count = 0

    for idx, (code, candidates) in enumerate(grouped.items(), start=1):
        name = candidates[0].get("stock_name", "")
        oldest_date = min(str(r.get("date", "")).strip() for r in candidates)

        print(f"[{idx}/{len(grouped)}] {code} {name} / 후보 {len(candidates)}건")

        try:
            bars = fetch_history_until(token, code, oldest_date)
            print(f"  분봉 {len(bars):,}개")

            for r in candidates:
                try:
                    result = analyze_candidate(r, bars)
                    append_row(OUTPUT_FILE, FIELDNAMES, result)
                    completed_now += 1
                except Exception as e:
                    append_row(
                        ERROR_FILE,
                        ["stock_code","stock_name","date","error"],
                        {
                            "stock_code": code,
                            "stock_name": r.get("stock_name", ""),
                            "date": r.get("date", ""),
                            "error": str(e),
                        },
                    )
                    error_count += 1
                    print(f"  후보 오류 {r.get('date')}: {e}")

        except Exception as e:
            for r in candidates:
                append_row(
                    ERROR_FILE,
                    ["stock_code","stock_name","date","error"],
                    {
                        "stock_code": code,
                        "stock_name": r.get("stock_name", ""),
                        "date": r.get("date", ""),
                        "error": str(e),
                    },
                )
                error_count += 1
            print(f"  종목 조회 오류: {e}")

        time.sleep(REQUEST_INTERVAL)

    print()
    print("=" * 72)
    print("RS3 성공/실패 분봉 구조 분석 v1 완료")
    print(f"이번 실행 완료: {completed_now}건")
    print(f"오류 기록: {error_count}건")
    print(f"결과: {OUTPUT_FILE}")
    print(f"오류: {ERROR_FILE}")
    print()
    print("주의: 이 파일은 개선 조건을 확정하는 프로그램이 아닙니다.")
    print("      원문판을 동결한 채 성공/실패 구조 차이를 찾기 위한 계측 파일입니다.")
    print("=" * 72)


if __name__ == "__main__":
    main()

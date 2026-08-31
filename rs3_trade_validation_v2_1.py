import csv
import getpass
import os
import time
from collections import defaultdict
from datetime import datetime

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
MINUTE_URL = f"{BASE_URL}/api/dostk/chart"

INPUT_CSV = "rs3_minute_entry_scan.csv"
OUTPUT_CSV = "rs3_trade_validation_v2_1.csv"
ERROR_CSV = "rs3_trade_validation_v2_1_errors.csv"

REQUEST_INTERVAL = 0.30
MAX_PAGES_PER_STOCK = 500
ENTRY_STATUS = "ENTRY_1_CANDIDATE"

OUTPUT_FIELDS = [
    "stock_code","stock_name","market","date","status",
    "daily_open","daily_high","rise_pct","traded_value_eok",
    "trigger_time","fixed_high","fixed_low",
    "buy1_price","buy2_price","take1_price","take2_price","stop70_price",
    "buy1_time","buy2_time","take1_time","take2_time","stop70_time",
    "buy1_filled","buy2_filled","take1_hit","take2_hit","stop70_hit",
    "first_exit_event","first_exit_time",
    "evaluation_last_time","evaluation_last_close",
    "mfe_pct_from_buy1","mae_pct_from_buy1",
    "max_price_after_buy1","min_price_after_buy1",
    "max_price_time","min_price_time",
    "hit_plus_5","hit_plus_7","hit_plus_10","hit_plus_15",
    "bars_after_buy1","trading_dates_evaluated",
    "intrabar_ambiguity","period_stop_rule","note",
]

def clean_number(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return abs(float(text))
    except ValueError:
        return None

def normalize_code(value):
    if value is None:
        return ""

    text = str(value).strip().upper()

    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    # 중요:
    # 최근 한국 종목코드에는 0195S0, 0001A0, 0096B0처럼
    # 영문자가 포함된 6자리 코드가 존재한다.
    # 영문자를 제거하면 전혀 다른 종목코드로 조회되므로
    # 6자리 영숫자 코드는 원형 그대로 보존한다.
    if len(text) == 6 and text.isalnum():
        return text

    # 순수 숫자 코드만 6자리 zero-padding
    if text.isdigit():
        return text.zfill(6)

    return text

def normalize_date(value):
    if value is None:
        return ""
    text = str(value).strip().replace("-", "").replace("/", "")
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:8]

def normalize_datetime_text(value):
    if value is None:
        return ""
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    return digits[:14] if len(digits) >= 14 else ""

def issue_token(appkey, secretkey):
    response = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "client_credentials",
            "appkey": appkey,
            "secretkey": secretkey,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    code = str(data.get("return_code", data.get("returnCode", "")))
    if code not in ("0", ""):
        raise RuntimeError(data.get("return_msg", data.get("returnMsg", data)))
    token = data.get("token")
    if not token:
        raise RuntimeError(f"토큰 값 없음: {data}")
    return token

def request_minute_page(token, stock_code, cont_yn=None, next_key=None):
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10080",
    }
    if cont_yn:
        headers["cont-yn"] = cont_yn
    if next_key:
        headers["next-key"] = next_key

    response = requests.post(
        MINUTE_URL,
        headers=headers,
        json={"stk_cd": stock_code, "tic_scope": "1", "upd_stkpc_tp": "1"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    code = str(data.get("return_code", data.get("returnCode", "")))
    if code not in ("0", ""):
        raise RuntimeError(data.get("return_msg", data.get("returnMsg", data)))

    rows = data.get("stk_min_pole_chart_qry", []) or []
    return (
        rows,
        response.headers.get("cont-yn") or response.headers.get("Cont-Yn") or "",
        response.headers.get("next-key") or response.headers.get("Next-Key") or "",
    )

def parse_minute_row(row):
    digits = "".join(ch for ch in str(row.get("cntr_tm", "")) if ch.isdigit())
    if len(digits) < 14:
        return None
    dt_text = digits[:14]
    try:
        dt = datetime.strptime(dt_text, "%Y%m%d%H%M%S")
    except ValueError:
        return None

    vals = [
        clean_number(row.get("open_pric")),
        clean_number(row.get("high_pric")),
        clean_number(row.get("low_pric")),
        clean_number(row.get("cur_prc")),
    ]
    if any(v is None for v in vals):
        return None

    return {
        "dt": dt,
        "dt_text": dt_text,
        "date": dt_text[:8],
        "open": vals[0],
        "high": vals[1],
        "low": vals[2],
        "close": vals[3],
    }

def fetch_stock_history(token, stock_code, oldest_needed_date):
    all_rows = []
    cont_yn = None
    next_key = None

    for _ in range(MAX_PAGES_PER_STOCK):
        rows, new_cont_yn, new_next_key = request_minute_page(
            token, stock_code, cont_yn, next_key
        )
        parsed = [p for p in (parse_minute_row(r) for r in rows) if p]
        all_rows.extend(parsed)

        if parsed and min(r["date"] for r in parsed) <= oldest_needed_date:
            break
        if str(new_cont_yn).upper() != "Y" or not new_next_key:
            break

        cont_yn = new_cont_yn
        next_key = new_next_key
        time.sleep(REQUEST_INTERVAL)

    unique = {r["dt_text"]: r for r in all_rows}
    return sorted(unique.values(), key=lambda x: x["dt"])

def load_candidates():
    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"{INPUT_CSV} 파일을 찾을 수 없습니다.")

    required = [
        "stock_code","stock_name","date","daily_open",
        "trigger_time","fixed_high","fixed_low",
        "fib50","fib618","fib70","entry1_time","status",
    ]

    out = []

    with open(INPUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        missing = [c for c in required if c not in fields]
        if missing:
            raise RuntimeError(
                "입력 CSV 필수 열 없음: "
                + ", ".join(missing)
                + f"\n현재 열: {fields}"
            )

        for row in reader:
            if str(row.get("status", "")).strip() != ENTRY_STATUS:
                continue

            item = {
                "stock_code": normalize_code(row.get("stock_code")),
                "stock_name": str(row.get("stock_name", "")).strip(),
                "market": str(row.get("market", "")).strip(),
                "date": normalize_date(row.get("date")),
                "daily_open": clean_number(row.get("daily_open")),
                "daily_high": clean_number(row.get("daily_high")),
                "rise_pct": clean_number(row.get("rise_pct")),
                "traded_value_eok": clean_number(row.get("traded_value_eok")),
                "trigger_time": normalize_datetime_text(row.get("trigger_time")),
                "fixed_high": clean_number(row.get("fixed_high")),
                "fixed_low": clean_number(row.get("fixed_low")),
                "fib50": clean_number(row.get("fib50")),
                "fib618": clean_number(row.get("fib618")),
                "fib70": clean_number(row.get("fib70")),
                "entry1_time": normalize_datetime_text(row.get("entry1_time")),
            }

            if not item["stock_code"]:
                raise RuntimeError(f"종목코드 누락 행: {row}")
            if len(item["date"]) != 8:
                raise RuntimeError(f"날짜 오류: {item['stock_code']} / {row.get('date')}")
            if len(item["trigger_time"]) != 14:
                raise RuntimeError(f"trigger_time 오류: {item['stock_code']} / {item['date']}")
            if len(item["entry1_time"]) != 14:
                raise RuntimeError(f"entry1_time 오류: {item['stock_code']} / {item['date']}")
            if any(item[k] is None for k in ["fixed_high","fixed_low","fib50","fib618","fib70"]):
                raise RuntimeError(f"동결 피보나치 값 누락: {item['stock_code']} / {item['date']}")

            out.append(item)

    return out

def ensure_header(path, fields):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()

def append_output(row):
    ensure_header(OUTPUT_CSV, OUTPUT_FIELDS)
    with open(OUTPUT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore").writerow(row)

def append_error(code, name, error):
    fields = ["stock_code","stock_name","error"]
    ensure_header(ERROR_CSV, fields)
    with open(ERROR_CSV, "a", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writerow(
            {"stock_code": code, "stock_name": name, "error": error}
        )

def group_by_date(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["date"]].append(row)
    for d in grouped:
        grouped[d].sort(key=lambda x: x["dt"])
    return grouped

def touched(row, price):
    return row["low"] <= price <= row["high"]

def rnd(v):
    return "" if v is None else round(v, 4)

def analyze(candidate, rows_by_date):
    target_date = candidate["date"]

    # 앞 단계 확정값: 절대 재계산하지 않음
    buy1 = candidate["fib50"]
    buy2 = candidate["fib618"]
    stop70 = candidate["fib70"]
    take1 = buy1 * 1.04
    take2 = buy2 * 1.04
    buy1_time = candidate["entry1_time"]

    base = {
        "stock_code": candidate["stock_code"],
        "stock_name": candidate["stock_name"],
        "market": candidate["market"],
        "date": target_date,
        "daily_open": rnd(candidate["daily_open"]),
        "daily_high": rnd(candidate["daily_high"]),
        "rise_pct": rnd(candidate["rise_pct"]),
        "traded_value_eok": rnd(candidate["traded_value_eok"]),
        "trigger_time": candidate["trigger_time"],
        "fixed_high": rnd(candidate["fixed_high"]),
        "fixed_low": rnd(candidate["fixed_low"]),
        "buy1_price": rnd(buy1),
        "buy2_price": rnd(buy2),
        "take1_price": rnd(take1),
        "take2_price": rnd(take2),
        "stop70_price": rnd(stop70),
        "buy1_time": buy1_time,
        "buy1_filled": "Y",
        "period_stop_rule": "UNRESOLVED_SOURCE_RULE",
    }

    available_dates = sorted(d for d in rows_by_date if d >= target_date)
    eval_dates = available_dates[:3]

    if not eval_dates:
        return {
            **base,
            "status": "NO_PATH_DATA",
            "note": "진입 이후 분봉 가격 경로 없음",
        }

    rows = []
    for d in eval_dates:
        rows.extend(rows_by_date[d])
    rows.sort(key=lambda x: x["dt"])

    buy1_dt = datetime.strptime(buy1_time, "%Y%m%d%H%M%S")
    path = [r for r in rows if r["dt"] >= buy1_dt]

    if not path:
        return {
            **base,
            "status": "NO_PATH_AFTER_ENTRY",
            "trading_dates_evaluated": "|".join(eval_dates),
            "note": "동결된 1차매수 시각 이후 분봉 없음",
        }

    exact_entry_bar = next((r for r in path if r["dt_text"] == buy1_time), None)

    buy2_filled = False
    take1_hit = False
    take2_hit = False
    stop70_hit = False

    buy2_time = ""
    take1_time = ""
    take2_time = ""
    stop70_time = ""

    first_exit_event = ""
    first_exit_time = ""

    active1 = True
    active2 = False
    max_price = None
    min_price = None
    max_price_time = ""
    min_price_time = ""
    ambiguous = []
    bars = 0

    for row in path:
        bars += 1

        if max_price is None or row["high"] > max_price:
            max_price = row["high"]
            max_price_time = row["dt_text"]
        if min_price is None or row["low"] < min_price:
            min_price = row["low"]
            min_price_time = row["dt_text"]

        events = []

        if active1 and touched(row, take1):
            events.append("TAKE1")
        if active1 and not buy2_filled and touched(row, buy2):
            events.append("BUY2")
        if (active1 or active2) and touched(row, stop70):
            events.append("STOP70")
        if active2 and touched(row, take2):
            events.append("TAKE2")

        event_set = set(events)
        conflict_pairs = [
            {"TAKE1","BUY2"},
            {"TAKE1","STOP70"},
            {"BUY2","STOP70"},
            {"TAKE2","STOP70"},
        ]
        conflict = any(pair.issubset(event_set) for pair in conflict_pairs)

        if conflict:
            ambiguous.append(f"{row['dt_text']}:{'/'.join(events)}")

        if "BUY2" in events and not buy2_filled:
            buy2_filled = True
            active2 = True
            buy2_time = row["dt_text"]

        if "TAKE1" in events and active1:
            take1_hit = True
            active1 = False
            take1_time = row["dt_text"]

        if "TAKE2" in events and active2:
            take2_hit = True
            active2 = False
            take2_time = row["dt_text"]

        if "STOP70" in events and (active1 or active2):
            stop70_hit = True
            stop70_time = row["dt_text"]
            active1 = False
            active2 = False

        if not first_exit_event:
            exits = [e for e in events if e in ("TAKE1","TAKE2","STOP70")]
            if exits:
                first_exit_event = "AMBIGUOUS_INTRABAR" if conflict else exits[0]
                first_exit_time = row["dt_text"]

    last_row = path[-1]
    mfe = (max_price / buy1 - 1.0) * 100.0 if max_price is not None and buy1 > 0 else None
    mae = (min_price / buy1 - 1.0) * 100.0 if min_price is not None and buy1 > 0 else None

    note_parts = [
        "트리거/A/B/피보나치/1차매수는 앞 단계 확정값 사용",
        "기간손절은 원문 기계적 정의 미확정으로 자동 판정하지 않음",
    ]
    if exact_entry_bar is None:
        note_parts.insert(
            0,
            "동결 entry1_time과 동일한 분봉이 재조회 데이터에 없으나 앞 단계 확정 진입값은 유지함"
        )

    return {
        **base,
        "status": "PATH_EXTRACTED",
        "buy2_time": buy2_time,
        "take1_time": take1_time,
        "take2_time": take2_time,
        "stop70_time": stop70_time,
        "buy2_filled": "Y" if buy2_filled else "N",
        "take1_hit": "Y" if take1_hit else "N",
        "take2_hit": "Y" if take2_hit else "N",
        "stop70_hit": "Y" if stop70_hit else "N",
        "first_exit_event": first_exit_event or "NONE_WITHIN_WINDOW",
        "first_exit_time": first_exit_time,
        "evaluation_last_time": last_row["dt_text"],
        "evaluation_last_close": rnd(last_row["close"]),
        "mfe_pct_from_buy1": rnd(mfe),
        "mae_pct_from_buy1": rnd(mae),
        "max_price_after_buy1": rnd(max_price),
        "min_price_after_buy1": rnd(min_price),
        "max_price_time": max_price_time,
        "min_price_time": min_price_time,
        "hit_plus_5": "Y" if max_price is not None and max_price >= buy1 * 1.05 else "N",
        "hit_plus_7": "Y" if max_price is not None and max_price >= buy1 * 1.07 else "N",
        "hit_plus_10": "Y" if max_price is not None and max_price >= buy1 * 1.10 else "N",
        "hit_plus_15": "Y" if max_price is not None and max_price >= buy1 * 1.15 else "N",
        "bars_after_buy1": bars,
        "trading_dates_evaluated": "|".join(eval_dates),
        "intrabar_ambiguity": ";".join(ambiguous),
        "note": " / ".join(note_parts),
    }

def main():
    print("=" * 72)
    print("Reverse SPES - RS3 실제 거래 경로 검증 v2.1")
    print("앞 단계 확정 A/B · 피보나치 · 진입시각 동결 적용")
    print("=" * 72)

    candidates = load_candidates()

    print(f"ENTRY_1_CANDIDATE 전체: {len(candidates)}건")
    print("재계산 금지: trigger / fixed A-B / fib50 / fib618 / fib70 / entry1_time")

    grouped = defaultdict(list)
    for c in candidates:
        grouped[c["stock_code"]].append(c)

    print(f"조회할 종목: {len(grouped)}개")
    print()

    # v2는 실행할 때마다 새 결과로 검증
    for path in (OUTPUT_CSV, ERROR_CSV):
        if os.path.exists(path):
            os.remove(path)

    appkey = getpass.getpass("Kiwoom App Key: ")
    secretkey = getpass.getpass("Kiwoom Secret Key: ")

    print()
    print("TOKEN 발급 중...")
    token = issue_token(appkey, secretkey)
    print("TOKEN 발급 성공")
    print()

    processed = 0
    path_ok = 0
    no_path = 0
    errors = 0

    for idx, (code, stock_candidates) in enumerate(grouped.items(), start=1):
        name = stock_candidates[0]["stock_name"]
        oldest_date = min(c["date"] for c in stock_candidates)

        print(f"[{idx}/{len(grouped)}] {code} {name} / 후보 {len(stock_candidates)}건")

        try:
            rows = fetch_stock_history(token, code, oldest_date)
            rows_by_date = group_by_date(rows)

            for c in stock_candidates:
                result = analyze(c, rows_by_date)
                append_output(result)
                processed += 1

                if result["status"] == "PATH_EXTRACTED":
                    path_ok += 1
                else:
                    no_path += 1

            print(
                f"  분봉 {len(rows):,}개 / 누적 완료 {processed}건 "
                f"/ 경로확인 {path_ok}건 / 경로없음 {no_path}건"
            )

        except KeyboardInterrupt:
            print()
            print("사용자 중단. v2는 재실행 시 처음부터 새로 검증합니다.")
            return

        except Exception as exc:
            errors += 1
            append_error(code, name, str(exc))
            print(f"  오류: {exc}")

        time.sleep(REQUEST_INTERVAL)

        if idx % 10 == 0:
            print()
            print(
                f"---- 중간 현황: 처리 {processed}/{len(candidates)} / "
                f"PATH_EXTRACTED {path_ok} / 경로없음 {no_path} / 오류종목 {errors} ----"
            )
            print()

    print()
    print("=" * 72)
    print("RS3 실제 거래 경로 검증 v2 완료")
    print(f"입력 후보: {len(candidates)}건")
    print(f"처리 후보: {processed}건")
    print(f"PATH_EXTRACTED: {path_ok}건")
    print(f"경로 없음: {no_path}건")
    print(f"오류 종목: {errors}개")
    print(f"결과: {OUTPUT_CSV}")
    print(f"오류: {ERROR_CSV}")
    print()
    print("목표: 122건 후보를 유지한 채 entry1_time 이후 경로만 검증")
    print("=" * 72)
    input("Enter를 누르면 종료합니다...")

if __name__ == "__main__":
    main()

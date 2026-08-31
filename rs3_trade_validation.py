import csv
import getpass
import os
import time
from collections import defaultdict
from datetime import datetime, time as dtime

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
MINUTE_URL = f"{BASE_URL}/api/dostk/chart"

INPUT_CSV = "rs3_minute_entry_scan.csv"
OUTPUT_CSV = "rs3_trade_validation.csv"
ERROR_CSV = "rs3_trade_validation_errors.csv"

REQUEST_INTERVAL = 0.30
MAX_PAGES_PER_STOCK = 500
ENTRY_STATUS = "ENTRY_1_CANDIDATE"

OUTPUT_FIELDS = [
    "stock_code", "stock_name", "date", "status", "daily_open",
    "trigger_time", "fixed_a", "fixed_b",
    "buy1_price", "buy2_price", "take1_price", "take2_price", "stop70_price",
    "buy1_time", "buy2_time", "take1_time", "take2_time", "stop70_time",
    "buy1_filled", "buy2_filled", "take1_hit", "take2_hit", "stop70_hit",
    "first_exit_event", "first_exit_time",
    "evaluation_last_time", "evaluation_last_close",
    "mfe_pct_from_buy1", "mae_pct_from_buy1",
    "max_price_after_buy1", "min_price_after_buy1", "max_price_time", "min_price_time",
    "hit_plus_5", "hit_plus_7", "hit_plus_10", "hit_plus_15",
    "bars_after_buy1", "trading_dates_evaluated", "period_stop_rule", "note",
]


def clean_number(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return abs(float(text))
    except ValueError:
        return None


def normalize_code(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else text


def normalize_date(value):
    if value is None:
        return ""
    text = str(value).strip().replace("-", "").replace("/", "")
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:8]


def find_header(fieldnames, candidates):
    lower_map = {name.lower(): name for name in (fieldnames or [])}
    for candidate in candidates:
        if candidate in (fieldnames or []):
            return candidate
        found = lower_map.get(candidate.lower())
        if found:
            return found
    return None


def ensure_csv_header(path, fields):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()


def append_row(path, fields, row):
    ensure_csv_header(path, fields)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writerow(row)


def issue_token(appkey, secretkey):
    response = requests.post(
        TOKEN_URL,
        json={"grant_type": "client_credentials", "appkey": appkey, "secretkey": secretkey},
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

    values = [
        clean_number(row.get("open_pric")), clean_number(row.get("high_pric")),
        clean_number(row.get("low_pric")), clean_number(row.get("cur_prc")),
    ]
    if any(v is None for v in values):
        return None

    return {
        "dt": dt, "dt_text": dt_text, "date": dt_text[:8],
        "open": values[0], "high": values[1], "low": values[2], "close": values[3],
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

    with open(INPUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []

        status_col = find_header(fields, ["status", "result_status", "scan_status"])
        code_col = find_header(fields, ["stock_code", "code", "stk_cd", "종목코드"])
        name_col = find_header(fields, ["stock_name", "name", "종목명"])
        date_col = find_header(fields, ["date", "trade_date", "candidate_date", "일자"])
        open_col = find_header(fields, ["daily_open", "open", "open_price", "시가"])

        missing = []
        for label, col in [("status", status_col), ("stock_code", code_col), ("date", date_col), ("daily_open", open_col)]:
            if not col:
                missing.append(label)
        if missing:
            raise RuntimeError(f"입력 CSV 필수 열 없음: {', '.join(missing)}\n현재 열: {fields}")

        result = []
        for row in reader:
            if str(row.get(status_col, "")).strip() != ENTRY_STATUS:
                continue
            code = normalize_code(row.get(code_col))
            date = normalize_date(row.get(date_col))
            daily_open = clean_number(row.get(open_col))
            if not code or len(date) != 8 or not daily_open:
                continue
            result.append({
                "stock_code": code,
                "stock_name": str(row.get(name_col, "")).strip() if name_col else "",
                "date": date,
                "daily_open": daily_open,
            })
        return result


def load_completed_keys():
    completed = set()
    if not os.path.exists(OUTPUT_CSV):
        return completed
    with open(OUTPUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = normalize_code(row.get("stock_code"))
            date = normalize_date(row.get("date"))
            if code and date:
                completed.add((code, date))
    return completed


def group_by_date(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["date"]].append(row)
    for date in grouped:
        grouped[date].sort(key=lambda x: x["dt"])
    return grouped


def reconstruct_levels(day_rows, daily_open):
    running_high = None
    running_low = None
    for row in day_rows:
        running_high = row["high"] if running_high is None else max(running_high, row["high"])
        running_low = row["low"] if running_low is None else min(running_low, row["low"])
        if running_high >= daily_open * 1.20:
            a, b = running_high, running_low
            k = a - b
            return {
                "trigger_time": row["dt_text"], "a": a, "b": b,
                "buy1": a - k * 0.5,
                "buy2": a - k * 0.618,
                "stop70": a - k * 0.7,
            }
    return None


def touched(row, price):
    return row["low"] <= price <= row["high"]


def rnd(value):
    return "" if value is None else round(value, 4)


def analyze(candidate, rows_by_date):
    code = candidate["stock_code"]
    name = candidate["stock_name"]
    date = candidate["date"]
    daily_open = candidate["daily_open"]
    base = {
        "stock_code": code, "stock_name": name, "date": date,
        "daily_open": daily_open, "period_stop_rule": "UNRESOLVED_SOURCE_RULE",
    }

    day_rows = rows_by_date.get(date, [])
    if not day_rows:
        return {**base, "status": "NO_MINUTE_DATA", "note": "후보일 분봉 없음"}

    levels = reconstruct_levels(day_rows, daily_open)
    if not levels:
        return {**base, "status": "NO_20_TRIGGER", "note": "+20% 트리거 재현 실패"}

    buy1 = levels["buy1"]
    buy2 = levels["buy2"]
    stop70 = levels["stop70"]
    take1 = buy1 * 1.04
    take2 = buy2 * 1.04

    buy1_row = None
    for row in day_rows:
        if row["dt"].time() >= dtime(14, 30) and touched(row, buy1):
            buy1_row = row
            break

    common = {
        **base,
        "trigger_time": levels["trigger_time"],
        "fixed_a": rnd(levels["a"]), "fixed_b": rnd(levels["b"]),
        "buy1_price": rnd(buy1), "buy2_price": rnd(buy2),
        "take1_price": rnd(take1), "take2_price": rnd(take2),
        "stop70_price": rnd(stop70),
    }

    if not buy1_row:
        return {**common, "status": "ENTRY_NOT_REPRODUCED", "note": "14:30 이후 50선 터치 재현 실패"}

    dates = sorted(d for d in rows_by_date if d >= date)[:3]
    path = []
    for d in dates:
        path.extend(rows_by_date[d])
    path = sorted((r for r in path if r["dt"] >= buy1_row["dt"]), key=lambda x: x["dt"])

    if not path:
        return {**common, "status": "NO_PATH_AFTER_ENTRY", "note": "1차 매수 이후 경로 없음"}

    buy2_filled = take1_hit = take2_hit = stop70_hit = False
    buy2_time = take1_time = take2_time = stop70_time = ""
    first_exit_event = first_exit_time = ""
    active1, active2 = True, False
    ambiguous = []

    max_price = min_price = None
    max_time = min_time = ""

    for row in path:
        if max_price is None or row["high"] > max_price:
            max_price, max_time = row["high"], row["dt_text"]
        if min_price is None or row["low"] < min_price:
            min_price, min_time = row["low"], row["dt_text"]

        events = []
        if active1 and touched(row, take1):
            events.append("TAKE1")
        if active1 and not buy2_filled and touched(row, buy2):
            events.append("BUY2")
        if (active1 or active2) and touched(row, stop70):
            events.append("STOP70")
        if active2 and touched(row, take2):
            events.append("TAKE2")

        conflicts = [
            {"TAKE1", "BUY2"}, {"TAKE1", "STOP70"},
            {"BUY2", "STOP70"}, {"TAKE2", "STOP70"},
        ]
        is_ambiguous = any(pair.issubset(set(events)) for pair in conflicts)
        if is_ambiguous:
            ambiguous.append(f"{row['dt_text']}:{'/'.join(events)}")

        if "BUY2" in events and not buy2_filled:
            buy2_filled, active2, buy2_time = True, True, row["dt_text"]
        if "TAKE1" in events and active1:
            take1_hit, active1, take1_time = True, False, row["dt_text"]
        if "TAKE2" in events and active2:
            take2_hit, active2, take2_time = True, False, row["dt_text"]
        if "STOP70" in events and (active1 or active2):
            stop70_hit, stop70_time = True, row["dt_text"]
            active1 = active2 = False

        if not first_exit_event:
            exits = [e for e in events if e in ("TAKE1", "TAKE2", "STOP70")]
            if exits:
                first_exit_event = "AMBIGUOUS_INTRABAR" if is_ambiguous else exits[0]
                first_exit_time = row["dt_text"]

    last = path[-1]
    mfe = (max_price / buy1 - 1) * 100 if max_price is not None else None
    mae = (min_price / buy1 - 1) * 100 if min_price is not None else None

    notes = []
    if ambiguous:
        notes.append("1분봉 내 이벤트 선후 불명확=" + ";".join(ambiguous))
    notes.append("기간손절은 원문 기계적 정의 미확정으로 자동 판정하지 않음")

    return {
        **common,
        "status": "PATH_EXTRACTED",
        "buy1_time": buy1_row["dt_text"], "buy2_time": buy2_time,
        "take1_time": take1_time, "take2_time": take2_time, "stop70_time": stop70_time,
        "buy1_filled": "Y", "buy2_filled": "Y" if buy2_filled else "N",
        "take1_hit": "Y" if take1_hit else "N", "take2_hit": "Y" if take2_hit else "N",
        "stop70_hit": "Y" if stop70_hit else "N",
        "first_exit_event": first_exit_event or "NONE_WITHIN_WINDOW",
        "first_exit_time": first_exit_time,
        "evaluation_last_time": last["dt_text"], "evaluation_last_close": rnd(last["close"]),
        "mfe_pct_from_buy1": rnd(mfe), "mae_pct_from_buy1": rnd(mae),
        "max_price_after_buy1": rnd(max_price), "min_price_after_buy1": rnd(min_price),
        "max_price_time": max_time, "min_price_time": min_time,
        "hit_plus_5": "Y" if max_price >= buy1 * 1.05 else "N",
        "hit_plus_7": "Y" if max_price >= buy1 * 1.07 else "N",
        "hit_plus_10": "Y" if max_price >= buy1 * 1.10 else "N",
        "hit_plus_15": "Y" if max_price >= buy1 * 1.15 else "N",
        "bars_after_buy1": len(path), "trading_dates_evaluated": "|".join(dates),
        "note": " / ".join(notes),
    }


def main():
    print("=" * 68)
    print("Reverse SPES - RS3 실제 거래 경로 검증")
    print("=" * 68)

    candidates = load_candidates()
    completed = load_completed_keys()
    pending = [c for c in candidates if (c["stock_code"], c["date"]) not in completed]

    grouped = defaultdict(list)
    for c in pending:
        grouped[c["stock_code"]].append(c)

    print(f"ENTRY_1_CANDIDATE 전체: {len(candidates)}건")
    print(f"이미 완료: {len(candidates) - len(pending)}건")
    print(f"남은 후보: {len(pending)}건")
    print(f"조회할 종목: {len(grouped)}개")
    print()

    if not pending:
        print("모든 후보가 이미 처리되었습니다.")
        return

    appkey = getpass.getpass("Kiwoom App Key: ")
    secretkey = getpass.getpass("Kiwoom Secret Key: ")

    print("\nTOKEN 발급 중...")
    token = issue_token(appkey, secretkey)
    print("TOKEN 발급 성공\n")

    processed = errors = 0

    for idx, (code, items) in enumerate(grouped.items(), 1):
        name = items[0].get("stock_name", "")
        oldest_date = min(c["date"] for c in items)
        print(f"[{idx}/{len(grouped)}] {code} {name} / 후보 {len(items)}건")

        try:
            rows = fetch_stock_history(token, code, oldest_date)
            rows_by_date = group_by_date(rows)
            for candidate in items:
                append_row(OUTPUT_CSV, OUTPUT_FIELDS, analyze(candidate, rows_by_date))
                processed += 1
            print(f"  분봉 {len(rows):,}개 / 누적 완료 {processed}건")

        except KeyboardInterrupt:
            print("\n사용자 중단. 완료분은 저장됐고 재실행 시 건너뜁니다.")
            return
        except Exception as exc:
            errors += 1
            append_row(
                ERROR_CSV,
                ["stock_code", "stock_name", "error"],
                {"stock_code": code, "stock_name": name, "error": str(exc)},
            )
            print(f"  오류: {exc}")

        time.sleep(REQUEST_INTERVAL)

        if idx % 10 == 0:
            print(f"--- 중간현황: 종목 {idx}/{len(grouped)}, 완료 {processed}/{len(pending)}, 오류 {errors} ---\n")

    print("\n" + "=" * 68)
    print("RS3 실제 거래 경로 검증 완료")
    print(f"이번 실행 완료 후보: {processed}건")
    print(f"오류 종목: {errors}개")
    print(f"결과: {OUTPUT_CSV}")
    print(f"오류: {ERROR_CSV}")
    print("- +4% / 61.8선 / 70선 이벤트 기록")
    print("- MFE/MAE 및 +5/+7/+10/+15% 도달 여부 기록")
    print("- '2일 안 반등' 기간손절은 정의 미확정이라 임의 판정하지 않음")
    print("- 같은 1분봉 내 상충 이벤트는 선후를 억지로 정하지 않음")
    print("=" * 68)


if __name__ == "__main__":
    main()

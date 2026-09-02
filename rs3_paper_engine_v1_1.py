import csv
import getpass
import json
import os
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

import requests

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
MINUTE_URL = f"{BASE_URL}/api/dostk/chart"

CANDIDATE_FILE = "rs3_paper_candidates.csv"
STATE_DIR = "rs3_paper_state"
LOG_DIR = "rs3_paper_logs"

POLL_SECONDS = 60
REQUEST_INTERVAL = 0.25

# -------------------------------------------------------------------
# RS3 SOURCE-FROZEN RULES
# -------------------------------------------------------------------
MIN_RISE_RATE = 0.20
MIN_TRADED_VALUE_EOK = 500.0
ENTRY_TIME = dtime(14, 30)

FIB50_FACTOR = 0.500
FIB618_FACTOR = 0.618
FIB70_FACTOR = 0.700
TAKE_RATE = 0.04

# -------------------------------------------------------------------
# RS3 IMPROVEMENT-FROZEN RESEARCH RULE: STAGE2 v1
# 원문 RS3가 아님. 연구동결 후보.
# -------------------------------------------------------------------
STAGE2_EARLY3_LOW_PCT = -1.5
STAGE2_EARLY3_DOWN_RATIO = 0.65

STAGE2_5M_HIGH_MAX = 1.0
STAGE2_5M_LOW_MAX = -1.0
STAGE2_5M_CLOSE_MAX = 0.0
STAGE2_5M_DOWN_RATIO = 0.70
STAGE2_5M_VOL_RATIO = 1.25
STAGE2_5M_SCORE_MIN = 4

STAGE2_FAST_618_MINUTES = 5
STAGE2_VOL_50_618_RATIO = 1.0


def normalize_code(value):
    s = str(value or "").strip().upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
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


def safe_bool(v):
    s = str(v or "").strip().upper()
    if s in {"1", "Y", "YES", "TRUE", "T"}:
        return True
    if s in {"0", "N", "NO", "FALSE", "F"}:
        return False
    return None


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

    return (
        data.get("stk_min_pole_chart_qry") or [],
        r.headers.get("cont-yn", ""),
        r.headers.get("next-key", ""),
    )


def parse_bar(raw):
    tm = str(raw.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    def p(name):
        v = safe_float(raw.get(name))
        return abs(v) if v is not None else None

    o = p("open_pric")
    h = p("high_pric")
    l = p("low_pric")
    c = p("cur_prc")
    v = safe_float(raw.get("trde_qty"), 0.0)

    if None in (o, h, l, c):
        return None

    return {
        "dt": datetime.strptime(tm, "%Y%m%d%H%M%S"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": abs(v or 0.0),
    }


def fetch_today_bars(token, code):
    raw, _, _ = request_minute_page(token, code)
    bars = [parse_bar(x) for x in raw]
    bars = [x for x in bars if x]

    today = datetime.now().strftime("%Y%m%d")
    bars = [b for b in bars if b["dt"].strftime("%Y%m%d") == today]

    uniq = {b["dt"]: b for b in bars}
    return [uniq[k] for k in sorted(uniq)]


def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def state_path(code):
    return os.path.join(STATE_DIR, f"{normalize_code(code)}.json")


def load_state(code):
    path = state_path(code)
    if not os.path.exists(path):
        return {
            "status": "WATCH",
            "trigger_time": None,
            "fixed_high": None,
            "fixed_low": None,
            "fib50": None,
            "fib618": None,
            "fib70": None,
            "take1": None,
            "take2": None,
            "before_1430_touch": False,
            "buy1_time": None,
            "buy1_price": None,
            "buy2_time": None,
            "buy2_price": None,
            "stage2_action": False,
            "t1_exit_time": None,
            "t1_exit_price": None,
            "t1_exit_reason": None,
            "t2_exit_time": None,
            "t2_exit_price": None,
            "t2_exit_reason": None,
            "m_indicator_eok": None,
            "m_probability_up": False,
        }

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(code, state):
    path = state_path(code)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_event(code, name, event, details):
    day = datetime.now().strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"rs3_paper_events_{day}.csv")
    exists = os.path.exists(path) and os.path.getsize(path) > 0

    row = {
        "time": datetime.now().strftime("%Y%m%d%H%M%S"),
        "stock_code": code,
        "stock_name": name,
        "event": event,
        "details": details,
    }

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)


def read_candidates():
    if not os.path.exists(CANDIDATE_FILE):
        raise FileNotFoundError(CANDIDATE_FILE)

    with open(CANDIDATE_FILE, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def m_indicator_eok(bars):
    total = 0.0
    for b in bars:
        typical = (b["high"] + b["open"] + b["low"] + b["close"]) / 4.0
        value_eok = typical * b["volume"] / 100000000.0
        if b["close"] > b["open"]:
            total += value_eok
        elif b["close"] < b["open"]:
            total -= value_eok
    return total


def first_trigger_bar(bars):
    if not bars:
        return None

    day_open = bars[0]["open"]
    threshold = day_open * 1.20

    for i, b in enumerate(bars):
        if max(x["high"] for x in bars[:i+1]) >= threshold:
            # lecture interpretation: fixed A/B at first bar +20% is reached
            fixed_high = max(x["high"] for x in bars[:i+1])
            fixed_low = min(x["low"] for x in bars[:i+1])
            return b, fixed_high, fixed_low

    return None


def compute_fibs(fixed_high, fixed_low):
    k = fixed_high - fixed_low
    return {
        "fib50": fixed_high - k * FIB50_FACTOR,
        "fib618": fixed_high - k * FIB618_FACTOR,
        "fib70": fixed_high - k * FIB70_FACTOR,
    }


def touched_level(bar, level):
    return bar["low"] <= level <= bar["high"]


def bars_after(bars, dt_str):
    if not dt_str:
        return []
    dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
    return [b for b in bars if b["dt"] >= dt]


def down_ratio(segment):
    if not segment:
        return None
    total = sum(b["volume"] for b in segment)
    down = sum(
        b["volume"]
        for b in segment
        if b["close"] < b["open"]
    )
    return down / total if total else None


def avg_volume(segment):
    if not segment:
        return None
    return sum(b["volume"] for b in segment) / len(segment)


def window_after_trade_minutes(bars, start_dt_str, n):
    if not start_dt_str:
        return []

    start_dt = datetime.strptime(start_dt_str, "%Y%m%d%H%M%S")
    post = [b for b in bars if b["dt"] > start_dt]
    return post[:n]


def window_before_trade_minutes(bars, start_dt_str, n):
    if not start_dt_str:
        return []

    start_dt = datetime.strptime(start_dt_str, "%Y%m%d%H%M%S")
    pre = [b for b in bars if b["dt"] < start_dt]
    return pre[-n:]


def stage2_early3(bars, state):
    seg = window_after_trade_minutes(bars, state["buy1_time"], 3)
    if len(seg) < 3:
        return False

    base = state["buy1_price"]
    low_pct = (min(b["low"] for b in seg) / base - 1.0) * 100.0
    dr = down_ratio(seg)

    return (
        low_pct <= STAGE2_EARLY3_LOW_PCT
        and dr is not None
        and dr >= STAGE2_EARLY3_DOWN_RATIO
    )


def stage2_early5(bars, state):
    seg = window_after_trade_minutes(bars, state["buy1_time"], 5)
    if len(seg) < 5:
        return False, 0

    base = state["buy1_price"]

    high_pct = (max(b["high"] for b in seg) / base - 1.0) * 100.0
    low_pct = (min(b["low"] for b in seg) / base - 1.0) * 100.0
    close_pct = (seg[-1]["close"] / base - 1.0) * 100.0
    dr = down_ratio(seg)

    pre30 = window_before_trade_minutes(bars, state["buy1_time"], 30)
    pre_avg = avg_volume(pre30)
    seg_avg = avg_volume(seg)
    vol_ratio = (
        seg_avg / pre_avg
        if pre_avg not in (None, 0) and seg_avg is not None
        else None
    )

    score = 0
    if high_pct < STAGE2_5M_HIGH_MAX:
        score += 1
    if low_pct <= STAGE2_5M_LOW_MAX:
        score += 1
    if close_pct < STAGE2_5M_CLOSE_MAX:
        score += 1
    if dr is not None and dr >= STAGE2_5M_DOWN_RATIO:
        score += 1
    if vol_ratio is not None and vol_ratio >= STAGE2_5M_VOL_RATIO:
        score += 1

    return score >= STAGE2_5M_SCORE_MIN, score


def trading_minutes_between(bars, start_str, end_dt):
    if not start_str:
        return None
    start_dt = datetime.strptime(start_str, "%Y%m%d%H%M%S")
    return sum(1 for b in bars if start_dt < b["dt"] <= end_dt)


def stage2_vol_50_to_618(bars, state, end_dt):
    if not state["buy1_time"]:
        return None

    start_dt = datetime.strptime(state["buy1_time"], "%Y%m%d%H%M%S")
    seg = [b for b in bars if start_dt < b["dt"] <= end_dt]
    pre30 = window_before_trade_minutes(bars, state["buy1_time"], 30)

    seg_avg = avg_volume(seg)
    pre_avg = avg_volume(pre30)

    if seg_avg is None or pre_avg in (None, 0):
        return None
    return seg_avg / pre_avg


def unresolved_exclusions(row):
    required = [
        "is_force_stock",
        "is_new_listing",
        "is_tusang_or_higher",
        "is_short_overheat_today",
    ]
    return [k for k in required if safe_bool(row.get(k)) is None]


def exclusion_result(row):
    unresolved = unresolved_exclusions(row)
    if unresolved:
        return None, "UNRESOLVED:" + ",".join(unresolved)

    if safe_bool(row.get("is_force_stock")) is not True:
        return True, "NOT_FORCE_STOCK"
    if safe_bool(row.get("is_new_listing")) is True:
        return True, "NEW_LISTING"
    if safe_bool(row.get("is_tusang_or_higher")) is True:
        return True, "TUSANG_OR_HIGHER"
    if safe_bool(row.get("is_short_overheat_today")) is True:
        return True, "SHORT_OVERHEAT_TODAY"

    return False, ""


def process_candidate(token, row):
    code = normalize_code(row.get("stock_code"))
    name = str(row.get("stock_name", "")).strip()
    state = load_state(code)

    bars = fetch_today_bars(token, code)
    if not bars:
        return

    traded_value_eok = safe_float(row.get("traded_value_eok"))
    if traded_value_eok is None or traded_value_eok < MIN_TRADED_VALUE_EOK:
        if state["status"] != "VALUE_GATE_FAIL":
            state["status"] = "VALUE_GATE_FAIL"
            append_event(
                code, name, "VALUE_GATE_FAIL",
                f"traded_value_eok={traded_value_eok}"
            )
            save_state(code, state)
        return

    ex, reason = exclusion_result(row)
    if ex is None:
        state["status"] = "PENDING_REVIEW"
        append_event(code, name, "PENDING_REVIEW", reason)
        save_state(code, state)
        return

    if ex is True:
        state["status"] = "EXCLUDED"
        append_event(code, name, "EXCLUDED", reason)
        save_state(code, state)
        return

    trigger = first_trigger_bar(bars)
    if trigger is None:
        return

    trigger_bar, fixed_high, fixed_low = trigger

    if state["trigger_time"] is None:
        fibs = compute_fibs(fixed_high, fixed_low)
        state["trigger_time"] = trigger_bar["dt"].strftime("%Y%m%d%H%M%S")
        state["fixed_high"] = fixed_high
        state["fixed_low"] = fixed_low
        state.update(fibs)
        state["take1"] = fibs["fib50"] * (1.0 + TAKE_RATE)
        state["take2"] = fibs["fib618"] * (1.0 + TAKE_RATE)

        # Source exclusion: 14:30 전에 50선 이미 터치했는지
        pre1430 = [
            b for b in bars
            if b["dt"].time() < ENTRY_TIME
            and b["dt"] >= trigger_bar["dt"]
        ]
        state["before_1430_touch"] = any(
            touched_level(b, state["fib50"])
            for b in pre1430
        )

        append_event(
            code, name, "TRIGGER_FIXED",
            (
                f"A={fixed_high},B={fixed_low},"
                f"fib50={state['fib50']:.2f},"
                f"fib618={state['fib618']:.2f},"
                f"fib70={state['fib70']:.2f},"
                f"before1430={state['before_1430_touch']}"
            )
        )

    state["m_indicator_eok"] = round(m_indicator_eok(bars), 4)
    state["m_probability_up"] = state["m_indicator_eok"] >= 200.0

    if state["before_1430_touch"]:
        state["status"] = "EXCLUDED_PRE1430_TOUCH"
        save_state(code, state)
        return

    # 1차 진입
    if state["buy1_time"] is None:
        eligible = [
            b for b in bars
            if b["dt"].time() >= ENTRY_TIME
            and b["dt"] >= trigger_bar["dt"]
        ]
        hit = next(
            (b for b in eligible if touched_level(b, state["fib50"])),
            None
        )

        if hit:
            state["buy1_time"] = hit["dt"].strftime("%Y%m%d%H%M%S")
            state["buy1_price"] = state["fib50"]
            state["status"] = "BUY1_FILLED"
            append_event(
                code, name, "PAPER_BUY1",
                (
                    f"price={state['buy1_price']:.2f},"
                    f"M={state['m_indicator_eok']:.2f},"
                    f"M200={state['m_probability_up']}"
                )
            )
            save_state(code, state)
        else:
            state["status"] = "WAIT_BUY1"
            save_state(code, state)
            return

    # 1차 익절/70선은 항상 감시
    active = bars_after(bars, state["buy1_time"])

    if state["t1_exit_time"] is None:
        for b in active:
            hit_tp = b["high"] >= state["take1"]
            hit_stop = b["low"] <= state["fib70"]

            if hit_tp and hit_stop:
                append_event(
                    code, name, "AMBIGUOUS_T1",
                    b["dt"].strftime("%Y%m%d%H%M%S")
                )
                break

            if hit_tp:
                state["t1_exit_time"] = b["dt"].strftime("%Y%m%d%H%M%S")
                state["t1_exit_price"] = state["take1"]
                state["t1_exit_reason"] = "TAKE1"
                append_event(
                    code, name, "PAPER_T1_EXIT",
                    f"TAKE1 price={state['take1']:.2f}"
                )
                break

            if hit_stop:
                state["t1_exit_time"] = b["dt"].strftime("%Y%m%d%H%M%S")
                state["t1_exit_price"] = state["fib70"]
                state["t1_exit_reason"] = "STOP70"
                append_event(
                    code, name, "PAPER_T1_EXIT",
                    f"STOP70 price={state['fib70']:.2f}"
                )
                break

    # 61.8 도달 감지 및 STAGE2
    if state["buy2_time"] is None and not state["stage2_action"]:
        b618 = next(
            (
                b for b in active
                if touched_level(b, state["fib618"])
            ),
            None
        )

        if b618:
            early3 = stage2_early3(bars, state)
            early5, score5 = stage2_early5(bars, state)

            mins = trading_minutes_between(
                bars, state["buy1_time"], b618["dt"]
            )
            vol_ratio = stage2_vol_50_to_618(
                bars, state, b618["dt"]
            )

            stage2_pressure = (
                (mins is not None and mins <= STAGE2_FAST_618_MINUTES)
                or (
                    vol_ratio is not None
                    and vol_ratio >= STAGE2_VOL_50_618_RATIO
                )
            )

            if (early3 or early5) and stage2_pressure:
                state["stage2_action"] = True
                state["status"] = "STAGE2_DEFENSE"
                # Improvement rule: 1차 방어 / 2차 취소
                if state["t1_exit_time"] is None:
                    state["t1_exit_time"] = b618["dt"].strftime(
                        "%Y%m%d%H%M%S"
                    )
                    state["t1_exit_price"] = state["fib618"]
                    state["t1_exit_reason"] = "STAGE2_DEFENSE"

                append_event(
                    code, name, "STAGE2_DEFENSE",
                    (
                        f"early3={early3},early5={early5},score5={score5},"
                        f"mins50to618={mins},vol_ratio={vol_ratio}"
                    )
                )
            else:
                # Source RS3: 2차 매수 61.8
                state["buy2_time"] = b618["dt"].strftime("%Y%m%d%H%M%S")
                state["buy2_price"] = state["fib618"]
                state["status"] = "BUY2_FILLED"
                append_event(
                    code, name, "PAPER_BUY2",
                    (
                        f"price={state['buy2_price']:.2f},"
                        f"early3={early3},early5={early5},score5={score5},"
                        f"mins50to618={mins},vol_ratio={vol_ratio}"
                    )
                )

    # 2차 익절/70선
    if state["buy2_time"] and state["t2_exit_time"] is None:
        active2 = bars_after(bars, state["buy2_time"])

        for b in active2:
            hit_tp = b["high"] >= state["take2"]
            hit_stop = b["low"] <= state["fib70"]

            if hit_tp and hit_stop:
                append_event(
                    code, name, "AMBIGUOUS_T2",
                    b["dt"].strftime("%Y%m%d%H%M%S")
                )
                break

            if hit_tp:
                state["t2_exit_time"] = b["dt"].strftime("%Y%m%d%H%M%S")
                state["t2_exit_price"] = state["take2"]
                state["t2_exit_reason"] = "TAKE2"
                append_event(
                    code, name, "PAPER_T2_EXIT",
                    f"TAKE2 price={state['take2']:.2f}"
                )
                break

            if hit_stop:
                state["t2_exit_time"] = b["dt"].strftime("%Y%m%d%H%M%S")
                state["t2_exit_price"] = state["fib70"]
                state["t2_exit_reason"] = "STOP70"
                append_event(
                    code, name, "PAPER_T2_EXIT",
                    f"STOP70 price={state['fib70']:.2f}"
                )
                break

    if (
        state["t1_exit_time"]
        and (state["stage2_action"] or not state["buy2_time"] or state["t2_exit_time"])
    ):
        if state["stage2_action"]:
            state["status"] = "CLOSED_STAGE2"
        elif state["buy2_time"] and state["t2_exit_time"]:
            state["status"] = "CLOSED"
        elif not state["buy2_time"]:
            state["status"] = "T1_CLOSED_WAIT"

    save_state(code, state)


def reset_daily_state_if_needed():
    marker = os.path.join(STATE_DIR, "_day.txt")
    today = datetime.now().strftime("%Y%m%d")

    old = ""
    if os.path.exists(marker):
        old = Path(marker).read_text(encoding="utf-8").strip()

    if old != today:
        for fn in os.listdir(STATE_DIR):
            if fn.endswith(".json"):
                try:
                    os.remove(os.path.join(STATE_DIR, fn))
                except Exception:
                    pass
        Path(marker).write_text(today, encoding="utf-8")


def main():
    print("=" * 92)
    print("Reverse SPES - RS3 PAPER Forward Engine v1.1")
    print("실제 주문 없음 / 원문 RS3 + STAGE2 v1 연구동결 후보를 병렬 기록")
    print("=" * 92)

    ensure_dirs()
    reset_daily_state_if_needed()

    if not os.path.exists(CANDIDATE_FILE):
        print(f"[ERROR] 후보파일 없음: {CANDIDATE_FILE}")
        print("템플릿 CSV를 같은 폴더에 두고 후보를 입력하십시오.")
        sys.exit(1)

    candidates = read_candidates()
    print(f"후보 종목: {len(candidates)}개")
    print("실제 주문 기능: OFF")
    print(f"폴링주기: {POLL_SECONDS}초")
    print()

    appkey = getpass.getpass("Kiwoom App Key: ")
    secret = getpass.getpass("Kiwoom Secret Key: ")

    print("\nTOKEN 발급 중...")
    token = get_token(appkey, secret)
    print("TOKEN 발급 성공")
    print()
    print("종료: Ctrl+C")
    print()

    try:
        while True:
            cycle_start = datetime.now()

            for idx, row in enumerate(candidates, start=1):
                code = normalize_code(row.get("stock_code"))
                name = str(row.get("stock_name", "")).strip()

                try:
                    process_candidate(token, row)
                    state = load_state(code)
                    print(
                        f"[{cycle_start:%H:%M:%S}] "
                        f"{idx}/{len(candidates)} {code} {name} "
                        f"=> {state.get('status')}"
                    )
                except Exception as e:
                    print(f"[ERROR] {code} {name}: {e}")
                    append_event(code, name, "ERROR", str(e))

                time.sleep(REQUEST_INTERVAL)

            elapsed = (datetime.now() - cycle_start).total_seconds()
            sleep_for = max(1, POLL_SECONDS - elapsed)
            print(
                f"--- cycle done {datetime.now():%H:%M:%S} "
                f"/ next ~{int(sleep_for)}s ---"
            )
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\nPAPER 엔진 종료")


if __name__ == "__main__":
    main()

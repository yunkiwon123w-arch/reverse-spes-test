import csv
import getpass
import json
import os
import sys
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path

import requests

# ============================================================
# Reverse SPES - RS3 PAPER Integrated v2
# 실제 주문 없음
# - 전 종목 자동 스캔
# - +20% & 거래대금 500억 이상 후보 자동 생성
# - 후보 분봉 감시
# - 원문 RS3 PAPER 기록
# - STAGE2 v1 개선판 신호 병렬 기록
# ============================================================

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"

STOCKINFO_URL = f"{BASE_URL}/api/dostk/stkinfo"
CHART_URL = f"{BASE_URL}/api/dostk/chart"

API_STOCK_LIST = "ka10099"
API_DAILY = "ka10081"
API_MINUTE = "ka10080"

CANDIDATE_FILE = "rs3_paper_candidates_auto.csv"
STATE_DIR = "rs3_paper_state_v2"
LOG_DIR = "rs3_paper_logs_v2"
CACHE_DIR = "rs3_paper_runtime_cache"

MARKET_OPEN = dtime(9, 0)
ENTRY_TIME = dtime(14, 30)
MARKET_CLOSE = dtime(15, 30)

# 전체시장 재스캔 주기: 한 번 스캔 완료 후 10분 대기
FULL_SCAN_REST_SECONDS = 600

# 후보 분봉 감시 주기
MONITOR_POLL_SECONDS = 60

# Kiwoom 국내 조회 제한 5/sec보다 보수적으로
API_MIN_INTERVAL = 0.24

# 원문 RS3
MIN_RISE_RATE = 0.20
MIN_TRADED_VALUE_EOK = 500.0
TAKE_RATE = 0.04

# 후보의 수동검토 항목
MANUAL_FIELDS = [
    "is_force_stock",
    "is_new_listing",
    "is_tusang_or_higher",
    "is_short_overheat_today",
]

# STAGE2 v1 연구동결 조건
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


FILE_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


class RateLimiter:
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            gap = now - self.last
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
            self.last = time.monotonic()


RATE = RateLimiter(API_MIN_INTERVAL)


def now():
    return datetime.now()


def market_phase():
    t = now().time()
    if t < MARKET_OPEN:
        return "BEFORE_OPEN"
    if t <= MARKET_CLOSE:
        return "OPEN"
    return "CLOSED"


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
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return default


def abs_float(v, default=None):
    x = safe_float(v, default)
    return abs(x) if x is not None else default


def safe_bool(v):
    s = str(v or "").strip().upper()
    if s in {"1", "Y", "YES", "TRUE", "T"}:
        return True
    if s in {"0", "N", "NO", "FALSE", "F"}:
        return False
    return None


def request_post(url, headers, body, timeout=30):
    RATE.wait()
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r


def get_token(appkey, secretkey):
    r = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "client_credentials",
            "appkey": appkey,
            "secretkey": secretkey,
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"TOKEN 발급 실패: {data}")
    return token


def auth_headers(token, api_id):
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": api_id,
    }


# ------------------------------------------------------------
# 종목 리스트
# ------------------------------------------------------------

def fetch_stock_list(token, market_type):
    r = request_post(
        STOCKINFO_URL,
        auth_headers(token, API_STOCK_LIST),
        {"mrkt_tp": str(market_type)},
    )
    data = r.json()
    rows = data.get("list") or []

    out = []
    for x in rows:
        code = normalize_code(
            x.get("code")
            or x.get("stk_cd")
            or x.get("stock_code")
            or x.get("종목코드")
        )
        name = str(
            x.get("name")
            or x.get("stk_nm")
            or x.get("stock_name")
            or x.get("종목명")
            or ""
        ).strip()

        if code:
            out.append({
                "stock_code": code,
                "stock_name": name,
                "market": "KOSPI" if str(market_type) == "0" else "KOSDAQ",
            })
    return out


def universe_path():
    return os.path.join(
        CACHE_DIR,
        f"rs3_universe_{now():%Y%m%d}.csv"
    )


def load_or_fetch_universe(token):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = universe_path()

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            return rows

    kospi = fetch_stock_list(token, "0")
    kosdaq = fetch_stock_list(token, "10")

    rows = kospi + kosdaq
    uniq = {}
    for r in rows:
        uniq[r["stock_code"]] = r
    rows = list(uniq.values())

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["stock_code", "stock_name", "market"]
        )
        w.writeheader()
        w.writerows(rows)

    return rows


# ------------------------------------------------------------
# 일봉 스캔
# ------------------------------------------------------------

def fetch_today_daily(token, code):
    today = now().strftime("%Y%m%d")
    r = request_post(
        CHART_URL,
        auth_headers(token, API_DAILY),
        {
            "stk_cd": code,
            "base_dt": today,
            "upd_stkpc_tp": "1",
        },
    )
    data = r.json()
    rows = data.get("stk_dt_pole_chart_qry") or []

    if not rows:
        return None

    # 기준일(today)과 맞는 행 우선
    chosen = None
    for x in rows:
        dt = str(
            x.get("dt")
            or x.get("date")
            or x.get("base_dt")
            or ""
        ).strip()
        if dt == today:
            chosen = x
            break

    if chosen is None:
        chosen = rows[0]

    open_price = abs_float(
        chosen.get("open_pric") or chosen.get("open") or chosen.get("시가")
    )
    high_price = abs_float(
        chosen.get("high_pric") or chosen.get("high") or chosen.get("고가")
    )
    traded_raw = abs_float(
        chosen.get("trde_prica")
        or chosen.get("trading_value")
        or chosen.get("거래대금")
    )

    if not open_price or high_price is None or traded_raw is None:
        return None

    # 기존 검증에서 Kiwoom trde_prica를 백만원으로 해석
    traded_value_eok = traded_raw / 100.0
    rise_pct = (high_price / open_price - 1.0) * 100.0

    return {
        "open_price": open_price,
        "day_high": high_price,
        "rise_pct": rise_pct,
        "traded_value_eok": traded_value_eok,
    }


def read_existing_manual_flags():
    if not os.path.exists(CANDIDATE_FILE):
        return {}

    with FILE_LOCK:
        try:
            with open(
                CANDIDATE_FILE,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as f:
                rows = list(csv.DictReader(f))
        except Exception:
            return {}

    result = {}
    for r in rows:
        code = normalize_code(r.get("stock_code"))
        if not code:
            continue
        result[code] = {
            k: str(r.get(k, "")).strip()
            for k in MANUAL_FIELDS
        }
    return result


CANDIDATE_FIELDS = [
    "stock_code",
    "stock_name",
    "market",
    "scan_time",
    "open_price",
    "day_high",
    "rise_pct",
    "traded_value_eok",
    "is_force_stock",
    "is_new_listing",
    "is_tusang_or_higher",
    "is_short_overheat_today",
    "review_status",
]


def merge_write_candidates(new_candidates):
    existing_flags = read_existing_manual_flags()

    current = {}
    if os.path.exists(CANDIDATE_FILE):
        with FILE_LOCK:
            try:
                with open(
                    CANDIDATE_FILE,
                    "r",
                    encoding="utf-8-sig",
                    newline=""
                ) as f:
                    for r in csv.DictReader(f):
                        code = normalize_code(r.get("stock_code"))
                        if code:
                            current[code] = r
            except Exception:
                pass

    for r in new_candidates:
        code = normalize_code(r["stock_code"])
        old = current.get(code, {})

        merged = {
            "stock_code": code,
            "stock_name": r.get("stock_name", old.get("stock_name", "")),
            "market": r.get("market", old.get("market", "")),
            "scan_time": r.get("scan_time", ""),
            "open_price": r.get("open_price", ""),
            "day_high": r.get("day_high", ""),
            "rise_pct": r.get("rise_pct", ""),
            "traded_value_eok": r.get("traded_value_eok", ""),
        }

        flags = existing_flags.get(code, {})
        for k in MANUAL_FIELDS:
            merged[k] = flags.get(k, old.get(k, ""))

        unresolved = [
            k for k in MANUAL_FIELDS
            if safe_bool(merged.get(k)) is None
        ]
        merged["review_status"] = (
            "READY" if not unresolved else "PENDING_REVIEW"
        )
        current[code] = merged

    rows = sorted(
        current.values(),
        key=lambda x: (
            -safe_float(x.get("traded_value_eok"), 0.0),
            x.get("stock_code", "")
        )
    )

    tmp = CANDIDATE_FILE + ".tmp"
    with FILE_LOCK:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CANDIDATE_FIELDS)
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in CANDIDATE_FIELDS})
        os.replace(tmp, CANDIDATE_FILE)


def full_market_scanner(token):
    while not STOP_EVENT.is_set():
        if market_phase() != "OPEN":
            break

        try:
            universe = load_or_fetch_universe(token)
            total = len(universe)
            found_now = 0
            scan_start = now()

            print(
                f"\n[SCANNER] 전체시장 스캔 시작 "
                f"{scan_start:%H:%M:%S} / {total}종목"
            )

            batch_candidates = []

            for idx, stock in enumerate(universe, start=1):
                if STOP_EVENT.is_set() or market_phase() != "OPEN":
                    break

                code = normalize_code(stock["stock_code"])

                try:
                    d = fetch_today_daily(token, code)
                    if d:
                        if (
                            d["rise_pct"] >= MIN_RISE_RATE * 100.0
                            and d["traded_value_eok"] >= MIN_TRADED_VALUE_EOK
                        ):
                            batch_candidates.append({
                                "stock_code": code,
                                "stock_name": stock.get("stock_name", ""),
                                "market": stock.get("market", ""),
                                "scan_time": now().strftime("%Y%m%d%H%M%S"),
                                "open_price": round(d["open_price"], 4),
                                "day_high": round(d["day_high"], 4),
                                "rise_pct": round(d["rise_pct"], 4),
                                "traded_value_eok": round(
                                    d["traded_value_eok"], 4
                                ),
                            })
                            found_now += 1

                    if idx % 250 == 0:
                        if batch_candidates:
                            merge_write_candidates(batch_candidates)
                            batch_candidates = []
                        print(
                            f"[SCANNER] {idx}/{total} "
                            f"/ 현재 후보 {found_now}건"
                        )

                except Exception as e:
                    append_system_log(
                        "SCANNER_ERROR",
                        f"{code} {stock.get('stock_name','')}: {e}"
                    )

            if batch_candidates:
                merge_write_candidates(batch_candidates)

            print(
                f"[SCANNER] 스캔 종료 {now():%H:%M:%S} "
                f"/ 이번 스캔 후보 {found_now}건"
            )

        except Exception as e:
            print(f"[SCANNER ERROR] {e}")
            append_system_log("SCANNER_FATAL", str(e))

        for _ in range(FULL_SCAN_REST_SECONDS):
            if STOP_EVENT.is_set() or market_phase() != "OPEN":
                break
            time.sleep(1)


# ------------------------------------------------------------
# PAPER 엔진
# ------------------------------------------------------------

def parse_bar(raw):
    tm = str(raw.get("cntr_tm", "")).strip()
    if len(tm) != 14 or not tm.isdigit():
        return None

    def p(name):
        return abs_float(raw.get(name))

    o = p("open_pric")
    h = p("high_pric")
    l = p("low_pric")
    c = p("cur_prc")
    v = abs_float(raw.get("trde_qty"), 0.0)

    if None in (o, h, l, c):
        return None

    return {
        "dt": datetime.strptime(tm, "%Y%m%d%H%M%S"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v or 0.0,
    }


def fetch_today_bars(token, code):
    r = request_post(
        CHART_URL,
        auth_headers(token, API_MINUTE),
        {
            "stk_cd": code,
            "tic_scope": "1",
            "upd_stkpc_tp": "1",
        },
    )
    data = r.json()
    raw = data.get("stk_min_pole_chart_qry") or []

    bars = [parse_bar(x) for x in raw]
    bars = [x for x in bars if x]

    today = now().strftime("%Y%m%d")
    bars = [b for b in bars if b["dt"].strftime("%Y%m%d") == today]

    uniq = {b["dt"]: b for b in bars}
    return [uniq[k] for k in sorted(uniq)]


def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)


def append_system_log(event, details):
    ensure_dirs()
    path = os.path.join(
        LOG_DIR,
        f"rs3_system_{now():%Y%m%d}.csv"
    )
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    row = {
        "time": now().strftime("%Y%m%d%H%M%S"),
        "event": event,
        "details": details,
    }
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)


def state_path(code):
    return os.path.join(STATE_DIR, f"{normalize_code(code)}.json")


def default_state():
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


def load_state(code):
    path = state_path(code)
    if not os.path.exists(path):
        return default_state()

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_state()


def save_state(code, state):
    path = state_path(code)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_event(code, name, event, details):
    ensure_dirs()
    path = os.path.join(
        LOG_DIR,
        f"rs3_paper_events_{now():%Y%m%d}.csv"
    )
    exists = os.path.exists(path) and os.path.getsize(path) > 0

    row = {
        "time": now().strftime("%Y%m%d%H%M%S"),
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
        return []

    with FILE_LOCK:
        with open(
            CANDIDATE_FILE,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:
            return list(csv.DictReader(f))


def m_indicator_eok(bars):
    total = 0.0
    for b in bars:
        typical = (
            b["high"] + b["open"] + b["low"] + b["close"]
        ) / 4.0
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

    running_high = None
    running_low = None

    for b in bars:
        running_high = (
            b["high"] if running_high is None
            else max(running_high, b["high"])
        )
        running_low = (
            b["low"] if running_low is None
            else min(running_low, b["low"])
        )

        if running_high >= threshold:
            return b, running_high, running_low

    return None


def compute_fibs(fixed_high, fixed_low):
    k = fixed_high - fixed_low
    return {
        "fib50": fixed_high - k * 0.500,
        "fib618": fixed_high - k * 0.618,
        "fib70": fixed_high - k * 0.700,
    }


def touched_level(bar, level):
    return bar["low"] <= level <= bar["high"]


def bars_after(bars, dt_str):
    if not dt_str:
        return []
    dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
    return [b for b in bars if b["dt"] >= dt]


def avg_volume(segment):
    if not segment:
        return None
    return sum(b["volume"] for b in segment) / len(segment)


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


def window_after(bars, start_str, n):
    if not start_str:
        return []
    start = datetime.strptime(start_str, "%Y%m%d%H%M%S")
    return [b for b in bars if b["dt"] > start][:n]


def window_before(bars, start_str, n):
    if not start_str:
        return []
    start = datetime.strptime(start_str, "%Y%m%d%H%M%S")
    pre = [b for b in bars if b["dt"] < start]
    return pre[-n:]


def stage2_early3(bars, state):
    seg = window_after(bars, state["buy1_time"], 3)
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
    seg = window_after(bars, state["buy1_time"], 5)
    if len(seg) < 5:
        return False, 0

    base = state["buy1_price"]
    high_pct = (max(b["high"] for b in seg) / base - 1.0) * 100.0
    low_pct = (min(b["low"] for b in seg) / base - 1.0) * 100.0
    close_pct = (seg[-1]["close"] / base - 1.0) * 100.0
    dr = down_ratio(seg)

    pre30 = window_before(bars, state["buy1_time"], 30)
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
    start = datetime.strptime(start_str, "%Y%m%d%H%M%S")
    return sum(1 for b in bars if start < b["dt"] <= end_dt)


def stage2_vol_50_to_618(bars, state, end_dt):
    start = datetime.strptime(state["buy1_time"], "%Y%m%d%H%M%S")
    seg = [b for b in bars if start < b["dt"] <= end_dt]
    pre30 = window_before(bars, state["buy1_time"], 30)
    seg_avg = avg_volume(seg)
    pre_avg = avg_volume(pre30)

    if seg_avg is None or pre_avg in (None, 0):
        return None
    return seg_avg / pre_avg


def unresolved_manual(row):
    return [
        k for k in MANUAL_FIELDS
        if safe_bool(row.get(k)) is None
    ]


def exclusion_result(row):
    unresolved = unresolved_manual(row)
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

    ex, reason = exclusion_result(row)
    if ex is None:
        if state["status"] != "PENDING_REVIEW":
            state["status"] = "PENDING_REVIEW"
            append_event(code, name, "PENDING_REVIEW", reason)
            save_state(code, state)
        return

    if ex is True:
        if state["status"] != "EXCLUDED":
            state["status"] = "EXCLUDED"
            append_event(code, name, "EXCLUDED", reason)
            save_state(code, state)
        return

    bars = fetch_today_bars(token, code)
    if not bars:
        return

    trigger = first_trigger_bar(bars)
    if trigger is None:
        state["status"] = "WAIT_TRIGGER"
        save_state(code, state)
        return

    trigger_bar, fixed_high, fixed_low = trigger

    if state["trigger_time"] is None:
        fibs = compute_fibs(fixed_high, fixed_low)
        state["trigger_time"] = trigger_bar["dt"].strftime("%Y%m%d%H%M%S")
        state["fixed_high"] = fixed_high
        state["fixed_low"] = fixed_low
        state.update(fibs)
        state["take1"] = state["fib50"] * 1.04
        state["take2"] = state["fib618"] * 1.04

        pre1430 = [
            b for b in bars
            if trigger_bar["dt"] <= b["dt"]
            and b["dt"].time() < ENTRY_TIME
        ]
        state["before_1430_touch"] = any(
            touched_level(b, state["fib50"])
            for b in pre1430
        )

        append_event(
            code,
            name,
            "TRIGGER_FIXED",
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

    # 14:30 이후 50선 1차 PAPER 진입
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

        if hit is None:
            state["status"] = "WAIT_BUY1"
            save_state(code, state)
            return

        state["buy1_time"] = hit["dt"].strftime("%Y%m%d%H%M%S")
        state["buy1_price"] = state["fib50"]
        state["status"] = "BUY1_FILLED"
        append_event(
            code,
            name,
            "PAPER_BUY1",
            (
                f"price={state['buy1_price']:.2f},"
                f"M={state['m_indicator_eok']:.2f},"
                f"M200={state['m_probability_up']}"
            )
        )

    active = bars_after(bars, state["buy1_time"])

    # 61.8 + STAGE2 / 2차매수 판정
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

            pressure = (
                mins <= STAGE2_FAST_618_MINUTES
                or (
                    vol_ratio is not None
                    and vol_ratio >= STAGE2_VOL_50_618_RATIO
                )
            )

            if (early3 or early5) and pressure:
                state["stage2_action"] = True
                state["status"] = "STAGE2_DEFENSE"

                if state["t1_exit_time"] is None:
                    state["t1_exit_time"] = b618["dt"].strftime(
                        "%Y%m%d%H%M%S"
                    )
                    state["t1_exit_price"] = state["fib618"]
                    state["t1_exit_reason"] = "STAGE2_DEFENSE"

                append_event(
                    code,
                    name,
                    "STAGE2_DEFENSE",
                    (
                        f"early3={early3},early5={early5},"
                        f"score5={score5},mins50to618={mins},"
                        f"vol_ratio={vol_ratio}"
                    )
                )
            else:
                state["buy2_time"] = b618["dt"].strftime("%Y%m%d%H%M%S")
                state["buy2_price"] = state["fib618"]
                state["status"] = "BUY2_FILLED"
                append_event(
                    code,
                    name,
                    "PAPER_BUY2",
                    (
                        f"price={state['buy2_price']:.2f},"
                        f"early3={early3},early5={early5},"
                        f"score5={score5},mins50to618={mins},"
                        f"vol_ratio={vol_ratio}"
                    )
                )

    # 1차 익절/70선
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

    if state["stage2_action"]:
        state["status"] = "CLOSED_STAGE2"
    elif state["buy2_time"] and state["t2_exit_time"]:
        state["status"] = "CLOSED"
    elif state["t1_exit_time"] and not state["buy2_time"]:
        state["status"] = "T1_CLOSED_WAIT"

    save_state(code, state)


def reset_daily_state_if_needed():
    ensure_dirs()
    marker = os.path.join(STATE_DIR, "_day.txt")
    today = now().strftime("%Y%m%d")

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


def monitor_candidates(token):
    while not STOP_EVENT.is_set():
        phase = market_phase()
        if phase == "CLOSED":
            break

        if phase == "BEFORE_OPEN":
            time.sleep(10)
            continue

        cycle_start = now()
        rows = read_candidates()

        if rows:
            for idx, row in enumerate(rows, start=1):
                if STOP_EVENT.is_set() or market_phase() == "CLOSED":
                    break

                code = normalize_code(row.get("stock_code"))
                name = str(row.get("stock_name", "")).strip()

                try:
                    process_candidate(token, row)
                    st = load_state(code)
                    print(
                        f"[MON {cycle_start:%H:%M:%S}] "
                        f"{idx}/{len(rows)} {code} {name} "
                        f"=> {st.get('status')}"
                    )
                except Exception as e:
                    print(f"[MON ERROR] {code} {name}: {e}")
                    append_event(code, name, "ERROR", str(e))
        else:
            print(
                f"[MON {cycle_start:%H:%M:%S}] "
                f"후보 없음 / scanner 동작 중"
            )

        elapsed = (now() - cycle_start).total_seconds()
        wait = max(1, MONITOR_POLL_SECONDS - elapsed)

        for _ in range(int(wait)):
            if STOP_EVENT.is_set() or market_phase() == "CLOSED":
                break
            time.sleep(1)


def main():
    print("=" * 96)
    print("Reverse SPES - RS3 PAPER 통합 v2")
    print("전종목 자동스캔 + 후보자동등록 + PAPER 감시 + STAGE2 v1")
    print("실제 주문 기능: OFF")
    print("=" * 96)

    ensure_dirs()
    reset_daily_state_if_needed()

    phase = market_phase()
    if phase == "CLOSED":
        print(
            f"현재 {now():%H:%M:%S} / 장 종료 후입니다."
        )
        print("오늘은 API 반복조회하지 않고 종료합니다.")
        print("장중 09:00~15:30 사이에 다시 실행하십시오.")
        return

    appkey = getpass.getpass("Kiwoom App Key: ")
    secret = getpass.getpass("Kiwoom Secret Key: ")

    print("\nTOKEN 발급 중...")
    token = get_token(appkey, secret)
    print("TOKEN 발급 성공")
    print()

    if phase == "BEFORE_OPEN":
        print("장 시작 전입니다. 09:00까지 대기합니다.")
        while market_phase() == "BEFORE_OPEN":
            time.sleep(5)

    universe = load_or_fetch_universe(token)
    print(f"전종목 Universe: {len(universe)}종목")
    print(f"후보파일: {CANDIDATE_FILE}")
    print(f"후보 감시: {MONITOR_POLL_SECONDS}초 주기")
    print("종료: Ctrl+C")
    print()
    print("중요:")
    print("- 자동 후보조건: 당일 고가/시가 +20% 이상 + 거래대금 500억 이상")
    print("- 원문 미확정 제외조건은 자동 추정하지 않고 PENDING_REVIEW")
    print("- 후보 CSV의 Y/N 검토값을 입력하면 PAPER 감시 활성화")
    print()

    scanner = threading.Thread(
        target=full_market_scanner,
        args=(token,),
        daemon=True,
        name="RS3Scanner"
    )
    monitor = threading.Thread(
        target=monitor_candidates,
        args=(token,),
        daemon=True,
        name="RS3Monitor"
    )

    scanner.start()
    monitor.start()

    try:
        while scanner.is_alive() or monitor.is_alive():
            if market_phase() == "CLOSED":
                STOP_EVENT.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n사용자 종료 요청")
        STOP_EVENT.set()

    scanner.join(timeout=5)
    monitor.join(timeout=5)

    print()
    print("=" * 96)
    print("RS3 PAPER 통합 v2 종료")
    print(f"종료시각: {now():%Y-%m-%d %H:%M:%S}")
    print(f"후보파일: {CANDIDATE_FILE}")
    print(f"상태폴더: {STATE_DIR}")
    print(f"로그폴더: {LOG_DIR}")
    print("실제 주문은 전혀 전송하지 않았습니다.")
    print("=" * 96)


if __name__ == "__main__":
    main()

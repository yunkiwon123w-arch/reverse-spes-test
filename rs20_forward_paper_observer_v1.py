# -*- coding: utf-8 -*-
"""
RS20 FORWARD PAPER OBSERVER v1
==============================

PURPOSE
- Observe RS20 source-numeric events live without placing orders.
- Build 1-minute bars from Kiwoom real-time stock executions (0B).
- Reconstruct source-faithful M indicator and cumulative traded value.
- Activate one continuous RS20 event when:
      M >= 200 eok
      M / cumulative traded value >= 20%
- Track dynamic Reverse Fibonacci from running DayHigh/DayLow.
- Record:
      exact/cross touch of Reverse-38
      nearest distance to Reverse-38
      program-flow snapshot (0w) as OBSERVATION ONLY
      parallel research exits: 5/3, 7/4, 10/5, EOD
- No actual orders.
- No invented "near" tolerance.
- No automatic 세력주/수급세력주 classifier.
- No invented 3-wave or new-listing exclusion mechanics.

IMPORTANT
- Start BEFORE 09:00 KST for source-faithful intraday M reconstruction.
- Same-day state is persisted, so a restart can resume.
- If started after 09:00 without same-day state, the program stops safely
  instead of pretending the M indicator is complete.

KIWOOM REALTIME
- 0B: 주식체결
- 0w: 종목프로그램매매 (subscribed only after an RS20 event activates)
Official websocket endpoint:
  wss://api.kiwoom.com:10000/api/dostk/websocket

AUTH
- App Key / App Secret entered locally with hidden getpass.
- Access token issued automatically and not written to disk.

NO ORDER API.
"""

import asyncio
import csv
import gzip
import json
import math
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date, time as dtime
from getpass import getpass
from pathlib import Path

import requests

try:
    import websockets
except ImportError:
    raise SystemExit(
        "Python package 'websockets' is required.\n"
        "Run once in PowerShell:\n"
        "python -m pip install websockets"
    )

TOKEN_URL = "https://api.kiwoom.com/oauth2/token"
WS_URL = "wss://api.kiwoom.com:10000/api/dostk/websocket"

# Official stock-list endpoint already used in this project.
STOCK_LIST_URL = "https://api.kiwoom.com/api/dostk/stkinfo"
STOCK_LIST_API_ID = "ka10099"

OUTPUT_ROOT = Path("forward_paper/rs20_v1")
STATE_FILE = OUTPUT_ROOT / "rs20_forward_state_v1.json"
EVENT_FILE = OUTPUT_ROOT / "rs20_forward_events_v1.csv"
MINUTE_FILE = OUTPUT_ROOT / "rs20_forward_minutes_v1.csv"
ERROR_FILE = OUTPUT_ROOT / "rs20_forward_errors_v1.csv"

M_MIN_EOK = 200.0
M_RATIO_MIN = 0.20

# Research exits only; NOT source rules.
RESEARCH_EXIT_MODELS = [
    ("P5_S3", 0.05, 0.03),
    ("P7_S4", 0.07, 0.04),
    ("P10_S5", 0.10, 0.05),
]

REGISTER_BATCH = 100
STATE_SAVE_INTERVAL_SEC = 15
EVENT_LOG_FLUSH_EVERY = 1

KST_MARKET_OPEN = dtime(9, 0)
KST_MARKET_CLOSE = dtime(15, 30)


def now_local():
    return datetime.now().astimezone()


def norm_code(v):
    s = str(v or "").strip()
    if "_" in s:
        s = s.split("_")[0]
    return s.zfill(6)


def num(v):
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", "").replace("+", "")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def abs_num(v):
    x = num(v)
    return abs(x) if x is not None else None


def ensure_dirs():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def append_csv(path, fields, row):
    new = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()


def issue_token():
    print()
    appkey = getpass("Kiwoom APP KEY (hidden): ").strip()
    secret = getpass("Kiwoom APP SECRET (hidden): ").strip()
    if not appkey or not secret:
        raise SystemExit("APP KEY or APP SECRET is empty.")

    r = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={
            "grant_type": "client_credentials",
            "appkey": appkey,
            "secretkey": secret,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"TOKEN HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    token = str(body.get("token", "")).strip()
    if not token:
        raise SystemExit(f"Token not returned: {body}")
    print("ACCESS TOKEN            : OK")
    if body.get("expires_dt"):
        print(f"TOKEN EXPIRES           : {body.get('expires_dt')}")
    return token


def stock_list(token, market_type):
    r = requests.post(
        STOCK_LIST_URL,
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": STOCK_LIST_API_ID,
        },
        json={"mrkt_tp": str(market_type)},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"ka10099 HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    rows = body.get("list") or []
    out = {}
    for x in rows:
        code = norm_code(x.get("code") or x.get("stk_cd") or x.get("stock_code"))
        name = str(x.get("name") or x.get("stk_nm") or x.get("stock_name") or "")
        if code and code.isdigit():
            out[code] = name
    return out


@dataclass
class MinuteBar:
    minute: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def update(self, price, vol):
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += vol


@dataclass
class StockState:
    code: str
    name: str = ""
    day_high: float = 0.0
    day_low: float = 0.0
    m_eok: float = 0.0
    turnover_eok: float = 0.0
    event_active: bool = False
    event_activation_time: str = ""
    first_exact_touch_time: str = ""
    fib38: float = 0.0
    nearest_distance_pct: float = 999999.0
    nearest_time: str = ""
    last_price: float = 0.0
    last_program_net_amt: float | None = None
    program_subscribed: bool = False
    current_bar: dict | None = None
    touch_entry_price: float = 0.0
    exit_p5_s3: str = ""
    exit_p7_s4: str = ""
    exit_p10_s5: str = ""


class Observer:
    def __init__(self, token, universe):
        self.token = token
        self.universe = universe
        self.states = {}
        self.ws = None
        self.last_state_save = 0.0
        self.trade_date = date.today().strftime("%Y%m%d")
        self.loaded_same_day_state = False

        self.event_fields = [
            "trade_date","event_type","event_time","stock_code","stock_name",
            "price","day_high","day_low","fib38","distance_pct",
            "m_eok","turnover_eok","m_ratio_pct",
            "program_net_amt",
            "source_review_required",
            "research_model","note"
        ]
        self.minute_fields = [
            "trade_date","minute","stock_code","stock_name",
            "open","high","low","close","volume",
            "bar_signed_value_eok","cum_m_eok","cum_turnover_eok",
            "day_high","day_low","fib38","event_active"
        ]
        self.error_fields = ["timestamp","where","stock_code","message"]

        self.load_state_if_today()

    def load_state_if_today(self):
        if not STATE_FILE.exists():
            return
        try:
            body = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if body.get("trade_date") != self.trade_date:
                return
            for code, x in body.get("states", {}).items():
                s = StockState(code=code)
                for k, v in x.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                self.states[code] = s
            self.loaded_same_day_state = True
            print(f"SAME-DAY STATE           : RESUMED ({len(self.states):,} stocks)")
        except Exception as e:
            print(f"STATE LOAD WARNING       : {e}")

    def save_state(self, force=False):
        now = time.time()
        if not force and now - self.last_state_save < STATE_SAVE_INTERVAL_SEC:
            return
        body = {
            "trade_date": self.trade_date,
            "saved_at": now_local().isoformat(),
            "states": {code: asdict(s) for code, s in self.states.items()},
        }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
        self.last_state_save = now

    def get_state(self, code):
        if code not in self.states:
            self.states[code] = StockState(
                code=code,
                name=self.universe.get(code, ""),
            )
        return self.states[code]

    def log_error(self, where, code, message):
        append_csv(ERROR_FILE, self.error_fields, {
            "timestamp": now_local().isoformat(),
            "where": where,
            "stock_code": code,
            "message": str(message)[:500],
        })

    def reverse38(self, day_high, day_low):
        if day_high <= 0 or day_low <= 0 or day_high < day_low:
            return 0.0
        k = day_high - day_low
        # Lecture naming: "0.382" line = K*0.618 + daylow
        return k * 0.618 + day_low

    def finalize_bar(self, s: StockState):
        if not s.current_bar:
            return
        b = s.current_bar
        o,h,l,c,v = b["open"],b["high"],b["low"],b["close"],b["volume"]

        typical = (h + o + l + c) / 4.0
        signed = 0.0
        if c > o:
            signed = typical * v / 100000000.0
        elif c < o:
            signed = -typical * v / 100000000.0

        turnover = typical * v / 100000000.0
        s.m_eok += signed
        s.turnover_eok += turnover

        s.day_high = max(s.day_high, h)
        if s.day_low <= 0:
            s.day_low = l
        else:
            s.day_low = min(s.day_low, l)
        s.fib38 = self.reverse38(s.day_high, s.day_low)

        ratio = s.m_eok / s.turnover_eok if s.turnover_eok > 0 else 0.0

        append_csv(MINUTE_FILE, self.minute_fields, {
            "trade_date": self.trade_date,
            "minute": b["minute"],
            "stock_code": s.code,
            "stock_name": s.name,
            "open": o,"high": h,"low": l,"close": c,"volume": v,
            "bar_signed_value_eok": signed,
            "cum_m_eok": s.m_eok,
            "cum_turnover_eok": s.turnover_eok,
            "day_high": s.day_high,
            "day_low": s.day_low,
            "fib38": s.fib38,
            "event_active": int(s.event_active),
        })

        if (not s.event_active and
            s.m_eok >= M_MIN_EOK and
            s.turnover_eok > 0 and
            ratio >= M_RATIO_MIN):
            s.event_active = True
            s.event_activation_time = b["minute"]
            self.log_event(
                s, "EVENT_ACTIVATED", c,
                note="SOURCE numeric core formed; stock-classification/exclusions still review-required."
            )

        s.current_bar = None

    def update_tick(self, code, values):
        s = self.get_state(code)
        tm = str(values.get("20", "")).strip()
        price = abs_num(values.get("10"))
        vol = abs_num(values.get("15")) or 0.0
        day_high = abs_num(values.get("17"))
        day_low = abs_num(values.get("18"))

        if not tm or price is None:
            return

        if day_high:
            s.day_high = max(s.day_high, day_high)
        if day_low:
            s.day_low = day_low if s.day_low <= 0 else min(s.day_low, day_low)

        minute = tm[:4]
        if s.current_bar is None:
            s.current_bar = {
                "minute": minute,
                "open": price,"high": price,"low":price,"close":price,"volume":vol
            }
        elif s.current_bar["minute"] != minute:
            self.finalize_bar(s)
            s.current_bar = {
                "minute": minute,
                "open": price,"high":price,"low":price,"close":price,"volume":vol
            }
        else:
            s.current_bar["high"] = max(s.current_bar["high"], price)
            s.current_bar["low"] = min(s.current_bar["low"], price)
            s.current_bar["close"] = price
            s.current_bar["volume"] += vol

        s.last_price = price
        s.fib38 = self.reverse38(s.day_high, s.day_low)

        if s.event_active and s.fib38 > 0:
            dist = abs(price - s.fib38) / s.fib38 * 100.0
            if dist < s.nearest_distance_pct:
                s.nearest_distance_pct = dist
                s.nearest_time = tm
                self.log_event(s, "NEAREST_UPDATE", price, note="Descriptive only; no near tolerance invented.")

            # Exact/cross touch is defined causally as this execution price crossing the current
            # mathematical fib line versus the immediately previous execution price.
            prev = getattr(s, "_prev_price", None)
            if not s.first_exact_touch_time and prev is not None:
                crossed = (prev - s.fib38) * (price - s.fib38) <= 0
                if crossed:
                    s.first_exact_touch_time = tm
                    s.touch_entry_price = price
                    self.log_event(
                        s, "FIRST_EXACT_OR_CROSS_TOUCH", price,
                        note="Forward-paper reference; actual fillability is observed, not assumed."
                    )
            s._prev_price = price

            if s.first_exact_touch_time:
                self.update_research_exits(s, tm, price)

    def update_research_exits(self, s, tm, price):
        if s.touch_entry_price <= 0:
            return
        for name, tp, sl in RESEARCH_EXIT_MODELS:
            attr = {
                "P5_S3":"exit_p5_s3",
                "P7_S4":"exit_p7_s4",
                "P10_S5":"exit_p10_s5",
            }[name]
            if getattr(s, attr):
                continue

            r = price / s.touch_entry_price - 1.0
            if r >= tp:
                setattr(s, attr, f"TP@{tm}")
                self.log_event(s, "RESEARCH_EXIT", price, research_model=name, note="TP")
            elif r <= -sl:
                setattr(s, attr, f"SL@{tm}")
                self.log_event(s, "RESEARCH_EXIT", price, research_model=name, note="SL")

    def update_program(self, code, values):
        s = self.get_state(code)
        v = num(values.get("212"))
        if v is not None:
            s.last_program_net_amt = v
            self.log_event(
                s, "PROGRAM_FLOW_SNAPSHOT", s.last_price,
                note="0w field 212 cumulative program net amount; observation only, not a trading gate."
            )

    def log_event(self, s, event_type, price, note="", research_model=""):
        ratio = s.m_eok / s.turnover_eok * 100.0 if s.turnover_eok > 0 else 0.0
        dist = (
            abs(price - s.fib38) / s.fib38 * 100.0
            if price and s.fib38 > 0 else ""
        )
        append_csv(EVENT_FILE, self.event_fields, {
            "trade_date": self.trade_date,
            "event_type": event_type,
            "event_time": now_local().strftime("%H%M%S"),
            "stock_code": s.code,
            "stock_name": s.name,
            "price": price,
            "day_high": s.day_high,
            "day_low": s.day_low,
            "fib38": s.fib38,
            "distance_pct": dist,
            "m_eok": s.m_eok,
            "turnover_eok": s.turnover_eok,
            "m_ratio_pct": ratio,
            "program_net_amt": "" if s.last_program_net_amt is None else s.last_program_net_amt,
            "source_review_required": "Y",
            "research_model": research_model,
            "note": note,
        })

    async def subscribe_batches(self, codes, types, group_prefix):
        for idx in range(0, len(codes), REGISTER_BATCH):
            batch = codes[idx:idx+REGISTER_BATCH]
            grp = str((idx // REGISTER_BATCH) + 1).zfill(4)[-4:]
            msg = {
                "trnm": "REG",
                "grp_no": grp,
                "refresh": "1",
                "data": [{"item": batch, "type": types}],
            }
            await self.ws.send(json.dumps(msg))
            await asyncio.sleep(0.05)

    async def subscribe_program_for(self, code):
        s = self.get_state(code)
        if s.program_subscribed:
            return
        msg = {
            "trnm":"REG",
            "grp_no":"9000",
            "refresh":"1",
            "data":[{"item":[code], "type":["0w"]}],
        }
        await self.ws.send(json.dumps(msg))
        s.program_subscribed = True

    async def run(self):
        # Safe-start check.
        local_t = now_local().time().replace(tzinfo=None)
        if local_t >= KST_MARKET_OPEN and not self.loaded_same_day_state:
            raise SystemExit(
                "SAFE STOP: started after 09:00 without same-day state.\n"
                "RS20 M indicator would be incomplete. Start before market open tomorrow."
            )

        headers = {"authorization": f"Bearer {self.token}"}
        print(f"WEBSOCKET               : connecting {WS_URL}")

        async with websockets.connect(
            WS_URL,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
        ) as ws:
            self.ws = ws
            codes = sorted(self.universe.keys())
            print(f"0B REGISTER TARGET      : {len(codes):,} stocks")
            await self.subscribe_batches(codes, ["0B"], "0")

            # Resume program subscriptions for already-active states.
            for s in list(self.states.values()):
                if s.event_active:
                    await self.subscribe_program_for(s.code)

            print("FORWARD PAPER OBSERVER   : RUNNING")
            print("NO ORDER API             : CONFIRMED")

            while True:
                raw = await ws.recv()
                try:
                    body = json.loads(raw)
                except Exception:
                    continue

                if body.get("trnm") != "REAL":
                    # registration responses
                    continue

                for item in body.get("data") or []:
                    typ = item.get("type")
                    code = norm_code(item.get("item"))
                    values = item.get("values") or {}

                    try:
                        if typ == "0B":
                            before = self.get_state(code).event_active
                            self.update_tick(code, values)
                            after = self.get_state(code).event_active
                            if after and not before:
                                await self.subscribe_program_for(code)

                        elif typ == "0w":
                            self.update_program(code, values)

                    except Exception as e:
                        self.log_error(f"REAL-{typ}", code, e)

                self.save_state()

    def eod_finalize(self):
        for s in self.states.values():
            if s.current_bar:
                self.finalize_bar(s)
            if s.first_exact_touch_time:
                for name, _, _ in RESEARCH_EXIT_MODELS:
                    attr = {
                        "P5_S3":"exit_p5_s3",
                        "P7_S4":"exit_p7_s4",
                        "P10_S5":"exit_p10_s5",
                    }[name]
                    if not getattr(s, attr):
                        self.log_event(
                            s, "RESEARCH_EXIT", s.last_price,
                            research_model=name, note="EOD"
                        )
        self.save_state(force=True)


def main():
    ensure_dirs()

    print("=" * 100)
    print("RS20 FORWARD PAPER OBSERVER v1")
    print("SOURCE NUMERIC CORE       : M>=200 eok AND M/turnover>=20%")
    print("FIBONACCI                 : dynamic DayHigh/DayLow Reverse-38")
    print("NEAR TOLERANCE            : NONE (distance only)")
    print("SOURCE REVIEW FLAGS       : 세력/수급세력, 3파, 신규상장")
    print("PROGRAM_FLOW              : OBSERVATION ONLY")
    print("ACTUAL ORDERS             : NONE")
    print("=" * 100)

    token = issue_token()

    print("LOADING KOSPI/KOSDAQ UNIVERSE...")
    universe = {}
    universe.update(stock_list(token, 0))
    universe.update(stock_list(token, 10))
    print(f"UNIVERSE                  : {len(universe):,}")

    observer = Observer(token, universe)

    try:
        asyncio.run(observer.run())
    except KeyboardInterrupt:
        print("\nSTOP REQUESTED. Saving same-day state...")
        observer.eod_finalize()
        print("STATE SAVED.")
    except Exception as e:
        observer.save_state(force=True)
        raise


if __name__ == "__main__":
    main()

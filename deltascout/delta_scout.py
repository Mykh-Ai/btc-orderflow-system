#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeltaScout — SIMPLE window triggers (lazy VWAP/POC, 1-line log)
Пише текстові рядки у форматі, який очікує buyer.py

Ця версія відновлює:
- INIT warmup (INIT_MAX / INIT_MIN) на старті з вікна lookback;
- базову архітектуру: emit(debug/telegram) → базові перевірки (sign/IMB/VWAP) → 3/3 → ворота (EMA50/CHOP/COH) → JSON для Buyer;
- завжди оновлює self.prev_peak наприкінці гілки MAX/MIN;
- виклик _ingest_buyer_events() на початку handle_row;
- уникнення FutureWarning від pandas (floor('min'), .ffill());
- єдиний набір методів у класі Scout (без дублів);
- ZERO-події знову проходять через _emit (як у базі);
- _emit відправляє «базовий» payload у webhook (не {"text": ...}).

Перевірено на відповідність «довгій» базовій структурі файлу (500+ рядків).
"""

import os, sys, csv, json, time, math, urllib.request
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

# ===== ENV =====
FEED_DIR        = os.getenv("FEED_DIR", "/data/feed")
FILE_PATH       = os.getenv("FILE_PATH", os.path.join(FEED_DIR, "aggregated.csv"))
POLL_SECS       = float(os.getenv("POLL_SECS", "20"))
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "")
ROLL_WINDOW_MIN = int(os.getenv("ROLL_WINDOW_MIN", "180"))
VWAP_WINDOW_MIN = int(os.getenv("VWAP_WINDOW_MIN", "180"))
POC_STEP_USD    = float(os.getenv("POC_STEP_USD", "10"))
ZERO_QTY_TH     = float(os.getenv("ZERO_QTY_TH", "0.24"))
AVG9_MAX        = float(os.getenv("AVG9_MAX", "1"))
PRINT_EVERY     = int(os.getenv("PRINT_EVERY", "1"))
STARTUP_LOOKBACK_MIN = int(os.getenv("STARTUP_LOOKBACK_MIN", "180"))
CHOP30_MAX = float(os.getenv("CHOP30_MAX", "2.6"))

COH10_MIN  = float(os.getenv("COH10_MIN", "0.30"))
IMB_MIN    = float(os.getenv("IMB_MIN", "0.55"))
IMB_MAX    = float(os.getenv("IMB_MAX", "0.65"))
INIT_EMIT  = os.getenv("INIT_EMIT", "true").lower() in {"1","true","yes"}

# --- Tier params ---
TIER_WINDOW_MIN  = int(os.getenv("TIER_WINDOW_MIN", "180"))
TIER_A_VOL_PCTL  = float(os.getenv("TIER_A_VOL_PCTL", "95"))
TIER_B_VOL_PCTL  = float(os.getenv("TIER_B_VOL_PCTL", "99"))
TIER_A_IMB_MAX   = float(os.getenv("TIER_A_IMB_MAX", "0.15"))
TIER_B_IMB_MIN   = float(os.getenv("TIER_B_IMB_MIN", "0.15"))

# Лог створюємо в тій самій теці, де aggregated.csv, або в DELTASCOUT_LOG
DEFAULT_LOG_PATH = "/data/logs/deltascout.log"
LOG_PATH        = os.getenv("DELTASCOUT_LOG") or DEFAULT_LOG_PATH
try:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    open(LOG_PATH, "a", encoding="utf-8").close()
except Exception as _e:
    print(f"[LOG TOUCH ERROR] {_e} -> {LOG_PATH}", file=sys.stderr, flush=True)

ENV = {
    "AGG_CSV": FILE_PATH,
    "ROLL_WINDOW_MIN": ROLL_WINDOW_MIN,
    "VWAP_WINDOW_MIN": VWAP_WINDOW_MIN,
    "POC_STEP_USD": POC_STEP_USD,
    "ZERO_QTY_TH": ZERO_QTY_TH,
    "AVG9_MAX": AVG9_MAX,
    "STARTUP_LOOKBACK_MIN": STARTUP_LOOKBACK_MIN,
    "TIER_WINDOW_MIN": TIER_WINDOW_MIN,
    "TIER_A_VOL_PCTL": TIER_A_VOL_PCTL,
    "TIER_B_VOL_PCTL": TIER_B_VOL_PCTL,
    "TIER_A_IMB_MAX": TIER_A_IMB_MAX,
    "TIER_B_IMB_MIN": TIER_B_IMB_MIN,
}

# ===== UTILS =====
EXPECTED_HEADER = [
    "Timestamp",
    "Trades",
    "TotalQty",
    "AvgSize",
    "BuyQty",
    "SellQty",
    "AvgPrice",
    "ClosePrice",
    "HiPrice",
    "LowPrice",
]
def _normalize_header(header: list[str] | None) -> list[str] | None:
    if header is None:
        return None
    return [h.strip() for h in header]

def _validate_header(header: list[str] | None, path: str):
    if header is None:
        print(f"[CSV HEADER ERROR] empty header in {path}", file=sys.stderr, flush=True)
        sys.exit(2)
    if header != EXPECTED_HEADER:
        print(
            "[CSV HEADER ERROR] header mismatch.\n"
            f"Expected: {EXPECTED_HEADER}\n"
            f"Got:      {header}\n"
            f"Path:     {path}",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(2)

def fmt_dt_iso_min(ts_str: str) -> str:
    return ts_str.split(".")[0][:16]

def post_json(url: str, payload: dict):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()

def sign_delta(v: float) -> str:
    return f"{v:+.2f}"

# ===================== Market context =====================

def load_df_sorted() -> pd.DataFrame:
    with open(ENV["AGG_CSV"], "r", encoding="utf-8-sig") as f:
        rdr = csv.reader(f)
        header = _normalize_header(next(rdr, None))
        _validate_header(header, ENV["AGG_CSV"])
    df = pd.read_csv(ENV["AGG_CSV"], encoding="utf-8-sig")  # Очікуємо: Timestamp, BuyQty, SellQty, ClosePrice/AvgPrice
    df.columns = [c.strip() for c in df.columns]
    df["Timestamp"] = pd.to_datetime(df["Timestamp"]).dt.floor("min")
    price = df["ClosePrice"] if "ClosePrice" in df.columns else df.get("AvgPrice")
    df["price"] = pd.to_numeric(price, errors="coerce").ffill()
    df["buy"]  = pd.to_numeric(df.get("BuyQty", 0.0), errors="coerce").fillna(0.0)
    df["sell"] = pd.to_numeric(df.get("SellQty", 0.0), errors="coerce").fillna(0.0)
    df["vol1m"] = df["buy"] + df["sell"]
    df["delta"] = df["buy"] - df["sell"]
    df["ema50"] = df["price"].ewm(span=50, adjust=False).mean()
    return df.reset_index(drop=True)

def locate_index_by_ts(df: pd.DataFrame, ts: datetime) -> int:
    m = df.index[df["Timestamp"] == ts]
    if len(m) == 0:
        m = df.index[df["Timestamp"].dt.floor("min") == ts]
    return int(m[0]) if len(m) else len(df)-1

# антібоковик

def chop30_idx(df: pd.DataFrame, i: int) -> float:
    lo = max(0, i-29)
    win = df["price"].iloc[lo:i+1].to_numpy()
    if win.size < 2:
        return float("inf")
    rng = float(np.nanmax(win) - np.nanmin(win))
    if rng <= 0:
        return float("inf")
    return float(np.nansum(np.abs(np.diff(win)))) / rng

def coh10_idx(df: pd.DataFrame, i: int) -> float:
    lo = max(0, i-9)
    buy = df["buy"].iloc[lo:i+1].to_numpy(); sell = df["sell"].iloc[lo:i+1].to_numpy()
    sV = float(np.nansum(buy + sell)); sD = float(np.nansum(buy - sell))
    return (abs(sD)/sV) if sV>0 else 0.0

# 3/3

def prev_pass_3of3(curr: dict, prev: dict) -> bool:
    if curr["kind"] == "long":
        return (curr["price"]>prev["price"]) and (curr["vol"]>prev["vol"]) and (curr["vwap"]>prev["vwap"]) 
    else:
        return (curr["price"]<prev["price"]) and (curr["vol"]>prev["vol"]) and (curr["vwap"]<prev["vwap"]) 

# ===================== Tier helpers =====================

def _vol_percentile(df: pd.DataFrame, i: int, minutes: int, q: float) -> float:
    lo = max(0, i - minutes + 1)
    arr = df["vol1m"].iloc[lo:i+1].to_numpy(dtype=float)
    if arr.size == 0:
        return 0.0
    return float(np.nanpercentile(arr, q))

# ===================== CORE =====================
class Scout:
    def __init__(self):
        self.win = deque(maxlen=ROLL_WINDOW_MIN)
        self.vbuf = deque(maxlen=VWAP_WINDOW_MIN)
        self.last_owner = {"max": None, "min": None}
        self._print_i = 0
        self.log_path = LOG_PATH
        self.prev_peak = None   # нова база для порівнянь між піками
        self._init_state()

    # ---- time helpers ----
    def _now(self) -> datetime:
        return datetime.utcnow().replace(tzinfo=timezone.utc)

    def _ts_iso(self, dt: datetime | None = None) -> str:
        return (dt or self._now()).isoformat().replace("+00:00", "Z")

    # ---- JSON SIGNAL ----
    def _emit_json(self, payload: dict):
        """Запис сигналу у deltascout.log у форматі JSONL (1 подія = 1 рядок)."""
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._truncate_log(max_lines=500, keep_tail=30)

        except Exception as e:
            print(f"[LOG JSON WRITE ERROR] {e} -> {self.log_path}", file=sys.stderr, flush=True)

    def _truncate_log(self, max_lines: int = 500, keep_tail: int = 30):
        """Обрізає файл, якщо перевищено max_lines, залишає останні keep_tail."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                tail = lines[-keep_tail:]
                with open(self.log_path, "w", encoding="utf-8") as f:
                    f.writelines(tail)
        except Exception as e:
            print(f"[LOG TRUNCATE ERROR] {e} -> {self.log_path}", file=sys.stderr, flush=True)
        

    # ---- context: lazy VWAP + POC ----
    def _context(self):
        if not self.vbuf:
            return None, None
        sum_pq = 0.0; sum_q = 0.0
        bins = defaultdict(float)
        step = POC_STEP_USD
        for p, q in self.vbuf:
            sum_pq += p*q; sum_q += q
            b = math.floor((p + step/2) / step) * step
            bins[b] += q
        vwap = int(round(sum_pq/sum_q)) if sum_q > 0 else None
        poc  = int(round(max(bins.items(), key=lambda x: x[1])[0])) if bins else None
        return vwap, poc

    # ---- debug emit: console + webhook (base payload) ----
    def _emit(self, kind: str, ts: str, delta: float, imba: float, ap: float, trades: int, tq: float):
        vwap, poc = self._context()
        rel = '>' if (vwap is not None and poc is not None and vwap > poc) else \
              '<' if (vwap is not None and poc is not None and vwap < poc) else '=' if (vwap is not None and poc is not None) else ''
        ts_short = fmt_dt_iso_min(ts)

        line = (
            f"Δ1m {kind} {sign_delta(delta)} @ {ts_short} | "
            f"Vol {tq:.0f} BTC | Ib {imba:.2f} | "
            f"Price {int(round(ap))} | "
            f"VWAP{vwap if vwap is not None else '-'} {rel} POC {poc if poc is not None else '-'}"
        )

        payload = {
            "ts": ts_short,
            "kind": kind,              # max|min|zero|init_max|init_min
            "d1m": sign_delta(delta),
            "imb": round(imba, 2),
            "price": int(round(ap)),
            "level": round(ap, 2),
            "tqty": float(f"{tq:.0f}"),
            "trades": trades,
            "vwap": vwap,
            "poc": poc,
            "text": line,
        }

        if WEBHOOK_URL:
            try:
                post_json(WEBHOOK_URL, payload)
            except Exception as e:
                print("webhook error:", e, file=sys.stderr)

        if PRINT_EVERY >= 1:
            self._print_i += 1
            if (self._print_i % PRINT_EVERY) == 0:
                print(line, flush=True)

    # ---------- STATE ----------
    def _init_state(self):
        self.state = {
            "mode": "IDLE",           # IDLE | ARM | OPEN | COOLDOWN
            "position_side": None,    # "LONG"/"SHORT"
            "entry": None,
            "cooldown_until": None,
            "arm_until": None,
        }
        self._last_seen_buyer_ts = None
        self._reconstruct_state_from_log()

    def _reconstruct_state_from_log(self):
        """Відновлення стану при старті з останніх рядків deltascout.log"""
        try:
            if not os.path.exists(self.log_path):
                return
            with open(self.log_path, "r", encoding="utf-8") as f:
                tail = deque(f, maxlen=200)
            for line in tail:
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                self._absorb_event(evt, startup=True)
        except Exception as e:
            print(f"[STATE RECONSTRUCT ERROR] {e}", file=sys.stderr, flush=True)

    def _ingest_buyer_events(self):
        """Читання подій Buyer із хвоста логу (реагує на CLOSE/STOPPED)"""
        try:
            if not os.path.exists(self.log_path):
                return
            with open(self.log_path, "r", encoding="utf-8") as f:
                tail = deque(f, maxlen=200)
            for line in tail:
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                self._absorb_event(evt, startup=False)
        except Exception as e:
            print(f"[STATE INGEST ERROR] {e}", file=sys.stderr, flush=True)

    def _absorb_event(self, evt: dict, startup: bool):
        """Оновлення стану за подіями Buyer"""
        if evt.get("source") != "Buyer":
            return
        act = evt.get("action")

        if act == "OPEN_FILLED":
            self.state["mode"] = "OPEN"
            self.state["position_side"] = evt.get("side")
            self.state["entry"] = evt.get("entry")

        elif act in ("CLOSED", "STOPPED"):
            self.state["mode"] = "COOLDOWN"
            self.state["position_side"] = None
            self.state["entry"] = None
            self.state["cooldown_until"] = self._now() + timedelta(minutes=15)

        elif act == "TP1_HIT":
            pass

    def _cooldown_active(self) -> bool:
        cu = self.state.get("cooldown_until")
        if not cu:
            return False
        if self._now() >= cu:
            self.state["cooldown_until"] = None
            if self.state["mode"] == "COOLDOWN":
                self.state["mode"] = "IDLE"
            return False
        return True

    def _arm_active(self) -> bool:
        au = self.state.get("arm_until")
        if self.state["mode"] != "ARM":
            return False
        if au and self._now() >= au:
            self.state["mode"] = "COOLDOWN"
            self.state["cooldown_until"] = self._now() + timedelta(minutes=15)
            self.state["arm_until"] = None
            return False
        return True

    # ---- Tier triggers ----
    def apply_tier_triggers(self, pk: dict, df: pd.DataFrame, i: int, env: dict) -> bool:
        if self.state["mode"] != "OPEN":
            return False

        vol_now = float(df.loc[i, "vol1m"]) if (i is not None and i >= 0 and "vol1m" in df.columns) else float(pk.get("vol") or 0.0)
        p95 = _vol_percentile(df, i, env["TIER_WINDOW_MIN"], env["TIER_A_VOL_PCTL"])
        p99 = _vol_percentile(df, i, env["TIER_WINDOW_MIN"], env["TIER_B_VOL_PCTL"])
        imb = float(pk.get("imb", 0.0))

        tierA = (vol_now >= p95) and (imb <= env["TIER_A_IMB_MAX"])
        tierB = (vol_now >= p99) and (imb > env["TIER_B_IMB_MIN"])

        if not (tierA or tierB):
            return False

        signal = {
            "ts": pk["ts"].isoformat() if hasattr(pk["ts"], "isoformat") else str(pk["ts"]),
            "source": "DeltaScout",
            "action": "TIER_TP1",
            "tier": "A" if tierA else "B",
            "vol": round(vol_now, 2),
            "imb": round(imb, 3),
        }
        self._emit_json(signal)
        return True

    # ---- main row handler ----
    def handle_row(self, row: dict):
        # реагуємо на Buyer-події (COOLDOWN після CLOSE/STOPPED)
        self._ingest_buyer_events()

        ts     = row["Timestamp"]
        trades = int(float(row.get("Trades", 0) or 0))
        tq     = float(row.get("TotalQty", 0) or 0)
        buy    = float(row.get("BuyQty", 0) or 0)
        sell   = float(row.get("SellQty", 0) or 0)
        ap     = float(row.get("AvgPrice", 0) or 0)

        delta = buy - sell
        vol   = buy + sell
        imba  = (abs(delta) / vol) if vol > 0 else 0.0

        # lazy context buffers
        self.vbuf.append((ap, tq))

        # ZERO event (як у базі — через _emit)
        if not hasattr(self, "_tail9"):
            self._tail9 = deque(maxlen=9)
        self._tail9.append(tq)
        avg9 = (sum(self._tail9)/len(self._tail9)) if self._tail9 else 0.0
        if tq < ZERO_QTY_TH and avg9 < AVG9_MAX:
            self._emit("zero", ts, delta, imba, ap, trades, tq)

        # rolling max/min window
        self.win.append((delta, imba, tq, ap, trades, ts))
        if not self.win:
            return

        ds = [x[0] for x in self.win]
        wmax = max(ds); wmin = min(ds)
        last_ts_max = last_ts_min = None
        for d, _, _, _, _, tss in reversed(self.win):
            if last_ts_max is None and d == wmax:
                last_ts_max = tss
            if last_ts_min is None and d == wmin:
                last_ts_min = tss
            if last_ts_max and last_ts_min:
                break

        # === MAX peak ===
        if last_ts_max == ts and self.last_owner.get("max") != ts:
            self.last_owner["max"] = ts

            # debug/telegram — завжди
            self._emit("max", ts, delta, imba, ap, trades, tq)

            # контекст
            df = load_df_sorted()
            ts_dt = pd.to_datetime(ts)
            i = locate_index_by_ts(df, ts_dt)
            price_now = float(df.loc[i, "price"])
            ema50_now = float(df.loc[i, "ema50"])
            vwap_now, poc_now = self._context()
            chop = chop30_idx(df, i)
            coh  = coh10_idx(df, i)

            curr = {"kind":"long","price":ap,"vol":vol,"vwap":vwap_now,"imb":imba}

            # --- базові перевірки ---
           # --- базові перевірки ---
            if not self.prev_peak:
                self.prev_peak = curr; return
            if curr["kind"] != self.prev_peak["kind"]:
                self.prev_peak = curr; return
            if vwap_now is not None and curr["price"] < vwap_now:
                self.prev_peak = curr; return
            if not prev_pass_3of3(curr, self.prev_peak):
                self.prev_peak = curr; return

            # завжди оновлюємо базу
            self.prev_peak = curr

            # --- ворота ---
            if not (price_now > ema50_now and (vwap_now is None or price_now > vwap_now)):
                return
            if not (chop <= CHOP30_MAX and coh >= COH10_MIN):
                return
            if not (IMB_MIN <= imba <= IMB_MAX):
                return


            # --- сигнал у лог (для Buyer) ---
            self._emit_json({
                "ts": str(ts),
                "source": "DeltaScout",
                "action": "PEAK",
                "kind": "long",
                "delta": round(delta, 2),
                "vol": round(vol, 2),
                "imb": round(imba, 3),
                "price": ap,
                "vwap": vwap_now,
                "poc": poc_now,
            })

            # оновлення бази
            self.prev_peak = curr

        # === MIN peak ===
        if last_ts_min == ts and self.last_owner.get("min") != ts:
            self.last_owner["min"] = ts

            # debug/telegram — завжди
            self._emit("min", ts, delta, imba, ap, trades, tq)

            # контекст
            df = load_df_sorted()
            ts_dt = pd.to_datetime(ts)
            i = locate_index_by_ts(df, ts_dt)
            price_now = float(df.loc[i, "price"])
            ema50_now = float(df.loc[i, "ema50"])
            vwap_now, poc_now = self._context()
            chop = chop30_idx(df, i)
            coh  = coh10_idx(df, i)

            curr = {"kind":"short","price":ap,"vol":vol,"vwap":vwap_now,"imb":imba}

            # --- базові перевірки ---
            if not self.prev_peak:
                self.prev_peak = curr; return
            if curr["kind"] != self.prev_peak["kind"]:
                self.prev_peak = curr; return
            if vwap_now is not None and curr["price"] > vwap_now:
                self.prev_peak = curr; return
            if not prev_pass_3of3(curr, self.prev_peak):
                self.prev_peak = curr; return

            # завжди оновлюємо базу
            self.prev_peak = curr

            # --- ворота ---
            if not (price_now < ema50_now and (vwap_now is None or price_now < vwap_now)):
                return
            if not (chop <= CHOP30_MAX and coh >= COH10_MIN):
                return
            if not (IMB_MIN <= imba <= IMB_MAX):
                return


            # --- сигнал у лог (для Buyer) ---
            self._emit_json({
                "ts": str(ts),
                "source": "DeltaScout",
                "action": "PEAK",
                "kind": "short",
                "delta": round(delta, 2),
                "vol": round(vol, 2),
                "imb": round(imba, 3),
                "price": ap,
                "vwap": vwap_now,
                "poc": poc_now,
            })

            # оновлення бази
            self.prev_peak = curr

# ===== CSV tail =====
def tail_csv(path: str):
    last_ts = None
    header = None
    ts_idx = None
    bad_rows = 0
    while True:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                rdr = csv.reader(f)
                header = _normalize_header(next(rdr, None))
                _validate_header(header, path)
                if not header:
                    time.sleep(POLL_SECS); continue

                if ts_idx is None:
                    try:
                        ts_idx = header.index("Timestamp")
                    except ValueError:
                        ts_idx = 0

                last = None
                for parts in rdr:
                    if len(parts) != len(header):
                        bad_rows += 1
                        if bad_rows % 100 == 0:
                            print(
                                f"[CSV WARN] bad row length ({len(parts)} != {len(header)}) in {path}",
                                file=sys.stderr,
                                flush=True,
                            )
                        continue
                    last = parts

                if last:
                    cur_ts = last[ts_idx]
                    if cur_ts != last_ts:
                        last_ts = cur_ts
                        yield dict(zip(header, last))
        except Exception as e:
            print("tail err:", e, file=sys.stderr)
        time.sleep(POLL_SECS)

# ===== STARTUP WARMUP =====
def read_last_rows(path: str, n: int):
    if n <= 0: return []
    tail = deque(maxlen=n)
    bad_rows = 0
    with open(path, "r", encoding="utf-8-sig") as f:
        rdr = csv.reader(f)
        header = _normalize_header(next(rdr, None))
        _validate_header(header, path)
        idx = {h:i for i,h in enumerate(header or [])}
        for parts in rdr:
            if not header or len(parts) != len(header):
                bad_rows += 1
                if bad_rows % 100 == 0:
                    print(
                        f"[CSV WARN] bad row length ({len(parts)} != {len(header)}) in {path}",
                        file=sys.stderr,
                        flush=True,
                    )
                continue
            tail.append({h: parts[idx[h]] for h in header})
    return list(tail)

def warmup_init(scout: Scout, rows: list):
    if not rows:
        return
    for row in rows:
        ts=row["Timestamp"]; tq=float(row.get("TotalQty",0) or 0)
        buy=float(row.get("BuyQty",0) or 0); sell=float(row.get("SellQty",0) or 0)
        ap=float(row.get("AvgPrice",0) or 0)
        tr=int(float(row.get("Trades",0) or 0))
        delta=buy-sell; vol=buy+sell
        imba=(abs(delta)/vol) if vol>0 else 0.0
        scout.vbuf.append((ap, tq))
        if not hasattr(scout, "_tail9"): scout._tail9 = deque(maxlen=9)
        scout._tail9.append(tq)
        scout.win.append((delta, imba, tq, ap, tr, ts))

    if not scout.win:
        return

    ds = [x[0] for x in scout.win]
    wmax = max(ds); wmin = min(ds)
    last_ts_max = last_ts_min = None
    last_row_max = last_row_min = None
    for d, im, tq, ap, tr, tss in reversed(scout.win):
        if last_ts_max is None and d == wmax:
            last_ts_max = tss; last_row_max = (tss, d, im, ap, tr, tq)
        if last_ts_min is None and d == wmin:
            last_ts_min = tss; last_row_min = (tss, d, im, ap, tr, tq)
        if last_ts_max and last_ts_min:
            break

    scout.last_owner["max"] = last_ts_max
    scout.last_owner["min"] = last_ts_min

    if INIT_EMIT:
        if last_row_max:
            ts, d, im, ap, tr, tq = last_row_max
            # JSON-сигнал
            scout._emit_json({
                "ts": str(ts),
                "source": "DeltaScout",
                "action": "INIT_MAX",
                "delta": round(d, 2),
                "vol": round(tq, 2),
                "imb": round(im, 3),
                "price": ap,
            })
            # Debug-лог
            scout._emit("init_max", ts, d, im, ap, tr, tq)

        if last_row_min:
            ts, d, im, ap, tr, tq = last_row_min
            scout._emit_json({
                "ts": str(ts),
                "source": "DeltaScout",
                "action": "INIT_MIN",
                "delta": round(d, 2),
                "vol": round(tq, 2),
                "imb": round(im, 3),
                "price": ap,
            })
            scout._emit("init_min", ts, d, im, ap, tr, tq)

# ===== MAIN =====
if __name__ == "__main__":
    while not os.path.exists(FILE_PATH):
        print("wait file:", FILE_PATH); time.sleep(1)

    print(f"🚀 DeltaScout SIMPLE started. Watching {FILE_PATH}")
    print(f"    roll={ROLL_WINDOW_MIN}m, vwap={VWAP_WINDOW_MIN}m(lazy), zero_qty<{ZERO_QTY_TH}, avg9<{AVG9_MAX}")

    # Перевірка колонок
    with open(FILE_PATH, "r", encoding="utf-8-sig") as f:
        rdr = csv.reader(f)
        header = _normalize_header(next(rdr, None))
        _validate_header(header, FILE_PATH)

    s = Scout()
    try:
        want = max(STARTUP_LOOKBACK_MIN, ROLL_WINDOW_MIN, VWAP_WINDOW_MIN, 9)
        last_rows = read_last_rows(FILE_PATH, want)
        warmup_init(s, last_rows)       # засіває last_owner і шле INIT_*
        print(f"🟢 init done: scanned {len(last_rows)} rows")
    except Exception as e:
        print("init err:", e, file=sys.stderr)

    for row in tail_csv(FILE_PATH):
        try:
            s.handle_row(row)
        except Exception as e:
            print("row err:", e, row, file=sys.stderr)

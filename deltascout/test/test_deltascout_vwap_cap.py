# test/test_deltascout_vwap_cap.py
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


def _find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(30):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path.cwd().resolve()


def _load_delta_scout_module():
    here = Path(__file__).resolve()
    repo = _find_repo_root(here)

    candidates = [
        repo / "delta_scout.py",
        repo / "deltascout" / "delta_scout.py",
    ]
    target = next((c for c in candidates if c.exists()), None)
    if not target:
        raise FileNotFoundError(
            f"Could not find delta_scout.py. Looked in: {candidates}. Repo root: {repo}"
        )

    spec = importlib.util.spec_from_file_location("delta_scout_mod", str(target))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ds():
    return _load_delta_scout_module()


def _wire(monkeypatch, ds, *, cap: float, vwap_by_ts: dict[str, float | None]):
    """
    Робимо тест детермінованим:
    - relax гейти (IMB/CHOP/COH/AVG9/ZERO)
    - підміняємо market context (df price/ema50) динамічно по поточному рядку
    - _context() повертає vwap з мапи по Timestamp
    - _emit_json збирає PEAK-и в список
    """
    # --- relax гейти щоб тестувався саме VWAP cap ---
    monkeypatch.setattr(ds, "VWAP_MAX_DIST_USD", float(cap), raising=False)
    monkeypatch.setattr(ds, "IMB_MIN", 0.0, raising=False)
    monkeypatch.setattr(ds, "IMB_MAX", 1.0, raising=False)
    monkeypatch.setattr(ds, "CHOP30_MAX", 9999.0, raising=False)
    monkeypatch.setattr(ds, "COH10_MIN", 0.0, raising=False)
    monkeypatch.setattr(ds, "AVG9_MAX", 9999.0, raising=False)
    monkeypatch.setattr(ds, "ZERO_QTY_TH", 1.0, raising=False)

    state = {"ts": "1970-01-01 00:00:00", "price": 0.0, "ema50": 0.0}

    def load_df_sorted():
        return pd.DataFrame(
            [
                {
                    "Timestamp": pd.to_datetime(state["ts"]).floor("min"),
                    "price": float(state["price"]),
                    "ema50": float(state["ema50"]),
                }
            ]
        )

    monkeypatch.setattr(ds, "load_df_sorted", load_df_sorted)
    monkeypatch.setattr(ds, "locate_index_by_ts", lambda _df, _ts: 0)
    monkeypatch.setattr(ds, "chop30_idx", lambda _df, _i: 1.0)
    monkeypatch.setattr(ds, "coh10_idx", lambda _df, _i: 0.5)

    # прибрати сторонні ефекти
    monkeypatch.setattr(ds.Scout, "_ingest_buyer_events", lambda self: None)
    monkeypatch.setattr(ds.Scout, "_emit", lambda self, *a, **k: None)

    # контекст VWAP по Timestamp
    def _context(self):
        ts = getattr(self, "_test_ts", None)
        v = vwap_by_ts.get(ts)
        if v is None:
            return None, None
        return float(v), 0

    monkeypatch.setattr(ds.Scout, "_context", _context)

    emitted: list[dict] = []

    def _emit_json(self, payload: dict):
        # збираємо всі JSON евенти; в тестах фільтруємо action=="PEAK"
        emitted.append(payload)

    monkeypatch.setattr(ds.Scout, "_emit_json", _emit_json)

    return state, emitted


def _run_rows(ds, state, scout, rows: list[dict]):
    for r in rows:
        ts = str(r["Timestamp"])
        price = float(r["AvgPrice"])
        delta = float(r["BuyQty"]) - float(r["SellQty"])

        scout._test_ts = ts
        state["ts"] = ts
        state["price"] = price

        # EMA50 gate: для long треба price > ema50, для short треба price < ema50
        if delta >= 0:
            state["ema50"] = price - 10_000.0
        else:
            state["ema50"] = price + 10_000.0

        scout.handle_row(r)


def _peaks(emitted: list[dict], kind: str):
    k = kind.lower()
    out = []
    for e in emitted:
        if e.get("action") != "PEAK":
            continue
        if str(e.get("kind", "")).lower() != k:
            continue
        out.append(e)
    return out


def test_long_within_cap_emits(monkeypatch, ds):
    cap = 1000.0

    # 3 хвилини: t0 short dummy (щоб "перший рядок" не був і max і min у long-сценарії),
    # t1 long baseline, t2 long confirm -> має емісити PEAK
    rows = [
        # t0 short dummy
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10, "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        # t1 long baseline (max)
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20, "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
        # t2 long confirm (new max)
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 30, "BuyQty": 18, "SellQty": 6, "AvgPrice": 10500},
    ]

    # VWAP по timestamp:
    # long: price >= vwap, vwap росте (для 3of3), і diff <= cap
    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,   # для dummy неважливо
        "2026-01-01 00:01:00": 9500,   # baseline
        "2026-01-01 00:02:00": 10000,  # confirm: 10500-10000=500
    }

    state, emitted = _wire(monkeypatch, ds, cap=cap, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run_rows(ds, state, s, rows)

    peaks = _peaks(emitted, "long")
    assert len(peaks) == 1
    diff = float(peaks[0]["price"]) - float(peaks[0]["vwap"])
    assert diff <= cap


def test_long_over_cap_blocked(monkeypatch, ds):
    cap = 1000.0

    rows = [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10, "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20, "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 30, "BuyQty": 18, "SellQty": 6, "AvgPrice": 12000},
    ]

    # diff = 12000 - 10500 = 1500 > cap => PEAK має бути заблокований
    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,
        "2026-01-01 00:01:00": 9500,
        "2026-01-01 00:02:00": 10500,
    }

    state, emitted = _wire(monkeypatch, ds, cap=cap, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run_rows(ds, state, s, rows)

    peaks = _peaks(emitted, "long")
    assert len(peaks) == 0


def test_short_within_cap_emits(monkeypatch, ds):
    cap = 1000.0

    # 4 хвилини:
    # t0 long dummy (щоб перший рядок не заважав short-циклу),
    # t1 short baseline,
    # t2 short candidate (НЕ проходить 3of3 через vwap не зменшився),
    # t3 short confirm -> має емісити PEAK
    rows = [
        # t0 long dummy
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10, "BuyQty": 3, "SellQty": 1, "AvgPrice": 12000},
        # t1 short baseline (min)
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 15, "BuyQty": 1, "SellQty": 3, "AvgPrice": 11000},
        # t2 short candidate (new min), але vwap той самий => prev_pass_3of3 має впасти
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 20, "BuyQty": 2, "SellQty": 6, "AvgPrice": 10500},
        # t3 short confirm (new min), vwap зменшився => 3of3 проходить; diff <= cap
        {"Timestamp": "2026-01-01 00:03:00", "Trades": 1, "TotalQty": 30, "BuyQty": 3, "SellQty": 9, "AvgPrice": 10000},
    ]

    vwap_by_ts = {
        "2026-01-01 00:00:00": 11500,  # dummy
        "2026-01-01 00:01:00": 12000,  # baseline (price < vwap)
        "2026-01-01 00:02:00": 12000,  # НЕ зменшився => t2 не емісить PEAK
        "2026-01-01 00:03:00": 10800,  # зменшився; diff=10800-10000=800
    }

    state, emitted = _wire(monkeypatch, ds, cap=cap, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run_rows(ds, state, s, rows)

    peaks = _peaks(emitted, "short")
    assert len(peaks) == 1
    diff = float(peaks[0]["vwap"]) - float(peaks[0]["price"])
    assert diff <= cap


def test_short_over_cap_blocked(monkeypatch, ds):
    cap = 1000.0

    rows = [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10, "BuyQty": 3, "SellQty": 1, "AvgPrice": 12000},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 15, "BuyQty": 1, "SellQty": 3, "AvgPrice": 11000},
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 20, "BuyQty": 2, "SellQty": 6, "AvgPrice": 10500},
        {"Timestamp": "2026-01-01 00:03:00", "Trades": 1, "TotalQty": 30, "BuyQty": 3, "SellQty": 9, "AvgPrice": 10000},
    ]

    # Тут робимо diff > cap на фінальному confirm:
    # vwap зменшується (для 3of3), але vwap-price = 11500-10000=1500 => заблокувати
    vwap_by_ts = {
        "2026-01-01 00:00:00": 11500,
        "2026-01-01 00:01:00": 12000,
        "2026-01-01 00:02:00": 12000,  # щоб t2 не емісив
        "2026-01-01 00:03:00": 11500,  # diff=1500 > cap
    }

    state, emitted = _wire(monkeypatch, ds, cap=cap, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run_rows(ds, state, s, rows)

    peaks = _peaks(emitted, "short")
    assert len(peaks) == 0


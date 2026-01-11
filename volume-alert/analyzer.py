import pandas as pd
import numpy as np
import os
import requests
from typing import Tuple

script_dir = os.path.dirname(os.path.abspath(__file__))
feed_dir = os.getenv("FEED_DIR", os.path.join(script_dir, "feed"))
csv_file = os.path.join(feed_dir, "aggregated.csv")

N8N_URL = "http://n8n:5678/webhook/volume-alert"  # Production URL
NIGHT_LOG_PATH = "/night_volume_spikes.log"

# =============================
# Helpers
# =============================

def _passes_volume_gate(rel_vol_90m: float, imbalance_10m: float, rv_thr: float = 3, imb_thr: float = 0.55 ) -> bool:
    """True коли 10-хв обсяг винятковий (vs 90хв-база) і тиск односторонній."""
    return (rel_vol_90m >= rv_thr) and (imbalance_10m >= imb_thr)

def _flip_climax_annotation() -> dict:
    global climax_buy, climax_sell
    return {"climax": "BUY" if climax_buy else ("SELL" if climax_sell else "—")}

def _fmt_signed_int(x: float) -> str:
    v = int(round(float(x)))
    return f"{v:+d}"

# -----------------------------
# Sessions with minute precision
# EU: 08:00–15:29, US: 15:30–23:59, else ASIA
# -----------------------------

def _session_by_time(ts: str) -> str:
    hh = int(ts[11:13]); mm = int(ts[14:16])
    m = hh * 60 + mm
    if 15*60 + 30 <= m < 24*60:
        return "US"
    elif 8*60 <= m < 15*60 + 30:
        return "EU"
    else:
        return "ASIA"

def get_volume_threshold_by_time(ts: str):
    hh = int(ts[11:13]); mm = int(ts[14:16])
    m = hh * 60 + mm
    if 8*60 <= m < 15*60 + 30:
        return 3  # EU
    elif 15*60 + 30 <= m < 24*60:
        return 5  # US
    else:
        return None

# -----------------------------
# Deterministic ΣΔsess from CSV
# -----------------------------

def _prepare_df_for_session_calc(df: pd.DataFrame) -> pd.DataFrame:
    dfx = df.dropna(subset=["Timestamp"]).copy()
    dfx = dfx.sort_values("Timestamp").copy()
    dfx = dfx.drop_duplicates(subset=["Timestamp"], keep="last").reset_index(drop=True)
    return dfx

def _compute_session_cum_from_df(df: pd.DataFrame) -> Tuple[str, float, float]:
    """Return (sid, sess_cum, from_low) for the current session tail.
    sess_cum = Σ(BuyQty) − Σ(SellQty) over the continuous tail that belongs to the same session as the last row.
    from_low = distance from the session's running-min of cumulative delta (prefix-sum based).
    """
    if df.empty:
        return "OFF", 0.0, 0.0

    last_ts = str(df.iloc[-1]["Timestamp"])  # 'YYYY-MM-DD HH:MM:SS'
    sid = _session_by_time(last_ts)

    # find start index of the same-session tail
    start_i = len(df) - 1
    for i in range(len(df) - 1, -1, -1):
        tsi = str(df.iloc[i]["Timestamp"])
        if _session_by_time(tsi) != sid:
            break
        start_i = i
    seg = df.iloc[start_i:]

    # ΣΔsess
    buy = seg["BuyQty"].astype(float).sum()
    sell = seg["SellQty"].astype(float).sum()
    sess_cum_val = float(buy - sell)

    # distance from session low
    deltas = (seg["BuyQty"].astype(float) - seg["SellQty"].astype(float)).to_numpy()
    if deltas.size:
        cum = np.cumsum(deltas)
        from_low = float(sess_cum_val - cum.min())
    else:
        from_low = 0.0

    return sid, sess_cum_val, from_low

# =============================
# Main
# =============================

def analyze_last_10():
    if not os.path.exists(csv_file):
        print(f"aggregated.csv not found: {csv_file}")
        return

    df = pd.read_csv(csv_file, header=0, encoding="utf-8-sig")
    df.rename(columns=lambda x: x.replace('\ufeff', ''), inplace=True)
    # Backward/forward compatible CSV schema:
    # - Old schema: ... AvgPrice,ClosePrice
    # - New schema: ... AvgPrice,ClosePrice,HiPrice,LowPrice
    # Ensure price columns are numeric, and provide Hi/Lo fallbacks for old CSVs.
    for _c in ("AvgPrice", "ClosePrice", "HiPrice", "LowPrice"):
        if _c in df.columns:
            df[_c] = pd.to_numeric(df[_c], errors="coerce")

    if "ClosePrice" in df.columns:
        if "HiPrice" not in df.columns:
            df["HiPrice"] = df["ClosePrice"]
        if "LowPrice" not in df.columns:
            df["LowPrice"] = df["ClosePrice"]
    df = _prepare_df_for_session_calc(df)

    if len(df) < 10:
        print("⚠️ Недостатньо даних для аналізу (менше 10 рядків).")
        return

    last_10 = df.tail(10)
    last_row = last_10.tail(1).iloc[0]

    global time_val, num_trades, total_volume, avg_price, dominance, mean_volume, dominance_10m, delta_10m
    global climax_buy, climax_sell

    # 1m metrics
    time_val = str(last_row["Timestamp"])  # ensure str
    num_trades = int(last_row["Trades"]) if not pd.isna(last_row["Trades"]) else 0
    total_volume = float(last_row["TotalQty"]) if not pd.isna(last_row["TotalQty"]) else 0.0
    avg_price = float(last_row["AvgPrice"]) if not pd.isna(last_row["AvgPrice"]) else 0.0
    buy_qty = float(last_row["BuyQty"]) if not pd.isna(last_row["BuyQty"]) else 0.0
    sell_qty = float(last_row["SellQty"]) if not pd.isna(last_row["SellQty"]) else 0.0
    dominance = buy_qty / (buy_qty + sell_qty) if (buy_qty + sell_qty) > 0 else 0.0
    mean_volume = float(last_10.head(9)["TotalQty"].astype(float).mean())
    delta_1m = buy_qty - sell_qty
    signed_imbalance_1m = (delta_1m / total_volume) if total_volume > 0 else 0.0

    # 10m aggregates
    total_buy_10m = float(last_10["BuyQty"].astype(float).sum())
    total_sell_10m = float(last_10["SellQty"].astype(float).sum())
    dominance_10m = (total_buy_10m / (total_buy_10m + total_sell_10m)) if (total_buy_10m + total_sell_10m) > 0 else 0.0
    delta_10m = float(total_buy_10m - total_sell_10m)

    # 90m base (exclude current minute)
    prev90 = df.iloc[-(90+1):-1] if len(df) > 91 else df.iloc[0:0]
    if not prev90.empty:
        base90 = float(prev90["TotalQty"].astype(float).median())
    else:
        prev30 = df.iloc[-(30+1):-1]
        base90 = float(prev30["TotalQty"].astype(float).median()) if not prev30.empty else max(float(last_10["TotalQty"].astype(float).median()), 1e-6)
    base90 = max(base90, 1e-6)

    vol10 = float(last_10["TotalQty"].astype(float).sum())
    rel_vol_90m = (vol10 / 10.0) / base90
    imbalance_10m = abs(delta_10m) / max(vol10, 1e-6)

    # 1m quantiles over prev90
    if not prev90.empty and len(prev90) >= 20:
        vols_prev90 = prev90["TotalQty"].astype(float).dropna().to_numpy()
        if vols_prev90.size >= 20:
            p90_1m = float(np.percentile(vols_prev90, 90))
            p95_1m = float(np.percentile(vols_prev90, 95))
            p99_1m = float(np.percentile(vols_prev90, 99))
        else:
            p90_1m, p95_1m, p99_1m = 34.0, 50.0, 120.0
    else:
        p90_1m, p95_1m, p99_1m = 34.0, 50.0, 120.0

    # Climax detection (message-only)
    climax_buy = False
    climax_sell = False
    if (rel_vol_90m >= 3.0) and (imbalance_10m >= 0.75):
        if delta_10m > 0:
            climax_buy = True
        elif delta_10m < 0:
            climax_sell = True

    # Threshold by minute-accurate session clock
    threshold = get_volume_threshold_by_time(time_val)

    # ===== Deterministic session CumΔ from CSV (NO incremental update!) =====
    sid, sess_cum_val, sess_from_low_val = _compute_session_cum_from_df(df)
    sess_line = f"ΣΔsess({sid}): {_fmt_signed_int(sess_cum_val)}  [↑{_fmt_signed_int(sess_from_low_val)}]"

    # --- Формування метрик для передачі ---
    metrics = {
        "time_val": time_val,
        "num_trades": num_trades,
        "total_volume": total_volume,
        "avg_price": avg_price,
        "dominance": dominance,
        "mean_volume": mean_volume,
        "dominance_10m": dominance_10m,
        "delta_10m": delta_10m,
        "rel_vol_90m": rel_vol_90m,
        "imbalance_10m": imbalance_10m,
        "signed_imbalance_1m": signed_imbalance_1m,
        "climax": _flip_climax_annotation(),
        "sess_line": sess_line,
        "current_sess": sid,
        "sess_cum": sess_cum_val,
        "sess_from_low": sess_from_low_val,
    }

    # Print log
    print(f"\n🔍 Час: {time_val}")
    print(f"📈 К-сть угод за хв.: {num_trades}")
    print(f"📅 Price: {avg_price:.0f}")
    print(f"💰 Об'єм BTC за останю хв.: \033[93m{int(round(metrics['total_volume']))} BTC\033[0m")
    print(f"🔢 Середній об'єм BTC (за попередні 9 хв): {int(round(mean_volume))} BTC")
    print(f"📊 Покупців за останні 10 хв: {int(round(dominance_10m * 100))}%")
    print(f"                          📉 Δ (10м): {delta_10m:.0f} BTC")
    print(f"                          📦imb(10m)={imbalance_10m:.2f} BTC")
    print(f"⚖️ Imb_1min: {signed_imbalance_1m:+.2f}")
    print(f"📦 relVol90={rel_vol_90m:.2f}")
    print(f"🎚 P90={p90_1m:.1f} | P95={p95_1m:.1f} | P99={p99_1m:.1f}")
    print(sess_line)
    print(f"⚠️ Climax: {'Achtung' if climax_buy else ('Achtung' if climax_sell else '—')}")

    # Triggering
    passes_gate = _passes_volume_gate(rel_vol_90m, imbalance_10m)
    if threshold is not None:
        is_spike3 = (
            passes_gate and (threshold == 3)
            and (mean_volume > 11)
            and (total_volume >= p99_1m)
            and (total_volume > mean_volume * 3)
        )
        is_spike5 = (
            passes_gate and (threshold == 5)
            and (mean_volume > 13)
            and (total_volume >= p99_1m)
            and (total_volume > mean_volume * 4)
        )
        if is_spike3 or is_spike5:
            send_alert(
                f"🚨 VPS-СПАЙК: об'єм перевищує середній!",
                night=False,
                metrics=metrics,
            )
    else:
        is_night_spike = (
            passes_gate and (mean_volume > 15)
            and (total_volume >= p99_1m)
            and (total_volume > mean_volume * 4)
        )
        if is_night_spike:
            send_alert(
                "🌙 Нічний VPS-спайк: обʼєм  перевищує середній!",
                night=False,
                metrics=metrics,
            )

def build_message(prefix: str, metrics: dict) -> str:
    ann = metrics.get("climax", {"climax": "—"})
    imb1m = float(metrics.get("signed_imbalance_1m", 0.0))
    rv90 = float(metrics.get("rel_vol_90m", 0.0))
    imb10 = float(metrics.get("imbalance_10m", 0.0))
    lines = [
        f"{prefix}",
        f"🔍 Час: {metrics['time_val']}",
        f"📈 К-сть угод за хв.: {metrics['num_trades']}",
        f"📅 Price: {metrics['avg_price']:.0f}",
        f"💰 Об'єм BTC за хв.: {int(round(metrics['total_volume']))} BTC",
        f"🔢 Середній об'єм BTC (за попередні 9 хв): {int(round(metrics['mean_volume']))} BTC",
        f"📊 Покупців за останні 10 хв: {int(round(metrics['dominance_10m'] * 100))}%",
        f"📉 Δ (10хв):   {metrics['delta_10m']:.0f} BTC",
        f"⚖️ Imb(10хв) ={imb10:.2f}",
        f"⚖️ Imb1m (1хв): {imb1m:+.2f}",
        f"📦 relVol90={rv90:.1f}",
        metrics.get('sess_line', "ΣΔsess(OFF): +0  [↑+0]"),
        f"⚠️ Climax: {ann['climax']}",
    ]
    return "\n".join(lines)

def send_alert(prefix: str, night: bool = False, metrics: dict | None = None):
    msg = build_message(prefix, metrics)
    payload = {
        "event": "volume_spike",
        "reason": prefix,
        "volume": float(metrics["total_volume"]),
        "mean_volume": float(metrics["mean_volume"]),
        "timestamp": str(metrics["time_val"]),
        "dominance_10m": float(metrics["dominance_10m"]),
        "delta_10m": float(metrics["delta_10m"]),
        "avg_price": float(metrics["avg_price"]),
        "relVol90": float(metrics["rel_vol_90m"]),
        "imbalance_10m": float(metrics["imbalance_10m"]),
        "imbalance_1m": float(round(metrics["signed_imbalance_1m"], 4)),
        "climax": metrics.get("climax", {"climax": "—"})["climax"],
        "message": msg,
        # Session CumΔ fields
        "sess": metrics.get("current_sess", "OFF"),
        "cumDelta_sess": int(round(metrics.get("sess_cum", 0.0))),
        "cumDelta_sess_from_low": int(round(metrics.get("sess_from_low", 0.0))),
        "cumDelta_line": metrics.get("sess_line", ""),
    }
    if night:
        payload["night"] = False
    requests.post(N8N_URL, json=payload, timeout=10)


if __name__ == "__main__":
    analyze_last_10()

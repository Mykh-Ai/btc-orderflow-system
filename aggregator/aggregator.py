#!/usr/bin/env python3
"""
Binance trade logger + interval aggregator.

This script:
- connects to Binance WebSocket trades stream (hardcoded stream URL as in your current VPS setup),
- appends each trade as a text line into /app/logs/trades_log.txt,
- every AGG_INTERVAL seconds aggregates the log into /app/feed/aggregated.csv,
- trims aggregated.csv to MAX_RECORDS (plus header),
- clears trades_log.txt for the next interval.

Repository-ready changes:
- English-only comments/messages.
- External process trigger removed (aggregator only produces aggregated.csv).

NOTE: Core aggregation metrics are unchanged.
HiPrice/LowPrice were added as extra columns computed per interval.
"""

import json, time, datetime, socket
import websocket
import threading
import os
import sys

# --- directories inside container ---
feed_dir = os.getenv("FEED_DIR", "/data/feed")
logs_dir = os.getenv("LOGS_DIR", "/data/logs")


os.makedirs(feed_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)


aggregated_file_path = os.path.join(feed_dir, "aggregated.csv")
log_file_path = os.path.join(logs_dir, "trades_log.txt")

# ===========================
# CSV schema (backward-safe)
# ===========================
OLD_HEADER = "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n"
NEW_HEADER = "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice\n"

def ensure_csv_schema() -> None:
    """Prevent mixed-width CSV rows.

    If aggregated.csv exists with the old 8-col header, migrate it in-place:
      - replace header with NEW_HEADER
      - pad existing 8-col rows with two empty columns
    """
    if not os.path.isfile(aggregated_file_path):
        return

    try:
        with open(aggregated_file_path, "r", encoding="utf-8") as f:
            rows = f.readlines()

        if not rows:
            return

        def _norm(s: str) -> str:
            # handle UTF-8 BOM and Windows newlines; compare logical header content
            return s.lstrip("\ufeff").strip("\r\n")

        hdr = rows[0]
        if _norm(hdr) == _norm(NEW_HEADER):
            return

        # Only migrate if we exactly recognize the old header.
        if _norm(hdr) != _norm(OLD_HEADER):
            return

        migrated = [NEW_HEADER]
        for ln in rows[1:]:
            line = ln.rstrip("\r\n")
            if not line:
                continue
            parts = line.split(",")
            if len(parts) == 8:
                parts += ["", ""]
                migrated.append(",".join(parts) + "\n")
            elif len(parts) == 10:
                migrated.append(line + "\n")
            else:
                # Unexpected width — keep as-is to avoid destroying data.
                migrated.append(line + "\n")

        tmp = aggregated_file_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(migrated)
        os.replace(tmp, aggregated_file_path)
        print("🛠️ aggregated.csv migrated to include HiPrice/LowPrice", flush=True)

    except Exception as e:
        print(f"CSV schema migration error: {e}", flush=True)

# Settings
AGG_INTERVAL = int(os.getenv("AGG_INTERVAL", "60"))
MAX_RECORDS = int(os.getenv("MAX_RECORDS", "1500"))

# Writer (Binance WebSocket)
# ===========================
websocket.setdefaulttimeout(5)
last_error_message = None
STATE = {"status": None, "since": 0, "retries": 0, "last_ping": 0}

def log_state(new_status, note="", remind_interval=120):
    now = time.time()
    if new_status != STATE["status"] or (
        new_status == "disconnected" and now - STATE["last_ping"] >= remind_interval
    ):
        if new_status == "connected":
            print("✅ Binance WS connected", flush=True)
            STATE.update({"status": "connected", "since": now, "retries": 0, "last_ping": now})
        else:
            retry_info = f" | retries={STATE['retries']}" if STATE["retries"] else ""
            print(f"⚠️ Binance WS disconnected{retry_info} | {note}", flush=True)
            STATE.update({"status": "disconnected", "last_ping": now})

def on_message(ws, message):
    data = json.loads(message)
    price = float(data["p"])
    qty = float(data["q"])
    trade_time = datetime.datetime.fromtimestamp(data["T"] / 1000)
    side = "Sell" if data["m"] else "Buy"

    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(f"{trade_time} | {side} | Price: {price} | Qty: {qty}\n")

def on_error(ws, error):
    global last_error_message
    msg = str(error)
    if msg != last_error_message:
        log_state("disconnected", msg)
        last_error_message = msg
    try:
        ws.close()
    except:
        pass

def on_close(ws, close_status_code, close_msg):
    log_state("disconnected", f"close_code={close_status_code} msg={close_msg}")

def on_open(ws):
    log_state("connected")


def writer_loop():
    socket_url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    backoff = 5

    while True:
        try:
            socket.gethostbyname("stream.binance.com")

            ws = websocket.WebSocketApp(
                socket_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.on_open = on_open
            ws.run_forever(ping_interval=20, ping_timeout=10)

            time.sleep(2)
            backoff = 5
        except Exception as e:
            STATE["retries"] = STATE.get("retries", 0) + 1
            log_state("disconnected", str(e))
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


# ===========================
# Aggregator
# ===========================
first_aggregation = True

def aggregate_and_clear():
    global first_aggregation

    if first_aggregation:
        print("\n🚀 Aggregation started...", flush=True)
        first_aggregation = False

    if not os.path.exists(log_file_path):
        print("Trades log file not found: trades_log.txt", flush=True)
        return

    with open(log_file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        print("Trades log is empty; waiting for the next interval...", flush=True)
        return

    # Ensure we never mix 8-col and 10-col rows in aggregated.csv
    ensure_csv_schema()

    num_trades = len(lines)
    total_qty = 0.0
    total_price = 0.0
    buy_qty = 0.0
    sell_qty = 0.0
    close_price = None
    high_price = None
    low_price = None

    for line in lines:
        try:
            parts = line.strip().split("|")
            side_part = parts[1].strip()
            price = float(parts[2].strip().replace("Price:", "").strip())
            qty = float(parts[3].strip().replace("Qty:", "").strip())

            total_qty += qty
            total_price += price * qty

            if "Buy" in side_part:
                buy_qty += qty
            elif "Sell" in side_part:
                sell_qty += qty

            close_price = price
            if high_price is None or price > high_price:
                high_price = price
            if low_price is None or price < low_price:
                low_price = price
        except Exception as e:
            print("Line parse error:", line, e, flush=True)

    avg_size = total_qty / num_trades if num_trades > 0 else 0.0
    avg_price = total_price / total_qty if total_qty > 0 else 0.0

    if close_price is None:
        # If all lines were unparsable, avoid crashing on formatting.
        close_price = avg_price
    if high_price is None:
        high_price = close_price
    if low_price is None:
        low_price = close_price

    file_exists = os.path.isfile(aggregated_file_path)
    with open(aggregated_file_path, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write(NEW_HEADER)

        f.write(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')},"
            f"{num_trades},"
            f"{total_qty:.6f},"
            f"{avg_size:.6f},"
            f"{buy_qty:.6f},"
            f"{sell_qty:.6f},"
            f"{avg_price:.0f},"
            f"{close_price:.0f},"
            f"{high_price:.0f},"
            f"{low_price:.0f}\n"
        )

    # Trim aggregated.csv to keep bounded size (original behavior preserved)
    with open(aggregated_file_path, "r", encoding="utf-8") as f:
        rows = f.readlines()

    if len(rows) > MAX_RECORDS + 1:
        with open(aggregated_file_path, "w", encoding="utf-8") as f:
            f.writelines([rows[0]] + rows[2:])

    # Clear trades_log.txt for the next interval
    open(log_file_path, "w", encoding="utf-8").close()


if __name__ == "__main__":
    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    sleep_to = AGG_INTERVAL - (time.time() % AGG_INTERVAL)
    time.sleep(sleep_to)

    while True:
        aggregate_and_clear()
        delay = AGG_INTERVAL - (time.time() % AGG_INTERVAL)
        time.sleep(delay)

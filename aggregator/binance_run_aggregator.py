import json, time, datetime, socket
import websocket
import threading
import os
import sys
import subprocess

# --- теки для збереження всередині контейнера ---
feed_dir = "/app/feed"
logs_dir = "/app/logs"

os.makedirs(feed_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)

aggregated_file_path = os.path.join(feed_dir, "aggregated.csv")
log_file_path = os.path.join(logs_dir, "trades_log.txt")
lock_file_path = os.path.join(logs_dir, "analyzer.lock")

AGG_INTERVAL = 60
first_aggregation = True
MAX_RECORDS = 1500
LOCK_TIMEOUT = 300  # 5 хвилин

# ===========================
# Writer (WebSocket Binance)
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
            print(f"⚠️ Binance WS disconnected{retry_info}" + (f" | {note}" if note else ""), flush=True)
            STATE.update({"status": "disconnected", "last_ping": now})

def on_message(ws, message):
    data = json.loads(message)
    price = float(data['p'])
    qty = float(data['q'])
    trade_time = datetime.datetime.fromtimestamp(data['T'] / 1000.0)
    is_buyer_maker = data['m']
    side = "Sell" if is_buyer_maker else "Buy"
    line = f"{trade_time} | {side} | Price: {price} | Qty: {qty}\n"
    with open(log_file_path, "a") as f:
        f.write(line)

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
    log_state("disconnected", f"close_code={close_status_code} msg={close_msg or ''}")

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
                on_close=on_close
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
def aggregate_and_clear():
    global first_aggregation
    if first_aggregation:
        print("\n🚀 Агрегація почалась...")
        first_aggregation = False
    if not os.path.exists(log_file_path):
        print("Файл trades_log.txt не найден.")
        return
    with open(log_file_path, "r") as f:
        lines = f.readlines()
    if not lines:
        print("Файл пуст, жду следующий интервал...")
        return
    num_trades = len(lines)
    total_qty = total_price = buy_qty = sell_qty = 0
    close_price = None
    high_price = None
    low_price = None
    for line in lines:
        try:
            parts = line.strip().split('|')
            side_part = parts[1].strip()
            price = float(parts[2].strip().replace('Price:', '').strip())
            qty = float(parts[3].strip().replace('Qty:', '').strip())
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
            print("Ошибка парсинга строки:", line, e)

    # Safety: if no valid trades parsed, avoid formatting None
    if close_price is None:
        return  # nothing to write this interval
    if high_price is None:
        high_price = close_price
    if low_price is None:
        low_price = close_price
    avg_size = total_qty / num_trades if num_trades > 0 else 0
    avg_price = total_price / total_qty if total_qty > 0 else 0
    file_exists = os.path.isfile(aggregated_file_path)
    with open(aggregated_file_path, "a") as f:
        if not file_exists:
            f.write("Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice\n")
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{num_trades},{total_qty:.6f},{avg_size:.6f},{buy_qty:.6f},{sell_qty:.6f},{avg_price:.6f},{close_price:.0f},{high_price:.0f},{low_price:.0f}\n")
    with open(aggregated_file_path, "r") as f:
        rows = f.readlines()
    if len(rows) > MAX_RECORDS + 1:
        with open(aggregated_file_path, "w") as f:
            f.writelines([rows[0]] + rows[2:])
    open(log_file_path, "w").close()
    # Запуск аналізатора з перевіркою блокування
    if os.path.exists(lock_file_path):
        mtime = os.path.getmtime(lock_file_path)
        if time.time() - mtime > LOCK_TIMEOUT:
            print("⏱️ Lock прострочений — видаляю...")
            try:
                os.remove(lock_file_path)
            except:
                pass
        else:
            print("🔒 Lock ще активний — пропускаю запуск analyzer.py")
            return
    if not os.path.exists(lock_file_path):
        try:
            open(lock_file_path, 'w').close()
            subprocess.Popen([sys.executable, "analyzer.py"])
        except Exception as e:
            print("❌ Не вдалося запустити analyzer.py:", e)
        finally:
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)

# ===========================
# Main loop
# ===========================
if __name__ == "__main__":
    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()
    # вирівнюємо старт на початок наступної хвилини (HH:MM:00)
    sleep_to = AGG_INTERVAL - (time.time() % AGG_INTERVAL)
    time.sleep(sleep_to)
    while True:
        aggregate_and_clear()
        # бездрейфова затримка: рівно до наступного кордону хвилини
        delay = AGG_INTERVAL - (time.time() % AGG_INTERVAL)
        time.sleep(delay)

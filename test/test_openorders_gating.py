import types
import executor


class _DummySnapshot:
    def __init__(self, orders=None, ok=True, error=None):
        self.ok = ok
        self.error = error
        self._orders = orders or []
        self.ts_updated = 0.0

    def freshness_sec(self):
        return 0.0

    def get_orders(self):
        return list(self._orders)


def _mk_state(status: str):
    # manage_v15_position має ранній return якщо немає orders/prices
    return {
        "position": {
            "mode": "live",
            "status": status,
            "orders": {"sl": 1, "tp1": 2, "tp2": 3},
            "prices": {"sl": 100.0, "tp1": 110.0, "tp2": 120.0},
        }
    }


def test_manage_does_not_call_openorders_in_open_filled(monkeypatch):
    st = _mk_state("OPEN_FILLED")

    # якщо open_orders буде викликаний — тест має впасти
    def _boom(_symbol):
        raise AssertionError("open_orders must NOT be called in OPEN_FILLED")

    monkeypatch.setattr(executor.binance_api, "open_orders", _boom, raising=True)

    events = []

    def _log_event(action, **fields):
        events.append((action, fields))

    monkeypatch.setattr(executor, "log_event", _log_event, raising=True)
    monkeypatch.setattr(executor, "save_state", lambda _st: None, raising=True)

    executor.manage_v15_position(executor.ENV.get("SYMBOL", "BTCUSDC"), st)

    assert any(a == "MANAGE_SKIP_OPENORDERS" for a, _ in events), events


def test_manage_calls_snapshot_refresh_only_in_open(monkeypatch):
    st = _mk_state("OPEN")

    calls = {"open_orders": 0, "refresh_snapshot": 0}
    dummy_snapshot = _DummySnapshot(orders=[{"orderId": 123}], ok=True)

    def _open_orders(_symbol):
        calls["open_orders"] += 1
        return [{"orderId": 123}]

    monkeypatch.setattr(executor.binance_api, "open_orders", _open_orders, raising=True)

    monkeypatch.setattr(executor, "get_snapshot", lambda: dummy_snapshot, raising=True)

    # тут важливо: manage_v15_position викликає refresh_snapshot(... open_orders_fn=binance_api.open_orders ...)
    def _refresh_snapshot(symbol, source, open_orders_fn, min_interval_sec):
        calls["refresh_snapshot"] += 1
        # імітуємо реальний refresh: дергаємо open_orders_fn 1 раз, кладемо в snapshot
        dummy_snapshot._orders = open_orders_fn(symbol)
        dummy_snapshot.ok = True
        dummy_snapshot.error = None
        return True  # refreshed=True → має залогувати SNAPSHOT_REFRESH

    monkeypatch.setattr(executor, "refresh_snapshot", _refresh_snapshot, raising=True)

    events = []

    def _log_event(action, **fields):
        events.append((action, fields))

    monkeypatch.setattr(executor, "log_event", _log_event, raising=True)
    monkeypatch.setattr(executor, "save_state", lambda _st: None, raising=True)

    executor.manage_v15_position(executor.ENV.get("SYMBOL", "BTCUSDC"), st)

    assert calls["refresh_snapshot"] == 1
    assert calls["open_orders"] == 1
    assert any(a == "SNAPSHOT_REFRESH" for a, _ in events), events

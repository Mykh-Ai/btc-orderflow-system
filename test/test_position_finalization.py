import ast
import unittest
from pathlib import Path

import executor_mod.position_finalization as pf


def _pos(**overrides):
    pos = {
        "mode": "live",
        "status": "OPEN_FILLED",
        "side": "LONG",
        "opened_at": "2026-01-01T00:00:00Z",
        "trade_key": "TK_CURRENT",
        "client_id": "CL_FALLBACK",
        "order_id": 101,
        "qty": 0.25,
        "entry_actual": 95010.0,
        "prices": {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
        "orders": {"sl": 201, "tp1": 202, "tp2": 203, "qty1": 0.08, "qty2": 0.08, "qty3": 0.09},
        "tp1_done": True,
        "tp2_done": False,
        "sl_done": True,
        "trail_active": True,
        "trail_sl_price": 94500.0,
    }
    pos.update(overrides)
    return pos


class TestPositionFinalizationBuilders(unittest.TestCase):
    def test_close_enrichment_exact_whitelist(self):
        out = pf.close_enrichment_from_pos(_pos())
        self.assertEqual(
            list(out.keys()),
            [
                "opened_at",
                "trade_key",
                "order_id",
                "qty",
                "entry_ref",
                "entry_actual",
                "order_id_sl",
                "order_id_tp1",
                "order_id_tp2",
                "qty1",
                "qty2",
                "qty3",
                "tp1_done",
                "tp2_done",
                "sl_done",
                "trail_active",
                "trail_sl_price",
                "prices",
            ],
        )
        self.assertEqual(out["trade_key"], "TK_CURRENT")
        self.assertEqual(out["entry_ref"], 95000.0)
        self.assertEqual(out["order_id_sl"], 201)
        self.assertIs(out["tp1_done"], True)
        self.assertIs(out["tp2_done"], False)
        self.assertIs(out["sl_done"], True)
        self.assertIs(out["trail_active"], True)

    def test_close_enrichment_trade_key_falls_back_to_client_id(self):
        pos = _pos()
        pos.pop("trade_key")
        self.assertEqual(pf.close_enrichment_from_pos(pos)["trade_key"], "CL_FALLBACK")

    def test_build_clear_position_last_closed_preserves_legacy_and_override(self):
        out = pf.build_clear_position_last_closed(
            _pos(order_id=101, entry_actual=95010.0),
            "ENTRY_TIMEOUT",
            "2026-01-01T00:01:00Z",
            {"order_id": 999, "entry_actual": None, "fallback": "NONE"},
        )
        self.assertEqual(out["ts"], "2026-01-01T00:01:00Z")
        self.assertEqual(out["mode"], "live")
        self.assertEqual(out["reason"], "ENTRY_TIMEOUT")
        self.assertEqual(out["pos_status"], "OPEN_FILLED")
        self.assertEqual(out["order_id"], 999)
        self.assertIsNone(out["entry_actual"])
        self.assertEqual(out["fallback"], "NONE")

    def test_build_live_close_last_closed_matches_current_close_slot_shape(self):
        out = pf.build_live_close_last_closed(_pos(), "SL", "2026-01-01T00:02:00Z")
        self.assertEqual(out["ts"], "2026-01-01T00:02:00Z")
        self.assertEqual(out["mode"], "live")
        self.assertEqual(out["reason"], "SL")
        self.assertEqual(out["side"], "LONG")
        self.assertEqual(out["entry"], 95000.0)
        self.assertEqual(out["trade_key"], "TK_CURRENT")
        self.assertEqual(out["prices"]["tp2"], 97000.0)

    def test_build_sync_last_closed_order_status_only_when_supplied(self):
        base = pf.build_sync_last_closed(_pos(), "SYNC_EXCHANGE_CLEAR", "2026-01-01T00:03:00Z")
        self.assertEqual(
            base,
            {
                "ts": "2026-01-01T00:03:00Z",
                "mode": "live",
                "reason": "SYNC_EXCHANGE_CLEAR",
                "pos_status": "OPEN_FILLED",
                "trade_key": "TK_CURRENT",
                "order_id": 101,
                "side": "LONG",
                "qty": 0.25,
                "entry_ref": 95000.0,
                "entry_actual": 95010.0,
                "opened_at": "2026-01-01T00:00:00Z",
            },
        )
        with_status = pf.build_sync_last_closed(
            _pos(status="PENDING"),
            "SYNC_CONFIRMED_CANCELED",
            "2026-01-01T00:04:00Z",
            order_status="CANCELED",
        )
        self.assertEqual(with_status["pos_status"], "PENDING")
        self.assertEqual(with_status["order_status"], "CANCELED")


class TestPositionFinalizationPurity(unittest.TestCase):
    def test_helper_module_imports_are_pure(self):
        source_path = Path(pf.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = set()
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)

        self.assertNotIn("executor", imported_modules)
        self.assertNotIn("executor_mod.binance_api", imported_modules)
        self.assertNotIn("executor_mod.notifications", imported_modules)
        self.assertNotIn("executor_mod.state_store", imported_modules)
        self.assertNotIn("executor_mod.margin_guard", imported_modules)
        self.assertNotIn("save_state", imported_names)
        self.assertNotIn("log_event", imported_names)
        self.assertNotIn("send_webhook", imported_names)

    def test_helper_module_contains_no_later_safety_identifiers(self):
        source = Path(pf.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "watch" + "dog",
            "WATCH" + "DOG",
            "Price" + "Snapshot",
            "price_" + "snapshot",
            "direct " + "price",
            "partial " + "fill",
            "PAR" + "TIAL",
            "sli" + "ppage",
            "sli" + "p",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

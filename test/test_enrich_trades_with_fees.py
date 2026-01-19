import sys
import types
import unittest


def _install_requests_failfast_stub() -> None:
    """
    Fail-fast stub for 'requests' so tests never accidentally hit the network.
    If real 'requests' is installed, we leave it alone.
    """
    if "requests" in sys.modules:
        return
    mod = types.ModuleType("requests")

    def _no_network(*args, **kwargs):
        raise RuntimeError("Network access is disabled in unit tests (requests stub).")

    class _Session:
        def __init__(self, *a, **k):
            raise RuntimeError("Network access is disabled in unit tests (requests stub).")

    mod.get = _no_network
    mod.post = _no_network
    mod.request = _no_network
    mod.Session = _Session
    sys.modules["requests"] = mod


def _notes_text(out: dict) -> str:
    """
    Normalize notes field(s) to text for robust asserts.
    Supports string / list / tuple / set. Falls back to str(value).
    """
    val = out.get("reconciliation_notes", None)
    if val is None:
        val = out.get("notes", "")
    if isinstance(val, (list, tuple, set)):
        return " ".join(str(x) for x in val)
    if isinstance(val, str):
        return val
    return str(val)


_install_requests_failfast_stub()

from tools import enrich_trades_with_fees


class TestEnrichTradesWithFees(unittest.TestCase):
    def test_blocks_pnl_when_all_exit_legs_unfilled(self):
        rec = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": "100",
            "qty_base_total": "1",
            "exit_leg_orders": {
                "tp1": {
                    "orderId": 123,
                    "executedQty": "0",
                    "cummulativeQuoteQty": "0",
                    "status": "NEW",
                }
            },
        }

        out = enrich_trades_with_fees._enrich_record(rec, cache={})

        self.assertIsNone(out.get("pnl_quote"))
        self.assertIsNone(out.get("roi_pct"))
        self.assertIn("pnl_blocked_no_filled_exit", _notes_text(out))

    def test_allows_pnl_when_exit_leg_filled(self):
        rec = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": "100",
            "qty_base_total": "1",
            "exit_leg_orders": {
                "tp1": {
                    "orderId": 456,
                    "executedQty": "1",
                    "cummulativeQuoteQty": "120",
                    "status": "FILLED",
                }
            },
        }
        cache = {
            ("BTCUSDT", 456): [
                {"commissionAsset": "USDT", "commission": "0.1"}
            ]
        }

        out = enrich_trades_with_fees._enrich_record(rec, cache=cache)

        self.assertIsNotNone(out.get("pnl_quote"))
        self.assertIsNotNone(out.get("roi_pct"))
        self.assertNotIn("pnl_blocked_no_filled_exit", _notes_text(out))


if __name__ == "__main__":
    unittest.main()

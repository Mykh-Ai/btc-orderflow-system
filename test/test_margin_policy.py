"""
Tests for margin_policy V2 integration with rolled-back executor.
Real config: SYMBOL=BTCUSDC, ASSET_STEP_SIZE_USDC=0.00000001
Core problem V2 solves: float arithmetic garbage (e.g. 59.856790199999995)
causes Binance to reject borrow requests.
"""
from decimal import Decimal
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from executor_mod.margin_policy import (
    ensure_borrow_if_needed,
    repay_if_any,
    _split_symbol_assets,
    _round_amount_up,
    _to_decimal,
)

# --- Real .env values ---
REAL_ENV = {"ASSET_STEP_SIZE_USDC": "0.00000001"}
STEP = Decimal("0.00000001")


class MockApi:
    def __init__(self, free=None, borrowed=None, env=None):
        self.free = free or {}
        self.borrowed = borrowed or {}
        self._env_data = env if env is not None else dict(REAL_ENV)
        self.borrows = []
        self.repays = []

    def _env(self):
        return self._env_data

    def margin_account(self, is_isolated=False, symbols=None):
        assets = []
        all_keys = set(list(self.free) + list(self.borrowed))
        for a in all_keys:
            assets.append({
                "asset": a,
                "free": self.free.get(a, "0"),
                "borrowed": self.borrowed.get(a, "0"),
            })
        return {"userAssets": assets}

    def margin_borrow(self, asset, amount, is_isolated=False, symbol=None):
        self.borrows.append({"asset": asset, "amount": amount})

    def margin_repay(self, asset, amount, is_isolated=False, symbol=None):
        self.repays.append({"asset": asset, "amount": amount})

    def log_event(self, *args, **kwargs):
        pass


# =====================================================================
# 1. THE REAL BUG: float garbage cleaned by V2
#    V1: 0.00062 * 96543.21 = 59.856790199999995 → Binance rejects
#    V2: Decimal rounds to step → 59.8567902 → Binance accepts
# =====================================================================

def test_float_garbage_cleaned():
    """The exact scenario that caused V1 failures.
    float multiplication produces trailing garbage digits;
    V2 must round to step and produce a clean Decimal."""
    float_garbage = 0.00062 * 96543.21  # platform-dependent trailing digits
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {
        "borrow_asset": "USDC",
        "borrow_amount": float_garbage,
        "trade_key": "t1",
    }
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.00062, plan)
    assert len(api.borrows) == 1
    amt = api.borrows[0]["amount"]
    assert isinstance(amt, Decimal)
    # must have at most 8 decimal places (step = 0.00000001)
    assert amt == amt.quantize(STEP)
    # must not contain float garbage (15+ digits)
    assert len(str(amt).split(".")[-1]) <= 8


def test_float_garbage_partial_free():
    """Float garbage with partial free balance."""
    float_needed = 0.00062 * 96543.21  # 59.856790199999995
    api = MockApi(free={"USDC": "20.5"})
    st = {}
    plan = {
        "borrow_asset": "USDC",
        "borrow_amount": float_needed,
        "trade_key": "t1",
    }
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.00062, plan)
    assert len(api.borrows) == 1
    amt = api.borrows[0]["amount"]
    assert isinstance(amt, Decimal)
    assert amt == amt.quantize(STEP)


def test_clean_decimal_passthrough():
    """When borrow_amount is already clean, no distortion."""
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {
        "borrow_asset": "USDC",
        "borrow_amount": "60.00",
        "trade_key": "t1",
    }
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert api.borrows[0]["amount"] == Decimal("61.20000000")  # 60 + 2% buffer


# =====================================================================
# 2. Step size found via ASSET_STEP_SIZE_USDC (real env key)
# =====================================================================

def test_step_found_via_asset_step_size_key():
    """V2 finds step via ASSET_STEP_SIZE_USDC — 4th priority in _asset_step_size."""
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {
        "borrow_asset": "USDC",
        "borrow_amount": "50.123456789012",
        "trade_key": "t1",
    }
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 1
    amt = api.borrows[0]["amount"]
    assert amt == Decimal("51.12592592")  # 50.123456789012 + 2% buffer, quantized


# =====================================================================
# 3. Missing step size → quote asset blocked (safety net)
# =====================================================================

def test_usdc_blocked_without_any_step_size():
    """Without ANY step size for USDC, borrow is blocked."""
    api = MockApi(free={"USDC": "0"}, env={})
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "100", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 0
    assert st["margin"]["last_borrow_skip_reason"] == "missing_quote_step_size"


def test_api_without_env_method_blocks_usdc():
    """Old api without _env() → no step size → USDC blocked."""
    class BareApi:
        def __init__(self):
            self.borrows = []
        def margin_account(self, is_isolated=False, symbols=None):
            return {"userAssets": [{"asset": "USDC", "free": "0", "borrowed": "0"}]}
        def margin_borrow(self, asset, amount, is_isolated=False, symbol=None):
            self.borrows.append({"asset": asset, "amount": amount})
        def log_event(self, *a, **kw):
            pass
    api = BareApi()
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "100", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 0


# =====================================================================
# 4. Free balance sufficient → no borrow
# =====================================================================

def test_no_borrow_when_free_covers_needed():
    api = MockApi(free={"USDC": "200.00"})
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "150", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 0


def test_no_borrow_free_equals_needed():
    api = MockApi(free={"USDC": "60.00"})
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "60.00", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 0


# =====================================================================
# 5. Idempotency — no double borrow
# =====================================================================

def test_no_double_borrow_same_trade_key():
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "50", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 1


# =====================================================================
# 6. Borrow → Repay roundtrip
# =====================================================================

def test_borrow_then_repay_roundtrip():
    api = MockApi(
        free={"USDC": "0"},
        borrowed={"USDC": "61.20"},  # matches 60 + 2% buffer
    )
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "60", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 1

    repay_if_any(st, api, "BTCUSDC")
    assert len(api.repays) == 1
    assert st["margin"]["active_trade_key"] is None
    assert "t1" in st["margin"]["repaid_trade_keys"]
    assert "t1" not in st["margin"].get("borrowed_by_trade", {})


# =====================================================================
# 7. Multiple sequential trades
# =====================================================================

def test_two_sequential_trades():
    api = MockApi(free={"USDC": "0"})
    st = {}

    plan1 = {"borrow_asset": "USDC", "borrow_amount": "60", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan1)

    api.borrowed = {"USDC": "61.20"}  # matches 60 + 2% buffer
    repay_if_any(st, api, "BTCUSDC")

    plan2 = {"borrow_asset": "USDC", "borrow_amount": "45", "trade_key": "t2"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.0005, plan2)

    assert len(api.borrows) == 2
    assert st["margin"]["active_trade_key"] == "t2"
    assert "t1" in st["margin"]["repaid_trade_keys"]


# =====================================================================
# 8. State tracking
# =====================================================================

def test_state_tracks_borrowed_amount():
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "59.856790199999995", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    m = st["margin"]
    assert m["active_trade_key"] == "t1"
    assert "t1" in m["borrowed_trade_keys"]
    assert "USDC" in m["borrowed_assets"]
    assert "USDC" in m["borrowed_by_trade"]["t1"]
    assert m["borrowed_assets"]["USDC"] == float(Decimal("61.05392600"))  # 59.8567902 + 2% buffer


# =====================================================================
# 9. Symbol parsing
# =====================================================================

def test_split_btcusdc():
    assert _split_symbol_assets("BTCUSDC") == ("BTC", "USDC")


def test_split_other_usdc_pairs():
    assert _split_symbol_assets("ETHUSDC") == ("ETH", "USDC")
    assert _split_symbol_assets("SOLUSDC") == ("SOL", "USDC")


def test_split_edge_cases():
    assert _split_symbol_assets("") == ("", "")
    assert _split_symbol_assets("USDC") == ("", "")


# =====================================================================
# 10. Rounding math with real step size (0.00000001)
# =====================================================================

def test_round_up_8_decimals():
    assert _round_amount_up(Decimal("59.856790199999995"), STEP) == Decimal("59.8567902")
    assert _round_amount_up(Decimal("59.85679020"), STEP) == Decimal("59.8567902")
    assert _round_amount_up(Decimal("59.856790201"), STEP) == Decimal("59.85679021")


def test_round_up_already_clean():
    assert _round_amount_up(Decimal("60.00"), STEP) == Decimal("60.00000000")


def test_round_up_zero():
    assert _round_amount_up(Decimal("0"), STEP) == Decimal("0E-8")


# =====================================================================
# 11. Edge: needed <= 0 or missing asset
# =====================================================================

def test_skip_if_needed_zero():
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {"borrow_asset": "USDC", "borrow_amount": "0", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 0
    assert st["margin"]["last_borrow_skip_reason"] == "needed<=0"


def test_skip_if_no_borrow_asset():
    api = MockApi(free={"USDC": "0"})
    st = {}
    plan = {"borrow_amount": "100", "trade_key": "t1"}
    ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)
    assert len(api.borrows) == 0
    assert st["margin"]["last_borrow_skip_reason"] == "missing_borrow_asset"


# =====================================================================
# Runner
# =====================================================================

if __name__ == "__main__":
    import inspect
    tests = sorted([
        name for name, fn in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
        if name.startswith("test_")
    ])
    passed = failed = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)}")

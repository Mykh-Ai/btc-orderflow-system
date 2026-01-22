"""Test tp1_be_disabled auto-clear after cooldown."""
import unittest
from unittest.mock import patch, MagicMock
from copy import deepcopy
import executor


class TestTP1BECooldown(unittest.TestCase):
    def test_tp1_be_disabled_clears_after_cooldown(self):
        """Test that tp1_be_disabled auto-clears when cooldown expires."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "qty": 0.1,
                "prices": {"entry": 100.0, "sl": 99.0},
                "orders": {"sl": 333, "qty2": 0.05, "qty3": 0.05},
                "tp1_done": True,
                "tp1_be_pending": True,
                "tp1_be_disabled": True,
                "tp1_be_attempts": 5,
                "tp1_be_next_s": 1000.0,  # Cooldown до цього часу
                "tp1_be_old_sl": 333,
                "tp1_be_exit_side": "SELL",
                "tp1_be_stop": 100.0,
                "tp1_be_rem_qty": 0.1,
                "tp1_be_source": "TP1",
            }
        }

        def fake_status(_symbol, oid):
            return {"status": "CANCELED"}

        prev_cooldown = executor.ENV.get("TP1_BE_COOLDOWN_SEC")
        try:
            executor.ENV["TP1_BE_COOLDOWN_SEC"] = 300.0
            
            now = {"t": 999.0}  # До закінчення cooldown
            with patch.object(executor, "_now_s", side_effect=lambda: now["t"]), \
                patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
                patch.object(executor.binance_api, "cancel_order", MagicMock()), \
                patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 444}), \
                patch.object(executor, "save_state", lambda *_: None), \
                patch.object(executor, "send_webhook", lambda *_: None), \
                patch.object(executor, "log_event", lambda *_, **__: None):
                
                # Перша спроба: cooldown ще не закінчився
                executor.manage_v15_position(executor.ENV["SYMBOL"], st)
                self.assertTrue(st["position"].get("tp1_be_disabled"))
                self.assertEqual(st["position"].get("tp1_be_attempts"), 5)
                
                # Час минув, cooldown закінчився
                now["t"] = 1001.0
                executor.manage_v15_position(executor.ENV["SYMBOL"], st)
                
                # tp1_be_disabled має бути очищений
                self.assertIsNone(st["position"].get("tp1_be_disabled"))
                # attempts має бути скинутий до 0 (або очищений при успішному placement)
                attempts_after = st["position"].get("tp1_be_attempts")
                self.assertIn(attempts_after, [0, None])  # 0 якщо cooldown expired, None якщо BE placed
                
                # Наступна спроба має спрацювати
                now["t"] = 1002.0
                executor.manage_v15_position(executor.ENV["SYMBOL"], st)
                self.assertEqual(int(st["position"]["orders"]["sl"]), 444)
        finally:
            if prev_cooldown is not None:
                executor.ENV["TP1_BE_COOLDOWN_SEC"] = prev_cooldown

    def test_tp1_be_cooldown_sec_env_variable(self):
        """Test that TP1_BE_COOLDOWN_SEC controls cooldown period."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "qty": 0.1,
                "prices": {"entry": 100.0, "sl": 99.0},
                "orders": {"sl": 333, "qty2": 0.05, "qty3": 0.05},
                "tp1_done": True,
                "tp1_be_pending": True,
                "tp1_be_old_sl": 333,
                "tp1_be_exit_side": "SELL",
                "tp1_be_stop": 100.0,
                "tp1_be_rem_qty": 0.1,
                "tp1_be_source": "TP1",
                "tp1_be_attempts": 10,  # Більше за max
            }
        }

        def fake_status(_symbol, oid):
            return {"status": "NEW"}

        prev_cooldown = executor.ENV.get("TP1_BE_COOLDOWN_SEC")
        prev_max = executor.ENV.get("TP1_BE_MAX_ATTEMPTS")
        try:
            executor.ENV["TP1_BE_COOLDOWN_SEC"] = 180.0  # 3 хв
            executor.ENV["TP1_BE_MAX_ATTEMPTS"] = 5
            
            now = {"t": 1000.0}
            with patch.object(executor, "_now_s", side_effect=lambda: now["t"]), \
                patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
                patch.object(executor, "save_state", lambda *_: None), \
                patch.object(executor, "send_webhook", lambda *_: None), \
                patch.object(executor, "log_event", lambda *_, **__: None):
                
                executor.manage_v15_position(executor.ENV["SYMBOL"], st)
                
                # Перевіряємо що cooldown встановлено на 180 сек
                self.assertTrue(st["position"].get("tp1_be_disabled"))
                self.assertEqual(st["position"]["tp1_be_next_s"], 1180.0)  # 1000 + 180
        finally:
            if prev_cooldown is not None:
                executor.ENV["TP1_BE_COOLDOWN_SEC"] = prev_cooldown
            if prev_max is not None:
                executor.ENV["TP1_BE_MAX_ATTEMPTS"] = prev_max


if __name__ == "__main__":
    unittest.main()

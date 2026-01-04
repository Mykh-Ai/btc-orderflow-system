import os
import unittest
from unittest.mock import Mock

import executor_mod.margin_guard as mg


class TestMarginGuard(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_spot_noop_does_not_crash(self):
        os.environ["TRADE_MODE"] = "spot"
        log = Mock()
        mg.configure({"TRADE_MODE": "spot"}, log)

        mg.on_startup({})
        mg.on_shutdown({})

        # optional: у spot можна очікувати 0 викликів
        # log.assert_not_called()

    def test_margin_hooks_do_not_crash(self):
        os.environ["TRADE_MODE"] = "margin"
        log = Mock()
        mg.configure({"TRADE_MODE": "spot"}, log)

        mg.on_startup({})
        mg.on_shutdown({})

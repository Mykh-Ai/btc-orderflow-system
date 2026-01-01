import unittest
from unittest.mock import patch

import pandas as pd

import executor
import executor_mod.market_data as market_data


class TestExecutorMarketDataWrappers(unittest.TestCase):
    def test_load_df_sorted_delegates(self):
        sentinel = pd.DataFrame({"x": [1]})
        with patch.object(market_data, "load_df_sorted", return_value=sentinel) as m:
            out = executor.load_df_sorted()
            self.assertIs(out, sentinel)
            m.assert_called_once()

    def test_latest_price_delegates(self):
        df = pd.DataFrame({"price": [1.0, 2.0]})
        with patch.object(market_data, "latest_price", return_value=123.0) as m:
            out = executor.latest_price(df)
            self.assertEqual(out, 123.0)
            m.assert_called_once()

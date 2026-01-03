import os
import tempfile
import unittest
from datetime import datetime
from pandas import Series

import pandas as pd

import executor_mod.market_data as market_data


class TestMarketData(unittest.TestCase):
    def test_load_df_sorted_missing_file_returns_empty_df(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "no_such.csv")
            market_data.configure({"AGG_CSV": path})
            df = market_data.load_df_sorted()
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 0)

    def test_load_df_sorted_parses_and_sorts(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "aggregated.csv")
            # спеціально не по порядку часу
            with open(path, "w", encoding="utf-8") as f:
                f.write("Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n")
                f.write("2026-01-01 10:02:00,1,1,1,1,0,100,101\n")
                f.write("2026-01-01 10:00:00,1,1,1,1,0,90,91\n")
                f.write("2026-01-01 10:01:00,1,1,1,1,0,95,96\n")

            market_data.configure({"AGG_CSV": path})
            df = market_data.load_df_sorted()

            self.assertTrue("Timestamp" in df.columns)
            self.assertTrue("price" in df.columns)
            self.assertEqual(len(df), 3)

            # має бути відсортовано за Timestamp зростанням
            self.assertLessEqual(df.iloc[0]["Timestamp"], df.iloc[1]["Timestamp"])
            self.assertLessEqual(df.iloc[1]["Timestamp"], df.iloc[2]["Timestamp"])

            # price має братися з ClosePrice (або fallback як у твоєму коді)
            self.assertEqual(float(df.iloc[0]["price"]), 91.0)
            self.assertEqual(float(df.iloc[-1]["price"]), 101.0)

            # latest_price
            lp = market_data.latest_price(df)
            self.assertEqual(float(lp), 101.0)

    def test_locate_index_by_ts_exact_minute(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "aggregated.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n")
                f.write("2026-01-01 10:00:00,1,1,1,1,0,90,91\n")
                f.write("2026-01-01 10:01:00,1,1,1,1,0,95,96\n")
                f.write("2026-01-01 10:02:00,1,1,1,1,0,100,101\n")

            market_data.configure({"AGG_CSV": path})
            df = market_data.load_df_sorted()

            idx = market_data.locate_index_by_ts(df, datetime(2026, 1, 1, 10, 1, 0))
            self.assertEqual(idx, 1)

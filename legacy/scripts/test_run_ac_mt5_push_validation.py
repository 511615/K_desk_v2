import unittest

from scripts import run_ac_mt5_push_validation as runner


class CorrectedPositionReconstructionTests(unittest.TestCase):
    def test_multiple_open_and_close_deals_are_combined_once(self):
        deals = [
            {
                "Deal": 1, "PositionID": 10, "Action": 0, "Entry": 0,
                "Time": "2026-07-10 10:00:00", "TimeMsc": "2026-07-10 10:00:00.100000",
                "Symbol": "XAUUSD", "Price": 3300, "Volume": 10000,
                "Commission": -1, "Storage": 0, "Fee": -0.1,
            },
            {
                "Deal": 2, "PositionID": 10, "Action": 0, "Entry": 0,
                "Time": "2026-07-10 10:00:01", "TimeMsc": "2026-07-10 10:00:01.100000",
                "Symbol": "XAUUSD", "Price": 3302, "Volume": 10000,
                "Commission": -2, "Storage": 0, "Fee": -0.2,
            },
            {
                "Deal": 3, "PositionID": 10, "Action": 1, "Entry": 1,
                "Time": "2026-07-10 10:01:00", "TimeMsc": "2026-07-10 10:01:00.100000",
                "Symbol": "XAUUSD", "Price": 3305, "Volume": 10000, "VolumeClosed": 10000,
                "Profit": 10, "Commission": -3, "Storage": -0.5, "Fee": -0.3,
            },
            {
                "Deal": 4, "PositionID": 10, "Action": 1, "Entry": 2,
                "Time": "2026-07-10 10:02:00", "TimeMsc": "2026-07-10 10:02:00.100000",
                "Symbol": "XAUUSD", "Price": 3307, "Volume": 10000, "VolumeClosed": 10000,
                "Profit": 20, "Commission": -4, "Storage": -0.5, "Fee": -0.4,
            },
        ]
        source = {"name": "AC GB MT5", "server": "AC GB MT5"}
        rows = runner.corrected_mt5_positions(deals, source, "900001", runner.app.account_money_meta("USD"))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["ticket"], "10")
        self.assertEqual(row["open_deal_count"], 2)
        self.assertEqual(row["close_deal_count"], 2)
        self.assertEqual(row["profit"], 30)
        self.assertEqual(row["commission"], -10)
        self.assertAlmostEqual(row["fee"], -1)
        self.assertEqual(row["swap"], -1)
        self.assertEqual(row["open_price"], 3301)
        self.assertEqual(row["close_price"], 3306)
        self.assertEqual(row["close_time"], "2026-07-10 10:02:00")


if __name__ == "__main__":
    unittest.main()

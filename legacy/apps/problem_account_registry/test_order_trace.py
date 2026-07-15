import unittest
from datetime import datetime

from order_trace import OrderTraceRequest, build_trace_result


class OrderTraceTests(unittest.TestCase):
    def setUp(self):
        self.request = OrderTraceRequest(
            login=616901,
            ticket=349892678,
            event_time=datetime(2026, 7, 15, 3, 8, 9),
            symbol="XAUUSD.CS",
            lots=0.06,
            price=4037.22,
            dealer_id=99,
            order_kind="Pending Order",
            command="Open Order",
        )
        self.final_deal = {
            "Deal": 348326514,
            "Login": 616901,
            "Order": 349892691,
            "PositionID": 349892691,
            "Dealer": 99,
            "Action": 0,
            "Entry": 0,
            "Reason": 1,
            "TimeMsc": datetime(2026, 7, 15, 3, 8, 11, 693000),
            "Symbol": "XAUUSD.CS",
            "Price": 4037.12,
            "Volume": 600,
            "VolumeExt": 6000000,
            "MarketBid": 4036.74,
            "MarketAsk": 4037.12,
        }
        self.symbol = {
            "Symbol": "XAUUSD.CS",
            "StopsLevel": 20,
            "Point": 0.01,
        }

    def test_correlates_replacement_and_infers_invalid_stops(self):
        result = build_trace_result(
            self.request,
            window_rows=[self.final_deal],
            symbol=self.symbol,
        )
        self.assertEqual(result["status"], "resubmitted_or_replaced")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["linkedFinal"]["order"], 349892691)
        self.assertEqual(result["linkedFinal"]["deltaSeconds"], 2.693)
        self.assertEqual(result["pendingPriceConstraint"]["inferredPendingType"], "buy_stop")
        self.assertEqual(result["pendingPriceConstraint"]["actualDistance"], 0.1)
        self.assertEqual(result["pendingPriceConstraint"]["minimumDistance"], 0.2)
        self.assertTrue(result["pendingPriceConstraint"]["violated"])
        self.assertEqual(result["pendingPriceConstraint"]["likelyRetcode"], 10016)

    def test_exact_deal_is_executed_exact(self):
        exact = dict(self.final_deal, Deal=349892678)
        result = build_trace_result(self.request, exact_rows=[exact], window_rows=[exact])
        self.assertEqual(result["status"], "executed_exact")
        self.assertEqual(result["reasonSource"], "mt5_deals")

    def test_logged_rejection_overrides_inference(self):
        result = build_trace_result(
            self.request,
            window_rows=[self.final_deal],
            symbol=self.symbol,
            rejection_logs=[
                {
                    "ticket": 349892678,
                    "login": 616901,
                    "time": "2026-07-15 03:08:09",
                    "retcode": 10016,
                    "message": "Invalid stops",
                }
            ],
        )
        self.assertEqual(result["status"], "rejected_logged")
        self.assertEqual(result["reasonSource"], "rejection_log")
        self.assertEqual(result["loggedRejection"]["retcode"], 10016)

    def test_unrelated_window_deal_is_not_linked(self):
        unrelated = dict(self.final_deal, Symbol="EURUSD", Volume=100, VolumeExt=1000000)
        result = build_trace_result(self.request, window_rows=[unrelated], symbol=self.symbol)
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["linkedFinal"])


if __name__ == "__main__":
    unittest.main()

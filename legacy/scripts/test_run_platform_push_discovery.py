import sys
import unittest
from unittest.mock import patch

from scripts import run_platform_push_discovery as runner


class PushDiscoveryTests(unittest.TestCase):
    def test_excluded_logins_only_uses_confirmed_actions(self):
        records = [
            {"账号": "100", "建议动作": "T"},
            {"账号": "101", "建议动作": "TA"},
            {"账号": "102", "建议动作": "A"},
            {"账号": "103", "建议动作": "A/TA"},
            {"账号": "104", "建议动作": "P->A/T"},
            {"账号": "105", "建议动作": "P"},
        ]
        self.assertEqual(runner.excluded_logins(records), {"100", "101", "102", "103"})

    def test_initial_score_below_40_routes_strong_structure_to_deep_check(self):
        rows = [{"ticket": str(index)} for index in range(20)]
        context = {
            "rows": rows,
            "filter": {},
            "behavior": {
                "concentratedCoreVolumeRatio": 92,
                "coreShortHoldVolumeRatio": 88,
                "quietGapRatio": 45,
                "eaVolumeRatio": 0,
                "copyVolumeRatio": 0,
            },
        }
        with patch.object(runner.app, "toxic_build_push_context", return_value=context), \
             patch.object(runner.app, "calculate_toxic_results", return_value=[{
                 "score": 30, "level": "无明显风险", "confidence": 50,
                 "triggeredRules": [],
             }]):
            result = runner.screen_candidate(
                {"login": "900001", "source": "Live", "server": "Live", "platform": "MT5"},
                rows,
                200,
            )
        self.assertTrue(result["deepEligible"])
        self.assertIn("集中度、短持仓和动态停手同时明显", result["routeReasons"])

    def test_default_order_limit_is_200_and_remains_configurable(self):
        with patch.object(sys, "argv", ["runner"]):
            self.assertEqual(runner.parse_args().max_orders, 200)
        with patch.object(sys, "argv", ["runner", "--max-orders", "350"]):
            self.assertEqual(runner.parse_args().max_orders, 350)


if __name__ == "__main__":
    unittest.main()

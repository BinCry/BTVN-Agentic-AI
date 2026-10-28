import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cache_aware_router import (Config, MODEL_A, MODEL_B, cache_status_at, compact_at,
    expected_route, keep_alive_cost, request_cost, route_at, switch_b_at, warm_a_at)


class RouterTests(unittest.TestCase):
    def test_slide_baselines(self):
        self.assertEqual(request_cost(MODEL_A, cached_tokens=50_000, uncached_input_tokens=2_000, output_tokens=1_000), D("0.055"))
        self.assertEqual(request_cost(MODEL_B, uncached_input_tokens=52_000, output_tokens=1_000), D("0.057"))

    def test_expired_cache_is_not_charged_as_cached(self):
        config = Config(keep_alive_interval_minutes=D("6"))
        warm, _ = cache_status_at(D("7"), config)
        self.assertFalse(warm)
        self.assertEqual(warm_a_at(D("7"), config).request_cost, D("0.28"))

    def test_keep_alive_is_added(self):
        result = warm_a_at(D("7"), Config())
        self.assertEqual(keep_alive_cost(Config()), D("0.025"))
        self.assertEqual(result.maintenance_or_compaction_cost, D("0.025"))
        self.assertEqual(result.total_cost, D("0.080"))

    def test_switch_cannot_reuse_a_cache(self):
        self.assertEqual(switch_b_at(Config()).total_cost, D("0.057"))

    def test_compaction_includes_both_requests(self):
        result = compact_at(Config())
        self.assertEqual(result.model, "Model B")
        self.assertEqual(result.maintenance_or_compaction_cost, D("0.055"))
        self.assertEqual(result.request_cost, D("0.019"))
        self.assertEqual(result.total_cost, D("0.074"))

    def test_probability_zero_has_no_request_cost(self):
        _, costs = expected_route(D("0"), D("10"), Config())
        self.assertTrue(all(x.total_cost == 0 for x in costs))

    def test_probability_one_has_expected_request_cost(self):
        _, costs = expected_route(D("1"), D("10"), Config())
        self.assertEqual(next(x for x in costs if x.strategy == "Switch B").total_cost, D("0.057"))

    def test_retry_changes_expected_cost(self):
        config = Config(switch_retry_probability=D("0.5"))
        self.assertEqual(switch_b_at(config).total_cost, D("0.0855"))

    def test_router_selects_lowest_valid_cost(self):
        winner, costs = route_at(D("3"), Config())
        self.assertEqual(winner.strategy, "Warm A")
        self.assertEqual(winner.total_cost, min(x.total_cost for x in costs))
        winner, costs = route_at(D("7"), Config())
        self.assertEqual(winner.strategy, "Switch B")
        self.assertEqual(winner.total_cost, min(x.total_cost for x in costs))


if __name__ == "__main__":
    unittest.main()

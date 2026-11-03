"""
Unit tests for algorithm comparison module.
"""

import logging
import unittest

from comparison import compare_algorithms, format_comparison_table, run_scenario


class TestComparisonModule(unittest.TestCase):
    def setUp(self) -> None:
        self.null_logger = logging.getLogger("TestComp")
        self.null_logger.addHandler(logging.NullHandler())

    def test_run_scenario_round_robin(self) -> None:
        durations = [0.05, 0.05, 0.05]
        res = run_scenario(
            algorithm_name="round_robin",
            worker_count=3,
            durations=durations,
            inter_arrival_delay=0.01,
            logger=self.null_logger,
        )
        self.assertEqual(res["tasks_submitted"], 3)
        self.assertEqual(res["tasks_completed"], 3)
        self.assertEqual(res["tasks_failed"], 0)
        self.assertGreater(res["throughput"], 0.0)
        self.assertEqual(res["distribution"]["Worker-1"], 1)
        self.assertEqual(res["distribution"]["Worker-2"], 1)
        self.assertEqual(res["distribution"]["Worker-3"], 1)

    def test_run_scenario_least_connections(self) -> None:
        durations = [0.05, 0.05, 0.05]
        res = run_scenario(
            algorithm_name="least_connections",
            worker_count=3,
            durations=durations,
            inter_arrival_delay=0.01,
            logger=self.null_logger,
        )
        self.assertEqual(res["tasks_submitted"], 3)
        self.assertEqual(res["tasks_completed"], 3)
        self.assertEqual(res["tasks_failed"], 0)

    def test_compare_algorithms_and_format(self) -> None:
        durations = [0.1, 0.05, 0.05]
        rr, lc = compare_algorithms(
            worker_count=3,
            durations=durations,
            inter_arrival_delay=0.01,
            logger=self.null_logger,
        )
        self.assertEqual(rr["tasks_completed"], 3)
        self.assertEqual(lc["tasks_completed"], 3)

        table = format_comparison_table(rr, lc)
        self.assertIn("ALGORITHM COMPARISON REPORT", table)
        self.assertIn("ROUND ROBIN", table)
        self.assertIn("LEAST CONNECTIONS", table)
        self.assertIn("Throughput", table)


if __name__ == "__main__":
    unittest.main()


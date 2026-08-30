"""Executable context-budget regression checks for plugin entrypoints."""

import unittest
from pathlib import Path

from scripts.context_budget import (
    compare_to_baseline,
    measure_context,
    validate_context_budget,
)


ROOT = Path(__file__).parents[1]


class ContextBudgetTests(unittest.TestCase):
    def test_measurement_matches_hand_checked_common_reference_baseline(self):
        report = measure_context(ROOT)

        self.assertEqual("utf8-bytes-ceil-div-4-v1", report["estimator"])
        self.assertEqual(11, len(report["skills"]))
        self.assertEqual(22_021, report["common_reference_bytes"])
        self.assertEqual(5_506, report["common_reference_estimated_tokens"])

    def test_model_entrypoints_stay_within_compact_budget(self):
        report = measure_context(ROOT)

        self.assertEqual([], validate_context_budget(report))

    def test_checked_in_baseline_reports_reproducible_reduction(self):
        report = measure_context(ROOT)
        comparison = compare_to_baseline(
            report,
            ROOT / "references/policies/context-budget-baseline.json",
        )

        self.assertEqual("13b9402", comparison["source_commit"])
        self.assertEqual(8_057, comparison["before"]["mean_estimated_tokens"])
        self.assertLessEqual(comparison["after"]["max_estimated_tokens"], 3_000)
        self.assertGreaterEqual(comparison["reduction_percent"], 80.0)


if __name__ == "__main__":
    unittest.main()

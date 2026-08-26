import unittest

from scripts.toolkit.coverage import evaluate_coverage


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.meaningful_shot = {
            "artifact_id": "scene-contract-S1-v1",
            "shot_id": "S1",
            "duration_ms": 6_000,
            "semantic_beats": ["premise", "result"],
            "visual_states": [
                {
                    "kind": "establish",
                    "beat": "premise",
                    "start_ms": 0,
                    "end_ms": 2_500,
                },
                {
                    "kind": "result",
                    "beat": "result",
                    "start_ms": 2_500,
                    "end_ms": 6_000,
                },
            ],
            "important_items": [],
            "readable_holds": [],
        }

    def test_decorative_motion_does_not_cover_semantic_beat(self):
        """Catches floating motion being counted as semantic explanation."""
        result = evaluate_coverage(
            [
                {
                    "shot_id": "S1",
                    "duration_ms": 6_000,
                    "semantic_beats": ["premise", "result"],
                    "visual_states": [
                        {"kind": "floating", "start_ms": 0, "end_ms": 6_000}
                    ],
                }
            ]
        )

        self.assertIn("decorative-only", {item["code"] for item in result["issues"]})

    def test_decorative_kind_cannot_override_its_canonical_role(self):
        """Catches a floating state bypassing coverage by declaring itself meaningful."""
        shot = {
            "shot_id": "S1",
            "duration_ms": 6_000,
            "semantic_beats": ["premise"],
            "visual_states": [
                {
                    "kind": "floating",
                    "coverage_role": "meaningful",
                    "beat": "premise",
                    "start_ms": 0,
                    "end_ms": 6_000,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "canonical coverage_role"):
            evaluate_coverage([shot])

    def test_known_meaningful_kind_rejects_even_matching_role_override(self):
        """Catches canonical kinds acquiring two conflicting sources of truth."""
        shot = {
            **self.meaningful_shot,
            "visual_states": [
                {
                    "kind": "evidence",
                    "coverage_role": "meaningful",
                    "beats": ["premise", "result"],
                    "start_ms": 0,
                    "end_ms": 6_000,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "canonical coverage_role"):
            evaluate_coverage([shot])

    def test_unknown_kind_may_declare_an_explicit_role(self):
        """Catches extension kinds losing their contract-declared semantic role."""
        shot = {
            **self.meaningful_shot,
            "visual_states": [
                {
                    "kind": "custom-proof-animation",
                    "coverage_role": "meaningful",
                    "beats": ["premise", "result"],
                    "start_ms": 0,
                    "end_ms": 6_000,
                }
            ],
        }

        self.assertEqual([], evaluate_coverage([shot])["issues"])

    def test_meaningful_states_cover_matching_beats(self):
        """Catches matching semantic states being rejected as uncovered."""
        result = evaluate_coverage([self.meaningful_shot])

        self.assertEqual(1, result["schema_version"])
        self.assertNotIn("shots", result)
        self.assertEqual([], result["issues"])
        self.assertEqual([], result["uncovered_intervals"])

    def test_zero_duration_shot_is_rejected(self):
        """Catches an empty timing contract passing as production-ready coverage."""
        shot = {
            "shot_id": "S0",
            "duration_ms": 0,
            "semantic_beats": [],
            "visual_states": [],
        }

        with self.assertRaisesRegex(ValueError, "duration_ms"):
            evaluate_coverage([shot])

    def test_semantic_beat_labels_may_use_narration_language(self):
        """Catches Chinese semantic labels being mistaken for filesystem IDs."""
        shot = {
            **self.meaningful_shot,
            "semantic_beats": ["前提", "结果"],
            "visual_states": [
                {
                    "kind": "establish",
                    "beat": "前提",
                    "start_ms": 0,
                    "end_ms": 2_500,
                },
                {
                    "kind": "result",
                    "beat": "结果",
                    "start_ms": 2_500,
                    "end_ms": 6_000,
                },
            ],
        }

        self.assertEqual([], evaluate_coverage([shot])["issues"])

    def test_meaningful_state_must_name_every_covered_beat(self):
        """Catches full-duration visuals silently claiming unrelated beats."""
        shot = {
            **self.meaningful_shot,
            "visual_states": [
                {
                    "kind": "evidence",
                    "beat": "premise",
                    "start_ms": 0,
                    "end_ms": 6_000,
                }
            ],
        }

        result = evaluate_coverage([shot])

        uncovered = [item for item in result["issues"] if item["code"] == "uncovered-beat"]
        self.assertEqual(["result"], [item["beat_id"] for item in uncovered])
        self.assertEqual("scene-contract-S1-v1", uncovered[0]["artifact_id"])

    def test_uncovered_intervals_are_returned_as_exact_issue_payloads(self):
        """Catches a validator that reports a gap without its repairable interval."""
        shot = {
            **self.meaningful_shot,
            "visual_states": [
                {
                    "kind": "establish",
                    "beat": "premise",
                    "start_ms": 1_000,
                    "end_ms": 2_000,
                },
                {
                    "kind": "result",
                    "beat": "result",
                    "start_ms": 3_000,
                    "end_ms": 5_000,
                },
            ],
        }

        result = evaluate_coverage([shot])

        self.assertEqual(
            [(0, 1_000), (2_000, 3_000), (5_000, 6_000)],
            [
                (item["start_ms"], item["end_ms"])
                for item in result["uncovered_intervals"]
            ],
        )
        self.assertTrue(
            all(item["code"] == "uncovered-interval" for item in result["uncovered_intervals"])
        )

    def test_readable_hold_uses_item_declared_minimum(self):
        """Catches reintroducing one global readable-hold duration."""
        shot = {
            **self.meaningful_shot,
            "important_items": [{"item_id": "formula", "min_hold_ms": 1_800}],
            "readable_holds": [
                {"item_id": "formula", "start_ms": 3_000, "end_ms": 4_200}
            ],
        }

        result = evaluate_coverage([shot])

        issue = next(item for item in result["issues"] if item["code"] == "short-readable-hold")
        self.assertEqual(1_800, issue["required_ms"])
        self.assertEqual(1_200, issue["actual_ms"])

    def test_important_item_without_hold_is_reported(self):
        """Catches important evidence passing with no declared readable hold."""
        shot = {**self.meaningful_shot, "important_items": ["72%"]}

        result = evaluate_coverage([shot])

        self.assertIn("missing-readable-hold", {item["code"] for item in result["issues"]})

    def test_invalid_timing_is_rejected_at_the_input_boundary(self):
        """Catches malformed timing reaching interval arithmetic or persisted issues."""
        shot = {
            **self.meaningful_shot,
            "visual_states": [
                {
                    "kind": "result",
                    "beat": "result",
                    "start_ms": 4_000,
                    "end_ms": 7_000,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "visual state interval"):
            evaluate_coverage([shot])


if __name__ == "__main__":
    unittest.main()

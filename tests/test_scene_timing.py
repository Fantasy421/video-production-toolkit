"""Contract tests for timing storyboards to approved semantic beat anchors."""

import copy
import unittest

from scripts.toolkit.scene_timing import (
    build_scene_timing_contracts,
    validate_scene_timing_contracts,
)


class SceneTimingContractTests(unittest.TestCase):
    """Each test names a timing regression that must block storyboard output."""

    @staticmethod
    def timed_beats(*, timing_kind="real"):
        return {
            "artifact_id": "timed-semantic-beats-v1",
            "type": "timed-semantic-beats",
            "version": 1,
            "status": "approved",
            "parents": ["semantic-beats-v1", "voice-timing-v1"],
            "path": "artifacts/timed-semantic-beats-v1.json",
            "semantic_beats_id": "semantic-beats-v1",
            "voice_timing_id": "voice-timing-v1",
            "timing_kind": timing_kind,
            "beats": [
                {
                    "beat_id": "B01",
                    "speech_start_ms": 0,
                    "speech_end_ms": 2_500,
                    "keyword_start_ms": 1_000,
                    "keyword_end_ms": 1_200,
                    "emphasis_ms": 1_100,
                    "visual_window_ms": [880, 1_400],
                    "approved_anchor_commitment": "sha256:" + "0" * 64,
                },
                {
                    "beat_id": "B02",
                    "speech_start_ms": 2_500,
                    "speech_end_ms": 5_000,
                    "keyword_start_ms": 3_000,
                    "keyword_end_ms": 3_200,
                    "emphasis_ms": 3_100,
                    "visual_window_ms": [2_880, 3_400],
                    "approved_anchor_commitment": "sha256:" + "1" * 64,
                },
            ],
        }

    @staticmethod
    def assignments():
        return [
            {
                "scene_id": "S01",
                "scene_window_ms": [0, 5_000],
                "beat_ids": ["B01", "B02"],
                "primary_carrier": "motion-graphics",
                "support_layer": "caption-emphasis",
                "visual_window_ms": [880, 3_400],
            }
        ]

    def test_builds_a_structural_contract_for_consecutive_timed_beats(self):
        """Catches a builder dropping the approved timed-beat lineage or windows."""
        record = build_scene_timing_contracts(self.timed_beats(), self.assignments())

        self.assertEqual("timed-semantic-beats-v1", record["timed_semantic_beats_id"])
        self.assertEqual(self.assignments(), record["scenes"])
        self.assertEqual(record, validate_scene_timing_contracts(record, self.timed_beats()))

    def test_rejects_a_beat_assigned_to_two_scenes(self):
        """Catches two visual arrangements claiming the same spoken emphasis."""
        assignments = self.assignments() + [
            {
                "scene_id": "S02",
                "scene_window_ms": [2_500, 5_000],
                "beat_ids": ["B02"],
                "primary_carrier": "a-roll",
                "support_layer": None,
                "visual_window_ms": [2_880, 3_400],
            }
        ]

        with self.assertRaisesRegex(ValueError, "exactly once"):
            build_scene_timing_contracts(self.timed_beats(), assignments)

    def test_rejects_a_scene_outside_its_spoken_timed_boundaries(self):
        """Catches a scene extending past the real timing of its assigned speech."""
        assignments = self.assignments()
        assignments[0]["scene_window_ms"] = [0, 5_100]
        assignments[0]["visual_window_ms"] = [880, 3_400]

        with self.assertRaisesRegex(ValueError, "spoken boundaries"):
            build_scene_timing_contracts(self.timed_beats(), assignments)

    def test_rejects_multiple_primary_carriers(self):
        """Catches a storyboard evading the one-primary-carrier decision gate."""
        assignments = self.assignments()
        assignments[0]["primary_carrier"] = ["scene", "motion-graphics"]

        with self.assertRaisesRegex(ValueError, "primary carrier"):
            build_scene_timing_contracts(self.timed_beats(), assignments)

    def test_rejects_multiple_support_layers(self):
        """Catches dense layering hidden in a single assignment field."""
        assignments = self.assignments()
        assignments[0]["support_layer"] = ["caption-emphasis", "callout"]

        with self.assertRaisesRegex(ValueError, "support layer"):
            build_scene_timing_contracts(self.timed_beats(), assignments)

    def test_rejects_an_unregistered_support_layer_at_scene_admission(self):
        """Catches scene authoring accepting a layer compact validation cannot consume."""
        assignments = self.assignments()
        assignments[0]["support_layer"] = "unregistered-overlay"

        with self.assertRaisesRegex(ValueError, "support layer"):
            build_scene_timing_contracts(self.timed_beats(), assignments)

    def test_rejects_a_keyword_window_that_crosses_its_scene_boundary(self):
        """Catches approved emphasis entry or exit being cut by the scene window."""
        assignments = self.assignments()
        assignments[0]["scene_window_ms"] = [0, 3_100]
        assignments[0]["visual_window_ms"] = [880, 3_100]

        with self.assertRaisesRegex(ValueError, "beat visual window"):
            build_scene_timing_contracts(self.timed_beats(), assignments)

    def test_rejects_adjacent_keywords_that_are_split_or_omitted(self):
        """Catches an adjacent emphasis requiring a merge being split or dropped."""
        timed = self.timed_beats()
        timed["beats"][0]["visual_window_ms"] = [880, 2_700]
        timed["beats"][1]["visual_window_ms"] = [2_380, 3_400]
        split = [
            {
                "scene_id": "S01",
                "scene_window_ms": [0, 2_500],
                "beat_ids": ["B01"],
                "primary_carrier": "scene",
                "support_layer": None,
                "visual_window_ms": [880, 2_500],
            },
            {
                "scene_id": "S02",
                "scene_window_ms": [2_500, 5_000],
                "beat_ids": ["B02"],
                "primary_carrier": "motion-graphics",
                "support_layer": None,
                "visual_window_ms": [2_500, 3_400],
            },
        ]

        with self.assertRaisesRegex(ValueError, "beat visual window"):
            build_scene_timing_contracts(timed, split)
        omitted = [
            {
                "scene_id": "S01",
                "scene_window_ms": [0, 2_500],
                "beat_ids": ["B01"],
                "primary_carrier": "scene",
                "support_layer": None,
                "visual_window_ms": [880, 1_400],
            }
        ]
        with self.assertRaisesRegex(ValueError, "exactly once"):
            build_scene_timing_contracts(self.timed_beats(), omitted)

    def test_rejects_an_estimated_time_storyboard_attempt(self):
        """Catches a plausible visual plan that is not tied to real voice timing."""
        with self.assertRaisesRegex(ValueError, "real"):
            build_scene_timing_contracts(
                self.timed_beats(timing_kind="estimated"), self.assignments()
            )

    def test_rejects_malformed_approved_real_timed_beats(self):
        """Catches reversed, out-of-speech, and keyword-missing visual ranges."""
        cases = (
            {"keyword_start_ms": 1_300, "keyword_end_ms": 1_100},
            {"keyword_start_ms": 2_600, "keyword_end_ms": 2_700},
            {"visual_window_ms": [0, 900]},
        )
        for mutation in cases:
            with self.subTest(mutation=mutation):
                timed = copy.deepcopy(self.timed_beats())
                timed["beats"][0].update(mutation)
                with self.assertRaises(ValueError):
                    build_scene_timing_contracts(timed, self.assignments())

    def test_validation_rejects_tampered_lineage(self):
        """Catches a saved timing contract being rebound to another beat artifact."""
        record = build_scene_timing_contracts(self.timed_beats(), self.assignments())
        tampered = copy.deepcopy(record)
        tampered["timed_semantic_beats_id"] = "timed-semantic-beats-v2"

        with self.assertRaisesRegex(ValueError, "lineage"):
            validate_scene_timing_contracts(tampered, self.timed_beats())


if __name__ == "__main__":
    unittest.main()

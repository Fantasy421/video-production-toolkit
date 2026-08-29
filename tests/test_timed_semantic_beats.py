"""Behavioral tests for binding frozen beats to real voice-timing metadata."""

import json
import unittest

from scripts.toolkit.timed_semantic_beats import (
    bind_semantic_beats,
    validate_timed_semantic_beats,
)


class TimedSemanticBeatTests(unittest.TestCase):
    @staticmethod
    def semantic():
        return {
            "narration_id": "narration-v3",
            "beats": [
                {
                    "beat_id": "B07",
                    "text_ref": "narration-v3:S03:L2",
                    "keyword": "context isolation",
                    "intent": "core-concept-emphasis",
                    "priority": "primary",
                    "preferred_carrier": "motion-graphics",
                    "approval_provenance": "user:keyword-review-v3",
                }
            ],
        }

    @staticmethod
    def real_timing(*, status="approved", timing_kind="real"):
        return {
            "artifact_id": "voice-timing-v4",
            "type": "voice-timing",
            "version": 4,
            "status": status,
            "parents": ["voiceover-v4"],
            "path": "metadata/voice-timing-v4.json",
            "voiceover_id": "voiceover-v4",
            "timing_kind": timing_kind,
            "duration_ms": 2_400,
            "segments": [
                {"start_ms": 0, "end_ms": 800, "text": "开场说明"},
                {"start_ms": 800, "end_ms": 2_100, "text": "解释上下文隔离"},
            ],
        }

    @staticmethod
    def keyword_anchors():
        return [
            {
                "beat_id": "B07",
                "keyword": "context isolation",
                "start_ms": 1_200,
                "end_ms": 1_500,
            }
        ]

    def test_binding_uses_real_sentence_timing_and_only_approved_keywords(self):
        """Catches broad word timing leaking beyond the frozen approval set."""
        timed = bind_semantic_beats(
            self.semantic(), self.real_timing(), self.keyword_anchors()
        )

        self.assertEqual("real", timed["timing_kind"])
        self.assertEqual("voice-timing-v4", timed["voice_timing_id"])
        self.assertEqual(["B07"], [beat["beat_id"] for beat in timed["beats"]])
        self.assertEqual(800, timed["beats"][0]["speech_start_ms"])
        self.assertEqual(2_100, timed["beats"][0]["speech_end_ms"])
        self.assertEqual(1_200, timed["beats"][0]["keyword_start_ms"])
        self.assertEqual(1_500, timed["beats"][0]["keyword_end_ms"])
        self.assertGreaterEqual(250, 1_200 - timed["beats"][0]["visual_window_ms"][0])
        self.assertGreaterEqual(500, timed["beats"][0]["visual_window_ms"][1] - 1_500)
        self.assertLessEqual(120, 1_200 - timed["beats"][0]["visual_window_ms"][0])
        self.assertLessEqual(200, timed["beats"][0]["visual_window_ms"][1] - 1_500)
        self.assertNotIn("unapproved-word", json.dumps(timed))
        self.assertNotIn("解释上下文隔离", json.dumps(timed))
        self.assertEqual(
            timed,
            validate_timed_semantic_beats(timed, self.semantic(), self.real_timing()),
        )

    def test_binding_rejects_estimated_or_stale_timing(self):
        """Catches a plausible estimate or invalidated timing becoming production timing."""
        for timing in (
            self.real_timing(timing_kind="estimated"),
            self.real_timing(status="stale"),
        ):
            with self.subTest(timing=timing["timing_kind"], status=timing["status"]):
                with self.assertRaisesRegex(ValueError, "real.*current"):
                    bind_semantic_beats(self.semantic(), timing, self.keyword_anchors())

    def test_binding_requires_one_matching_anchor_per_frozen_beat(self):
        """Catches skipped approved emphasis or an unapproved word timestamp."""
        with self.assertRaisesRegex(ValueError, "anchor"):
            bind_semantic_beats(self.semantic(), self.real_timing(), [])

        extra = self.keyword_anchors() + [
            {
                "beat_id": "B99",
                "keyword": "unapproved-word",
                "start_ms": 1_600,
                "end_ms": 1_700,
            }
        ]
        with self.assertRaisesRegex(ValueError, "approved"):
            bind_semantic_beats(self.semantic(), self.real_timing(), extra)

        widened = self.keyword_anchors()
        widened[0]["word_start_ms"] = 1_150
        with self.assertRaisesRegex(ValueError, "closed"):
            bind_semantic_beats(self.semantic(), self.real_timing(), widened)

    def test_binding_rejects_anchor_outside_its_spoken_segment(self):
        """Catches a keyword interval spanning sentence timing boundaries."""
        anchors = self.keyword_anchors()
        anchors[0].update(start_ms=750, end_ms=850)

        with self.assertRaisesRegex(ValueError, "spoken segment"):
            bind_semantic_beats(self.semantic(), self.real_timing(), anchors)

    def test_validation_rejects_mismatched_lineage_and_extra_timestamps(self):
        """Catches a timed record being reattached or expanded after binding."""
        timed = bind_semantic_beats(
            self.semantic(), self.real_timing(), self.keyword_anchors()
        )

        with self.assertRaisesRegex(ValueError, "voice timing"):
            validate_timed_semantic_beats(
                {**timed, "voice_timing_id": "voice-timing-v5"},
                self.semantic(),
                self.real_timing(),
            )
        with self.assertRaisesRegex(ValueError, "closed"):
            validate_timed_semantic_beats(
                {**timed, "word_timestamps": []}, self.semantic(), self.real_timing()
            )


if __name__ == "__main__":
    unittest.main()

"""Behavioral tests for the approved, untimed semantic-beat boundary."""

import unittest

from scripts.toolkit.semantic_beats import (
    freeze_semantic_beats,
    project_legacy_timed_beats,
    validate_semantic_beats,
)


class SemanticBeatTests(unittest.TestCase):
    @staticmethod
    def candidates():
        return [
            {
                "beat_id": "B01",
                "text_ref": "narration-v3:S01:L1",
                "keyword": "timing",
                "intent": "core-concept-emphasis",
                "priority": "primary",
                "preferred_carrier": "motion-graphics",
            }
        ]

    @staticmethod
    def approval():
        return {
            "decision": "approved",
            "provenance": "user:keyword-review-v3",
            "keywords": ["timing"],
        }

    def test_freeze_requires_user_approved_keywords_without_timing(self):
        """Catches Stage A publishing anchors before the user approves them."""
        with self.assertRaisesRegex(ValueError, "approval"):
            freeze_semantic_beats("narration-v3", self.candidates(), None)

        frozen = freeze_semantic_beats(
            "narration-v3", self.candidates(), self.approval()
        )

        self.assertEqual("narration-v3", frozen["narration_id"])
        self.assertEqual(
            {
                "beat_id",
                "text_ref",
                "keyword",
                "intent",
                "priority",
                "preferred_carrier",
                "approval_provenance",
            },
            set(frozen["beats"][0]),
        )
        self.assertEqual("user:keyword-review-v3", frozen["beats"][0]["approval_provenance"])
        self.assertNotIn("voice_timing_id", frozen)
        self.assertNotIn("keyword_start_ms", frozen["beats"][0])

    def test_duplicate_keywords_need_distinct_beat_ids(self):
        """Catches repeated keywords collapsing distinct approved teaching beats."""
        candidates = self.candidates() + [
            {
                **self.candidates()[0],
                "beat_id": "B02",
                "text_ref": "narration-v3:S02:L1",
            }
        ]
        frozen = freeze_semantic_beats("narration-v3", candidates, self.approval())
        self.assertEqual(["B01", "B02"], [beat["beat_id"] for beat in frozen["beats"]])

        candidates[1]["beat_id"] = "B01"
        with self.assertRaisesRegex(ValueError, "unique"):
            freeze_semantic_beats("narration-v3", candidates, self.approval())

    def test_closed_stage_a_records_reject_missing_reference_unknown_choices_and_timing(self):
        """Catches a planner leaking unverifiable text or formal timing downstream."""
        cases = (
            ("missing-text-ref", lambda beat: beat.pop("text_ref")),
            ("missing-keyword", lambda beat: beat.pop("keyword")),
            ("non-text-keyword", lambda beat: beat.update(keyword=[])),
            ("unknown-priority", lambda beat: beat.update(priority="urgent")),
            ("unknown-carrier", lambda beat: beat.update(preferred_carrier="music")),
            ("timing-leak", lambda beat: beat.update(keyword_start_ms=1200)),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                candidate = dict(self.candidates()[0])
                mutate(candidate)
                with self.assertRaises(ValueError):
                    freeze_semantic_beats("narration-v3", [candidate], self.approval())

    def test_freeze_returns_fresh_records_and_rejects_rewriting_frozen_anchors(self):
        """Catches downstream callers re-submitting approved anchors as editable candidates."""
        frozen = freeze_semantic_beats(
            "narration-v3", self.candidates(), self.approval()
        )
        copy = validate_semantic_beats(frozen)
        copy["beats"][0]["keyword"] = "rewritten"

        self.assertEqual("timing", frozen["beats"][0]["keyword"])
        self.assertEqual("rewritten", validate_semantic_beats(copy)["beats"][0]["keyword"])
        with self.assertRaises(ValueError):
            freeze_semantic_beats("narration-v3", frozen["beats"], self.approval())

    def test_approval_is_user_scoped_and_matches_each_keyword(self):
        """Catches delegated or partial approvals being treated as a keyword freeze."""
        non_user = {**self.approval(), "provenance": "system:review-v3"}
        with self.assertRaisesRegex(ValueError, "user"):
            freeze_semantic_beats("narration-v3", self.candidates(), non_user)

        partial = {**self.approval(), "keywords": ["other"]}
        with self.assertRaisesRegex(ValueError, "keyword"):
            freeze_semantic_beats("narration-v3", self.candidates(), partial)

        malformed = {**self.approval(), "keywords": [[]]}
        with self.assertRaises(ValueError):
            freeze_semantic_beats("narration-v3", self.candidates(), malformed)

    def test_generic_validation_rejects_non_user_approval_provenance(self):
        """Catches generic Artifact callers bypassing the user-approved freeze helper."""
        frozen = freeze_semantic_beats(
            "narration-v3", self.candidates(), self.approval()
        )
        frozen["beats"][0]["approval_provenance"] = "system-generated"

        with self.assertRaisesRegex(ValueError, "user"):
            validate_semantic_beats(frozen)

    def test_legacy_projection_is_read_only_and_defensive(self):
        """Catches a compatibility projection becoming an authorable timing record."""
        legacy = {
            "artifact_id": "semantic-beats-v0",
            "type": "semantic-beats",
            "version": 1,
            "status": "approved",
            "parents": ["voice-timing-v0"],
            "path": "metadata/semantic-beats-v0.json",
            "voice_timing_id": "voice-timing-v0",
        }
        projected = project_legacy_timed_beats(legacy)

        self.assertEqual(legacy, projected)
        self.assertIsNot(legacy, projected)
        self.assertIsNone(project_legacy_timed_beats({"type": "semantic-beats"}))
        with self.assertRaises(ValueError):
            project_legacy_timed_beats({**legacy, "beats": []})

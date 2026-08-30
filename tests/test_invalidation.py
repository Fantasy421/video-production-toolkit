import json
import unittest
from pathlib import Path

from scripts.toolkit.invalidation import invalidate_descendants


ROOT = Path(__file__).parents[1]


class InvalidationTests(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads(
            (ROOT / "references" / "policies" / "invalidation.json").read_text(encoding="utf-8")
        )
        self.artifacts = [
            {"artifact_id": "narration-v1", "type": "narration", "parents": []},
            {"artifact_id": "style-v1", "type": "style-pack", "parents": []},
            {"artifact_id": "voice-v1", "type": "voice-timing", "parents": []},
            {"artifact_id": "scene-S01-v1", "type": "media", "parents": ["style-v1"]},
            {"artifact_id": "storyboard-v1", "type": "storyboard", "parents": ["voice-v1"]},
            {"artifact_id": "timeline-v1", "type": "timeline", "parents": ["scene-S01-v1", "storyboard-v1"]},
        ]

    def test_style_change_does_not_invalidate_narration(self):
        """Catches style invalidation leaking into content-planning artifacts."""
        stale = invalidate_descendants(self.artifacts, "style-v1", self.rules)

        self.assertEqual({"scene-S01-v1", "timeline-v1"}, stale)

    def test_voice_change_invalidates_timing_descendants(self):
        """Catches voice timing changes leaving its storyboard or timeline fresh."""
        stale = invalidate_descendants(self.artifacts, "voice-v1", self.rules)

        self.assertIn("storyboard-v1", stale)
        self.assertIn("timeline-v1", stale)

    def test_voice_profile_change_invalidates_audio_and_timing_consumers(self):
        """Catches a profile revision leaving generated audio or its consumers fresh."""
        artifacts = [
            {"artifact_id": "voice-profile-v1", "type": "voice-profile", "parents": []},
            {"artifact_id": "voiceover-v1", "type": "voiceover", "parents": ["voice-profile-v1"]},
            {"artifact_id": "voice-timing-v1", "type": "voice-timing", "parents": ["voiceover-v1"]},
            {"artifact_id": "beats-v1", "type": "semantic-beats", "parents": ["voice-timing-v1"]},
            {"artifact_id": "storyboard-v1", "type": "storyboard", "parents": ["beats-v1"]},
            {"artifact_id": "timeline-v1", "type": "timeline", "parents": ["storyboard-v1"]},
            {"artifact_id": "review-v1", "type": "review-pack", "parents": ["timeline-v1"]},
        ]

        self.assertEqual(
            {
                "voiceover-v1",
                "voice-timing-v1",
                "beats-v1",
                "storyboard-v1",
                "timeline-v1",
                "review-v1",
            },
            invalidate_descendants(artifacts, "voice-profile-v1", self.rules),
        )

    def test_every_timing_upstream_invalidates_the_exact_full_timing_chain(self):
        """Catches any timing revision leaving scene contracts or validation approved."""
        cases = (
            ("narration", {"voice-timing-v1", "semantic-beats-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("voice-source-decision", {"voiceover-v1", "voice-timing-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("voice-profile", {"voiceover-v1", "voice-timing-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("audio", {"voiceover-v1", "voice-timing-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("audio-asset", {"voiceover-v1", "voice-timing-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("uploaded-audio", {"voiceover-v1", "voice-timing-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("voiceover", {"voice-timing-v1", "timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("voice-timing", {"timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("semantic-beats", {"timed-semantic-beats-v1", "scene-timing-v1", "timing-validation-v1"}),
            ("timed-semantic-beats", {"scene-timing-v1", "timing-validation-v1"}),
            ("scene-timing-contracts", {"timing-validation-v1"}),
        )
        for upstream_type, expected in cases:
            with self.subTest(upstream_type=upstream_type):
                artifacts = self._timed_semantic_graph(upstream_type)

                stale = invalidate_descendants(
                    artifacts, "upstream-v1", self.rules
                )

                self.assertEqual(expected, stale)

    @staticmethod
    def _timed_semantic_graph(upstream_type):
        artifacts = [
            {"artifact_id": "narration-v1", "type": "narration", "parents": []},
            {
                "artifact_id": "semantic-beats-v1",
                "type": "semantic-beats",
                "parents": ["narration-v1"],
            },
        ]
        if upstream_type == "semantic-beats":
            artifacts[1]["artifact_id"] = "upstream-v1"
            semantic_id = "upstream-v1"
            voiceover_parent = None
        elif upstream_type == "narration":
            artifacts[0] = {
                "artifact_id": "upstream-v1",
                "type": "narration",
                "parents": [],
            }
            artifacts[1]["parents"] = ["upstream-v1"]
            semantic_id = "semantic-beats-v1"
            voiceover_parent = "upstream-v1"
        elif upstream_type == "voiceover":
            artifacts.append(
                {"artifact_id": "upstream-v1", "type": "voiceover", "parents": []}
            )
            semantic_id = "semantic-beats-v1"
            voiceover_parent = "upstream-v1"
        elif upstream_type == "voice-timing":
            artifacts.append(
                {
                    "artifact_id": "upstream-v1",
                    "type": "voice-timing",
                    "parents": [],
                }
            )
            semantic_id = "semantic-beats-v1"
            voiceover_parent = None
        elif upstream_type in {"timed-semantic-beats", "scene-timing-contracts"}:
            semantic_id = "semantic-beats-v1"
            voiceover_parent = None
        else:
            artifacts.extend(
                [
                    {
                        "artifact_id": "upstream-v1",
                        "type": upstream_type,
                        "parents": [],
                    },
                    {
                        "artifact_id": "voiceover-v1",
                        "type": "voiceover",
                        "parents": ["upstream-v1"],
                    },
                ]
            )
            semantic_id = "semantic-beats-v1"
            voiceover_parent = "voiceover-v1"
        if upstream_type not in {"voice-timing", "timed-semantic-beats", "scene-timing-contracts"}:
            artifacts.append(
                {
                    "artifact_id": "voice-timing-v1",
                    "type": "voice-timing",
                    "parents": [voiceover_parent],
                }
            )
            timing_parent = "voice-timing-v1"
        else:
            timing_parent = "upstream-v1" if upstream_type == "voice-timing" else "voice-timing-v1"
            if upstream_type in {"timed-semantic-beats", "scene-timing-contracts"}:
                artifacts.append({"artifact_id": "voice-timing-v1", "type": "voice-timing", "parents": []})
        timed_id = "upstream-v1" if upstream_type == "timed-semantic-beats" else "timed-semantic-beats-v1"
        if upstream_type != "timed-semantic-beats":
            artifacts.append(
                {
                    "artifact_id": timed_id,
                    "type": "timed-semantic-beats",
                    "parents": [semantic_id, timing_parent],
                }
            )
        else:
            artifacts.append({"artifact_id": timed_id, "type": "timed-semantic-beats", "parents": [semantic_id, timing_parent]})
        scene_id = "upstream-v1" if upstream_type == "scene-timing-contracts" else "scene-timing-v1"
        artifacts.append({"artifact_id": scene_id, "type": "scene-timing-contracts", "parents": [timed_id]})
        artifacts.append({"artifact_id": "timing-validation-v1", "type": "timing-validation", "parents": [scene_id]})
        return artifacts

    def test_style_change_does_not_invalidate_unchanged_voiceover(self):
        """Catches visual-only invalidation crossing into an independent voice branch."""
        artifacts = [
            {"artifact_id": "style-v1", "type": "style-pack", "parents": []},
            {"artifact_id": "voiceover-v1", "type": "voiceover", "parents": []},
            {"artifact_id": "scene-S01-v1", "type": "media", "parents": ["style-v1"]},
        ]

        self.assertNotIn(
            "voiceover-v1", invalidate_descendants(artifacts, "style-v1", self.rules)
        )

    def test_uploaded_audio_replacement_invalidates_exact_voice_descendants(self):
        """Catches uploaded narration replacement leaving derived timing current."""
        for uploaded_type in ("audio", "audio-asset", "uploaded-audio"):
            with self.subTest(uploaded_type=uploaded_type):
                artifacts = [
                    {"artifact_id": "upload-v1", "type": uploaded_type, "parents": []},
                    {
                        "artifact_id": "voiceover-v1",
                        "type": "voiceover",
                        "parents": ["upload-v1"],
                    },
                    {
                        "artifact_id": "voice-timing-v1",
                        "type": "voice-timing",
                        "parents": ["voiceover-v1"],
                    },
                    {
                        "artifact_id": "captions-v1",
                        "type": "captions",
                        "parents": ["voice-timing-v1"],
                    },
                    {
                        "artifact_id": "timeline-v1",
                        "type": "timeline",
                        "parents": ["captions-v1"],
                    },
                ]

                self.assertEqual(
                    {
                        "voiceover-v1",
                        "voice-timing-v1",
                        "captions-v1",
                        "timeline-v1",
                    },
                    invalidate_descendants(artifacts, "upload-v1", self.rules),
                )

    def test_disallowed_descendant_type_remains_fresh(self):
        """Catches DAG traversal ignoring the policy's explicit type boundary."""
        artifacts = [
            {"artifact_id": "style-v1", "type": "style-pack", "parents": []},
            {"artifact_id": "beats-v1", "type": "semantic-beats", "parents": ["style-v1"]},
        ]

        self.assertEqual(set(), invalidate_descendants(artifacts, "style-v1", self.rules))

    def test_shipped_policy_invalidates_scene_contract_media_and_timeline_descendants(self):
        """Catches resume smoke passing only because it injects private invalidation rules."""
        artifacts = [
            {"artifact_id": "contract-S01-v1", "type": "scene-contract", "parents": []},
            {"artifact_id": "scene-S01-v1", "type": "media", "parents": ["contract-S01-v1"]},
            {"artifact_id": "timeline-v1", "type": "timeline", "parents": ["scene-S01-v1"]},
            {"artifact_id": "review-v1", "type": "review-pack", "parents": ["timeline-v1"]},
        ]

        self.assertEqual(
            {"scene-S01-v1", "timeline-v1", "review-v1"},
            invalidate_descendants(artifacts, "contract-S01-v1", self.rules),
        )

    def test_shipped_policy_uses_the_canonical_media_artifact_type(self):
        """Catches the policy naming scene-media while production artifacts are media."""
        self.assertIn("media", self.rules["scene-contract"])
        self.assertIn("media", self.rules["style-pack"])
        self.assertNotIn("scene-media", self.rules)

    def test_semantic_beats_change_invalidates_the_full_timed_production_dag(self):
        """Catches split timing invalidation stopping at timed beats."""
        artifacts = [
            {"artifact_id": "semantic-v2", "type": "semantic-beats", "parents": []},
            {"artifact_id": "voice-v1", "type": "voice-timing", "parents": []},
            {"artifact_id": "timed-v2", "type": "timed-semantic-beats", "parents": ["semantic-v2", "voice-v1"]},
            {"artifact_id": "scene-timing-v2", "type": "scene-timing-contracts", "parents": ["timed-v2"]},
            {"artifact_id": "storyboard-v2", "type": "storyboard", "parents": ["scene-timing-v2"]},
            {"artifact_id": "scene-v2", "type": "scene-contract", "parents": ["storyboard-v2"]},
            {"artifact_id": "media-v2", "type": "media", "parents": ["scene-v2"]},
            {"artifact_id": "motion-v2", "type": "motion-graphic", "parents": ["media-v2"]},
            {"artifact_id": "timeline-v2", "type": "timeline", "parents": ["motion-v2"]},
        ]

        self.assertEqual(
            {
                "timed-v2", "scene-timing-v2", "storyboard-v2", "scene-v2",
                "media-v2", "motion-v2", "timeline-v2",
            },
            invalidate_descendants(artifacts, "semantic-v2", self.rules),
        )

    def test_voice_only_change_does_not_invalidate_stage_a_semantic_beats(self):
        """Catches recursive timing invalidation crossing back into Stage A."""
        artifacts = [
            {"artifact_id": "semantic-v1", "type": "semantic-beats", "parents": []},
            {"artifact_id": "voice-v1", "type": "voice-timing", "parents": []},
            {"artifact_id": "timed-v1", "type": "timed-semantic-beats", "parents": ["semantic-v1", "voice-v1"]},
            {"artifact_id": "scene-timing-v1", "type": "scene-timing-contracts", "parents": ["timed-v1"]},
            {"artifact_id": "storyboard-v1", "type": "storyboard", "parents": ["scene-timing-v1"]},
        ]

        stale = invalidate_descendants(artifacts, "voice-v1", self.rules)
        self.assertNotIn("semantic-v1", stale)
        self.assertEqual(
            {"timed-v1", "scene-timing-v1", "storyboard-v1"}, stale
        )


if __name__ == "__main__":
    unittest.main()

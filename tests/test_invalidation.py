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


if __name__ == "__main__":
    unittest.main()

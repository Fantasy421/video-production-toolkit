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

    def test_disallowed_descendant_type_remains_fresh(self):
        """Catches DAG traversal ignoring the policy's explicit type boundary."""
        artifacts = [
            {"artifact_id": "style-v1", "type": "style-pack", "parents": []},
            {"artifact_id": "beats-v1", "type": "semantic-beats", "parents": ["style-v1"]},
        ]

        self.assertEqual(set(), invalidate_descendants(artifacts, "style-v1", self.rules))


if __name__ == "__main__":
    unittest.main()

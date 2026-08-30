"""Compact deterministic validation for one scene-production batch."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.toolkit.batch_media_validation import validate_media_batch_json


class BatchMediaValidationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "media").mkdir()
        for scene_id in ("S01", "S02", "S03", "S04"):
            (self.root / "media" / f"{scene_id}.mp4").write_bytes(b"fixture")

    def tearDown(self):
        self.folder.cleanup()

    @staticmethod
    def item(scene_id, start_ms):
        return {
            "scene_id": scene_id,
            "path": f"media/{scene_id}.mp4",
            "start_ms": start_ms,
            "end_ms": start_ms + 2_000,
            "expected_duration_ms": 2_000,
            "required_streams": ["audio", "video"],
            "cues": [
                {"cue_id": f"{scene_id}-cue-1", "at_ms": start_ms + 200},
                {"cue_id": f"{scene_id}-cue-2", "at_ms": start_ms + 800},
            ],
        }

    def test_valid_batch_returns_checks_without_per_scene_logs(self):
        items = [self.item(f"S{index:02d}", (index - 1) * 2_000) for index in range(1, 5)]
        probes = {
            item["path"]: {
                "duration_ms": 2_000,
                "streams": ["audio", "video"],
                "black_intervals_ms": [],
            }
            for item in items
        }

        result = validate_media_batch_json(
            self.root,
            json.dumps({"items": items}),
            probe_results=probes,
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual({}, result["issue_counts"])
        self.assertEqual({}, result["examples"])
        self.assertEqual(
            ["json-valid", "files-present", "duration-valid", "av-valid", "black-frame-valid", "cue-order-valid"],
            result["checks"],
        )
        self.assertNotIn("items", result)

    def test_failures_are_aggregated_and_examples_are_capped(self):
        items = [self.item(f"S{index:02d}", (index - 1) * 2_000) for index in range(1, 5)]
        items[0]["cues"].reverse()
        (self.root / items[3]["path"]).unlink()
        probes = {
            item["path"]: {
                "duration_ms": 3_000,
                "streams": ["video"],
                "black_intervals_ms": [[0, 500]],
            }
            for item in items[:3]
        }

        result = validate_media_batch_json(
            self.root,
            json.dumps({"items": items}),
            probe_results=probes,
        )

        self.assertEqual("blocked", result["status"])
        self.assertEqual(
            {
                "AV_STREAM_MISSING": 3,
                "BLACK_FRAME_DETECTED": 3,
                "CUE_ORDER_INVALID": 1,
                "DURATION_MISMATCH": 3,
                "FILE_MISSING": 1,
            },
            result["issue_counts"],
        )
        self.assertEqual(["S01", "S02", "S03"], result["examples"]["DURATION_MISMATCH"])
        self.assertNotIn("S04", result["examples"]["DURATION_MISMATCH"])

    def test_invalid_json_returns_one_compact_failure(self):
        result = validate_media_batch_json(self.root, "{not-json")

        self.assertEqual(
            {
                "status": "blocked",
                "checks": [],
                "issue_counts": {"INVALID_MANIFEST_JSON": 1},
                "examples": {"INVALID_MANIFEST_JSON": []},
            },
            result,
        )


if __name__ == "__main__":
    unittest.main()

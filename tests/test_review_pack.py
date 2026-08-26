import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.build_review_pack import build_review_pack


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "previews").mkdir()
        (self.root / "timeline").mkdir()
        (self.root / "approvals").mkdir()
        (self.root / "artifacts" / "timeline").mkdir(parents=True)
        (self.root / "previews" / "S01-preview.jpg").write_bytes(b"jpg")
        (self.root / "timeline" / "editable.project").write_text("saved", encoding="utf-8")
        (self.root / "timeline" / "timeline.json").write_text(
            json.dumps(
                {
                    "duration_ms": 5_000,
                    "saved_project": "timeline/editable.project",
                    "tracks": [
                        {
                            "id": "primary",
                            "primary": True,
                            "clips": [{"scene_id": "S01", "start_ms": 0, "end_ms": 5_000}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "artifacts" / "timeline" / "timeline-v1.json").write_text(
            json.dumps({"artifact_id": "timeline-v1", "type": "timeline", "version": 1, "status": "approved", "parents": [], "path": "timeline/timeline.json"}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.folder.cleanup()

    def test_review_pack_links_previews_and_decisions_without_embedding_media(self):
        path = build_review_pack(self.root, self.root / "review")

        html = path.read_text(encoding="utf-8")
        review = json.loads((path.parent / "review.json").read_text(encoding="utf-8"))
        self.assertIn('data-scene-id="S01"', html)
        self.assertNotIn("data:image/", html)
        self.assertIn("../previews/S01-preview.jpg", html)
        self.assertEqual("Representative slice and final draft", review["decision_requests"][0]["gate"])

    def test_review_pack_rejects_output_outside_project(self):
        with self.assertRaises(ValueError):
            build_review_pack(self.root, self.root.parent / "outside-review")

    def test_review_pack_does_not_link_preview_symlinks_outside_project(self):
        external = self.root.parent / "outside-preview.jpg"
        external.write_bytes(b"outside")
        (self.root / "previews" / "outside.jpg").symlink_to(external)

        path = build_review_pack(self.root, self.root / "review")

        self.assertNotIn("outside.jpg", path.read_text(encoding="utf-8"))

    def test_failed_regeneration_keeps_the_published_bundle_consistent(self):
        published = build_review_pack(self.root, self.root / "review")
        previous_html = published.read_text(encoding="utf-8")
        previous_review = (published.parent / "review.json").read_text(encoding="utf-8")
        (self.root / "previews" / "S02-preview.jpg").write_bytes(b"new jpg")

        with patch("scripts.build_review_pack._render_html", side_effect=RuntimeError("render failed")):
            with self.assertRaises(RuntimeError):
                build_review_pack(self.root, self.root / "review")

        self.assertEqual(previous_html, published.read_text(encoding="utf-8"))
        self.assertEqual(previous_review, (published.parent / "review.json").read_text(encoding="utf-8"))

    def test_review_timecodes_only_use_approved_timeline_artifact(self):
        (self.root / "timeline" / "active.json").write_text(
            json.dumps(
                {
                    "duration_ms": 5_000,
                    "saved_project": "timeline/editable.project",
                    "tracks": [{"id": "primary", "primary": True, "clips": [{"scene_id": "S01", "start_ms": 0, "end_ms": 5_000}]}],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "timeline" / "timeline.json").write_text(
            json.dumps(
                {
                    "duration_ms": 5_000,
                    "tracks": [{"id": "primary", "primary": True, "clips": [{"scene_id": "S99", "start_ms": 0, "end_ms": 5_000}]}],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "artifacts" / "timeline" / "timeline-v1.json").write_text(
            json.dumps({"artifact_id": "timeline-v1", "type": "timeline", "version": 1, "status": "approved", "parents": [], "path": "timeline/active.json"}),
            encoding="utf-8",
        )
        (self.root / "timeline" / "other.json").write_text(
            json.dumps({"duration_ms": 5_000, "tracks": [{"id": "primary", "primary": True, "clips": [{"scene_id": "S02", "start_ms": 0, "end_ms": 5_000}]}]}),
            encoding="utf-8",
        )
        (self.root / "artifacts" / "timeline" / "timeline-v2.json").write_text(
            json.dumps({"artifact_id": "timeline-v2", "type": "timeline", "version": 2, "status": "approved", "parents": [], "path": "timeline/other.json"}),
            encoding="utf-8",
        )
        (self.root / "project.json").write_text(
            json.dumps({"schema_version": 1, "project_id": "review-test", "workflow": "knowledge-video", "phase": "review_ready", "active_timeline_id": "timeline-v1"}),
            encoding="utf-8",
        )

        path = build_review_pack(self.root, self.root / "review")

        html = path.read_text(encoding="utf-8")
        self.assertIn('data-scene-id="S01"', html)
        self.assertNotIn('data-scene-id="S99"', html)
        self.assertNotIn('data-scene-id="S02"', html)


if __name__ == "__main__":
    unittest.main()

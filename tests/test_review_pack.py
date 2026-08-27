import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.build_review_pack import build_review_pack
from scripts.toolkit.project_state import append_event, initialize_project, set_active_timeline


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "previews").mkdir()
        (self.root / "timeline").mkdir()
        (self.root / "approvals").mkdir()
        (self.root / "artifacts" / "timeline").mkdir(parents=True)
        (self.root / "artifacts" / "visual-preview").mkdir()
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
        (self.root / "artifacts" / "visual-preview" / "preview-S01-v1.json").write_text(
            json.dumps(
                {
                    "artifact_id": "preview-S01-v1",
                    "type": "visual-preview",
                    "version": 1,
                    "status": "approved",
                    "parents": [],
                    "path": "previews/S01-preview.jpg",
                }
            ),
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

    def test_review_pack_labels_only_effectively_approved_preview_artifacts(self):
        """Catches event-invalidated preview metadata still being presented as current."""
        initialize_project(self.root, "review-preview-status", "knowledge-video")
        (self.root / "previews" / "S02-preview.jpg").write_bytes(b"stale jpg")
        (self.root / "artifacts" / "visual-preview" / "preview-S02-v1.json").write_text(
            json.dumps(
                {
                    "artifact_id": "preview-S02-v1",
                    "type": "visual-preview",
                    "version": 1,
                    "status": "approved",
                    "parents": [],
                    "path": "previews/S02-preview.jpg",
                }
            ),
            encoding="utf-8",
        )
        append_event(
            self.root,
            {
                "event": "artifacts.invalidated",
                "changed_id": "preview-S02-v1",
                "artifact_ids": ["preview-S02-v1"],
            },
        )

        path = build_review_pack(self.root, self.root / "review")
        review = json.loads((path.parent / "review.json").read_text(encoding="utf-8"))

        self.assertEqual(
            [{"artifact_id": "preview-S01-v1", "label": "S01-preview.jpg", "href": "../../previews/S01-preview.jpg", "status": "approved"}],
            review["previews"],
        )
        html = path.read_text(encoding="utf-8")
        self.assertIn("S01-preview.jpg [approved]", html)
        self.assertNotIn("S02-preview.jpg", html)

    def test_review_pack_excludes_a_timeline_staled_by_an_event_overlay(self):
        """Catches review packaging presenting a timeline invalidated only in the event log."""
        initialize_project(self.root, "review-invalidated", "knowledge-video")
        append_event(
            self.root,
            {
                "event": "artifacts.invalidated",
                "changed_id": "timeline-v1",
                "artifact_ids": ["timeline-v1"],
            },
        )

        path = build_review_pack(self.root, self.root / "review")
        review = json.loads((path.parent / "review.json").read_text(encoding="utf-8"))

        self.assertNotIn('data-scene-id="S01"', path.read_text(encoding="utf-8"))
        self.assertIn(
            "missing-active-timeline",
            {item["code"] for item in review["structural_errors"]},
        )

    def test_review_pack_excludes_timeline_scenes_when_referenced_media_is_stale(self):
        """Catches an approved timeline presenting scene media invalidated by an event."""
        initialize_project(self.root, "review-stale-media", "knowledge-video")
        (self.root / "artifacts" / "media").mkdir()
        (self.root / "artifacts" / "media" / "scene-S01-v1.json").write_text(
            json.dumps(
                {
                    "artifact_id": "scene-S01-v1",
                    "type": "media",
                    "version": 1,
                    "status": "approved",
                    "parents": [],
                    "path": "media/scene-S01.png",
                }
            ),
            encoding="utf-8",
        )
        timeline_path = self.root / "timeline" / "timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["clips"][0]["artifact_id"] = "scene-S01-v1"
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
        append_event(
            self.root,
            {
                "event": "artifacts.invalidated",
                "changed_id": "scene-S01-v1",
                "artifact_ids": ["scene-S01-v1"],
            },
        )

        path = build_review_pack(self.root, self.root / "review")
        review = json.loads((path.parent / "review.json").read_text(encoding="utf-8"))

        self.assertEqual([], review["scenes"])
        self.assertNotIn('data-scene-id="S01"', path.read_text(encoding="utf-8"))
        self.assertIn(
            "stale-active-artifact",
            {item["code"] for item in review["structural_errors"]},
        )

    def test_review_pack_rejects_output_outside_project(self):
        with self.assertRaises(ValueError):
            build_review_pack(self.root, self.root.parent / "outside-review")

    def test_review_pack_rejects_a_symlinked_project_root(self):
        """Catches root resolution hiding a caller-controlled project symlink."""
        with TemporaryDirectory() as folder:
            linked_root = Path(folder) / "project-link"
            linked_root.symlink_to(self.root, target_is_directory=True)

            with self.assertRaises(ValueError):
                build_review_pack(linked_root, linked_root / "review")

    def test_review_pack_does_not_link_preview_symlinks_outside_project(self):
        external = self.root.parent / "outside-preview.jpg"
        external.write_bytes(b"outside")
        (self.root / "previews" / "outside.jpg").symlink_to(external)
        (self.root / "artifacts" / "visual-preview" / "preview-outside-v1.json").write_text(
            json.dumps(
                {
                    "artifact_id": "preview-outside-v1",
                    "type": "visual-preview",
                    "version": 1,
                    "status": "approved",
                    "parents": [],
                    "path": "previews/outside.jpg",
                }
            ),
            encoding="utf-8",
        )

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
        initialize_project(self.root, "review-test", "knowledge-video")
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
        set_active_timeline(self.root, "timeline-v1")

        path = build_review_pack(self.root, self.root / "review")

        html = path.read_text(encoding="utf-8")
        self.assertIn('data-scene-id="S01"', html)
        self.assertNotIn('data-scene-id="S99"', html)
        self.assertNotIn('data-scene-id="S02"', html)


if __name__ == "__main__":
    unittest.main()

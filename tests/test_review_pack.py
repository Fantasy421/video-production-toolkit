import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_review_pack import build_review_pack


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "previews").mkdir()
        (self.root / "timeline").mkdir()
        (self.root / "approvals").mkdir()
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


if __name__ == "__main__":
    unittest.main()

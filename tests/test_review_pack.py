"""Review relay tests: compact metadata in, compact user decision out."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.build_review_pack import build_review_pack


class ReviewPackTests(unittest.TestCase):
    """The review boundary must not inspect or expand visual-media handoffs."""

    def setUp(self):
        self.root = Path("unused-project-root")

    def visual_handoff(self, **overrides):
        handoff = {
            "artifact_ids": ["media-S03-v4"],
            "paths": ["media/media-S03-v4.mp4"],
            "media": {
                "kind": "video",
                "format": "mp4",
                "width": 1280,
                "height": 720,
                "duration_ms": 12_000,
                "fps": 24,
                "readiness": "ready",
            },
            "checks": ["timeline-aligned", "preview-created"],
            "issues": [{"code": "caption-overlap", "severity": "warning"}],
            "summary": "Scene S03 preview is ready",
            "review_preview_path": None,
        }
        handoff.update(overrides)
        return handoff

    def test_review_pack_relays_preview_path_without_dereferencing_it(self):
        """Catches a relay reopening the user-only preview path."""
        preview_path = "previews/S03-v4-low.mp4"
        handoff = self.visual_handoff(review_preview_path=preview_path)

        with TemporaryDirectory() as folder:
            root = Path(folder)
            preview_target = root / preview_path
            json_path = root / "artifacts" / "media-S03-v4.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text('{"safe": true}', encoding="utf-8")
            original_methods = {
                name: getattr(Path, name)
                for name in ("resolve", "open", "read_bytes", "read_text", "exists", "is_file", "stat")
            }

            def guard(name):
                def guarded(path, *args, **kwargs):
                    if path == preview_target:
                        raise AssertionError(f"preview target dereferenced via {name}")
                    return original_methods[name](path, *args, **kwargs)

                return guarded

            with (
                patch.object(Path, "resolve", autospec=True, side_effect=guard("resolve")),
                patch.object(Path, "open", autospec=True, side_effect=guard("open")),
                patch.object(Path, "read_bytes", autospec=True, side_effect=guard("read_bytes")),
                patch.object(Path, "read_text", autospec=True, side_effect=guard("read_text")),
                patch.object(Path, "exists", autospec=True, side_effect=guard("exists")),
                patch.object(Path, "is_file", autospec=True, side_effect=guard("is_file")),
                patch.object(Path, "stat", autospec=True, side_effect=guard("stat")),
            ):
                self.assertEqual('{"safe": true}', json_path.read_text(encoding="utf-8"))
                pack = build_review_pack(root, handoff)

        self.assertEqual(preview_path, pack["review_preview_path"])

    def test_review_pack_rejects_two_preview_candidates(self):
        """Catches a handoff that would make the user compare multiple previews."""
        handoff = self.visual_handoff(
            review_preview_path=["previews/S03-a.mp4", "previews/S03-b.mp4"]
        )

        with self.assertRaisesRegex(ValueError, "preview"):
            build_review_pack(self.root, handoff)

    def test_review_pack_rejects_unvalidated_or_malformed_handoffs(self):
        """Catches a relay dropping, truncating, or coercing invalid handoff data."""
        cases = (
            (self.visual_handoff(extra="unknown"), "unknown top-level field"),
            (self.visual_handoff(prompt_history=["make it brighter"]), "prompt history"),
            (self.visual_handoff(video_bytes=b"not allowed"), "media payload"),
            (self.visual_handoff(media={"kind": "video", "extra": "unknown"}), "unknown media field"),
            (self.visual_handoff(issues=[{"code": "issue-1", "extra": "unknown"}]), "unknown issue field"),
            (self.visual_handoff(artifact_ids=("media-S03-v4",)), "wrong artifact list type"),
            (self.visual_handoff(checks=[f"check-{index}" for index in range(9)]), "oversized checks"),
            (self.visual_handoff(checks=["same", "same"]), "duplicate checks"),
            (self.visual_handoff(paths=["../outside.mp4"]), "malformed path"),
            (self.visual_handoff(summary=""), "malformed scalar"),
        )

        for handoff, name in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_review_pack(self.root, handoff)

    def test_review_pack_preserves_all_validated_structural_media_scalars(self):
        """Catches the relay dropping validated media identity metadata."""
        pack = build_review_pack(
            self.root,
            self.visual_handoff(
                media={
                    "kind": "video",
                    "format": "mp4",
                    "mime_type": "video/mp4",
                    "width": 1280,
                    "height": 720,
                    "duration_ms": 12_000,
                    "fps": 24,
                    "readiness": "ready",
                    "checksum": "a1b2c3d4",
                }
            ),
        )

        self.assertEqual(
            {
                "kind": "video",
                "format": "mp4",
                "mime_type": "video/mp4",
                "width": 1280,
                "height": 720,
                "duration_ms": 12_000,
                "fps": 24,
                "readiness": "ready",
                "checksum": "a1b2c3d4",
            },
            pack["media"],
        )

    def test_review_pack_keeps_subjective_acceptance_with_the_user(self):
        """Catches an automated review relay declaring a visual decision final."""
        pack = build_review_pack(self.root, self.visual_handoff())

        self.assertEqual("waiting_user", pack["decision_status"])
        self.assertEqual("user", pack["subjective_acceptance_authority"])
        self.assertEqual(
            ["approve", "reject", "request_revision"], pack["allowed_user_decisions"]
        )



if __name__ == "__main__":
    unittest.main()

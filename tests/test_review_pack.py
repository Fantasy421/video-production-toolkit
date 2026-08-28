"""Review relay tests: compact metadata in, compact user decision out."""

import unittest
from pathlib import Path
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
        handoff = self.visual_handoff(review_preview_path="previews/S03-v4-low.mp4")

        with (
            patch("pathlib.Path.open", side_effect=AssertionError("media dereferenced")),
            patch("pathlib.Path.read_bytes", side_effect=AssertionError("media dereferenced")),
            patch("pathlib.Path.read_text", side_effect=AssertionError("media dereferenced")),
        ):
            pack = build_review_pack(self.root, handoff)

        self.assertEqual("previews/S03-v4-low.mp4", pack["review_preview_path"])

    def test_review_pack_rejects_two_preview_candidates(self):
        """Catches a handoff that would make the user compare multiple previews."""
        handoff = self.visual_handoff(
            review_preview_path=["previews/S03-a.mp4", "previews/S03-b.mp4"]
        )

        with self.assertRaisesRegex(ValueError, "zero or one review preview path"):
            build_review_pack(self.root, handoff)

    def test_review_pack_omits_prompt_and_payload_fields(self):
        """Catches media payload or prompt history leaking through a trusted relay."""
        handoff = self.visual_handoff(
            prompt_history=["make it brighter"],
            video_bytes=b"not allowed",
        )

        pack = build_review_pack(self.root, handoff)

        self.assertNotIn("prompt_history", pack)
        self.assertNotIn("video_bytes", pack)
        self.assertEqual(["timeline-aligned", "preview-created"], pack["checks"])

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
                    "checksum": "abc123",
                    "sha256": "def456",
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
                "checksum": "abc123",
                "sha256": "def456",
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

    def test_review_pack_caps_check_and_issue_codes(self):
        """Catches a malformed handoff expanding the review relay without bound."""
        pack = build_review_pack(
            self.root,
            self.visual_handoff(
                checks=[f"check-{index}" for index in range(10)],
                issues=[{"code": f"issue-{index}"} for index in range(10)],
            ),
        )

        self.assertEqual([f"check-{index}" for index in range(8)], pack["checks"])
        self.assertEqual(
            [{"code": f"issue-{index}"} for index in range(8)], pack["issues"]
        )


if __name__ == "__main__":
    unittest.main()

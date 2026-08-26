import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
import zlib

from scripts.toolkit.validation import validate_project


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "artifacts" / "timeline").mkdir(parents=True)
        (self.root / "artifacts" / "scene-media").mkdir(parents=True)
        (self.root / "artifacts" / "scene-contract").mkdir(parents=True)
        (self.root / "timeline").mkdir()
        (self.root / "media").mkdir()
        (self.root / "contracts").mkdir()
        (self.root / "approvals").mkdir()
        (self.root / "media" / "scene-S01.mp4").write_bytes(b"preview")
        (self.root / "timeline" / "editable.project").write_text("saved", encoding="utf-8")
        (self.root / "timeline" / "timeline-v1.json").write_text(
            json.dumps(
                {
                    "duration_ms": 10_000,
                    "saved_project": "timeline/editable.project",
                    "tracks": [
                        {
                            "id": "primary",
                            "primary": True,
                            "clips": [
                                {
                                    "scene_id": "S01",
                                    "artifact_id": "scene-S01-v1",
                                    "contract_id": "scene-contract-S01-v1",
                                    "start_ms": 0,
                                    "end_ms": 10_000,
                                }
                            ],
                        }
                    ],
                    "captions": [
                        {
                            "start_ms": 0,
                            "end_ms": 10_000,
                            "safe_region": "subtitle-bottom",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.write_artifact(
            "scene-S01-v1", "scene-media", 1, "approved", "media/scene-S01.mp4"
        )
        (self.root / "contracts" / "S01.json").write_text(
            json.dumps(
                {
                    "scene_id": "S01",
                    "semantic_beats": [{"beat_id": "B01", "primary_carrier": "Scene"}],
                }
            ),
            encoding="utf-8",
        )
        self.write_artifact(
            "scene-contract-S01-v1",
            "scene-contract",
            1,
            "approved",
            "contracts/S01.json",
        )
        self.write_artifact(
            "timeline-v1",
            "timeline",
            1,
            "approved",
            "timeline/timeline-v1.json",
            parents=["scene-S01-v1", "scene-contract-S01-v1"],
        )
        (self.root / "approvals" / "approval-final.json").write_text(
            json.dumps(
                {
                    "approval_id": "approval-final",
                    "target_id": "timeline-v1",
                    "scope": "whole-project",
                    "decision": "approved",
                    "notes": "reviewed",
                }
            ),
            encoding="utf-8",
        )
        (self.root / "project.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": "validation-test",
                    "workflow": "knowledge-video",
                    "phase": "review_ready",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.folder.cleanup()

    def write_artifact(
        self, artifact_id, artifact_type, version, status, path, parents=None, **metadata
    ):
        artifact = {
            "artifact_id": artifact_id,
            "type": artifact_type,
            "version": version,
            "status": status,
            "parents": parents or [],
            "path": path,
            **metadata,
        }
        destination = self.root / "artifacts" / artifact_type / f"{artifact_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(artifact), encoding="utf-8")

    def write_rgba_png(self, relative, alpha):
        def chunk(kind, payload):
            checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

        header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        pixel = bytes((32, 64, 96, alpha))
        path = self.root / relative
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00" + pixel))
            + chunk(b"IEND", b"")
        )
        return path

    def promoted_character_metadata(self):
        return {
            "promotion": {
                "ownership": "cross-project-registry",
                "scope": "project-independent",
                "source_or_license": "user-owned",
                "provenance": {
                    "project_id": "source-project",
                    "artifact_id": "character-action-v1",
                },
                "validation_evidence": ["identity-continuity-reviewed"],
                "applicability": ["neutral-presenter-action"],
                "asset_kind": "character-action",
                "subject": "presenter",
                "action": "points-right",
                "orientation": "right",
                "scene": "",
                "alpha": "yes",
            }
        }

    def test_promoted_character_action_requires_real_transparency(self):
        """Catches metadata-only alpha claims accepting a fully opaque PNG."""
        self.write_rgba_png("media/opaque.png", 255)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/opaque.png",
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-missing",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_action_with_real_transparency_passes(self):
        """Catches a real transparent pixel being rejected as metadata-only alpha."""
        self.write_rgba_png("media/transparent.png", 0)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/transparent.png",
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertEqual(
            [],
            [
                item
                for item in result["errors"]
                if "promoted" in item["code"]
            ],
        )

    def test_promoted_character_action_requires_neutral_owned_provenance(self):
        """Catches project-coupled or unattributed media entering cross-project reuse."""
        self.write_rgba_png("media/coupled.png", 0)
        metadata = self.promoted_character_metadata()
        promotion = metadata["promotion"]
        promotion["ownership"] = "current-project"
        promotion["source_or_license"] = ""
        promotion["provenance"] = {}
        promotion["scene"] = "S04-specific-background"
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/coupled.png",
            **metadata,
        )

        result = validate_project(self.root)
        codes = {item["code"] for item in result["errors"]}

        self.assertIn("invalid-promoted-asset-ownership", codes)
        self.assertIn("missing-promoted-asset-source", codes)
        self.assertIn("missing-promoted-asset-provenance", codes)
        self.assertIn("non-neutral-promoted-character-action", codes)

    def test_promoted_character_action_requires_explicit_neutral_scene_metadata(self):
        """Catches an absent scene field being treated as proven project independence."""
        self.write_rgba_png("media/transparent.png", 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"].pop("scene")
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/transparent.png",
            **metadata,
        )

        result = validate_project(self.root)

        self.assertIn(
            "non-neutral-promoted-character-action",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_action_requires_identity_continuity_evidence(self):
        """Catches generic evidence satisfying the character identity promise."""
        self.write_rgba_png("media/transparent.png", 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["validation_evidence"] = ["alpha-reviewed"]
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/transparent.png",
            **metadata,
        )

        result = validate_project(self.root)

        self.assertIn(
            "missing-character-identity-evidence",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_alpha_inspection_failure_is_an_issue(self):
        """Catches corrupt or unsupported files crashing structural validation."""
        (self.root / "media" / "corrupt.png").write_bytes(b"not a png")
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/corrupt.png",
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-unverifiable",
            {item["code"] for item in result["errors"]},
        )

    def test_malformed_promotion_evidence_is_an_issue_not_an_exception(self):
        """Catches unhashable metadata values crashing structural validation."""
        self.write_rgba_png("media/transparent.png", 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["validation_evidence"] = [{}]
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/transparent.png",
            **metadata,
        )

        result = validate_project(self.root)

        self.assertIn(
            "missing-promoted-asset-validation-evidence",
            {item["code"] for item in result["errors"]},
        )

    def test_stale_artifact_on_active_timeline_is_error(self):
        self.write_artifact(
            "scene-S01-v2",
            "scene-media",
            2,
            "stale",
            "media/scene-S01-v2.mp4",
            parents=["scene-S01-v1"],
        )
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["clips"][0]["artifact_id"] = "scene-S01-v2"
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("stale-active-artifact", {item["code"] for item in result["errors"]})

    def test_subjective_aesthetic_language_is_not_emitted(self):
        result = validate_project(self.root)

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual([], result["errors"])
        self.assertNotIn("不高级", rendered)
        self.assertNotIn("不好看", rendered)

    def test_missing_saved_project_and_caption_safe_region_are_errors(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline.pop("saved_project")
        timeline["captions"][0].pop("safe_region")
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)

        codes = {item["code"] for item in result["errors"]}
        self.assertIn("missing-saved-project-reference", codes)
        self.assertIn("missing-caption-safe-region", codes)

    def test_absolute_artifact_path_is_rejected_even_when_it_points_inside_project(self):
        artifact_path = self.root / "artifacts" / "scene-media" / "scene-S01-v1.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["path"] = str(self.root / "media" / "scene-S01.mp4")
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("unsafe-artifact-path", {item["code"] for item in result["errors"]})

    def test_malformed_mixed_timing_emits_an_issue_without_crashing(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["clips"].append(
            {"scene_id": "S02", "start_ms": "bad", "end_ms": 10_000}
        )
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("invalid-timeline-clip", {item["code"] for item in result["errors"]})

    def test_artifact_parent_cycle_is_an_error(self):
        scene_path = self.root / "artifacts" / "scene-media" / "scene-S01-v1.json"
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        scene["parents"] = ["timeline-v1"]
        scene_path.write_text(json.dumps(scene), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("artifact-parent-cycle", {item["code"] for item in result["errors"]})

    def test_tracks_require_one_primary_and_zero_primary_tracks_still_check_gaps(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["primary"] = False
        timeline["tracks"][0]["clips"][0]["end_ms"] = 9_000
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)

        codes = {item["code"] for item in result["errors"]}
        self.assertIn("invalid-primary-track-count", codes)
        self.assertIn("timeline-gap", codes)

    def test_tracks_reject_multiple_primary_definitions(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"].append(
            {"id": "second-primary", "primary": True, "clips": []}
        )
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("invalid-primary-track-count", {item["code"] for item in result["errors"]})

    def test_active_clips_require_a_contract_and_its_beat_coverage(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["clips"][0].pop("contract_id")
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        missing_result = validate_project(self.root)
        self.assertIn("missing-contract-reference", {item["code"] for item in missing_result["errors"]})

        timeline["tracks"][0]["clips"][0]["contract_id"] = "scene-contract-S01-v1"
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
        contract_path = self.root / "contracts" / "S01.json"
        contract_path.write_text(json.dumps({"scene_id": "S01", "semantic_beats": []}), encoding="utf-8")

        coverage_result = validate_project(self.root)
        self.assertIn("missing-contract-coverage", {item["code"] for item in coverage_result["errors"]})

    def test_nonvisual_tracks_are_exempt_from_scene_contracts_but_visual_tracks_are_not(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        base_timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        for track_kind in ("voice", "captions", "music", "sfx", "transitions"):
            with self.subTest(track_kind=track_kind):
                timeline = json.loads(json.dumps(base_timeline))
                timeline["tracks"][0]["kind"] = track_kind
                timeline["tracks"][0]["clips"][0].pop("contract_id")
                timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

                result = validate_project(self.root)
                self.assertNotIn("missing-contract-reference", {item["code"] for item in result["errors"]})

        timeline = json.loads(json.dumps(base_timeline))
        timeline["tracks"][0]["kind"] = "visual"
        timeline["tracks"][0]["clips"][0].pop("contract_id")
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)
        self.assertIn("missing-contract-reference", {item["code"] for item in result["errors"]})


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import shutil
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
        (self.root / "artifacts" / "media").mkdir(parents=True)
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
            "scene-S01-v1", "media", 1, "approved", "media/scene-S01.mp4"
        )
        (self.root / "contracts" / "S01.json").write_text(
            json.dumps(
                {
                    "scene_id": "S01",
                    "voice_timing_id": "voice-timing-v1",
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "primary_carrier": "scene",
                    "purpose": "show the concrete cause",
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

    @staticmethod
    def png_chunk(kind, payload):
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    @classmethod
    def rgba_png_bytes(cls, alpha):
        header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        pixel = bytes((32, 64, 96, alpha))
        return (
            b"\x89PNG\r\n\x1a\n"
            + cls.png_chunk(b"IHDR", header)
            + cls.png_chunk(b"IDAT", zlib.compress(b"\x00" + pixel))
            + cls.png_chunk(b"IEND", b"")
        )

    def write_rgba_png(self, relative, alpha):
        path = self.root / relative
        path.write_bytes(self.rgba_png_bytes(alpha))
        return path

    def promoted_png_error_codes(self, contents):
        path = "media/presenter_points-right_right_v01.png"
        (self.root / path).write_bytes(contents)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **self.promoted_character_metadata(),
        )
        return {item["code"] for item in validate_project(self.root)["errors"]}

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
        self.write_rgba_png("media/presenter_points-right_right_v01.png", 255)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/presenter_points-right_right_v01.png",
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-missing",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_action_with_real_transparency_passes(self):
        """Catches a real transparent pixel being rejected as metadata-only alpha."""
        self.write_rgba_png("media/presenter_points-right_right_v01.png", 0)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/presenter_points-right_right_v01.png",
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
        self.write_rgba_png("media/presenter_points-right_right_v01.png", 0)
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
            "media/presenter_points-right_right_v01.png",
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
        self.write_rgba_png("media/presenter_points-right_right_v01.png", 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"].pop("scene")
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/presenter_points-right_right_v01.png",
            **metadata,
        )

        result = validate_project(self.root)

        self.assertIn(
            "non-neutral-promoted-character-action",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_action_requires_identity_continuity_evidence(self):
        """Catches generic evidence satisfying the character identity promise."""
        self.write_rgba_png("media/presenter_points-right_right_v01.png", 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["validation_evidence"] = ["alpha-reviewed"]
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/presenter_points-right_right_v01.png",
            **metadata,
        )

        result = validate_project(self.root)

        self.assertIn(
            "missing-character-identity-evidence",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_alpha_inspection_failure_is_an_issue(self):
        """Catches corrupt or unsupported files crashing structural validation."""
        path = "media/presenter_points-right_right_v01.png"
        (self.root / path).write_bytes(b"not a png")
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-unverifiable",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_png_with_bad_crc_is_unverifiable(self):
        """Catches transparent pixel data bypassing a corrupt IDAT checksum."""
        png = bytearray(self.rgba_png_bytes(0))
        idat_type = png.index(b"IDAT")
        idat_length = struct.unpack(">I", png[idat_type - 4 : idat_type])[0]
        idat_crc = idat_type + 4 + idat_length
        png[idat_crc] ^= 0x01
        path = "media/presenter_points-right_right_v01.png"
        (self.root / path).write_bytes(png)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-unverifiable",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_png_without_iend_is_unverifiable(self):
        """Catches a complete pixel stream being accepted without terminal IEND."""
        path = "media/presenter_points-right_right_v01.png"
        (self.root / path).write_bytes(self.rgba_png_bytes(0)[:-12])
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-unverifiable",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_png_requires_valid_chunk_structure(self):
        """Catches reordered, duplicate, or post-IEND PNG chunks."""
        valid = self.rgba_png_bytes(0)
        signature = valid[:8]
        ihdr = valid[8:33]
        idat = valid[33:-12]
        iend = valid[-12:]
        malformed_files = {
            "idat-before-ihdr": signature + idat + ihdr + iend,
            "duplicate-ihdr": signature + ihdr + ihdr + idat + iend,
            "trailing-data": valid + b"trailing",
        }
        for label, contents in malformed_files.items():
            with self.subTest(label=label):
                path = "media/presenter_points-right_right_v01.png"
                (self.root / path).write_bytes(contents)
                self.write_artifact(
                    "promoted-character-v1",
                    "promoted-asset",
                    1,
                    "approved",
                    path,
                    **self.promoted_character_metadata(),
                )

                result = validate_project(self.root)

                self.assertIn(
                    "promoted-character-action-alpha-unverifiable",
                    {item["code"] for item in result["errors"]},
                )

    def test_promoted_character_png_rejects_illegal_plte_chunks(self):
        """Catches misplaced, duplicate, malformed, or forbidden PLTE chunks."""
        valid = self.rgba_png_bytes(0)
        signature = valid[:8]
        rgba_ihdr = valid[8:33]
        rgba_idat = valid[33:-12]
        iend = valid[-12:]
        plte = self.png_chunk(b"PLTE", b"\x20\x40\x60")
        grayscale_alpha_ihdr = self.png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 4, 0, 0, 0)
        )
        grayscale_alpha_idat = self.png_chunk(
            b"IDAT", zlib.compress(b"\x00\x20\x00")
        )
        malformed_files = {
            "after-idat": signature + rgba_ihdr + rgba_idat + plte + iend,
            "duplicate": signature + rgba_ihdr + plte + plte + rgba_idat + iend,
            "invalid-length": (
                signature
                + rgba_ihdr
                + self.png_chunk(b"PLTE", b"\x00")
                + rgba_idat
                + iend
            ),
            "forbidden-for-grayscale-alpha": (
                signature
                + grayscale_alpha_ihdr
                + plte
                + grayscale_alpha_idat
                + iend
            ),
        }
        for label, contents in malformed_files.items():
            with self.subTest(label=label):
                self.assertIn(
                    "promoted-character-action-alpha-unverifiable",
                    self.promoted_png_error_codes(contents),
                )

    def test_promoted_character_png_rejects_unknown_critical_chunks(self):
        """Catches unknown chunks whose first type byte marks them critical."""
        valid = self.rgba_png_bytes(0)
        signature = valid[:8]
        ihdr = valid[8:33]
        idat_and_iend = valid[33:]
        variants = {
            "unknown-critical": (
                self.png_chunk(b"VpAg", b"payload"),
                True,
            ),
            "unknown-ancillary": (
                self.png_chunk(b"vpAg", b"payload"),
                False,
            ),
        }
        for label, (chunk, expect_unverifiable) in variants.items():
            with self.subTest(label=label):
                codes = self.promoted_png_error_codes(
                    signature + ihdr + chunk + idat_and_iend
                )
                self.assertEqual(
                    expect_unverifiable,
                    "promoted-character-action-alpha-unverifiable" in codes,
                )

    def test_promoted_character_png_rejects_invalid_zlib_or_scanline_streams(self):
        """Catches nonterminal zlib streams and invalid decoded scanlines."""
        valid = self.rgba_png_bytes(0)
        signature_and_ihdr = valid[:33]
        iend = valid[-12:]
        pixel = bytes((32, 64, 96, 0))
        scanline = b"\x00" + pixel
        compressed = zlib.compress(scanline)
        malformed_streams = {
            "trailing-zlib-bytes": compressed + b"trailing",
            "concatenated-zlib-stream": compressed + zlib.compress(scanline),
            "incomplete-zlib-stream": compressed[:-1],
            "wrong-decoded-size": zlib.compress(scanline + b"\x00"),
            "invalid-filter": zlib.compress(b"\x05" + pixel),
        }
        for label, stream in malformed_streams.items():
            with self.subTest(label=label):
                contents = (
                    signature_and_ihdr
                    + self.png_chunk(b"IDAT", stream)
                    + iend
                )
                self.assertIn(
                    "promoted-character-action-alpha-unverifiable",
                    self.promoted_png_error_codes(contents),
                )

    def test_promoted_character_name_rejects_project_coupling(self):
        """Catches legacy shot identifiers in promoted character filenames."""
        path = "media/复利效应_S004_灰发猫耳少年_讲解_右侧_v01.png"
        self.write_rgba_png(path, 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["subject"] = "灰发猫耳少年"
        metadata["promotion"]["action"] = "讲解"
        metadata["promotion"]["orientation"] = "右侧"
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **metadata,
        )

        result = validate_project(self.root)

        self.assertIn(
            "project-coupled-promoted-character-name",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_name_requires_version_suffix(self):
        """Catches promoted names that omit the legacy two-digit version suffix."""
        path = "media/presenter_points-right_right.png"
        self.write_rgba_png(path, 0)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "invalid-promoted-character-version-suffix",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_name_requires_literal_subject_and_action(self):
        """Catches filename metadata drift for the declared subject or action."""
        path = "media/presenter_wave_right_v01.png"
        self.write_rgba_png(path, 0)
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            path,
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-name-metadata-mismatch",
            {item["code"] for item in result["errors"]},
        )

    def test_malformed_promotion_evidence_is_an_issue_not_an_exception(self):
        """Catches unhashable metadata values crashing structural validation."""
        self.write_rgba_png("media/presenter_points-right_right_v01.png", 0)
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["validation_evidence"] = [{}]
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/presenter_points-right_right_v01.png",
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
            "media",
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

    def test_event_overlay_invalidation_is_applied_before_structural_review(self):
        """Catches immutable artifact metadata hiding a newer invalidation event."""
        events = self.root / "events"
        events.mkdir()
        (events / "events.jsonl").write_text(
            "\n".join(
                (
                    json.dumps(
                        {
                            "event": "project.initialized",
                            "schema_version": 1,
                            "project_id": "validation-test",
                            "workflow": "knowledge-video",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "artifacts.invalidated",
                            "changed_id": "scene-S01-v1",
                            "artifact_ids": ["scene-S01-v1"],
                        }
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )

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
        artifact_path = self.root / "artifacts" / "media" / "scene-S01-v1.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["path"] = str(self.root / "media" / "scene-S01.mp4")
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("unsafe-artifact-path", {item["code"] for item in result["errors"]})

    def test_validator_rejects_symlinked_runtime_storage_outside_project(self):
        """Catches structural validation reading attacker-controlled artifacts outside root."""
        with TemporaryDirectory() as outside_folder:
            outside = Path(outside_folder) / "artifacts"
            shutil.copytree(self.root / "artifacts", outside)
            shutil.rmtree(self.root / "artifacts")
            (self.root / "artifacts").symlink_to(outside, target_is_directory=True)

            result = validate_project(self.root)

        self.assertIn("unsafe-runtime-storage", {item["code"] for item in result["errors"]})

    def test_validator_rejects_symlinked_approval_and_task_records(self):
        """Catches validation ingesting foreign records from otherwise local storage."""
        (self.root / "tasks").mkdir()
        with TemporaryDirectory() as outside_folder:
            outside = Path(outside_folder)
            approval_id = "approval-outside"
            (outside / f"{approval_id}.json").write_text(
                json.dumps(
                    {
                        "approval_id": approval_id,
                        "target_id": "timeline-v1",
                        "scope": "whole-project",
                        "decision": "approved",
                        "notes": "foreign",
                    }
                ),
                encoding="utf-8",
            )
            task_id = "task-outside"
            (outside / f"{task_id}.json").write_text(
                json.dumps(
                    {
                        "task_id": task_id,
                        "capability": "project.manage",
                        "inputs": [],
                        "adapter_preferences": ["chatcut"],
                        "output_contract": "task-result-v1",
                        "constraints": {"required_gate": None},
                    }
                ),
                encoding="utf-8",
            )
            (self.root / "approvals" / f"{approval_id}.json").symlink_to(
                outside / f"{approval_id}.json"
            )
            (self.root / "tasks" / f"{task_id}.json").symlink_to(
                outside / f"{task_id}.json"
            )

            result = validate_project(self.root)

        unsafe = {
            item["storage"]
            for item in result["errors"]
            if item["code"] == "unsafe-runtime-storage"
        }
        self.assertTrue(
            {
                f"approvals/{approval_id}.json",
                f"tasks/{task_id}.json",
            }
            <= unsafe
        )

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
        scene_path = self.root / "artifacts" / "media" / "scene-S01-v1.json"
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

    def test_active_clips_require_a_canonical_scene_contract(self):
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["clips"][0].pop("contract_id")
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        missing_result = validate_project(self.root)
        self.assertIn("missing-contract-reference", {item["code"] for item in missing_result["errors"]})

        timeline["tracks"][0]["clips"][0]["contract_id"] = "scene-contract-S01-v1"
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
        contract_path = self.root / "contracts" / "S01.json"
        contract_path.write_text(
            json.dumps(
                {
                    "scene_id": "S01",
                    "voice_timing_id": "voice-timing-v1",
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "primary_carrier": "Scene",
                    "purpose": "wrong vocabulary",
                }
            ),
            encoding="utf-8",
        )

        coverage_result = validate_project(self.root)
        self.assertIn("invalid-scene-contract", {item["code"] for item in coverage_result["errors"]})

    def test_schema_valid_lowercase_scene_contract_is_accepted_by_structural_validation(self):
        """Catches the validator requiring semantic_beats and title-case carrier aliases."""
        result = validate_project(self.root)

        self.assertNotIn(
            "missing-contract-coverage",
            {item["code"] for item in result["errors"]},
        )
        self.assertNotIn(
            "invalid-scene-contract",
            {item["code"] for item in result["errors"]},
        )

    def test_current_project_scene_contract_rejects_estimated_timing_artifact(self):
        """Catches v2 structural validation using the legacy syntax-only path."""
        project_path = self.root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["schema_version"] = 2
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.write_artifact(
            "voice-timing-v1",
            "voice-timing",
            1,
            "approved",
            "metadata/voice-timing-v1.json",
            voiceover_id="voiceover-v1",
            timing_kind="estimated",
            duration_ms=10_000,
            segments=[{"start_ms": 0, "end_ms": 10_000, "text": "estimate"}],
        )

        result = validate_project(self.root)

        self.assertIn(
            "invalid-scene-contract",
            {item["code"] for item in result["errors"]},
        )

    def test_canonical_demo_contract_requires_a_lifecycle_record(self):
        """Catches lifecycle validation relying on a duplicate carrier field on the clip."""
        contract_path = self.root / "contracts" / "S01.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["primary_carrier"] = "demo"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        timeline_path = self.root / "timeline" / "timeline-v1.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["tracks"][0]["clips"][0]["demo_id"] = "demo-S01"
        timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

        result = validate_project(self.root)

        lifecycle_errors = [
            item
            for item in result["errors"]
            if item["code"] == "demo-lifecycle-incomplete"
        ]
        self.assertEqual(
            [{"code": "demo-lifecycle-incomplete", "demo_id": "demo-S01", "timeline_id": "timeline-v1"}],
            lifecycle_errors,
        )

    def test_project_snapshot_rejects_an_unknown_phase(self):
        """Catches structural validation accepting a phase replay cannot produce."""
        project_path = self.root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["phase"] = "not-a-phase"
        project_path.write_text(json.dumps(project), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("invalid-project-state", {item["code"] for item in result["errors"]})

    def test_style_pack_requires_structural_font_evidence(self):
        """Catches approved style packs naming a bundled font that is not present."""
        pack_dir = self.root / "packs"
        pack_dir.mkdir()
        preview = self.root / "previews" / "style.html"
        preview.parent.mkdir()
        preview.write_text("preview", encoding="utf-8")
        source = json.loads(
            (
                Path(__file__).parents[1]
                / "registries/styles/editorial-clean/v1/manifest.json"
            ).read_text(encoding="utf-8")
        )
        source["preview"] = "previews/style.html"
        source["previews"] = ["previews/style.html"]
        source["required_fonts"] = [
            {"family": "Toolkit Sans", "source": "bundled", "path": "fonts/missing.otf"}
        ]
        (pack_dir / "style.json").write_text(json.dumps(source), encoding="utf-8")
        self.write_artifact(
            "style-v1", "style-pack", 1, "approved", "packs/style.json"
        )

        result = validate_project(self.root)

        self.assertIn("missing-required-font", {item["code"] for item in result["errors"]})

    def test_layout_pack_rejects_regions_outside_the_normalized_canvas(self):
        """Catches a schema-shaped layout whose region extends beyond the frame."""
        pack_dir = self.root / "packs"
        pack_dir.mkdir()
        source = json.loads(
            (
                Path(__file__).parents[1]
                / "registries/layouts/talking-head-left-explainer-right/v1/manifest.json"
            ).read_text(encoding="utf-8")
        )
        source["regions"]["subject"] = {
            "x": 0.9,
            "y": 0.0,
            "width": 0.2,
            "height": 0.5,
        }
        (pack_dir / "layout.json").write_text(json.dumps(source), encoding="utf-8")
        self.write_artifact(
            "layout-v1", "layout-pack", 1, "approved", "packs/layout.json"
        )

        result = validate_project(self.root)

        self.assertIn("invalid-layout-pack", {item["code"] for item in result["errors"]})

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

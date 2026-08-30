import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jsonschema import Draft202012Validator

from scripts.toolkit import artifacts
from scripts.toolkit.artifacts import approve_artifact, create_artifact, read_approval
from tests.encoding_boundary_cases import (
    HARMLESS_PROSE_CONTROLS,
    STRUCTURAL_ENCODING_CASES,
    TYPED_CHECKSUM_CONTROL,
    TYPED_SAFE_ID_CONTROL,
)


FIXTURES = Path(__file__).parent / "fixtures"


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.artifact = {
            "artifact_id": "style-v1",
            "type": "style-pack",
            "version": 1,
            "status": "draft",
            "parents": [],
            "path": "previews/style-v1.html",
        }

    def tearDown(self):
        self.folder.cleanup()

    @staticmethod
    def semantic_timing_artifact(artifact_type):
        common = {
            "artifact_id": f"{artifact_type}-v1",
            "type": artifact_type,
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": f"metadata/{artifact_type}-v1.json",
        }
        if artifact_type == "semantic-beats":
            return {
                **common,
                "narration_id": "narration-v1",
                "beats": [
                    {
                        "beat_id": "B01",
                        "text_ref": "narration-v1:S01:L1",
                        "keyword": "timing",
                        "intent": "core-concept-emphasis",
                        "priority": "primary",
                        "preferred_carrier": "motion-graphics",
                        "approval_provenance": "user:keyword-review-v1",
                    }
                ],
            }
        if artifact_type == "timed-semantic-beats":
            return {
                **common,
                "semantic_beats_id": "semantic-beats-v1",
                "voice_timing_id": "voice-timing-v1",
                "timing_kind": "real",
                "beats": [
                    {
                        "beat_id": "B01",
                        "speech_start_ms": 1000,
                        "speech_end_ms": 2000,
                        "keyword_start_ms": 1200,
                        "keyword_end_ms": 1600,
                        "emphasis_ms": 1400,
                        "visual_window_ms": [1080, 1900],
                        "approved_anchor_commitment": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                    }
                ],
            }
        return {
            **common,
            "timed_semantic_beats_id": "timed-semantic-beats-v1",
            "scenes": [
                {
                    "scene_id": "S01",
                    "scene_window_ms": [1000, 2000],
                    "beat_ids": ["B01"],
                    "primary_carrier": "motion-graphics",
                    "support_layer": "caption-emphasis",
                    "visual_window_ms": [1080, 1900],
                }
            ],
        }

    def test_timing_artifacts_require_closed_dedicated_metadata_on_create(self):
        """Catches generic artifact admission bypassing timing contract fields or nesting."""
        cases = (
            (
                "semantic-missing-beats",
                "semantic-beats",
                lambda artifact: artifact.pop("beats"),
            ),
            (
                "semantic-empty-beats",
                "semantic-beats",
                lambda artifact: artifact.update({"beats": []}),
            ),
            (
                "semantic-unexpected-beat-key",
                "semantic-beats",
                lambda artifact: artifact["beats"][0].update({"unexpected": "metadata"}),
            ),
            (
                "timed-missing-lineage",
                "timed-semantic-beats",
                lambda artifact: artifact.pop("semantic_beats_id"),
            ),
            (
                "timed-empty-beats",
                "timed-semantic-beats",
                lambda artifact: artifact.update({"beats": []}),
            ),
            (
                "timed-unexpected-beat-key",
                "timed-semantic-beats",
                lambda artifact: artifact["beats"][0].update({"unexpected": "metadata"}),
            ),
            (
                "scene-missing-lineage",
                "scene-timing-contracts",
                lambda artifact: artifact.pop("timed_semantic_beats_id"),
            ),
            (
                "scene-empty-contracts",
                "scene-timing-contracts",
                lambda artifact: artifact.update({"scenes": []}),
            ),
            (
                "scene-unexpected-nested-key",
                "scene-timing-contracts",
                lambda artifact: artifact["scenes"][0].update({"unexpected": "metadata"}),
            ),
        )
        for name, artifact_type, mutate in cases:
            with self.subTest(name=name):
                artifact = self.semantic_timing_artifact(artifact_type)
                mutate(artifact)

                with self.assertRaises(ValueError):
                    artifacts.validate_artifact_record(artifact)
                with TemporaryDirectory() as folder, self.assertRaises(ValueError):
                    create_artifact(Path(folder), artifact)

    def test_timing_artifacts_reject_zero_duration_windows(self):
        """Catches artifact admission accepting a window rejected by construction."""
        for artifact_type in ("timed-semantic-beats", "scene-timing-contracts"):
            artifact = self.semantic_timing_artifact(artifact_type)
            if artifact_type == "timed-semantic-beats":
                artifact["beats"][0]["visual_window_ms"] = [1000, 1000]
            else:
                artifact["scenes"][0]["scene_window_ms"] = [1000, 1000]
            with self.subTest(artifact_type=artifact_type), self.assertRaises(ValueError):
                artifacts.validate_artifact_record(artifact)

    def test_voice_timing_keyword_anchors_are_closed_authoritative_evidence(self):
        """Catches Artifact validation admitting worker-controlled anchor fields."""
        timing = {
            "artifact_id": "voice-timing-v1",
            "type": "voice-timing",
            "version": 1,
            "status": "approved",
            "parents": ["voiceover-v1"],
            "path": "metadata/voice-timing-v1.json",
            "voiceover_id": "voiceover-v1",
            "timing_kind": "real",
            "duration_ms": 1_000,
            "segments": [{"start_ms": 0, "end_ms": 1_000, "text": "旁白"}],
            "keyword_anchors": [
                {
                    "beat_id": "B01",
                    "keyword": "旁白",
                    "start_ms": 200,
                    "end_ms": 500,
                    "unexpected": True,
                }
            ],
        }

        with self.assertRaises(ValueError):
            artifacts.validate_artifact_record(timing)

    @staticmethod
    def legacy_voice_timing():
        return {
            "artifact_id": "voice-timing-v0",
            "type": "voice-timing",
            "version": 1,
            "status": "approved",
            "parents": ["voiceover-v0"],
            "path": "metadata/voice-timing-v0.json",
            "voiceover_id": "voiceover-v0",
            "timing_kind": "real",
            "duration_ms": 1_000,
            "segments": [{"start_ms": 0, "end_ms": 1_000, "text": "旧旁白"}],
        }

    def test_legacy_voice_timing_is_readable_but_not_authorable(self):
        """Catches the new anchor requirement erasing a persisted old timing record."""
        legacy = self.legacy_voice_timing()

        artifacts.validate_artifact_record(legacy)
        persisted = self.root / "artifacts" / "voice-timing" / "voice-timing-v0.json"
        persisted.parent.mkdir(parents=True)
        persisted.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertEqual(legacy, artifacts._read_valid_artifact(persisted))
        with TemporaryDirectory() as folder, self.assertRaises(ValueError):
            create_artifact(Path(folder), legacy)

    def test_legacy_voice_timing_compatibility_rejects_new_timing_fields(self):
        """Catches the read-only legacy branch becoming a general timing bypass."""
        legacy = self.legacy_voice_timing()
        legacy["beats"] = []

        with self.assertRaises(ValueError):
            artifacts.validate_artifact_record(legacy)

    @staticmethod
    def legacy_semantic_beats_projection():
        return {
            "artifact_id": "semantic-beats-v0",
            "type": "semantic-beats",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "metadata/semantic-beats-v0.json",
            "voice_timing_id": "voice-timing-v0",
        }

    def test_valid_legacy_semantic_beats_projection_is_readable_but_not_authorable(self):
        """Catches the compatibility projection reopening the new-artifact write path."""
        legacy = self.legacy_semantic_beats_projection()
        artifacts.validate_artifact_record(legacy)

        persisted = (
            self.root
            / "artifacts"
            / "semantic-beats"
            / "semantic-beats-v0.json"
        )
        persisted.parent.mkdir(parents=True)
        persisted.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertEqual(legacy, artifacts._read_valid_artifact(persisted))
        with TemporaryDirectory() as folder, self.assertRaises(ValueError):
            create_artifact(Path(folder), legacy)

    def test_legacy_semantic_beats_projection_rejects_new_timing_fields(self):
        """Catches legacy compatibility carrying new timing metadata or nested scenes."""
        legacy = self.legacy_semantic_beats_projection()
        artifacts.validate_artifact_record(legacy)

        cases = (
            ("beats", [{"unexpected": "metadata"}]),
            ("scenes", [{"unexpected": "metadata"}]),
            ("semantic_beats_id", "semantic-beats-v1"),
            ("timed_semantic_beats_id", "timed-semantic-beats-v1"),
            ("timing_kind", "real"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                record = {**legacy, field: value}

                with self.assertRaises(ValueError):
                    artifacts.validate_artifact_record(record)
                with TemporaryDirectory() as folder, self.assertRaises(ValueError):
                    create_artifact(Path(folder), record)

    def test_existing_artifact_id_cannot_be_overwritten(self):
        """Catches a later artifact write replacing an immutable version."""
        create_artifact(self.root, self.artifact)

        with self.assertRaises(FileExistsError):
            create_artifact(self.root, self.artifact)

    def test_artifact_is_stored_at_its_type_and_id_path(self):
        """Catches metadata being saved outside the stable artifact location."""
        path = create_artifact(self.root, self.artifact)

        self.assertEqual(self.root / "artifacts" / "style-pack" / "style-v1.json", path)
        self.assertEqual(self.artifact, json.loads(path.read_text(encoding="utf-8")))

    def test_artifact_and_approval_storage_reject_symlink_escapes(self):
        """Catches runtime metadata writes following artifacts or approvals outside the project."""
        with TemporaryDirectory() as outside_folder:
            outside = Path(outside_folder)
            (self.root / "artifacts").symlink_to(outside / "artifacts", target_is_directory=True)
            (outside / "artifacts").mkdir()

            with self.assertRaises(ValueError):
                create_artifact(self.root, self.artifact)
            self.assertEqual([], list((outside / "artifacts").rglob("*.json")))

        (self.root / "artifacts").unlink()
        create_artifact(self.root, self.artifact)
        with TemporaryDirectory() as outside_folder:
            outside = Path(outside_folder)
            (outside / "approvals").mkdir()
            (self.root / "approvals").symlink_to(
                outside / "approvals", target_is_directory=True
            )

            with self.assertRaises(ValueError):
                approve_artifact(self.root, "style-v1", "whole-project", "approved")
            self.assertEqual([], list((outside / "approvals").glob("*.json")))

    def test_artifact_rejects_unknown_parent(self):
        """Catches a DAG edge being recorded without a durable parent artifact."""
        artifact = {**self.artifact, "artifact_id": "preview-v1", "parents": ["missing-v1"]}

        with self.assertRaises(ValueError):
            create_artifact(self.root, artifact)

    def test_artifact_type_must_be_a_safe_single_path_component(self):
        """Catches a type escaping or bypassing the artifacts directory."""
        for artifact_type in (".", "..", "nested/type"):
            with self.subTest(artifact_type=artifact_type):
                artifact = {**self.artifact, "type": artifact_type}

                with self.assertRaises(ValueError):
                    create_artifact(self.root, artifact)

    def test_artifact_payload_path_must_remain_inside_the_project(self):
        """Catches metadata registering an absolute or traversing payload path."""
        unsafe_paths = (
            "../outside.json",
            "/tmp/outside.json",
            "..\\outside.json",
            "C:/outside.json",
            ".",
        )
        for index, payload_path in enumerate(unsafe_paths, 1):
            with self.subTest(payload_path=payload_path):
                artifact_id = f"style-unsafe-v{index}"
                artifact = {
                    **self.artifact,
                    "artifact_id": artifact_id,
                    "path": payload_path,
                }

                with self.assertRaises(ValueError):
                    create_artifact(self.root, artifact)

                self.assertFalse(
                    (self.root / "artifacts" / "style-pack" / f"{artifact_id}.json").exists()
                )

    def test_artifact_boundary_recursively_rejects_payload_history_urls_and_oversize(self):
        """Catches immutable Artifact metadata becoming a coordinator side channel."""
        base = {
            "artifact_id": "safe-report-v1",
            "type": "report",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "artifacts/reports/safe-report-v1.json",
        }
        cases = (
            ({"metadata": {"prompt_transcript": ["secret"]}}, "prompt"),
            ({"metadata": {"source": "s3://bucket/hidden.png"}}, "URL|scheme"),
            (
                {
                    "metadata": {
                        "opaque": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYX"
                        "GBkaGxwdHh8gISIjJCUmJygpKissLS4v"
                    }
                },
                "Base64|binary",
            ),
            ({"metadata": {"raw": b"bytes"}}, "payload|binary"),
            ({"metadata": {"notes": "x" * 33_000}}, "budget"),
        )
        for extra, message in cases:
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, message):
                create_artifact(self.root, {**base, **extra})

    def test_artifact_extension_contract_rejects_reviewed_side_channel_probes(self):
        """Catches unknown typed-looking extensions bypassing the Artifact boundary."""
        base = {
            "artifact_id": "safe-report-v1",
            "type": "report",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "artifacts/reports/safe-report-v1.json",
        }
        cases = (
            ("checksum alias", {"checksum_backup": "A" * 64}),
            ("unknown URI scheme", {"source_ref": "gopher:opaque-resource"}),
            ("allowlisted URI scheme", {"provenance": "gopher:opaque-resource"}),
            (
                "Base64URL",
                {
                    "opaque": (
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "abcdefghijklmnopqrstuvwxyz0123456789-_"
                    )
                },
            ),
            ("numeric samples", {"sample_values": [0, 1, 2, 3]}),
            ("prompt alias", {"prompt_records": ["secret instruction"]}),
        )

        with patch(
            "base64.b64decode",
            side_effect=AssertionError("Artifact validation must never decode Base64"),
        ):
            for name, extra in cases:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    artifacts.validate_artifact_record({**base, **extra})

    def test_artifact_schema_closes_and_types_business_metadata_extensions(self):
        """Catches schema consumers reopening arbitrary nested Artifact extensions."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references/schemas/artifact.schema.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        self.assertFalse(schema["additionalProperties"])

        safe_license = {
            "artifact_id": "license-v1",
            "type": "license-document",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "artifacts/licenses/license-v1.json",
            "license": {
                "owner": "Example Studio",
                "territories": ["global"],
                "expires": None,
            },
        }
        self.assertTrue(validator.is_valid(safe_license))
        artifacts.validate_artifact_record(safe_license)

        for extra in (
            {"checksum_backup": "A" * 64},
            {"metadata": {"notes": "arbitrary nested extension"}},
            {"sample_values": [0, 1, 2, 3]},
            {"license": {"owner": "Example Studio", "payload": "hidden"}},
        ):
            record = {**safe_license, **extra}
            with self.subTest(extra=extra):
                self.assertFalse(validator.is_valid(record))
                with self.assertRaises(ValueError):
                    artifacts.validate_artifact_record(record)

    def test_artifact_preserves_safe_business_metadata_but_projects_coordinator_fields(self):
        """Catches safety hardening deleting business fields or resume leaking them."""
        artifact = {
            "artifact_id": "license-v1",
            "type": "license-document",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "artifacts/licenses/source.json",
            "license": {
                "owner": "Example Studio",
                "territories": ["global"],
                "expires": None,
            },
            "checksum": "0123456789abcdef",
        }
        path = create_artifact(self.root, artifact)
        self.assertEqual(artifact, json.loads(path.read_text(encoding="utf-8")))

        projection = artifacts.coordinator_safe_artifact_projection(artifact)

        self.assertEqual("license-v1", projection["artifact_id"])
        self.assertEqual("artifacts/licenses/source.json", projection["path"])
        self.assertEqual("0123456789abcdef", projection["checksum"])
        self.assertNotIn("license", projection)

    def test_tampered_artifact_payload_is_rejected_on_read(self):
        """Catches read/recovery paths trusting unsafe extras written out of band."""
        artifact = {
            **self.artifact,
            "artifact_id": "tampered-v1",
            "path": "previews/tampered-v1.html",
        }
        path = create_artifact(self.root, artifact)
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["metadata"] = {"thumbnail": "inline"}
        path.write_text(json.dumps(tampered), encoding="utf-8")

        self.assertIsNone(artifacts._read_valid_artifact(path))

    def test_artifact_rejects_structural_encodings_at_create_and_read(self):
        """Catches closed text and path carriers bypassing the shared payload scrub."""
        for carrier in ("path", "text"):
            for name, value in STRUCTURAL_ENCODING_CASES:
                with self.subTest(carrier=carrier, name=name):
                    record = {
                        **self.artifact,
                        "artifact_id": f"create-{carrier}-{name}",
                        "path": f"metadata/create-{carrier}-{name}.json",
                        carrier: value,
                    }
                    with self.assertRaisesRegex(ValueError, "Base64|binary"):
                        create_artifact(self.root, record)

                    stored = create_artifact(
                        self.root,
                        {
                            **self.artifact,
                            "artifact_id": f"read-{carrier}-{name}",
                            "path": f"metadata/read-{carrier}-{name}.json",
                        },
                    )
                    tampered = json.loads(stored.read_text(encoding="utf-8"))
                    tampered[carrier] = value
                    stored.write_text(json.dumps(tampered), encoding="utf-8")
                    self.assertIsNone(artifacts._read_valid_artifact(stored))

        for index, (name, prose) in enumerate(HARMLESS_PROSE_CONTROLS):
            safe_control = {
                **self.artifact,
                "artifact_id": (
                    TYPED_SAFE_ID_CONTROL
                    if index == 0
                    else f"safe-prose-v{index + 1}"
                ),
                "path": f"metadata/encoding-boundary-safe-{index}.json",
                "text": prose,
                "checksum": TYPED_CHECKSUM_CONTROL,
            }
            with self.subTest(control=name):
                stored = create_artifact(self.root, safe_control)
                self.assertEqual(
                    safe_control, artifacts._read_valid_artifact(stored)
                )

    def test_artifact_schema_rejects_unsafe_project_paths(self):
        """Catches schema consumers accepting paths the runtime must reject."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references/schemas/artifact.schema.json"
            ).read_text(encoding="utf-8")
        )
        path_schema = schema["properties"]["path"]
        self.assertIn("pattern", path_schema)
        pattern = path_schema["pattern"]

        for unsafe in (
            "../outside.json",
            "/tmp/outside.json",
            "..\\outside.json",
            "C:/outside.json",
            ".",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertIsNone(re.search(pattern, unsafe))
        for valid in ("media/scene-S01.png", "timeline/editable.project"):
            with self.subTest(valid=valid):
                self.assertIsNotNone(re.search(pattern, valid))

    def test_artifact_schema_and_runtime_share_id_mime_and_path_bounds(self):
        """Catches Artifact validation drifting from its Draft 2020-12 schema."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references/schemas/artifact.schema.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        valid = {
            "artifact_id": "license-v1",
            "type": "license-document",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "artifacts/licenses/source.json",
            "mime_type": "text/plain",
            "media_kind": "document",
            "format": "txt",
            "width": 1920,
            "height": 1080,
            "duration_ms": 0,
            "fps": 24,
            "file_size": 1024,
            "size_bytes": 1024,
            "checksum": "0123456789abcdef",
            "readiness": "ready",
            "license": {"owner": "Example Studio"},
        }
        cases = (
            (valid, True),
            ({**valid, "artifact_id": "a" * 129}, False),
            ({**valid, "type": "t" * 129}, False),
            ({**valid, "parents": ["p" * 129]}, False),
            ({**valid, "mime_type": " image/png"}, False),
            ({**valid, "media_kind": "visual"}, False),
            ({**valid, "path": "s3://bucket/source.json"}, False),
            ({**valid, "format": ""}, False),
            ({**valid, "width": 0}, False),
            ({**valid, "height": True}, False),
            ({**valid, "duration_ms": 36_000_001}, False),
            ({**valid, "fps": float("inf")}, False),
            ({**valid, "file_size": -1}, False),
            ({**valid, "size_bytes": 1_099_511_627_777}, False),
            ({**valid, "checksum": "not-hex!!"}, False),
            ({**valid, "readiness": "r" * 65}, False),
        )
        for record, expected in cases:
            runtime_valid = True
            try:
                artifacts.validate_artifact_record(record)
            except ValueError:
                runtime_valid = False
            with self.subTest(record=record):
                self.assertEqual(expected, validator.is_valid(record))
                self.assertEqual(expected, runtime_valid)

    def test_artifact_schema_and_runtime_match_closed_promotion_metadata(self):
        """Catches nested promotion and lexical path parity drift."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references/schemas/artifact.schema.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        base = {
            "artifact_id": "promotion-v1",
            "type": "promoted-asset",
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": "artifacts/promotion-v1.json",
        }
        cases = (
            (
                {
                    **base,
                    "promotion": {
                        "action": "",
                        "applicability": [""],
                        "validation_evidence": ["", {}],
                    },
                },
                True,
            ),
            (
                {**base, "promotion": {"validation_evidence": ["same", "same"]}},
                False,
            ),
            (
                {**base, "promotion": {"validation_evidence": [{}, {}]}},
                False,
            ),
            (
                {
                    **base,
                    "promotion": {"validation_evidence": [{"unexpected": "value"}]},
                },
                False,
            ),
            ({**base, "path": "."}, False),
            ({**base, "path": "artifacts/./promotion-v1.json"}, False),
            ({**base, "artifact_id": "gopher:opaque-resource"}, False),
            (
                {
                    **base,
                    "promotion": {
                        "provenance": {"artifact_id": "gopher:opaque-resource"}
                    },
                },
                False,
            ),
            (
                {
                    **base,
                    "promotion": {
                        "provenance": {"project_id": "gopher:opaque-resource"}
                    },
                },
                False,
            ),
        )
        for record, expected in cases:
            runtime_valid = True
            try:
                artifacts.validate_artifact_record(record)
            except ValueError:
                runtime_valid = False
            with self.subTest(record=record):
                self.assertEqual(expected, validator.is_valid(record))
                self.assertEqual(expected, runtime_valid)

    def test_colon_free_ids_keep_explicit_provenance_namespaces(self):
        """Catches generic IDs reopening URI syntax or losing approved provenance."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references/schemas/artifact.schema.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        record = {
            "artifact_id": "artifact-v1",
            "type": "report",
            "version": 1,
            "status": "approved",
            "parents": ["parent-v1"],
            "path": "artifacts/artifact-v1.json",
            "consent_provenance": "user:consent-v1",
            "decision_provenance": "user:decision-v1",
            "identity_provenance": "user:identity-v1",
            "profile_provenance": "user:profile-v1",
            "provenance": "chatcut:voice",
            "promotion": {
                "provenance": {
                    "artifact_id": "source-v1",
                    "project_id": "project-v1",
                }
            },
        }
        self.assertTrue(validator.is_valid(record))
        artifacts.validate_artifact_record(record)

    def test_artifact_keeps_evidence_backed_explicit_scheme_tokens(self):
        """Catches the coordinator scrub rejecting documented uploaded/inspection metadata."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references/schemas/artifact.schema.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        record = {
            "artifact_id": "uploaded-voice-v2",
            "type": "voiceover",
            "version": 1,
            "status": "approved",
            "parents": ["upload-v2"],
            "path": "artifacts/uploaded-voice-v2.json",
            "provenance": "user-upload:upload-v2",
            "promotion": {
                "validation_evidence": [
                    "isolated-image-inspect:alpha-transparency-present"
                ]
            },
        }

        self.assertTrue(validator.is_valid(record))
        artifacts.validate_artifact_record(record)

        for key, value in (
            ("provenance", "gopher:upload-v2"),
            ("validation_evidence", ["gopher:alpha-transparency-present"]),
        ):
            unsafe = {
                **record,
                "promotion": dict(record["promotion"]),
            }
            if key == "provenance":
                unsafe[key] = value
            else:
                unsafe["promotion"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                artifacts.validate_artifact_record(unsafe)

    def test_serialization_failure_leaves_no_artifact_and_retry_succeeds(self):
        """Catches a failed JSON write reserving an ID or publishing a partial file."""
        invalid = {**self.artifact, "custom_metadata": object()}

        with self.assertRaisesRegex(ValueError, "JSON metadata"):
            create_artifact(self.root, invalid)

        self.assertFalse((self.root / "artifacts" / "style-pack" / "style-v1.json").exists())
        self.assertEqual(
            self.root / "artifacts" / "style-pack" / "style-v1.json",
            create_artifact(self.root, self.artifact),
        )

    def test_corrupt_metadata_is_not_a_valid_approval_target(self):
        """Catches filename-only target checks accepting corrupt artifact metadata."""
        corrupt = self.root / "artifacts" / "style-pack" / "style-v1.json"
        corrupt.parent.mkdir(parents=True)
        corrupt.write_text("{not json", encoding="utf-8")

        with self.assertRaises(ValueError):
            approve_artifact(self.root, "style-v1", "whole-project", "approved")

    def test_approval_is_persisted_as_artifact(self):
        """Catches an approval that is returned but not durably recorded."""
        create_artifact(self.root, self.artifact)

        approval_id = approve_artifact(self.root, "style-v1", "whole-project", "approved")
        approval_path = self.root / "approvals" / f"{approval_id}.json"

        self.assertTrue(approval_path.is_file())
        self.assertEqual(
            {
                "approval_id": approval_id,
                "target_id": "style-v1",
                "scope": "whole-project",
                "decision": "approved",
                "notes": "approved",
            },
            json.loads(approval_path.read_text(encoding="utf-8")),
        )

    def test_approval_persists_the_explicit_gate_decision(self):
        """Catches delegated or skipped gates being indistinguishable from approval."""
        create_artifact(self.root, self.artifact)

        for decision in ("delegated", "skipped"):
            with self.subTest(decision=decision):
                approval_id = approve_artifact(
                    self.root,
                    "style-v1",
                    "whole-project",
                    f"user {decision} the gate",
                    decision=decision,
                )

                approval = json.loads(
                    (self.root / "approvals" / f"{approval_id}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(decision, approval["decision"])

    def test_approval_rejects_an_unknown_gate_decision(self):
        """Catches records that violate the persisted approval decision enum."""
        create_artifact(self.root, self.artifact)

        with self.assertRaises(ValueError):
            approve_artifact(
                self.root,
                "style-v1",
                "whole-project",
                "not a durable gate outcome",
                decision="pending",
            )

        with self.assertRaises(ValueError):
            approve_artifact(
                self.root,
                "style-v1",
                "whole-project",
                "not a schema decision",
                decision=["approved"],
            )

    def test_resume_normalizes_legacy_approval_without_rewriting_history(self):
        """Catches a new schema making an existing approval unreadable on resume."""
        source = FIXTURES / "approvals" / "approval-legacy.json"
        approval_path = self.root / "approvals" / "approval-legacy.json"
        approval_path.parent.mkdir()
        raw = source.read_text(encoding="utf-8")
        approval_path.write_text(raw, encoding="utf-8")

        normalized = read_approval(self.root, "approval-legacy")

        self.assertEqual(
            {
                "approval_id": "approval-legacy",
                "target_id": "style-v1",
                "scope": "whole-project",
                "decision": "approved",
                "notes": "approved before decision values existed",
            },
            normalized,
        )
        self.assertEqual(set(artifacts.APPROVAL_REQUIRED_KEYS), set(normalized))
        schema = json.loads(
            (Path(__file__).parents[1] / "references/schemas/approval.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(set(schema["required"]).issubset(normalized))
        self.assertTrue(set(normalized).issubset(schema["properties"]))
        self.assertIn(normalized["decision"], schema["properties"]["decision"]["enum"])
        self.assertEqual(raw, approval_path.read_text(encoding="utf-8"))

    def test_resume_rejects_an_invalid_current_approval_decision(self):
        """Catches read normalization accepting values outside the approval schema."""
        approval_path = self.root / "approvals" / "approval-invalid.json"
        approval_path.parent.mkdir()
        approval_path.write_text(
            json.dumps(
                {
                    "approval_id": "approval-invalid",
                    "target_id": "style-v1",
                    "scope": "whole-project",
                    "decision": ["approved"],
                    "notes": "malformed current record",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            read_approval(self.root, "approval-invalid")

    def test_approval_serialization_failure_leaves_no_partial_file(self):
        """Catches approval publication beginning before its JSON is complete."""
        create_artifact(self.root, self.artifact)

        with patch(
            "scripts.toolkit.artifacts._serialize_json",
            side_effect=TypeError("bad JSON"),
        ):
            with self.assertRaises(TypeError):
                approve_artifact(self.root, "style-v1", "whole-project", "approved")

        approvals = self.root / "approvals"
        self.assertFalse(approvals.exists())

    def test_concurrent_cross_type_writes_allow_only_one_artifact_id(self):
        """Catches a check-then-write race allowing duplicate IDs across types."""
        barrier = Barrier(2)

        def create(artifact_type):
            barrier.wait()
            try:
                return create_artifact(self.root, {**self.artifact, "type": artifact_type})
            except FileExistsError:
                return "exists"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, ("style-pack", "layout-pack")))

        self.assertEqual(1, sum(result == "exists" for result in results))
        self.assertEqual(1, sum(isinstance(result, Path) for result in results))

    def test_successful_artifact_creation_leaves_no_lock(self):
        """Catches a transient acquisition lock becoming durable project state."""
        create_artifact(self.root, self.artifact)

        self.assertFalse((self.root / "artifacts" / ".locks" / "style-v1.json").exists())

    def test_keyboard_interrupt_during_publication_releases_lock(self):
        """Catches interruption leaving a lock that permanently blocks retries."""
        publish_json = artifacts._publish_json

        def interrupt_artifact_publication(destination, payload):
            if destination.parent.name == ".locks":
                return publish_json(destination, payload)
            raise KeyboardInterrupt

        with patch(
            "scripts.toolkit.artifacts._publish_json", side_effect=interrupt_artifact_publication
        ):
            with self.assertRaises(KeyboardInterrupt):
                create_artifact(self.root, self.artifact)

        self.assertFalse((self.root / "artifacts" / ".locks" / "style-v1.json").exists())
        create_artifact(self.root, self.artifact)

    def test_keyboard_interrupt_during_published_lock_retry_allows_retry(self):
        """Catches interruption during flock retry leaving the creator's live lock."""
        lock = self.root / "artifacts" / ".locks" / "style-v1.json"

        with patch(
            "scripts.toolkit.artifacts._hold_lock", side_effect=BlockingIOError
        ), patch(
            "scripts.toolkit.artifacts.time.sleep", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                create_artifact(self.root, self.artifact)

        self.assertEqual(
            self.root / "artifacts" / "style-pack" / "style-v1.json",
            create_artifact(self.root, self.artifact),
        )
        self.assertFalse(lock.exists())

    def test_interrupted_lock_retry_preserves_replacement_owner(self):
        """Catches failed-acquisition cleanup unlinking a replacement live lock."""
        lock = self.root / "artifacts" / ".locks" / "style-v1.json"
        replacement = lock.with_name("replacement.json")
        replacement_owner = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "owner_token": "replacement-owner",
        }

        def replace_lock_then_interrupt(_delay):
            artifacts._publish_json(
                replacement, artifacts._serialize_json(replacement_owner)
            )
            os.replace(replacement, lock)
            raise KeyboardInterrupt

        with patch(
            "scripts.toolkit.artifacts._hold_lock", side_effect=BlockingIOError
        ), patch(
            "scripts.toolkit.artifacts.time.sleep",
            side_effect=replace_lock_then_interrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                create_artifact(self.root, self.artifact)

        self.assertEqual(
            replacement_owner, json.loads(lock.read_text(encoding="utf-8"))
        )
        lock.unlink()

    def test_dead_pid_lock_is_reclaimed_for_retry(self):
        """Catches a crashed process permanently reserving an unpublished artifact ID."""
        lock = self.root / "artifacts" / ".locks" / "style-v1.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"pid": 999999, "timestamp": time.time()}), encoding="utf-8")

        with patch("scripts.toolkit.artifacts._pid_is_alive", return_value=False):
            create_artifact(self.root, self.artifact)

        self.assertFalse(lock.exists())

    def test_live_pid_lock_refuses_concurrent_writer(self):
        """Catches a live writer's lock being reclaimed by a concurrent create."""
        lock = self.root / "artifacts" / ".locks" / "style-v1.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"pid": os.getpid(), "timestamp": time.time()}), encoding="utf-8")

        with self.assertRaises(FileExistsError):
            create_artifact(self.root, self.artifact)

    def test_creator_waits_for_contender_in_publish_to_flock_gap(self):
        """Catches a creator abandoning its live-PID lock before it can hold the inode."""
        lock = self.root / "artifacts" / ".locks" / "style-v1.json"
        publish_json = artifacts._publish_json
        hold_lock = artifacts._hold_lock
        lock_published = Event()
        contender_holds_lock = Event()
        creator_encountered_contention = Event()
        release_contender = Event()

        def publish_then_wait_for_contender(destination, payload):
            result = publish_json(destination, payload)
            if destination == lock:
                lock_published.set()
                self.assertTrue(contender_holds_lock.wait(timeout=1))
            return result

        def observe_creator_hold(path, *args, **kwargs):
            if contender_holds_lock.is_set() and not release_contender.is_set():
                creator_encountered_contention.set()
                raise BlockingIOError
            return hold_lock(path, *args, **kwargs)

        def hold_creator_lock_as_contender():
            self.assertTrue(lock_published.wait(timeout=1))
            guard = hold_lock(lock)
            contender_holds_lock.set()
            try:
                self.assertTrue(release_contender.wait(timeout=1))
            finally:
                os.close(guard[1])

        with ThreadPoolExecutor(max_workers=2) as executor:
            contender = executor.submit(hold_creator_lock_as_contender)
            try:
                with patch(
                    "scripts.toolkit.artifacts._publish_json",
                    side_effect=publish_then_wait_for_contender,
                ), patch(
                    "scripts.toolkit.artifacts._hold_lock",
                    side_effect=observe_creator_hold,
                ):
                    creation = executor.submit(create_artifact, self.root, self.artifact)
                    self.assertTrue(creator_encountered_contention.wait(timeout=1))
                    release_contender.set()
                    self.assertEqual(
                        self.root / "artifacts" / "style-pack" / "style-v1.json",
                        creation.result(timeout=1),
                    )
            finally:
                release_contender.set()
                contender.result(timeout=1)

        self.assertFalse(lock.exists())

    def test_post_lock_scan_rejects_artifact_published_in_another_type(self):
        """Catches a cross-type artifact appearing between the scan and lock acquisition."""
        acquire_lock = artifacts._acquire_artifact_lock
        lock_acquired = Event()
        artifact_published = Event()

        def acquire_then_wait_for_competing_write(artifacts_root, artifact_id):
            lock = acquire_lock(artifacts_root, artifact_id)
            lock_acquired.set()
            self.assertTrue(artifact_published.wait(timeout=1))
            return lock

        def publish_competing_artifact():
            self.assertTrue(lock_acquired.wait(timeout=1))
            published = {**self.artifact, "type": "layout-pack"}
            path = self.root / "artifacts" / "layout-pack" / "style-v1.json"
            artifacts._publish_json(path, artifacts._serialize_json(published))
            artifact_published.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch(
                "scripts.toolkit.artifacts._acquire_artifact_lock",
                side_effect=acquire_then_wait_for_competing_write,
            ):
                competing_write = executor.submit(publish_competing_artifact)
                with self.assertRaises(FileExistsError):
                    create_artifact(self.root, self.artifact)
            competing_write.result()

        self.assertFalse((self.root / "artifacts" / ".locks" / "style-v1.json").exists())

    def test_competing_reclaimers_do_not_remove_a_new_live_lock(self):
        """Catches one dead-lock reclaimer unlinking another reclaimer's new lock."""
        lock = self.root / "artifacts" / ".locks" / "style-v1.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"pid": 999999, "timestamp": time.time()}), encoding="utf-8")
        barrier = Barrier(2)

        def acquire():
            barrier.wait()
            try:
                return artifacts._acquire_artifact_lock(self.root / "artifacts", "style-v1")
            except FileExistsError:
                return "locked"

        with patch("scripts.toolkit.artifacts._pid_is_alive", return_value=False):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: acquire(), range(2)))

        handles = [result for result in results if result != "locked"]
        self.assertEqual(1, len(handles))
        self.assertEqual(1, results.count("locked"))
        artifacts._release_artifact_lock(handles[0])

    def test_releasing_displaced_lock_does_not_remove_replacement_lock(self):
        """Catches a stale lock handle deleting a replacement writer's live lock."""
        handle = artifacts._acquire_artifact_lock(self.root / "artifacts", "style-v1")
        lock = handle[0]
        replacement = lock.with_name("replacement.json")
        artifacts._publish_json(
            replacement, json.dumps({"pid": os.getpid(), "timestamp": time.time()})
        )
        os.replace(replacement, lock)

        artifacts._release_artifact_lock(handle)

        self.assertTrue(lock.exists())
        self.assertEqual(
            os.getpid(), json.loads(lock.read_text(encoding="utf-8"))["pid"]
        )
        lock.unlink()


if __name__ == "__main__":
    unittest.main()

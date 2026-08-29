import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import scripts.validate_package as package_validation
from scripts.validate_package import validate_package
from scripts.toolkit.tasks import (
    _validate_persisted_envelope,
    _validate_result,
    validate_current_task_envelope,
)
from scripts.toolkit.visual_media_context import (
    validate_compact_visual_media_handoff,
    validate_result_envelope,
)


ROOT = Path(__file__).parents[1]


class PackageTests(unittest.TestCase):
    def task_envelope_validator(self):
        schema_root = ROOT / "references" / "schemas"
        envelope_path = schema_root / "task-envelope.schema.json"
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        envelope["$id"] = envelope_path.as_uri()
        registry = Registry()
        for name in (
            "image-task-context.schema.json",
            "visual-media-task-context.schema.json",
        ):
            path = schema_root / name
            resource = Resource.from_contents(
                json.loads(path.read_text(encoding="utf-8"))
            )
            registry = registry.with_resource(path.as_uri(), resource)
        return Draft202012Validator(envelope, registry=registry)

    def task_result_validator(self):
        schema = json.loads(
            (ROOT / "references/schemas/task-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        return Draft202012Validator(schema)

    def copy_package(self, folder):
        package = Path(folder) / "package"
        shutil.copytree(
            ROOT,
            package,
            ignore=shutil.ignore_patterns(
                ".git", ".worktrees", ".superpowers", "__pycache__", "*.pyc"
            ),
        )
        return package

    def refresh_release_fingerprint(self, package):
        manifest_path = package / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["release_fingerprint"] = package_validation._release_fingerprint(
            package
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_visual_media_schema_is_closed_and_bounded(self):
        """Catches a visual-media task context that expands beyond its isolated scope."""
        schema = json.loads(
            (ROOT / "references/schemas/visual-media-task-context.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            [
                "scene-contract",
                "character-asset-batch",
                "review-batch",
            ],
            schema["properties"]["scope_identity"]["properties"]["kind"]["enum"],
        )
        self.assertEqual("character-only", schema["properties"]["historical_access"]["const"])
        self.assertEqual(1, schema["properties"]["max_review_previews"]["maximum"])
        self.assertEqual(32768, schema["properties"]["context_budget_bytes"]["maximum"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            [
                "scope_identity",
                "allowed_artifact_ids",
                "historical_access",
                "continuity_exception",
                "max_review_previews",
                "context_budget_bytes",
            ],
            schema["required"],
        )

    def test_task_envelope_declares_exact_visual_media_operations(self):
        """Catches envelope operations that omit or broaden the visual-media context gate."""
        envelope = json.loads(
            (ROOT / "references/schemas/task-envelope.schema.json").read_text(
                encoding="utf-8"
            )
        )
        operations = envelope["properties"]["constraints"]["properties"][
            "visual_media_operation"
        ]["enum"]
        self.assertEqual(
            [
                "none",
                "image-generate",
                "image-edit",
                "image-inspect",
                "video-generate",
                "video-edit",
                "video-render",
                "video-inspect",
                "frame-extract",
                "contact-sheet",
            ],
            operations,
        )
        conditionals = envelope["properties"]["constraints"]["allOf"]
        self.assertIn(
            {
                "if": {
                    "properties": {"visual_media_operation": {"const": "none"}},
                    "required": ["visual_media_operation"],
                },
                "then": {"not": {"required": ["visual_media_context"]}},
            },
            conditionals,
        )
        structure_rule = next(
            rule
            for rule in envelope["allOf"]
            if rule["if"].get("properties", {}).get("capability")
            == {"const": "structure.validate"}
        )
        self.assertEqual(
            {
                "oneOf": [
                    {
                        "required": ["visual_media_operation"],
                        "properties": {
                            "visual_media_operation": {
                                "enum": ["none", "image-inspect"]
                            }
                        },
                        "not": {
                            "anyOf": [
                                {"required": ["image_operation"]},
                                {"required": ["image_context"]},
                            ]
                        },
                    },
                    {
                        "required": ["image_operation"],
                        "properties": {
                            "image_operation": {
                                "enum": ["structure-only", "image-inspect"]
                            }
                        },
                        "not": {
                            "anyOf": [
                                {"required": ["visual_media_operation"]},
                                {"required": ["visual_media_context"]},
                            ]
                        },
                    },
                ]
            },
            structure_rule["then"]["properties"]["constraints"],
        )
        self.assertIn(
            {
                "if": {
                    "properties": {
                        "visual_media_operation": {
                            "enum": operations[1:],
                        }
                    },
                    "required": ["visual_media_operation"],
                },
                "then": {
                    "required": ["visual_media_context", "execution_context"],
                    "properties": {
                        "execution_context": {"const": "isolated-child-agent"}
                    },
                },
            },
            conditionals,
        )

    def test_structure_validation_schema_accepts_current_and_persisted_legacy_only(self):
        """Catches the structure conditional dropping legacy reads or broadening authority."""
        validator = self.task_envelope_validator()
        base = {
            "task_id": "structure-schema-case",
            "capability": "structure.validate",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "validation-report-v1",
        }
        visual_context = {
            "scope_identity": {"kind": "scene-contract", "id": "scene-S01"},
            "allowed_artifact_ids": [],
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 0,
            "context_budget_bytes": 1024,
        }
        image_context = {
            "scope_identity": {"kind": "scene-contract", "id": "scene-S01"},
            "allowed_image_artifact_ids": [],
            "allowed_character_pack_ids": [],
            "forbidden_scene_image_access": True,
            "max_review_previews": 0,
            "context_budget": 1024,
        }
        valid_constraints = (
            {"visual_media_operation": "none"},
            {
                "visual_media_operation": "image-inspect",
                "visual_media_context": visual_context,
                "execution_context": "isolated-child-agent",
            },
            {"image_operation": "structure-only"},
            {"image_operation": "image-inspect", "image_context": image_context},
        )
        for index, constraints in enumerate(valid_constraints, 1):
            with self.subTest(valid=index):
                validator.validate({**base, "constraints": constraints})

        invalid_constraints = (
            {},
            {
                "visual_media_operation": "video-inspect",
                "visual_media_context": visual_context,
            },
            {"image_operation": "generate", "image_context": image_context},
            {
                "visual_media_operation": "none",
                "image_operation": "structure-only",
            },
        )
        for index, constraints in enumerate(invalid_constraints, 1):
            with self.subTest(invalid=index):
                self.assertFalse(
                    validator.is_valid({**base, "constraints": constraints})
                )

    def test_scene_schema_accepts_current_and_persisted_legacy_only(self):
        """Catches schema/runtime drift or mixed scene authority becoming valid."""
        validator = self.task_envelope_validator()
        base = {
            "task_id": "scene-schema-case",
            "capability": "scene.produce",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "scene-image-v1",
        }
        visual_context = {
            "scope_identity": {"kind": "scene-contract", "id": "scene-S01"},
            "allowed_artifact_ids": [],
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 0,
            "context_budget_bytes": 1024,
        }
        image_context = {
            "scope_identity": {"kind": "scene-contract", "id": "scene-S01"},
            "allowed_image_artifact_ids": [],
            "allowed_character_pack_ids": [],
            "forbidden_scene_image_access": True,
            "max_review_previews": 0,
            "context_budget": 1024,
        }
        current = {
            **base,
            "constraints": {
                "visual_media_operation": "image-generate",
                "visual_media_context": visual_context,
                "execution_context": "isolated-child-agent",
            },
        }
        persisted_legacy = {
            **base,
            "constraints": {
                "visual_operation": "image-generation",
                "image_operation": "generate",
                "image_context": image_context,
            },
        }
        validate_current_task_envelope(current)
        _validate_persisted_envelope(persisted_legacy)
        validator.validate(current)
        validator.validate(persisted_legacy)

        invalid_constraints = (
            {},
            {
                "visual_media_operation": "image-generate",
                "visual_media_context": visual_context,
                "visual_operation": "non-image",
            },
            {
                "visual_media_operation": "image-generate",
                "visual_media_context": visual_context,
                "image_operation": "generate",
                "image_context": image_context,
            },
            {
                "visual_operation": "non-image",
                "visual_media_operation": "none",
            },
        )
        for index, constraints in enumerate(invalid_constraints, 1):
            with self.subTest(invalid=index):
                self.assertFalse(
                    validator.is_valid({**base, "constraints": constraints})
                )

    def test_task_result_visual_media_handoff_uses_one_review_preview_path(self):
        """Catches result handoffs reopening visual-media fields or preview fan-out."""
        schema = json.loads(
            (ROOT / "references/schemas/task-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        handoff = schema["properties"]["visual_media_handoff"]

        self.assertEqual(
            [
                "artifact_ids",
                "paths",
                "media",
                "checks",
                "issues",
                "summary",
                "review_preview_path",
            ],
            list(handoff["properties"]),
        )
        self.assertFalse(handoff["additionalProperties"])
        self.assertEqual(
            [
                {"type": "null"},
                {
                    "allOf": [
                        {"$ref": "#/$defs/previewPath"},
                        {
                            "maxLength": 256,
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9._/-]*$",
                        },
                    ]
                },
            ],
            handoff["properties"]["review_preview_path"]["anyOf"],
        )
        self.assertTrue(schema["properties"]["image_handoff"]["deprecated"])

    def test_draft202012_schema_and_runtime_match_active_execution_and_preview_null(self):
        """Catches schema/runtime drift in both acceptance directions."""
        envelope_validator = self.task_envelope_validator()
        context = {
            "scope_identity": {
                "kind": "scene-contract",
                "id": "scene-contract-S03-v2",
            },
            "allowed_artifact_ids": [],
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 1,
            "context_budget_bytes": 32_768,
        }
        base_envelope = {
            "task_id": "render-S03-v1",
            "capability": "scene.produce",
            "inputs": ["scene-contract-S03-v2"],
            "adapter_preferences": ["chatcut"],
            "output_contract": "scene-video-v1",
            "constraints": {
                "visual_media_operation": "video-render",
                "visual_media_context": context,
                "execution_context": "isolated-child-agent",
            },
        }
        envelope_cases = (
            (base_envelope, True),
            (
                {
                    **base_envelope,
                    "constraints": {
                        key: value
                        for key, value in base_envelope["constraints"].items()
                        if key != "execution_context"
                    },
                },
                False,
            ),
            (
                {
                    **base_envelope,
                    "constraints": {
                        **base_envelope["constraints"],
                        "execution_context": "primary-coordinator",
                    },
                },
                False,
            ),
        )
        for envelope, expected in envelope_cases:
            runtime_valid = True
            try:
                validate_current_task_envelope(envelope)
            except ValueError:
                runtime_valid = False
            with self.subTest(envelope=envelope):
                self.assertEqual(expected, envelope_validator.is_valid(envelope))
                self.assertEqual(expected, runtime_valid)

        handoff = {
            "artifact_ids": ["media-S03-v4"],
            "paths": ["media/media-S03-v4.mp4"],
            "media": {"kind": "video", "mime_type": "video/mp4"},
            "checks": [],
            "issues": [],
            "summary": "Ready for user review.",
            "review_preview_path": None,
        }
        result = {
            "task_id": "render-S03-v1",
            "status": "waiting_user",
            "inputs": ["scene-contract-S03-v2"],
            "artifacts": ["media-S03-v4"],
            "checks": [],
            "warnings": [],
            "worker_id": "worker-1",
            "claim_token": "claim-1",
            "visual_media_handoff": handoff,
        }
        self.assertTrue(self.task_result_validator().is_valid(result))
        self.assertEqual(handoff, validate_compact_visual_media_handoff(handoff))

    def test_draft202012_and_runtime_reject_mixed_authority_for_every_visual_capability(self):
        """Catches non-scene visual routes bypassing current/legacy exclusivity."""
        validator = self.task_envelope_validator()
        context = {
            "scope_identity": {"kind": "scene-contract", "id": "scene-S01"},
            "allowed_artifact_ids": [],
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 0,
            "context_budget_bytes": 1024,
        }
        operations = {
            "visual.preview": "image-generate",
            "scene.produce": "image-generate",
            "motion.preview": "video-generate",
            "motion.produce": "video-render",
            "timeline.assemble": "video-edit",
            "review.package": "video-inspect",
            "structure.validate": "image-inspect",
        }
        for capability, operation in operations.items():
            current = {
                "task_id": capability.replace(".", "-") + "-v1",
                "capability": capability,
                "inputs": [],
                "adapter_preferences": ["chatcut"],
                "output_contract": "visual-report-v1",
                "constraints": {
                    "visual_media_operation": operation,
                    "visual_media_context": context,
                    "execution_context": "isolated-child-agent",
                },
            }
            mixed = {
                **current,
                "constraints": {
                    **current["constraints"],
                    "image_operation": "structure-only",
                },
            }
            with self.subTest(capability=capability, current=True):
                self.assertTrue(validator.is_valid(current))
                validate_current_task_envelope(current)
            with self.subTest(capability=capability, current=False):
                self.assertFalse(validator.is_valid(mixed))
                with self.assertRaises(ValueError):
                    validate_current_task_envelope(mixed)

        persisted_legacy = {
            "task_id": "legacy-scene-v1",
            "capability": "scene.produce",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "scene-image-v1",
            "constraints": {
                "visual_operation": "non-image",
                "image_operation": "structure-only",
            },
        }
        self.assertTrue(validator.is_valid(persisted_legacy))
        _validate_persisted_envelope(persisted_legacy)
        with self.assertRaisesRegex(ValueError, "read-only"):
            validate_current_task_envelope(persisted_legacy)

    def test_draft202012_and_runtime_match_handoff_mime_kind_decisions(self):
        """Catches the result schema accepting MIME/kind pairs runtime rejects."""
        validator = self.task_result_validator()
        base_handoff = {
            "artifact_ids": ["media-v1"],
            "paths": ["media/media-v1.bin"],
            "checks": [],
            "issues": [],
            "summary": "Structural result ready.",
            "review_preview_path": None,
        }
        cases = (
            ({"kind": "image", "mime_type": "image/png"}, True),
            ({"kind": "video", "mime_type": "video/mp4"}, True),
            ({"kind": "visual", "mime_type": "image/png"}, True),
            ({"mime_type": "image/png"}, True),
            ({"kind": "image", "mime_type": "video/mp4"}, False),
            ({"kind": "video", "mime_type": "image/png"}, False),
            ({"mime_type": "audio/wav"}, False),
            ({"kind": "visual", "mime_type": "audio/wav"}, False),
            ({"kind": "image", "mime_type": "audio/wav"}, False),
        )
        for media, expected in cases:
            handoff = {**base_handoff, "media": media}
            result = {
                "task_id": "mime-parity-v1",
                "status": "succeeded",
                "inputs": [],
                "artifacts": ["media-v1"],
                "checks": [],
                "warnings": [],
                "worker_id": "worker-v1",
                "claim_token": "claim-v1",
                "visual_media_handoff": handoff,
            }
            runtime_valid = True
            try:
                validate_compact_visual_media_handoff(handoff)
            except ValueError:
                runtime_valid = False
            with self.subTest(media=media):
                self.assertEqual(expected, validator.is_valid(result))
                self.assertEqual(expected, runtime_valid)

    def test_generic_task_and_result_ids_are_colon_free(self):
        """Catches schema/runtime treating URI-like strings as generic identifiers."""
        envelope = {
            "task_id": "gopher:task-v1",
            "capability": "project.manage",
            "inputs": ["artifact-v1"],
            "adapter_preferences": ["chatcut"],
            "output_contract": "project-report-v1",
            "constraints": {"visual_media_operation": "none"},
        }
        self.assertFalse(self.task_envelope_validator().is_valid(envelope))
        with self.assertRaises(ValueError):
            validate_current_task_envelope(envelope)

        result = {
            "task_id": "task-v1",
            "status": "succeeded",
            "inputs": [],
            "artifacts": ["gopher:artifact-v1"],
            "checks": ["adapter-selected:chatcut"],
            "warnings": [],
            "worker_id": "worker-v1",
            "claim_token": "claim-v1",
        }
        self.assertFalse(self.task_result_validator().is_valid(result))
        with self.assertRaises(ValueError):
            validate_result_envelope(result)

        validate_result_envelope(
            {
                **result,
                "artifacts": ["artifact-v1"],
                "checks": ["adapter-selected:chatcut"],
            }
        )

    def test_task_result_worker_and_claim_ids_match_safe_id_contract(self):
        """Catches worker authority bypassing the bounded generic-ID boundary."""
        base = {
            "task_id": "task-v1",
            "status": "waiting_user",
            "inputs": [],
            "artifacts": [],
            "checks": [],
            "warnings": [],
            "worker_id": "worker-a",
            "claim_token": "0123456789abcdef0123456789abcdef",
        }
        cases = (
            ("worker_id", "worker-a", True),
            ("claim_token", "0123456789abcdef0123456789abcdef", True),
            ("worker_id", "gopher:worker", False),
            ("claim_token", "claim:token", False),
            ("worker_id", "worker/one", False),
            ("claim_token", "x" * 129, False),
        )
        validator = self.task_result_validator()
        for field, value, expected in cases:
            result = {**base, field: value}
            runtime_valid = True
            try:
                _validate_result(result)
            except ValueError:
                runtime_valid = False
            with self.subTest(field=field, value=value):
                self.assertEqual(expected, validator.is_valid(result))
                self.assertEqual(expected, runtime_valid)

    def test_visual_media_handoff_has_a_bounded_compact_result_shape(self):
        """Catches a visual-media result whose variable handoff fields exceed its budget."""
        schema = json.loads(
            (ROOT / "references/schemas/task-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        handoff = schema["properties"]["visual_media_handoff"]["properties"]

        for name in ("artifact_ids", "paths", "checks", "issues"):
            with self.subTest(name=name):
                self.assertEqual(8, handoff[name]["maxItems"])
        self.assertEqual(128, handoff["artifact_ids"]["items"]["maxLength"])
        self.assertEqual(256, handoff["paths"]["items"]["maxLength"])
        self.assertEqual(
            "^[A-Za-z0-9][A-Za-z0-9._/-]*$", handoff["paths"]["items"]["pattern"]
        )
        media = handoff["media"]
        self.assertEqual("object", media["type"])
        self.assertEqual(
            [
                "kind",
                "format",
                "mime_type",
                "width",
                "height",
                "duration_ms",
                "fps",
                "readiness",
                "checksum",
            ],
            list(media["properties"]),
        )
        self.assertFalse(media["additionalProperties"])
        self.assertEqual(
            {"type": "string", "enum": ["image", "video", "visual"]},
            media["properties"]["kind"],
        )
        for name in ("format", "readiness"):
            with self.subTest(name=name):
                self.assertEqual("string", media["properties"][name]["type"])
                self.assertEqual(64, media["properties"][name]["maxLength"])
        self.assertEqual(
            {
                "type": "string",
                "minLength": 7,
                "maxLength": 128,
                "pattern": "^(?:image|video)/[a-z0-9][a-z0-9!#$&^_.+-]*$",
            },
            media["properties"]["mime_type"],
        )
        self.assertEqual(
            {
                "type": "string",
                "minLength": 8,
                "maxLength": 128,
                "pattern": "^[A-Fa-f0-9]{8,128}$",
            },
            media["properties"]["checksum"],
        )
        self.assertEqual(
            {"type": "integer", "minimum": 1, "maximum": 16384},
            media["properties"]["width"],
        )
        self.assertEqual(
            {"type": "integer", "minimum": 1, "maximum": 16384},
            media["properties"]["height"],
        )
        self.assertEqual(
            {"type": "integer", "minimum": 0, "maximum": 36000000},
            media["properties"]["duration_ms"],
        )
        self.assertEqual(
            {"type": "number", "exclusiveMinimum": 0, "maximum": 240},
            media["properties"]["fps"],
        )
        self.assertEqual(64, handoff["checks"]["items"]["maxLength"])
        issue = handoff["issues"]["items"]["properties"]
        self.assertEqual(128, issue["code"]["maxLength"])
        self.assertEqual(128, issue["artifact_id"]["maxLength"])
        self.assertEqual(64, issue["message"]["maxLength"])
        self.assertEqual(64, issue["severity"]["maxLength"])
        self.assertEqual(64, handoff["summary"]["maxLength"])
        preview_string = handoff["review_preview_path"]["anyOf"][1]["allOf"][1]
        self.assertEqual(256, preview_string["maxLength"])
        self.assertEqual(
            "^[A-Za-z0-9][A-Za-z0-9._/-]*$",
            preview_string["pattern"],
        )

        high_codepoint = "\U0010ffff" * 63
        payload = {
            "artifact_ids": [f"a{'a' * 126}{index}" for index in range(8)],
            "paths": [f"artifacts/{'a' * 245}{index}" for index in range(8)],
            "media": {
                "kind": f"{high_codepoint}k",
                "format": f"{high_codepoint}f",
                "mime_type": "video/mp4",
                "width": 16384,
                "height": 16384,
                "duration_ms": 36000000,
                "fps": 240,
                "readiness": f"{high_codepoint}r",
                "checksum": "0123456789abcdef" * 4,
            },
            "checks": [f"{high_codepoint}{index}" for index in range(8)],
            "issues": [
                {
                    "code": f"c{'a' * 126}{index}",
                    "artifact_id": f"a{'a' * 126}{index}",
                    "message": f"{high_codepoint}{index}",
                    "severity": f"{high_codepoint}{index}",
                }
                for index in range(8)
            ],
            "summary": f"{high_codepoint}s",
            "review_preview_path": f"previews/{'a' * 246}x",
        }
        self.assertLess(
            len(json.dumps(payload, ensure_ascii=True).encode("utf-8")),
            32768,
        )

    def test_required_plugin_entrypoints_exist(self):
        self.assertEqual([], validate_package(ROOT))

    def test_visual_isolation_release_is_versioned_and_fingerprinted(self):
        """Catches a cache-reusing version or a release surface omitted from identity."""
        manifest = json.loads(
            (ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )

        self.assertEqual("0.1.4", manifest["version"])
        self.assertEqual("0.1.4", package_validation.PLUGIN_VERSION)
        self.assertRegex(
            manifest.get("release_fingerprint", ""), r"^sha256:[0-9a-f]{64}$"
        )
        self.assertIn(
            ".codex-plugin/plugin.json", package_validation.REQUIRED_FILES
        )
        self.assertIn("tests/test_artifacts.py", package_validation.REQUIRED_FILES)
        self.assertIn("scripts/migration_audit.py", package_validation.REQUIRED_FILES)

    def test_each_required_file_is_content_fingerprinted(self):
        """Catches any required release file being present but changed or deleted."""
        with TemporaryDirectory() as folder:
            package = self.copy_package(folder)
            for relative in package_validation.REQUIRED_FILES:
                path = package / relative
                original = path.read_bytes()
                with self.subTest(relative=relative, mutation="modified"):
                    if relative == ".codex-plugin/plugin.json":
                        manifest = json.loads(original)
                        manifest["description"] = "tampered release description"
                        path.write_text(json.dumps(manifest), encoding="utf-8")
                    else:
                        path.write_bytes(original + b"\nrelease-fingerprint-tamper\n")
                    self.assertIn("invalid:release-fingerprint", validate_package(package))
                path.write_bytes(original)
                with self.subTest(relative=relative, mutation="deleted"):
                    path.unlink()
                    self.assertIn(f"missing:{relative}", validate_package(package))
                path.write_bytes(original)

    def test_manifest_non_fingerprint_fields_participate_in_release_identity(self):
        """Catches manifest description drift hidden behind valid id/version fields."""
        with TemporaryDirectory() as folder:
            package = self.copy_package(folder)
            manifest_path = package / ".codex-plugin/plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["description"] = "changed without refreshing release identity"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertIn("invalid:release-fingerprint", validate_package(package))

    def test_weakened_visual_envelope_conditionals_fail_after_fingerprint_refresh(self):
        """Catches visual context or capability authority becoming optional."""
        cases = (
            (
                "none-context-ban",
                lambda envelope: envelope["properties"]["constraints"]["allOf"].pop(3),
                "invalid:visual-media-conditionals",
            ),
            (
                "active-context-requirement",
                lambda envelope: envelope["properties"]["constraints"]["allOf"][4][
                    "if"
                ]["properties"]["visual_media_operation"]["enum"].pop(),
                "invalid:visual-media-conditionals",
            ),
            (
                "legacy-scene-read-only-marker",
                lambda envelope: envelope["properties"]["constraints"][
                    "properties"
                ]["visual_operation"].pop("readOnly"),
                "invalid:legacy-visual-operation",
            ),
            (
                "scene-exclusive-branches",
                lambda envelope: envelope["allOf"][0]["then"]["properties"][
                    "constraints"
                ]["oneOf"][0].pop("not"),
                "invalid:scene-visual-authority",
            ),
            (
                "structure-exclusive-branches",
                lambda envelope: envelope["allOf"][1]["then"]["properties"][
                    "constraints"
                ]["oneOf"][0].pop("not"),
                "invalid:structure-visual-authority",
            ),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), TemporaryDirectory() as folder:
                package = self.copy_package(folder)
                path = package / "references/schemas/task-envelope.schema.json"
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                self.refresh_release_fingerprint(package)

                errors = validate_package(package)

                self.assertNotIn("invalid:release-fingerprint", errors)
                self.assertIn(expected, errors)

    def test_side_channel_contract_mutations_fail_after_fingerprint_refresh(self):
        """Catches a refreshed hash blessing reopened Artifact or MIME authority."""
        authority_exclusion = {
            "if": {
                "anyOf": [
                    {"required": ["visual_media_operation"]},
                    {"required": ["visual_media_context"]},
                ]
            },
            "then": {
                "not": {
                    "anyOf": [
                        {"required": ["visual_operation"]},
                        {"required": ["image_operation"]},
                        {"required": ["image_context"]},
                    ]
                }
            },
        }
        envelope = json.loads(
            (ROOT / "references/schemas/task-envelope.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            authority_exclusion,
            envelope["properties"]["constraints"]["allOf"],
        )
        result_schema = json.loads(
            (ROOT / "references/schemas/task-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        media_schema = result_schema["properties"]["visual_media_handoff"][
            "properties"
        ]["media"]
        self.assertIn("allOf", media_schema)

        cases = (
            (
                "artifact-open",
                "references/schemas/artifact.schema.json",
                lambda schema: schema.update({"additionalProperties": True}),
                "invalid:artifact-extension-contract",
            ),
            (
                "mixed-authority",
                "references/schemas/task-envelope.schema.json",
                lambda schema: schema["properties"]["constraints"]["allOf"].remove(
                    authority_exclusion
                ),
                "invalid:visual-media-conditionals",
            ),
            (
                "mime-kind",
                "references/schemas/task-result.schema.json",
                lambda schema: schema["properties"]["visual_media_handoff"][
                    "properties"
                ]["media"].pop("allOf"),
                "invalid:visual-media-mime-contract",
            ),
        )
        for name, relative, mutate, expected in cases:
            with self.subTest(name=name), TemporaryDirectory() as folder:
                package = self.copy_package(folder)
                path = package / relative
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                self.refresh_release_fingerprint(package)

                errors = validate_package(package)

                self.assertNotIn("invalid:release-fingerprint", errors)
                self.assertIn(expected, errors)

    def test_invalid_visual_media_context_refs_fail_after_fingerprint_refresh(self):
        """Catches the envelope dropping or redirecting its visual context schema."""
        cases = (
            ("empty-schema", lambda context: context.clear()),
            ("missing-ref", lambda context: context.pop("$ref")),
            (
                "incorrect-ref",
                lambda context: context.update(
                    {"$ref": "image-task-context.schema.json"}
                ),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name), TemporaryDirectory() as folder:
                package = self.copy_package(folder)
                path = package / "references/schemas/task-envelope.schema.json"
                schema = json.loads(path.read_text(encoding="utf-8"))
                context = schema["properties"]["constraints"]["properties"][
                    "visual_media_context"
                ]
                mutate(context)
                path.write_text(json.dumps(schema), encoding="utf-8")
                self.refresh_release_fingerprint(package)

                errors = validate_package(package)

                self.assertNotIn("invalid:release-fingerprint", errors)
                self.assertIn("invalid:visual-media-context-ref", errors)

    def test_weakened_visual_scope_mapping_fails_after_fingerprint_refresh(self):
        """Catches single-scope or review-batch IDs no longer using their exact defs."""
        cases = (
            (
                "single-id",
                lambda schema: schema["properties"]["scope_identity"]["allOf"][0][
                    "then"
                ]["properties"].update({"id": {}}),
                "invalid:visual-media-scope-mapping",
            ),
            (
                "review-id-list",
                lambda schema: schema["properties"]["scope_identity"]["allOf"][1][
                    "then"
                ]["properties"].update({"id": {"$ref": "#/$defs/safeId"}}),
                "invalid:visual-media-scope-mapping",
            ),
            (
                "safe-id-definition",
                lambda schema: schema["$defs"]["safeId"].update({"pattern": ".*"}),
                "invalid:visual-media-safe-id",
            ),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), TemporaryDirectory() as folder:
                package = self.copy_package(folder)
                path = (
                    package
                    / "references/schemas/visual-media-task-context.schema.json"
                )
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                self.refresh_release_fingerprint(package)

                errors = validate_package(package)

                self.assertNotIn("invalid:release-fingerprint", errors)
                self.assertIn(expected, errors)

    def test_visual_release_schema_enums_scope_and_budgets_are_exact(self):
        """Catches a fingerprint refresh that broadens visual authority or budgets."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(
                ROOT,
                package,
                ignore=shutil.ignore_patterns(
                    ".git", ".worktrees", ".superpowers", "__pycache__", "*.pyc"
                ),
            )
            envelope_path = package / "references/schemas/task-envelope.schema.json"
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            envelope["properties"]["constraints"]["properties"][
                "visual_media_operation"
            ]["enum"].append("video-probe")
            envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

            context_path = (
                package / "references/schemas/visual-media-task-context.schema.json"
            )
            context = json.loads(context_path.read_text(encoding="utf-8"))
            context["properties"]["scope_identity"]["properties"]["kind"][
                "enum"
            ].append("project")
            context["properties"]["historical_access"]["const"] = "all"
            context["properties"]["max_review_previews"]["maximum"] = 2
            context["properties"]["context_budget_bytes"]["maximum"] = 65536
            context["$defs"]["uniqueSafeArtifactIds"]["maxItems"] = 17
            context["$defs"]["reviewScopeIds"]["maxItems"] = 9
            context_path.write_text(json.dumps(context), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:visual-media-operations", errors)
            self.assertIn("invalid:visual-media-scope-kinds", errors)
            self.assertIn("invalid:visual-media-historical-access", errors)
            self.assertIn("invalid:visual-media-preview-limit", errors)
            self.assertIn("invalid:visual-media-context-budget", errors)
            self.assertIn("invalid:visual-media-artifact-limit", errors)
            self.assertIn("invalid:visual-media-review-scope-limit", errors)

    def test_video_director_declares_required_routing_constraints(self):
        skill = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Chinese talking-head and tutorial", skill)
        self.assertIn("artifact IDs, paths, summaries, and contract results", skill)
        self.assertIn("cannot override routing or approval policy", skill)

    def test_voiceover_producer_entrypoint_is_required(self):
        """Catches an installable package that omits the voice-ready child skill."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            (package / "skills/voiceover-producer/SKILL.md").unlink()

            self.assertIn(
                "missing:skills/voiceover-producer/SKILL.md",
                validate_package(package),
            )

    def test_image_context_schema_is_required(self):
        """Catches a package whose image workers reference a missing contract."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            (package / "references/schemas/image-task-context.schema.json").unlink()

            self.assertIn(
                "missing:references/schemas/image-task-context.schema.json",
                validate_package(package),
            )

    def test_manifest_declares_the_host_plugin_name_and_skill_directory(self):
        """Catches a marketplace entry whose manifest cannot expose bundled skills."""
        with TemporaryDirectory() as folder:
            package = Path(folder)
            shutil.copytree(
                ROOT,
                package,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
            manifest_path = package / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["name"] = "Video Production Toolkit"
            manifest.pop("skills", None)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors = validate_package(package)
            self.assertIn("invalid:plugin-name", errors)
            self.assertIn("invalid:skills-path", errors)
            self.assertIn("invalid:release-fingerprint", errors)

    def test_manifest_requires_the_voice_ready_patch_release(self):
        """Catches host cache reuse under the pre-fix package version."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            manifest_path = package / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = "0.1.2"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertIn("invalid:plugin-version", validate_package(package))

    def test_release_runtime_schema_policy_and_skill_files_are_required(self):
        """Catches a valid-looking archive that omits a final-fix contract owner."""
        required = (
            "scripts/build_review_pack.py",
            "scripts/toolkit/adapters.py",
            "scripts/toolkit/image_context.py",
            "scripts/toolkit/orchestrator.py",
            "scripts/toolkit/project_state.py",
            "scripts/toolkit/tasks.py",
            "scripts/toolkit/validation.py",
            "scripts/toolkit/voice.py",
            "scripts/toolkit/voice_tasks.py",
            "references/policies/decision-gates.md",
            "references/policies/invalidation.json",
            "references/policies/project-assets.md",
            "references/schemas/event.schema.json",
            "references/schemas/project.schema.json",
            "references/schemas/task-envelope.schema.json",
            "references/schemas/task-result.schema.json",
            "registries/adapters/chatcut.json",
            "skills/scene-producer/SKILL.md",
            "skills/structural-validator/SKILL.md",
            "skills/timeline-assembler/SKILL.md",
        )
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            for relative in required:
                (package / relative).unlink()

            errors = validate_package(package)

            for relative in required:
                self.assertIn(f"missing:{relative}", errors)

    def test_chatcut_voice_media_and_probe_contract_is_exact(self):
        """Catches packaged formats drifting beyond the verifier's real probes."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            manifest_path = package / "registries/adapters/chatcut.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["accepted_voice_media_formats"] = ["wav", "ogg"]
            manifest["duration_probe"] = {"wav": "metadata-only"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:chatcut-voice-formats", errors)
            self.assertIn("invalid:chatcut-duration-probe", errors)

    def test_image_context_release_bounds_and_scope_are_exact(self):
        """Catches a shipped schema broadening one isolated image task."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            schema_path = package / "references/schemas/image-task-context.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["required"].remove("scope_identity")
            schema["$defs"]["uniqueSafeImageIds"]["maxItems"] = 17
            schema["$defs"]["uniqueSafePackIds"]["maxItems"] = 9
            schema["properties"]["context_budget"]["maximum"] = 65536
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:image-scope-identity", errors)
            self.assertIn("invalid:image-artifact-limit", errors)
            self.assertIn("invalid:image-pack-limit", errors)
            self.assertIn("invalid:image-context-budget", errors)

    def test_voice_schemas_keep_provenance_and_mode_specific_lineage(self):
        """Catches a distributable schema accepting anonymous or ambiguous audio."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            source_path = package / "references/schemas/voice-source-decision.schema.json"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["required"].remove("decision_provenance")
            source_path.write_text(json.dumps(source), encoding="utf-8")
            profile_path = package / "references/schemas/voice-profile.schema.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["required"].remove("consent_provenance")
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            voiceover_path = package / "references/schemas/voiceover.schema.json"
            voiceover = json.loads(voiceover_path.read_text(encoding="utf-8"))
            voiceover["required"].remove("provenance")
            voiceover["allOf"] = []
            voiceover_path.write_text(json.dumps(voiceover), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:voice-source-provenance", errors)
            self.assertIn("invalid:voice-profile-provenance", errors)
            self.assertIn("invalid:voiceover-provenance", errors)
            self.assertIn("invalid:voiceover-mode-lineage", errors)

    def test_runtime_project_and_review_pack_templates_are_required(self):
        """Catches a plugin package that cannot initialize or review a project."""
        for relative in (
            "assets/project-template/project.json",
            "assets/project-template/review-pack/index.html",
        ):
            with self.subTest(relative=relative), TemporaryDirectory() as folder:
                package = Path(folder) / "package"
                shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
                (package / relative).unlink()

                self.assertIn(f"missing:{relative}", validate_package(package))

    def test_project_template_uses_the_current_project_schema_version(self):
        """Catches new projects starting from the legacy pre-voice contract."""
        template = json.loads(
            (ROOT / "assets/project-template/project.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            {
                "schema_version": 2,
                "project_id": "<project-id>",
                "workflow": "knowledge-video",
                "phase": "initialized",
            },
            template,
        )

    def test_style_and_layout_pack_assets_are_required(self):
        """Catches installation omitting schemas, manifests, or human previews."""
        required_pack_assets = (
            "references/schemas/style-pack.schema.json",
            "references/schemas/layout-pack.schema.json",
            "registries/styles/editorial-clean/v1/manifest.json",
            "registries/layouts/talking-head-left-explainer-right/v1/manifest.json",
            "previews/styles/editorial-clean-v1.html",
            "previews/layouts/talking-head-left-explainer-right-v1.html",
        )
        for relative in required_pack_assets:
            with self.subTest(relative=relative), TemporaryDirectory() as folder:
                package = Path(folder) / "package"
                shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
                (package / relative).unlink()

                self.assertIn(f"missing:{relative}", validate_package(package))


if __name__ == "__main__":
    unittest.main()

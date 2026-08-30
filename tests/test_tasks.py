import base64
import json
import os
import shutil
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from scripts.toolkit.artifacts import create_artifact
from scripts.toolkit import tasks
from scripts.toolkit.tasks import (
    claim_task,
    complete_task,
    create_task,
    retry_decision,
    timing_contract_inputs_are_current,
)
from scripts.toolkit.project_state import initialize_project
from scripts.toolkit.visual_media_context import ACTIVE_VISUAL_MEDIA_OPERATIONS
from tests.encoding_boundary_cases import (
    HARMLESS_PROSE_CONTROLS,
    STRUCTURAL_ENCODING_CASES,
    TYPED_CHECKSUM_TEXT_CONTROL,
    TYPED_SAFE_ID_CONTROL,
)


class CurrentTaskEnvelopeMetadataTests(unittest.TestCase):
    @staticmethod
    def envelope(**constraints):
        return {
            "task_id": "metadata-only-task",
            "capability": "project.manage",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "task-result-v1",
            "constraints": constraints,
        }

    def test_current_validator_rejects_all_deprecated_authority_keys(self):
        for key, value in (
            ("visual_operation", "non-image"),
            ("image_operation", "structure-only"),
            ("image_context", {}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                tasks.validate_current_task_envelope(self.envelope(**{key: value}))

    def test_v3_formal_tasks_require_current_timed_beats_and_scene_contract(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_project(root, "v3-task-gate", "knowledge-video", schema_version=3)
            envelope = {
                "task_id": "v3-scene",
                "capability": "scene.produce",
                "inputs": ["voice-timing-v2", "timed-beats-v2", "scene-timing-v2"],
                "adapter_preferences": ["chatcut"],
                "output_contract": "scene-video-v1",
                "constraints": {
                    "voice_timing_id": "voice-timing-v2",
                    "timed_semantic_beats_id": "timed-beats-v2",
                    "scene_timing_contracts_id": "scene-timing-v2",
                    "visual_media_operation": "none",
                },
            }
            records = [
                {"artifact_id": "voice-timing-v2", "type": "voice-timing", "status": "approved"},
                {"artifact_id": "timed-beats-v2", "type": "timed-semantic-beats", "status": "approved", "version": 2, "voice_timing_id": "voice-timing-v2"},
                {"artifact_id": "scene-timing-v2", "type": "scene-timing-contracts", "status": "approved", "version": 2, "timed_semantic_beats_id": "timed-beats-v2"},
            ]
            with patch(
                "scripts.toolkit.tasks.voice_timing_input_is_current",
                return_value=True,
            ):
                self.assertTrue(timing_contract_inputs_are_current(envelope, records, root=root))
                envelope["constraints"].pop("scene_timing_contracts_id")
                self.assertFalse(timing_contract_inputs_are_current(envelope, records, root=root))

    def test_persisted_validator_keeps_explicit_legacy_separate_from_current(self):
        tasks._validate_persisted_envelope(
            self.envelope(
                visual_operation="non-image",
                image_operation="structure-only",
            )
        )
        with self.assertRaises(ValueError):
            tasks._validate_persisted_envelope(
                self.envelope(
                    visual_media_operation="none",
                    visual_operation="non-image",
                )
            )

    def test_public_persisted_validator_keeps_legacy_recovery_readable(self):
        """Catches recovery importing a private/current-only validator."""
        legacy = self.envelope(
            visual_operation="non-image",
            image_operation="structure-only",
        )

        tasks.validate_persisted_task_envelope(legacy)

        with self.assertRaisesRegex(ValueError, "legacy .* authority is read-only"):
            tasks.validate_current_task_envelope(legacy)

    def test_scene_schema_separates_current_and_persisted_legacy_authority(self):
        """Catches the scene schema requiring authority rejected by current runtime."""
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "references"
                / "schemas"
                / "task-envelope.schema.json"
            ).read_text(encoding="utf-8")
        )
        scene_rule = next(
            rule
            for rule in schema["allOf"]
            if rule["if"].get("properties", {}).get("capability")
            == {"const": "scene.produce"}
        )

        self.assertEqual(
            {
                "oneOf": [
                    {
                        "required": ["visual_media_operation"],
                        "properties": {
                            "visual_media_operation": {
                                "enum": [
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
                                ]
                            }
                        },
                        "not": {
                            "anyOf": [
                                {"required": ["visual_operation"]},
                                {"required": ["image_operation"]},
                                {"required": ["image_context"]},
                            ]
                        },
                    },
                    {
                        "required": ["visual_operation"],
                        "properties": {
                            "visual_operation": {
                                "enum": ["image-generation", "non-image"]
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
            scene_rule["then"]["properties"]["constraints"],
        )


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.create_artifact("narration-v1", "narration", 1)
        self.create_artifact(
            "voice-source-v1",
            "voice-source-decision",
            1,
            parents=["narration-v1"],
            narration_id="narration-v1",
            mode="tts",
            decision="approved",
            decision_provenance="user:source-v1",
        )
        self.create_artifact(
            "voice-profile-v1",
            "voice-profile",
            1,
            parents=["narration-v1", "voice-source-v1"],
            narration_id="narration-v1",
            source_decision_id="voice-source-v1",
            mode="tts",
            language="zh-CN",
            provider="chatcut",
            voice_id="narrator-1",
            speaking_rate=1.0,
            emotion="calm",
            pronunciations=[],
            approved=True,
            consent_provenance="user:consent-v1",
            profile_provenance="user:profile-v1",
        )
        self.create_artifact(
            "voiceover-v1",
            "voiceover",
            1,
            parents=["narration-v1", "voice-source-v1", "voice-profile-v1"],
            narration_id="narration-v1",
            source_decision_id="voice-source-v1",
            mode="tts",
            profile_id="voice-profile-v1",
            media_path="media/voiceover-v1.wav",
            media_format="wav",
            duration_ms=12000,
            provenance="chatcut:voice",
        )
        sample_rate = 8_000
        audio = b"\0\0" * (12 * sample_rate)
        (self.root / "media").mkdir(exist_ok=True)
        (self.root / "media/voiceover-v1.wav").write_bytes(
            b"RIFF" + struct.pack("<I", 36 + len(audio)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(audio)) + audio
        )
        self.inputs = [
            self.create_artifact("scene-contract-S03-v4", "scene-contract", 4),
            self.create_artifact("style-v3", "style-pack", 3),
            self.create_artifact("layout-v2", "layout-pack", 2),
            self.create_artifact(
                "voice-timing-v1",
                "voice-timing",
                1,
                parents=["voiceover-v1"],
                voiceover_id="voiceover-v1",
                timing_kind="real",
                duration_ms=12000,
                segments=[{"start_ms": 0, "end_ms": 12000, "text": "narration"}],
                keyword_anchors=[],
            ),
        ]
        self.create_artifact(
            "motion-preview-S03-v2",
            "visual-preview",
            2,
            parents=self.inputs,
            path="media/motion-preview-S03-v2.mp4",
            media_kind="video",
            historical=False,
            output_contract="motion-preview-v1",
        )
        self.create_artifact(
            "image-preview-S03-v2",
            "scene-image",
            2,
            parents=self.inputs,
            path="media/image-preview-S03-v2.png",
            media_kind="image",
            historical=False,
            output_contract="motion-preview-v1",
        )
        self.envelope = {
            "task_id": "preview-S03-v2",
            "capability": "motion.preview",
            "inputs": self.inputs,
            "adapter_preferences": ["hyperframes", "remotion"],
            "output_contract": "motion-preview-v1",
            "constraints": {
                "do_not_rewrite_script": True,
                "max_attempts": 2,
                "voice_timing_id": "voice-timing-v1",
                "visual_media_operation": "video-render",
                "visual_media_context": self.visual_context(),
                "execution_context": "isolated-child-agent",
            },
        }

    def tearDown(self):
        self.folder.cleanup()

    def create_artifact(
        self, artifact_id, artifact_type, version, status="approved", parents=None, **metadata
    ):
        create_artifact(
            self.root,
            {
                "artifact_id": artifact_id,
                "type": artifact_type,
                "version": version,
                "status": status,
                "parents": [] if parents is None else parents,
                "path": f"media/{artifact_id}.json",
                **metadata,
            },
        )
        return artifact_id

    def result_for(self, claim, **updates):
        result = {
            "task_id": "preview-S03-v2",
            "status": "succeeded",
            "inputs": self.inputs,
            "artifacts": ["motion-preview-S03-v2"],
            "checks": ["duration-valid"],
            "warnings": [],
            **claim,
        }
        result.update(updates)
        task_path = self.root / "tasks" / f"{result['task_id']}.json"
        if task_path.is_file():
            envelope = json.loads(task_path.read_text(encoding="utf-8"))
            operation = envelope["constraints"].get("visual_media_operation")
            if operation not in {None, "none"} and not {
                "visual_media_handoff",
                "image_handoff",
            } & result.keys():
                artifacts = tasks._artifacts_by_id(self.root / "artifacts")
                paths = [
                    artifacts[artifact_id]["path"]
                    for artifact_id in result["artifacts"]
                    if artifact_id in artifacts
                ]
                result["visual_media_handoff"] = {
                    "artifact_ids": list(result["artifacts"]),
                    "paths": paths,
                    "media": {"kind": "video", "format": "mp4"},
                    "checks": [],
                    "issues": [],
                    "summary": "Visual task result is ready.",
                    "review_preview_path": None,
                }
        return result

    def image_context(self):
        return {
            "scope_identity": {
                "kind": "scene-contract",
                "id": "scene-contract-S03-v4",
            },
            "allowed_image_artifact_ids": [],
            "allowed_character_pack_ids": ["host-pack-v1"],
            "forbidden_scene_image_access": True,
            "max_review_previews": 1,
            "context_budget": 4096,
            "continuity_exception": {
                "artifact_id": "scene-S03-v1",
                "user_requested": True,
                "reason": "Inspect the exact scene image named by the user.",
            },
        }

    def visual_context(self):
        return {
            "scope_identity": {
                "kind": "scene-contract",
                "id": "scene-contract-S03-v4",
            },
            "allowed_artifact_ids": [],
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 1,
            "context_budget_bytes": 4096,
        }

    def visual_envelope(self, *, task_id, operation):
        return {
            **self.envelope,
            "task_id": task_id,
            "constraints": {
                **self.envelope["constraints"],
                "visual_media_operation": operation,
                "visual_media_context": self.visual_context(),
                "execution_context": "isolated-child-agent",
            },
        }

    def visual_input_envelope(self, *, task_id, artifact_id, operation="video-inspect"):
        envelope = self.visual_envelope(task_id=task_id, operation=operation)
        envelope["inputs"] = [*envelope["inputs"], artifact_id]
        envelope["constraints"]["visual_media_context"]["allowed_artifact_ids"] = []
        envelope["constraints"]["visual_media_context"]["continuity_exception"] = {
            "artifact_id": artifact_id,
            "user_requested": True,
            "reason": "Use this exact current visual Artifact.",
        }
        return envelope

    def legacy_constraints(self, **updates):
        constraints = {
            key: value
            for key, value in self.envelope["constraints"].items()
            if key
            not in {
                "visual_media_operation",
                "visual_media_context",
                "execution_context",
            }
        }
        constraints.update(updates)
        return constraints

    def persist_legacy_envelope(self, envelope):
        tasks_root = self.root / "tasks"
        tasks_root.mkdir(exist_ok=True)
        path = tasks_root / f"{envelope['task_id']}.json"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        return path

    def non_visual_envelope(self, *, task_id="non-visual-task"):
        return {
            "task_id": task_id,
            "capability": "project.manage",
            "inputs": ["narration-v1"],
            "adapter_preferences": ["hyperframes"],
            "output_contract": "project-plan-v1",
            "constraints": {"visual_media_operation": "none"},
        }

    def test_every_visual_operation_requires_isolated_child_at_create_and_claim(self):
        """Catches any active visual mode executing outside an isolated child."""
        for index, operation in enumerate(sorted(ACTIVE_VISUAL_MEDIA_OPERATIONS), 1):
            rejected = self.visual_envelope(
                task_id=f"reject-context-{index}", operation=operation
            )
            rejected["constraints"]["execution_context"] = "primary-coordinator"
            with self.subTest(operation=operation, phase="create"), self.assertRaisesRegex(
                ValueError, "isolated child"
            ):
                create_task(self.root, rejected)

            persisted = self.visual_envelope(
                task_id=f"recheck-context-{index}", operation=operation
            )
            task_path = create_task(self.root, persisted)
            stored = json.loads(task_path.read_text(encoding="utf-8"))
            stored["constraints"]["execution_context"] = "primary-coordinator"
            task_path.write_text(json.dumps(stored), encoding="utf-8")
            with self.subTest(operation=operation, phase="claim"), self.assertRaisesRegex(
                ValueError, "isolated child"
            ):
                claim_task(self.root, persisted["task_id"], "worker-a")

    def test_none_task_cannot_return_visual_artifact(self):
        """Catches worker self-report hiding a visual output behind operation none."""
        envelope = self.non_visual_envelope()
        create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        self.create_artifact(
            "hidden-video-v1",
            "scene-video",
            1,
            media_kind="video",
            path="media/hidden-video-v1.mp4",
            historical=False,
            output_contract=envelope["output_contract"],
        )
        result = {
            "task_id": envelope["task_id"],
            "status": "succeeded",
            "inputs": envelope["inputs"],
            "artifacts": ["hidden-video-v1"],
            "checks": [],
            "warnings": [],
            **claim,
        }

        with self.assertRaisesRegex(ValueError, "visual media"):
            complete_task(self.root, result)

    def test_every_visual_operation_requires_context_at_create_and_claim(self):
        """Catches an active operation losing its bounded scope before execution."""
        for index, operation in enumerate(sorted(ACTIVE_VISUAL_MEDIA_OPERATIONS), 1):
            missing = self.visual_envelope(
                task_id=f"missing-context-{index}", operation=operation
            )
            missing["constraints"].pop("visual_media_context")
            with self.subTest(operation=operation, phase="create"), self.assertRaisesRegex(
                ValueError, "visual_media_context"
            ):
                create_task(self.root, missing)

            persisted = self.visual_envelope(
                task_id=f"claim-missing-context-{index}", operation=operation
            )
            task_path = create_task(self.root, persisted)
            stored = json.loads(task_path.read_text(encoding="utf-8"))
            stored["constraints"].pop("visual_media_context")
            task_path.write_text(json.dumps(stored), encoding="utf-8")
            with self.subTest(operation=operation, phase="claim"), self.assertRaisesRegex(
                ValueError, "visual_media_context"
            ):
                claim_task(self.root, persisted["task_id"], "worker-a")

    def test_none_rejects_visual_capability_input_and_output_at_create_and_claim(self):
        """Catches operation none laundering any immutable visual task signal."""
        self.create_artifact(
            "none-hidden-video-v1",
            "scene-video",
            1,
            path="media/none-hidden-video-v1.mp4",
            media_kind="video",
            historical=False,
        )
        mutations = (
            ("capability", lambda envelope: envelope.update(capability="visual.preview")),
            (
                "input",
                lambda envelope: envelope["inputs"].append("none-hidden-video-v1"),
            ),
            (
                "output",
                lambda envelope: envelope.update(output_contract="rendered-video"),
            ),
        )
        for index, (signal, mutate) in enumerate(mutations, 1):
            rejected = self.non_visual_envelope(task_id=f"none-create-{index}")
            mutate(rejected)
            with self.subTest(signal=signal, phase="create"), self.assertRaisesRegex(
                ValueError, "visual media.*none"
            ):
                create_task(self.root, rejected)

            persisted = self.non_visual_envelope(task_id=f"none-claim-{index}")
            task_path = create_task(self.root, persisted)
            stored = json.loads(task_path.read_text(encoding="utf-8"))
            mutate(stored)
            task_path.write_text(json.dumps(stored), encoding="utf-8")
            with self.subTest(signal=signal, phase="claim"), self.assertRaisesRegex(
                ValueError, "visual media.*none"
            ):
                claim_task(self.root, persisted["task_id"], "worker-a")

    def test_visual_completion_requires_exact_handoff_and_one_preview(self):
        """Catches ambiguous IDs, paths, or previews crossing completion."""
        envelope = self.visual_envelope(
            task_id="exact-visual-handoff", operation="video-render"
        )
        create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        valid = self.result_for(claim, task_id=envelope["task_id"])

        missing_preview = json.loads(json.dumps(valid))
        missing_preview["visual_media_handoff"].pop("review_preview_path")
        with self.assertRaisesRegex(ValueError, "missing fields.*review_preview_path"):
            complete_task(self.root, missing_preview)

        multiple_previews = json.loads(json.dumps(valid))
        multiple_previews["visual_media_handoff"]["review_preview_path"] = [
            "previews/motion-preview-S03-v2-a.mp4",
            "previews/motion-preview-S03-v2-b.mp4",
        ]
        with self.assertRaisesRegex(ValueError, "more than one preview"):
            complete_task(self.root, multiple_previews)

        undeclared_id = json.loads(json.dumps(valid))
        undeclared_id["visual_media_handoff"]["artifact_ids"].append("extra-v1")
        with self.assertRaisesRegex(ValueError, "artifact_ids must match"):
            complete_task(self.root, undeclared_id)

        undeclared_path = json.loads(json.dumps(valid))
        undeclared_path["visual_media_handoff"]["paths"] = [
            "media/undeclared-v1.mp4"
        ]
        with self.assertRaisesRegex(ValueError, "undeclared path"):
            complete_task(self.root, undeclared_path)

        mixed = json.loads(json.dumps(valid))
        mixed["image_handoff"] = {"artifact_ids": valid["artifacts"]}
        with self.assertRaisesRegex(ValueError, "must not mix"):
            complete_task(self.root, mixed)

        self.assertEqual("completed", complete_task(self.root, valid))
        persisted = json.loads(
            (
                self.root
                / "tasks"
                / "results"
                / f"{envelope['task_id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("visual_media_handoff", persisted)
        self.assertNotIn("image_handoff", persisted)

    def test_create_rejects_legacy_authority_but_claim_projects_persisted_legacy(self):
        """Catches deprecated image authority being minted as a new task."""
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "persisted-legacy-image-task",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": self.legacy_constraints(
                image_operation="image-inspect",
                image_context=self.image_context(),
            ),
        }

        with self.assertRaisesRegex(ValueError, "legacy image.*read-only"):
            create_task(self.root, envelope)

        self.persist_legacy_envelope(envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        self.assertEqual("worker-a", claim["worker_id"])

    def test_claim_rejects_persisted_task_id_mismatch_and_cleans_lock(self):
        """Catches claim authority being issued for a differently identified record."""
        envelope = self.non_visual_envelope(task_id="claim-file-identity")
        task_path = create_task(self.root, envelope)
        stored = json.loads(task_path.read_text(encoding="utf-8"))
        stored["task_id"] = "different-task-identity"
        task_path.write_text(json.dumps(stored), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "task_id.*does not match"):
            claim_task(self.root, envelope["task_id"], "worker-a")
        self.assertFalse(
            (self.root / "tasks" / "locks" / f"{envelope['task_id']}.lock").exists()
        )

    def test_completion_rejects_persisted_task_id_mismatch_without_publication(self):
        """Catches completion publishing under a filename whose record names another task."""
        envelope = self.visual_envelope(
            task_id="completion-file-identity", operation="video-render"
        )
        task_path = create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        result = self.result_for(claim, task_id=envelope["task_id"])
        stored = json.loads(task_path.read_text(encoding="utf-8"))
        stored["task_id"] = "different-completion-identity"
        task_path.write_text(json.dumps(stored), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "task_id.*does not match"):
            complete_task(self.root, result)
        for directory in ("results", "stale-results", "status"):
            self.assertFalse(
                (self.root / "tasks" / directory / f"{envelope['task_id']}.json").exists()
            )

    def test_new_visual_result_rejects_null_legacy_handoff_key(self):
        """Catches a null deprecated key bypassing new/legacy handoff exclusivity."""
        envelope = self.visual_envelope(
            task_id="new-result-null-legacy-handoff", operation="video-render"
        )
        create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        result = self.result_for(claim, task_id=envelope["task_id"])
        result["image_handoff"] = None

        with self.assertRaisesRegex(ValueError, "must not mix"):
            complete_task(self.root, result)

    def test_legacy_result_rejects_null_visual_handoff_key(self):
        """Catches a null new key bypassing legacy-result exclusivity."""
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "legacy-result-null-visual-handoff",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": self.legacy_constraints(
                image_operation="image-inspect",
                image_context=self.image_context(),
            ),
        }
        self.persist_legacy_envelope(envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        result = self.result_for(
            claim,
            task_id=envelope["task_id"],
            inputs=envelope["inputs"],
            artifacts=["image-preview-S03-v2"],
        )
        result["image_handoff"] = {
            "artifact_ids": ["image-preview-S03-v2"],
            "paths": ["media/image-preview-S03-v2.png"],
            "summary": "Legacy image inspection complete.",
            "status": "succeeded",
        }
        result["visual_media_handoff"] = None

        with self.assertRaisesRegex(ValueError, "must not mix"):
            complete_task(self.root, result)

    def test_succeeded_result_rejects_noncurrent_output_artifacts(self):
        """Catches terminal success publishing non-current Artifact metadata."""
        cases = ("draft", "stale", "superseded", "invalid")
        for status in cases:
            artifact_id = f"result-{status}-v1"
            self.create_artifact(
                artifact_id,
                f"result-{status}",
                1,
                status=status,
                output_contract="project-plan-v1",
            )
            envelope = self.non_visual_envelope(task_id=f"reject-result-{status}")
            create_task(self.root, envelope)
            claim = claim_task(self.root, envelope["task_id"], "worker-a")
            result = {
                "task_id": envelope["task_id"],
                "status": "succeeded",
                "inputs": envelope["inputs"],
                "artifacts": [artifact_id],
                "checks": [],
                "warnings": [],
                **claim,
            }
            with self.subTest(status=status), self.assertRaisesRegex(
                ValueError, "current approved"
            ):
                complete_task(self.root, result)

    def test_succeeded_result_rejects_event_invalidated_or_superseded_lineage(self):
        """Catches effective state and newer lineage being ignored at publication."""
        cases = ("invalidated", "newer-lineage")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as folder:
                root = Path(folder)
                shutil.copytree(self.root / "artifacts", root / "artifacts")
                shutil.copytree(self.root / "media", root / "media")
                artifact_id = f"{case}-output-v1"
                create_artifact(
                    root,
                    {
                        "artifact_id": artifact_id,
                        "type": f"{case}-output",
                        "version": 1,
                        "status": "approved",
                        "parents": [],
                        "path": f"media/{artifact_id}.json",
                        "output_contract": "project-plan-v1",
                    },
                )
                envelope = self.non_visual_envelope(task_id=f"reject-{case}-output")
                create_task(root, envelope)
                claim = claim_task(root, envelope["task_id"], "worker-a")
                if case == "invalidated":
                    events = root / "events"
                    events.mkdir(exist_ok=True)
                    with (events / "events.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "event": "artifacts.invalidated",
                                    "changed_id": artifact_id,
                                    "artifact_ids": [artifact_id],
                                }
                            )
                            + "\n"
                        )
                else:
                    create_artifact(
                        root,
                        {
                            "artifact_id": f"{case}-output-v2",
                            "type": f"{case}-output",
                            "version": 2,
                            "status": "approved",
                            "parents": [artifact_id],
                            "path": f"media/{case}-output-v2.json",
                            "output_contract": "project-plan-v1",
                        },
                    )
                result = {
                    "task_id": envelope["task_id"],
                    "status": "succeeded",
                    "inputs": envelope["inputs"],
                    "artifacts": [artifact_id],
                    "checks": [],
                    "warnings": [],
                    **claim,
                }
                with self.assertRaisesRegex(ValueError, "current approved"):
                    complete_task(root, result)

    def test_resumable_result_allows_a_draft_partial_artifact(self):
        """Catches output hardening breaking resumable draft checkpoints."""
        artifact_id = "draft-partial-v1"
        self.create_artifact(
            artifact_id,
            "partial-output",
            1,
            status="draft",
            output_contract="project-plan-v1",
        )
        envelope = self.non_visual_envelope(task_id="draft-partial-checkpoint")
        create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        result = {
            "task_id": envelope["task_id"],
            "status": "waiting_external",
            "inputs": envelope["inputs"],
            "artifacts": [artifact_id],
            "checks": [],
            "warnings": [],
            **claim,
        }

        self.assertEqual("resumable", complete_task(self.root, result))

    def test_resumable_result_rejects_unusable_partial_artifacts(self):
        """Catches resumable checkpoints retaining invalid output authority."""
        for status in ("stale", "superseded", "invalid"):
            artifact_id = f"partial-{status}-v1"
            self.create_artifact(
                artifact_id,
                f"partial-{status}",
                1,
                status=status,
                output_contract="project-plan-v1",
            )
            envelope = self.non_visual_envelope(task_id=f"partial-{status}-checkpoint")
            create_task(self.root, envelope)
            claim = claim_task(self.root, envelope["task_id"], "worker-a")
            result = {
                "task_id": envelope["task_id"],
                "status": "waiting_external",
                "inputs": envelope["inputs"],
                "artifacts": [artifact_id],
                "checks": [],
                "warnings": [],
                **claim,
            }

            with self.subTest(status=status), self.assertRaisesRegex(
                ValueError, "draft or approved"
            ):
                complete_task(self.root, result)

    def test_every_result_rejects_payloads_histories_and_oversized_envelopes(self):
        """Catches non-image task results bypassing the shared result scrub."""
        leaks = (
            ("checks", ["embedded=data:image/png;base64,AAEC"], "image payload"),
            ("warnings", ["preview=https://example.invalid/scene.png"], "URL|scheme"),
            ("error", "prompt history: first, second", "prompt history"),
            (
                "warnings",
                [
                    base64.b64encode(
                        b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 128
                    ).decode("ascii")
                ],
                "Base64|binary",
            ),
            ("checks", ["x" * 33_000], "result budget"),
        )
        for index, (field, value, message) in enumerate(leaks, 1):
            task_id = f"non-image-result-leak-{index}"
            envelope = self.non_visual_envelope(task_id=task_id)
            create_task(self.root, envelope)
            claim = claim_task(self.root, task_id, "worker-a")
            result = {
                "task_id": task_id,
                "status": "blocked",
                "inputs": envelope["inputs"],
                "artifacts": [],
                "checks": [],
                "warnings": [],
                **claim,
                field: value,
            }
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                complete_task(self.root, result)

    def test_completion_rejects_structural_encodings_in_error_text(self):
        """Catches task completion accepting fragmented or low-entropy payload text."""
        for index, (name, value) in enumerate(STRUCTURAL_ENCODING_CASES, 1):
            task_id = f"encoded-error-result-{index}"
            envelope = self.non_visual_envelope(task_id=task_id)
            create_task(self.root, envelope)
            claim = claim_task(self.root, task_id, "worker-a")
            result = {
                "task_id": task_id,
                "status": "blocked",
                "inputs": envelope["inputs"],
                "artifacts": [],
                "checks": [],
                "warnings": [],
                **claim,
                "error": value,
            }
            with self.subTest(name=name), self.assertRaisesRegex(
                ValueError, "Base64|binary"
            ):
                complete_task(self.root, result)

        for index, (name, prose) in enumerate(HARMLESS_PROSE_CONTROLS):
            task_id = (
                TYPED_SAFE_ID_CONTROL
                if index == 0
                else f"safe-prose-result-{index + 1}"
            )
            safe_envelope = self.non_visual_envelope(task_id=task_id)
            create_task(self.root, safe_envelope)
            safe_claim = claim_task(self.root, task_id, "worker-a")
            safe_result = {
                "task_id": task_id,
                "status": "blocked",
                "inputs": safe_envelope["inputs"],
                "artifacts": [],
                "checks": [TYPED_CHECKSUM_TEXT_CONTROL],
                "warnings": [prose],
                **safe_claim,
                "error": prose,
            }
            with self.subTest(control=name):
                self.assertEqual("resumable", complete_task(self.root, safe_result))

    def test_general_result_scrub_preserves_harmless_digest_metadata(self):
        """Catches the payload heuristic rejecting hashes or ordinary base64 prose."""
        task_id = "non-image-result-harmless-metadata"
        envelope = self.non_visual_envelope(task_id=task_id)
        self.create_artifact(
            "project-plan-v1",
            "project-plan",
            1,
            output_contract=envelope["output_contract"],
        )
        create_task(self.root, envelope)
        claim = claim_task(self.root, task_id, "worker-a")
        result = {
            "task_id": task_id,
            "status": "succeeded",
            "inputs": envelope["inputs"],
            "artifacts": ["project-plan-v1"],
            "checks": ["sha512=" + "0123456789abcdef" * 8],
            "warnings": [
                "The exporter may mention base64; no embedded payload is present."
            ],
            **claim,
        }

        self.assertEqual("completed", complete_task(self.root, result))

    def create_image_context_artifacts(self, *, historical=False, image_type="scene-image"):
        self.create_artifact(
            "host-pack-v1",
            "character-pack",
            1,
            identity_provenance="approved-host-v1",
        )
        self.create_artifact(
            "scene-S03-v1",
            image_type,
            1,
            path="media/scene-S03-v1.png",
            media_kind="image",
            character_pack_id="host-pack-v1",
            historical=historical,
        )

    def invalidate_artifact(self, artifact_id):
        events = self.root / "events"
        events.mkdir(exist_ok=True)
        event_log = events / "events.jsonl"
        with event_log.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": "artifacts.invalidated",
                        "changed_id": artifact_id,
                        "artifact_ids": [artifact_id],
                    }
                )
                + "\n"
            )

    def dispatch_and_claim(self, worker_id="worker-a"):
        create_task(self.root, self.envelope)
        return claim_task(self.root, "preview-S03-v2", worker_id)

    def test_create_task_persists_immutable_envelope_at_task_id_path(self):
        """Catches a task dispatch that loses its contracted input versions."""
        path = create_task(self.root, self.envelope)

        self.assertEqual(self.root / "tasks" / "preview-S03-v2.json", path)
        self.assertEqual(self.envelope, json.loads(path.read_text(encoding="utf-8")))
        with self.assertRaises(FileExistsError):
            create_task(self.root, self.envelope)

    def test_downstream_task_envelope_requires_declared_voice_timing_input(self):
        """Catches production work being persisted without immutable timing provenance."""
        envelope = {
            **self.envelope,
            "task_id": "preview-without-timing",
            "inputs": [
                artifact_id
                for artifact_id in self.envelope["inputs"]
                if artifact_id != "voice-timing-v1"
            ],
            "constraints": {**self.envelope["constraints"]},
        }
        envelope["constraints"].pop("voice_timing_id")

        with self.assertRaisesRegex(ValueError, "voice_timing_id"):
            create_task(self.root, envelope)

    def test_downstream_task_cannot_persist_a_superseded_timing_input(self):
        """Catches immutable dispatch accepting a non-current real timing version."""
        self.create_artifact(
            "voice-timing-v2",
            "voice-timing",
            2,
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=12000,
            segments=[{"start_ms": 0, "end_ms": 12000, "text": "current"}],
            keyword_anchors=[],
        )
        envelope = {**self.envelope, "task_id": "preview-with-stale-timing"}

        with self.assertRaisesRegex(ValueError, "current real voice_timing_id"):
            create_task(self.root, envelope)

    def test_downstream_task_cannot_use_voice_for_a_superseded_narration(self):
        """Catches task creation deriving narration authority from its old voiceover."""
        self.create_artifact(
            "narration-v2",
            "narration",
            2,
            parents=["narration-v1"],
        )

        with self.assertRaisesRegex(ValueError, "current real voice_timing_id"):
            create_task(
                self.root,
                {**self.envelope, "task_id": "preview-with-old-narration"},
            )

    def test_downstream_task_cannot_persist_event_invalidated_timing(self):
        """Catches task creation reading approved metadata without event overlays."""
        self.invalidate_artifact("voice-timing-v1")

        with self.assertRaisesRegex(ValueError, "current"):
            create_task(
                self.root,
                {**self.envelope, "task_id": "preview-with-invalidated-timing"},
            )

    def test_claim_revalidates_inputs_after_acquiring_its_task_lock(self):
        """Catches invalidation between persistence and claim starting external work."""
        create_task(self.root, self.envelope)
        publish_claim = tasks._create_claim

        def publish_then_invalidate(path, claim):
            publish_claim(path, claim)
            self.invalidate_artifact("voice-timing-v1")

        with patch(
            "scripts.toolkit.tasks._create_claim",
            side_effect=publish_then_invalidate,
        ):
            with self.assertRaisesRegex(ValueError, "current"):
                claim_task(self.root, "preview-S03-v2", "worker-a")

        self.assertFalse(
            (self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists()
        )

    def test_task_storage_rejects_a_symlink_escape(self):
        """Catches task envelopes and claims being written outside the runtime project."""
        with TemporaryDirectory() as outside_folder:
            outside = Path(outside_folder) / "tasks"
            outside.mkdir()
            (self.root / "tasks").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                create_task(self.root, self.envelope)
            self.assertEqual([], list(outside.rglob("*.json")))

    def test_active_claim_scan_rejects_a_symlinked_claim_record(self):
        """Catches live-claim discovery reading a foreign lock through a symlink."""
        locks = self.root / "tasks" / "locks"
        locks.mkdir(parents=True)
        with TemporaryDirectory() as outside_folder:
            foreign = Path(outside_folder) / "foreign.lock"
            foreign.write_text(
                json.dumps(
                    {
                        "task_id": "foreign",
                        "worker_id": "outside-worker",
                        "claim_token": "outside-token",
                        "pid": os.getpid(),
                        "created_at": 1.0,
                        "lease_expires_at": 2.0,
                    }
                ),
                encoding="utf-8",
            )
            (locks / "foreign.lock").symlink_to(foreign)

            with self.assertRaises(ValueError):
                tasks.active_claim_task_ids(self.root)

    def test_runtime_rejects_properties_outside_task_schemas(self):
        """Catches runtime records accepting fields rejected by the persisted schemas."""
        with self.assertRaises(ValueError):
            create_task(self.root, {**self.envelope, "unexpected": True})

        claim = self.dispatch_and_claim()
        with self.assertRaises(ValueError):
            complete_task(self.root, self.result_for(claim, unexpected=True))

    def test_task_capability_is_a_closed_runtime_enum(self):
        """Catches unknown worker routes being persisted as ordinary tasks."""
        with self.assertRaisesRegex(ValueError, "capability"):
            create_task(
                self.root,
                {
                    **self.envelope,
                    "task_id": "unknown-capability",
                    "capability": "unknown.route",
                },
            )

    def test_existing_voice_timing_capabilities_remain_valid_task_routes(self):
        """Catches the closed capability enum dropping existing timing consumers."""
        for capability in ("captions.produce", "representative-slice.produce"):
            task_id = capability.replace(".", "-")
            envelope = {
                **self.envelope,
                "task_id": task_id,
                "capability": capability,
            }
            with self.subTest(capability=capability):
                self.assertEqual(
                    self.root / "tasks" / f"{task_id}.json",
                    create_task(self.root, envelope),
                )

    def test_reserved_visual_operation_is_validated_for_every_capability(self):
        """Catches non-scene tasks persisting an unknown current visual mode."""
        with self.assertRaisesRegex(ValueError, "visual_media_operation"):
            create_task(
                self.root,
                {
                    **self.envelope,
                    "task_id": "project-manage-bogus-visual",
                    "capability": "project.manage",
                    "constraints": {
                        **self.envelope["constraints"],
                        "visual_media_operation": "bogus",
                    },
                },
            )

    def test_persisted_legacy_image_operation_requires_closed_context(self):
        """Catches persisted legacy image work losing its bounded authority checks."""
        missing_context = {
            **self.envelope,
            "task_id": "image-inspect-without-context",
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
            },
        }
        self.persist_legacy_envelope(missing_context)
        with self.assertRaisesRegex(ValueError, "image_context"):
            claim_task(self.root, missing_context["task_id"], "worker-a")

        context_without_operation = {
            **self.envelope,
            "task_id": "context-without-image-operation",
            "constraints": {
                **self.legacy_constraints(),
                "image_context": self.image_context(),
            },
        }
        self.persist_legacy_envelope(context_without_operation)
        with self.assertRaisesRegex(ValueError, "image_operation"):
            claim_task(self.root, context_without_operation["task_id"], "worker-a")

        null_context = {
            **self.envelope,
            "task_id": "null-image-context",
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": None,
            },
        }
        self.persist_legacy_envelope(null_context)
        with self.assertRaisesRegex(ValueError, "image_context"):
            claim_task(self.root, null_context["task_id"], "worker-a")

    def test_current_structure_validation_accepts_visual_media_none(self):
        """Catches current structure-only validation being forced onto legacy authority."""
        envelope = {
            **self.non_visual_envelope(task_id="current-structure-only"),
            "capability": "structure.validate",
            "output_contract": "validation-report-v1",
        }

        self.assertEqual(
            self.root / "tasks" / "current-structure-only.json",
            create_task(self.root, envelope),
        )
        self.assertEqual(
            "worker-a",
            claim_task(self.root, envelope["task_id"], "worker-a")["worker_id"],
        )

    def test_current_structure_validation_accepts_isolated_image_inspect(self):
        """Catches current image inspection being forced onto legacy image fields."""
        self.create_image_context_artifacts()
        envelope = self.visual_input_envelope(
            task_id="current-structure-image-inspect",
            artifact_id="scene-S03-v1",
            operation="image-inspect",
        )
        envelope["capability"] = "structure.validate"
        envelope["output_contract"] = "validation-report-v1"

        self.assertEqual(
            self.root / "tasks" / "current-structure-image-inspect.json",
            create_task(self.root, envelope),
        )
        self.assertEqual(
            "worker-a",
            claim_task(self.root, envelope["task_id"], "worker-a")["worker_id"],
        )

    def test_current_structure_validation_rejects_operations_outside_its_subset(self):
        """Catches structure validation acquiring generation, editing, or video authority."""
        disallowed = ACTIVE_VISUAL_MEDIA_OPERATIONS - {"image-inspect"}
        for index, operation in enumerate(sorted(disallowed), 1):
            envelope = self.visual_envelope(
                task_id=f"structure-operation-{index}", operation=operation
            )
            envelope["capability"] = "structure.validate"
            envelope["output_contract"] = "validation-report-v1"

            with self.subTest(operation=operation), self.assertRaisesRegex(
                ValueError, "structure.validate.*visual_media_operation"
            ):
                create_task(self.root, envelope)

    def test_persisted_legacy_structure_validation_requires_exact_image_operation(self):
        """Catches legacy structural validation silently changing image authority."""
        base = {
            **self.envelope,
            "capability": "structure.validate",
            "constraints": self.legacy_constraints(),
        }
        missing_operation = {**base, "task_id": "structure-mode-missing"}
        self.persist_legacy_envelope(missing_operation)
        with self.assertRaisesRegex(ValueError, "image_operation"):
            claim_task(self.root, missing_operation["task_id"], "worker-a")

        legacy_inspect = {
            **base,
            "task_id": "structure-mode-legacy",
            "constraints": {**base["constraints"], "image_operation": "inspect"},
        }
        self.persist_legacy_envelope(legacy_inspect)
        with self.assertRaisesRegex(ValueError, "image_operation"):
            claim_task(self.root, legacy_inspect["task_id"], "worker-a")

        image_without_context = {
            **base,
            "task_id": "structure-image-without-context",
            "constraints": {**base["constraints"], "image_operation": "image-inspect"},
        }
        self.persist_legacy_envelope(image_without_context)
        with self.assertRaisesRegex(ValueError, "image_context"):
            claim_task(self.root, image_without_context["task_id"], "worker-a")

        structure_with_context = {
            **base,
            "task_id": "structure-only-with-context",
            "constraints": {
                **base["constraints"],
                "image_operation": "structure-only",
                "image_context": self.image_context(),
            },
        }
        self.persist_legacy_envelope(structure_with_context)
        with self.assertRaisesRegex(ValueError, "structure-only"):
            claim_task(self.root, structure_with_context["task_id"], "worker-a")

        structure_only = {
            **base,
            "task_id": "structure-only-valid",
            "constraints": {**base["constraints"], "image_operation": "structure-only"},
        }
        self.assertEqual(
            self.root / "tasks" / "structure-only-valid.json",
            self.persist_legacy_envelope(structure_only),
        )
        claim_task(self.root, structure_only["task_id"], "worker-a")

        self.create_image_context_artifacts()
        image_inspect = {
            **base,
            "task_id": "structure-image-valid",
            "inputs": [*base["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **base["constraints"],
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        self.assertEqual(
            self.root / "tasks" / "structure-image-valid.json",
            self.persist_legacy_envelope(image_inspect),
        )
        claim_task(self.root, image_inspect["task_id"], "worker-a")

    def test_create_and_claim_enforce_every_declared_image_access(self):
        """Catches metadata authorization existing only as an unused helper."""
        self.create_image_context_artifacts(historical=True)
        envelope = {
            **self.envelope,
            "task_id": "historical-scene-inspect",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        self.persist_legacy_envelope(envelope)
        with self.assertRaisesRegex(PermissionError, "historical scene image"):
            claim_task(self.root, envelope["task_id"], "worker-a")

        image_path = self.root / "artifacts" / "scene-image" / "scene-S03-v1.json"
        artifact = json.loads(image_path.read_text(encoding="utf-8"))
        artifact.pop("historical")
        image_path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "explicit historical origin"):
            claim_task(self.root, envelope["task_id"], "worker-a")

        artifact["historical"] = False
        image_path.write_text(json.dumps(artifact), encoding="utf-8")
        claim_task(self.root, envelope["task_id"], "worker-a")

    def test_image_task_rejects_an_additional_scene_contract_scope_input(self):
        """Catches one scene scope silently authorizing a second scene contract."""
        self.create_artifact("scene-contract-S04-v1", "scene-contract", 1)
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "two-scene-contract-image-scope-inputs",
            "inputs": [
                *self.envelope["inputs"],
                "scene-contract-S04-v1",
                "scene-S03-v1",
                "host-pack-v1",
            ],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }

        self.persist_legacy_envelope(envelope)
        with self.assertRaisesRegex(PermissionError, "exactly one scene-contract"):
            claim_task(self.root, envelope["task_id"], "worker-a")

    def test_character_batch_scope_allows_explicit_member_packs(self):
        """Catches an allowlisted member pack being mistaken for a second scope."""
        self.create_artifact("character-batch-a", "character-asset-batch", 1)
        self.create_artifact(
            "member-pack-a",
            "character-pack",
            1,
            identity_provenance="approved-member-v1",
        )
        envelope = {
            **self.envelope,
            "task_id": "character-scope-with-member-pack",
            "inputs": [
                *(artifact_id for artifact_id in self.envelope["inputs"] if artifact_id != "scene-contract-S03-v4"),
                "character-batch-a",
                "member-pack-a",
            ],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": {
                    **self.image_context(),
                    "scope_identity": {
                        "kind": "character-asset-batch",
                        "id": "character-batch-a",
                    },
                    "allowed_character_pack_ids": ["member-pack-a"],
                    "continuity_exception": None,
                },
            },
        }

        self.assertEqual(
            self.root / "tasks" / "character-scope-with-member-pack.json",
            self.persist_legacy_envelope(envelope),
        )
        claim_task(self.root, envelope["task_id"], "worker-a")

    def test_character_batch_image_scope_rejects_other_batch_or_pack_inputs(self):
        """Catches one character scope silently authorizing another batch or pack."""
        self.create_artifact("character-batch-a", "character-asset-batch", 1)
        for extra_scope_id, extra_scope_type in (
            ("character-batch-b", "character-asset-batch"),
            ("character-pack-b", "character-pack"),
        ):
            with self.subTest(extra_scope_type=extra_scope_type):
                self.create_artifact(extra_scope_id, extra_scope_type, 1)
                envelope = {
                    **self.envelope,
                    "task_id": f"character-scope-with-{extra_scope_type}",
                    "inputs": [
                        *(artifact_id for artifact_id in self.envelope["inputs"] if artifact_id != "scene-contract-S03-v4"),
                        "character-batch-a",
                        extra_scope_id,
                    ],
                    "constraints": {
                        **self.legacy_constraints(),
                        "image_operation": "image-inspect",
                        "image_context": {
                            **self.image_context(),
                            "scope_identity": {
                                "kind": "character-asset-batch",
                                "id": "character-batch-a",
                            },
                            "allowed_character_pack_ids": [],
                            "continuity_exception": None,
                        },
                    },
                }

                with self.assertRaisesRegex(
                    PermissionError, "exactly one character-asset-batch"
                ):
                    self.persist_legacy_envelope(envelope)
                    claim_task(self.root, envelope["task_id"], "worker-a")

    def test_scene_contract_scope_rejects_a_character_batch_input(self):
        """Catches a scene scope gaining an independent character batch."""
        self.create_image_context_artifacts()
        self.create_artifact("character-batch-a", "character-asset-batch", 1)
        envelope = {
            **self.envelope,
            "task_id": "scene-scope-with-character-batch",
            "inputs": [
                *self.envelope["inputs"],
                "scene-S03-v1",
                "host-pack-v1",
                "character-batch-a",
            ],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }

        self.persist_legacy_envelope(envelope)
        with self.assertRaisesRegex(PermissionError, "exactly one scene-contract"):
            claim_task(self.root, envelope["task_id"], "worker-a")

    def test_scene_contract_scope_allows_an_explicit_member_pack(self):
        """Catches a listed character pack being treated as a scene conflict."""
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "scene-scope-with-member-pack",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }

        self.assertEqual(
            self.root / "tasks" / "scene-scope-with-member-pack.json",
            self.persist_legacy_envelope(envelope),
        )
        claim_task(self.root, envelope["task_id"], "worker-a")

    def test_scene_contract_scope_rejects_an_unlisted_character_pack_input(self):
        """Catches a scene scope gaining an unlisted independent character pack."""
        self.create_image_context_artifacts()
        self.create_artifact(
            "unlisted-pack-a",
            "character-pack",
            1,
            identity_provenance="unlisted-pack-v1",
        )
        envelope = {
            **self.envelope,
            "task_id": "scene-scope-with-unlisted-pack",
            "inputs": [
                *self.envelope["inputs"],
                "scene-S03-v1",
                "host-pack-v1",
                "unlisted-pack-a",
            ],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }

        self.persist_legacy_envelope(envelope)
        with self.assertRaisesRegex(PermissionError, "exactly one scene-contract"):
            claim_task(self.root, envelope["task_id"], "worker-a")

    def test_character_batch_scope_rejects_a_scene_contract_input(self):
        """Catches a character scope gaining an independent Scene Contract."""
        self.create_artifact("character-batch-a", "character-asset-batch", 1)
        self.create_artifact("scene-contract-S04-v1", "scene-contract", 1)
        envelope = {
            **self.envelope,
            "task_id": "character-scope-with-scene-contract",
            "inputs": [
                *(artifact_id for artifact_id in self.envelope["inputs"] if artifact_id != "scene-contract-S03-v4"),
                "character-batch-a",
                "scene-contract-S04-v1",
            ],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": {
                    **self.image_context(),
                    "scope_identity": {
                        "kind": "character-asset-batch",
                        "id": "character-batch-a",
                    },
                    "allowed_character_pack_ids": [],
                    "continuity_exception": None,
                },
            },
        }

        with self.assertRaisesRegex(
            PermissionError, "exactly one character-asset-batch"
        ):
            self.persist_legacy_envelope(envelope)
            claim_task(self.root, envelope["task_id"], "worker-a")

    def test_claim_revalidates_exact_image_scope_inputs(self):
        """Catches a persisted image task gaining another scope before claim."""
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "claim-rechecks-image-scope",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        task_path = self.persist_legacy_envelope(envelope)
        self.create_artifact("scene-contract-S04-v1", "scene-contract", 1)
        persisted = json.loads(task_path.read_text(encoding="utf-8"))
        persisted["inputs"].append("scene-contract-S04-v1")
        task_path.write_text(json.dumps(persisted), encoding="utf-8")

        with self.assertRaisesRegex(PermissionError, "exactly one scene-contract"):
            claim_task(self.root, envelope["task_id"], "worker-a")

    def test_claim_revalidates_an_unlisted_character_pack_scope_input(self):
        """Catches a persisted scene task gaining an unlisted pack before claim."""
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "claim-rechecks-unlisted-character-pack",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        task_path = self.persist_legacy_envelope(envelope)
        self.create_artifact(
            "unlisted-pack-a",
            "character-pack",
            1,
            identity_provenance="unlisted-pack-v1",
        )
        persisted = json.loads(task_path.read_text(encoding="utf-8"))
        persisted["inputs"].append("unlisted-pack-a")
        task_path.write_text(json.dumps(persisted), encoding="utf-8")

        with self.assertRaisesRegex(PermissionError, "exactly one scene-contract"):
            claim_task(self.root, envelope["task_id"], "worker-a")

    def test_image_bearing_inputs_cannot_make_the_context_opt_in(self):
        """Catches ordinary task inputs exposing undeclared neighboring images."""
        self.create_image_context_artifacts()
        inputs = [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"]
        without_context = {
            **self.envelope,
            "task_id": "image-input-without-context",
            "inputs": inputs,
        }
        with self.assertRaisesRegex(PermissionError, "visual media|scope"):
            create_task(self.root, without_context)

        empty_allowlist = {
            **self.envelope,
            "task_id": "image-input-outside-allowlist",
            "inputs": inputs,
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": {
                    **self.image_context(),
                    "allowed_image_artifact_ids": [],
                    "continuity_exception": {
                        "artifact_id": "scene-S02-v1",
                        "user_requested": True,
                        "reason": "Inspect only the other explicitly named scene.",
                    },
                },
            },
        }
        self.persist_legacy_envelope(empty_allowlist)
        with self.assertRaisesRegex(PermissionError, "undeclared image|continuity exception"):
            claim_task(self.root, empty_allowlist["task_id"], "worker-a")

    def test_scene_production_requires_an_explicit_visual_operation(self):
        """Catches text-to-image work hiding behind the generic scene route."""
        scene_envelope = {
            **self.envelope,
            "task_id": "scene-without-visual-operation",
            "capability": "scene.produce",
            "constraints": self.legacy_constraints(),
        }
        with self.assertRaisesRegex(ValueError, "visual_media_operation"):
            create_task(self.root, scene_envelope)

        image_generation = {
            **scene_envelope,
            "task_id": "scene-image-without-context",
            "constraints": {
                **scene_envelope["constraints"],
                "visual_media_operation": "image-generate",
                "execution_context": "isolated-child-agent",
            },
        }
        with self.assertRaisesRegex(ValueError, "visual_media_context"):
            create_task(self.root, image_generation)

    def test_generic_media_input_is_classified_from_its_suffix(self):
        """Catches an image suffix bypassing visual input authorization."""
        self.create_artifact(
            "generic-media-v1",
            "media",
            1,
            path="media/generic-media-v1.bmp",
            historical=False,
        )
        envelope = {
            **self.envelope,
            "task_id": "generic-media-without-kind",
            "inputs": [*self.envelope["inputs"], "generic-media-v1"],
        }
        with self.assertRaisesRegex(PermissionError, "undeclared visual media"):
            create_task(self.root, envelope)

        path = self.root / "artifacts" / "media" / "generic-media-v1.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["media_kind"] = "image"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "undeclared visual media"):
            create_task(self.root, {**envelope, "task_id": "generic-image-without-context"})

        self.create_artifact(
            "conflicting-media-v1",
            "media",
            1,
            path="media/conflicting-media-v1.png",
            media_kind="video",
            mime_type="image/png",
            historical=False,
        )
        conflicting = {
            **self.envelope,
            "task_id": "conflicting-media-kind",
            "inputs": [*self.envelope["inputs"], "conflicting-media-v1"],
        }
        with self.assertRaisesRegex(ValueError, "mime_type|conflicts"):
            create_task(self.root, conflicting)

    def test_media_kind_mime_and_suffix_are_bidirectionally_consistent(self):
        """Catches same-family MIME or unknown-image suffix relabeling."""
        conflicts = (
            ("png-as-mp4", "media/png-as-mp4.mp4", "image", "image/png"),
            ("jpeg-as-png", "media/jpeg-as-png.png", "image", "image/jpeg"),
            ("video-as-wav", "media/video-as-wav.wav", "video", "video/mp4"),
            ("jxl-as-video", "media/jxl-as-video.jxl", "video", "video/mp4"),
        )
        for artifact_id, path, media_kind, mime_type in conflicts:
            self.create_artifact(
                artifact_id,
                "media",
                1,
                path=path,
                media_kind=media_kind,
                mime_type=mime_type,
                historical=False,
            )
            envelope = {
                **self.envelope,
                "task_id": f"task-{artifact_id}",
                "inputs": [*self.envelope["inputs"], artifact_id],
            }
            with self.subTest(artifact_id=artifact_id), self.assertRaisesRegex(
                ValueError, "suffix|extension|conflicts"
            ):
                create_task(self.root, envelope)

        valid = (
            ("valid-video", "media/valid-video.mp4", "video", "video/mp4"),
            ("valid-audio", "media/valid-audio.wav", "audio", "audio/wav"),
        )
        for artifact_id, path, media_kind, mime_type in valid:
            self.create_artifact(
                artifact_id,
                "media",
                1,
                path=path,
                media_kind=media_kind,
                mime_type=mime_type,
                historical=False,
            )
            envelope = (
                self.visual_input_envelope(
                    task_id=f"task-{artifact_id}", artifact_id=artifact_id
                )
                if media_kind == "video"
                else {
                    **self.envelope,
                    "task_id": f"task-{artifact_id}",
                    "inputs": [*self.envelope["inputs"], artifact_id],
                }
            )
            with self.subTest(artifact_id=artifact_id):
                self.assertEqual(
                    self.root / "tasks" / f"task-{artifact_id}.json",
                    create_task(self.root, envelope),
                )

    def test_unknown_media_suffixes_fail_closed_without_rejecting_known_video(self):
        """Catches unlisted image formats relabeled with an unknown video MIME."""
        invalid = (
            ("apng-as-video", "media/apng-as-video.apng", "video/x-apng"),
            ("unknown-as-video", "media/unknown-as-video.unknown", "video/x-unknown"),
        )
        for artifact_id, path, mime_type in invalid:
            self.create_artifact(
                artifact_id,
                "media",
                1,
                path=path,
                media_kind="video",
                mime_type=mime_type,
            )
            envelope = {
                **self.envelope,
                "task_id": f"task-{artifact_id}",
                "inputs": [*self.envelope["inputs"], artifact_id],
            }
            expected_error = (
                (ValueError, "suffix|extension|conflicts")
                if artifact_id == "apng-as-video"
                else (PermissionError, "undeclared visual media")
            )
            with self.subTest(artifact_id=artifact_id), self.assertRaisesRegex(
                expected_error[0], expected_error[1]
            ):
                create_task(self.root, envelope)

        self.create_artifact(
            "valid-matroska",
            "media",
            1,
            path="media/valid-matroska.mkv",
            media_kind="video",
            mime_type="video/x-matroska",
            historical=False,
        )
        valid = self.visual_input_envelope(
            task_id="task-valid-matroska", artifact_id="valid-matroska"
        )
        self.assertEqual(
            self.root / "tasks" / "task-valid-matroska.json",
            create_task(self.root, valid),
        )

    def test_declared_data_and_document_media_kinds_have_closed_mappings(self):
        """Catches fail-closed media validation making declared non-AV kinds unusable."""
        valid = (
            ("pdf-document", "media/pdf-document.pdf", "document", "application/pdf"),
            ("text-document", "media/text-document.txt", "document", "text/plain"),
            ("markdown-document", "media/markdown-document.md", "document", "text/markdown"),
            ("json-data", "media/json-data.json", "data", "application/json"),
            ("csv-data", "media/csv-data.csv", "data", "text/csv"),
            ("tsv-data", "media/tsv-data.tsv", "data", "text/tab-separated-values"),
        )
        for artifact_id, path, media_kind, mime_type in valid:
            self.create_artifact(
                artifact_id,
                "media",
                1,
                path=path,
                media_kind=media_kind,
                mime_type=mime_type,
            )
            with self.subTest(artifact_id=artifact_id):
                self.assertEqual(
                    self.root / "tasks" / f"task-{artifact_id}.json",
                    create_task(
                        self.root,
                        {
                            **self.envelope,
                            "task_id": f"task-{artifact_id}",
                            "inputs": [*self.envelope["inputs"], artifact_id],
                        },
                    ),
                )

    def test_image_result_requires_one_validated_compact_handoff(self):
        """Catches image payloads or absent handoffs crossing the task boundary."""
        self.create_image_context_artifacts()
        envelope = {
            **self.envelope,
            "task_id": "image-inspect-S03-v2",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        self.persist_legacy_envelope(envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        result = self.result_for(
            claim,
            task_id=envelope["task_id"],
            inputs=envelope["inputs"],
            artifacts=["image-preview-S03-v2"],
        )

        with self.assertRaisesRegex(ValueError, "image_handoff"):
            complete_task(self.root, result)

        with self.assertRaisesRegex(ValueError, "image payload"):
            complete_task(
                self.root,
                {
                    **result,
                    "image_handoff": {
                        "artifact_ids": result["artifacts"],
                        "image_bytes": "base64",
                    },
                },
            )

        handoff = {
            "artifact_ids": result["artifacts"],
            "paths": ["media/image-preview-S03-v2.png"],
            "summary": "Structural image QA complete.",
            "metadata": {"width": 1920, "height": 1080},
            "issues": [],
            "status": "succeeded",
            "review_previews": ["previews/image-preview-S03-v2.jpg"],
        }
        self.assertEqual(
            "completed",
            complete_task(self.root, {**result, "image_handoff": handoff}),
        )

    def test_image_result_scrubs_the_entire_persisted_envelope(self):
        """Catches coordinator-visible result fields bypassing image leak checks."""
        self.create_image_context_artifacts()
        leaks = (
            ("checks", ["verified", "preview=(https://example.invalid/review.png)"]),
            ("warnings", ["payload=data:image/png;base64,AAEC"]),
            ("error", "prompt history: first, second"),
            ("user_decision_request", "preview=https://example.invalid/review.png"),
        )
        for index, (field, value) in enumerate(leaks, 1):
            task_id = f"image-result-leak-{index}"
            envelope = {
                **self.envelope,
                "task_id": task_id,
                "capability": "structure.validate",
                "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
                "constraints": {
                    **self.legacy_constraints(),
                    "image_operation": "image-inspect",
                    "image_context": self.image_context(),
                },
            }
            self.persist_legacy_envelope(envelope)
            claim = claim_task(self.root, task_id, "worker-a")
            result = {
                **self.result_for(
                    claim,
                    task_id=task_id,
                    inputs=envelope["inputs"],
                    artifacts=["image-preview-S03-v2"],
                ),
                field: value,
                "image_handoff": {
                    "artifact_ids": ["image-preview-S03-v2"],
                    "paths": ["media/image-preview-S03-v2.png"],
                    "summary": "Structural image inspection complete.",
                    "status": "succeeded",
                },
            }
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "payload|prompt history|URL|scheme"
            ):
                complete_task(self.root, result)

    def test_image_result_budgets_the_full_persisted_envelope(self):
        """Catches compact handoffs hiding an oversized coordinator result envelope."""
        self.create_image_context_artifacts()
        task_id = "image-result-full-budget"
        envelope = {
            **self.envelope,
            "task_id": task_id,
            "capability": "structure.validate",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.legacy_constraints(),
                "image_operation": "image-inspect",
                "image_context": {**self.image_context(), "context_budget": 512},
            },
        }
        self.persist_legacy_envelope(envelope)
        claim = claim_task(self.root, task_id, "worker-a")
        result = {
            **self.result_for(
                claim,
                task_id=task_id,
                inputs=envelope["inputs"],
                artifacts=["image-preview-S03-v2"],
            ),
            "checks": ["structural-check-" + "x" * 400],
            "image_handoff": {
                "artifact_ids": ["image-preview-S03-v2"],
                "paths": ["media/image-preview-S03-v2.png"],
                "summary": "Structural image inspection complete.",
                "status": "succeeded",
            },
        }

        with self.assertRaisesRegex(ValueError, "context budget"):
            complete_task(self.root, result)

    def test_nonvisual_completion_rejects_a_visual_artifact(self):
        """Catches a visual output emerging from a task declared non-visual."""
        self.create_artifact(
            "scene-image-output-v1",
            "scene-image",
            1,
            path="media/scene-image-output-v1.png",
            historical=False,
            output_contract="project-plan-v1",
        )
        non_image_scene = self.non_visual_envelope(
            task_id="non-image-scene-output"
        )
        create_task(self.root, non_image_scene)
        non_image_claim = claim_task(self.root, non_image_scene["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "visual media"):
            complete_task(
                self.root,
                {
                    "task_id": non_image_scene["task_id"],
                    "status": "succeeded",
                    "inputs": non_image_scene["inputs"],
                    "artifacts": ["scene-image-output-v1"],
                    "checks": [],
                    "warnings": [],
                    **non_image_claim,
                },
            )

    def test_current_visual_completion_enforces_operation_output_kinds(self):
        """Catches lifecycle completion crossing image/video output contracts."""

        def handoff(artifact_id, kind, suffix):
            return {
                "artifact_ids": [artifact_id],
                "paths": [f"media/{artifact_id}.{suffix}"],
                "media": {"kind": kind, "format": suffix},
                "checks": [],
                "issues": [],
                "summary": "Visual output is ready.",
                "review_preview_path": None,
            }

        rejected = (
            *((operation, "motion-preview-S03-v2", "video", "mp4") for operation in (
                "image-generate",
                "image-edit",
                "image-inspect",
            )),
            *((operation, "image-preview-S03-v2", "image", "png") for operation in (
                "video-generate",
                "video-edit",
                "video-render",
                "video-inspect",
            )),
        )
        for index, (operation, artifact_id, kind, suffix) in enumerate(rejected, 1):
            task = self.visual_envelope(
                task_id=f"output-kind-rejected-{index}",
                operation=operation,
            )
            create_task(self.root, task)
            claim = claim_task(self.root, task["task_id"], "worker-a")
            result = self.result_for(
                claim,
                task_id=task["task_id"],
                artifacts=[artifact_id],
                visual_media_handoff=handoff(artifact_id, kind, suffix),
            )
            with self.subTest(operation=operation), self.assertRaisesRegex(
                ValueError, "cannot return|cannot declare"
            ):
                complete_task(self.root, result)

        for index, operation in enumerate(("frame-extract", "contact-sheet"), 1):
            task = self.visual_envelope(
                task_id=f"image-output-accepted-{index}",
                operation=operation,
            )
            create_task(self.root, task)
            claim = claim_task(self.root, task["task_id"], "worker-a")
            self.assertEqual(
                "completed",
                complete_task(
                    self.root,
                    self.result_for(
                        claim,
                        task_id=task["task_id"],
                        artifacts=["image-preview-S03-v2"],
                        visual_media_handoff=handoff(
                            "image-preview-S03-v2", "image", "png"
                        ),
                    ),
                ),
            )

        self.create_artifact(
            "malformed-media-output-v1",
            "media",
            1,
            path="media/malformed-media-output-v1.wav",
            media_kind="video",
            mime_type="video/mp4",
            output_contract="motion-preview-v1",
        )
        malformed_task = {**self.envelope, "task_id": "malformed-media-output"}
        create_task(self.root, malformed_task)
        malformed_claim = claim_task(self.root, malformed_task["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "suffix|conflicts"):
            complete_task(
                self.root,
                {
                    **self.result_for(malformed_claim),
                    "task_id": malformed_task["task_id"],
                    "artifacts": ["malformed-media-output-v1"],
                },
            )

    def test_successful_visual_producer_requires_a_visual_output_and_typed_kind(self):
        """Catches completion succeeding with only a report or an untyped handoff."""
        self.create_artifact(
            "render-report-v1",
            "report",
            1,
            output_contract="motion-preview-v1",
        )
        report_only = self.visual_envelope(
            task_id="producer-report-only", operation="video-render"
        )
        create_task(self.root, report_only)
        report_claim = claim_task(self.root, report_only["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "at least one|visual output"):
            complete_task(
                self.root,
                self.result_for(
                    report_claim,
                    task_id=report_only["task_id"],
                    artifacts=["render-report-v1"],
                    visual_media_handoff={
                        "artifact_ids": ["render-report-v1"],
                        "paths": ["media/render-report-v1.json"],
                        "media": {"kind": "video"},
                        "checks": [],
                        "issues": [],
                        "summary": "Render report only.",
                        "review_preview_path": None,
                    },
                ),
            )

        untyped = self.visual_envelope(
            task_id="producer-untyped-kind", operation="video-render"
        )
        create_task(self.root, untyped)
        untyped_claim = claim_task(self.root, untyped["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "media.kind|handoff"):
            complete_task(
                self.root,
                self.result_for(
                    untyped_claim,
                    task_id=untyped["task_id"],
                    visual_media_handoff={
                        "artifact_ids": ["motion-preview-S03-v2"],
                        "paths": ["media/motion-preview-S03-v2.mp4"],
                        "media": {},
                        "checks": [],
                        "issues": [],
                        "summary": "Render completed.",
                        "review_preview_path": None,
                    },
                ),
            )

    def test_completion_rejects_output_artifact_with_unknown_extension_side_channel(self):
        """Catches completion trusting a typed-looking field added out of band."""
        path = (
            self.root
            / "artifacts"
            / "visual-preview"
            / "motion-preview-S03-v2.json"
        )
        record = json.loads(path.read_text(encoding="utf-8"))
        record["checksum_backup"] = "A" * 64
        path.write_text(json.dumps(record), encoding="utf-8")
        create_task(self.root, self.envelope)
        claim = claim_task(self.root, self.envelope["task_id"], "worker-a")

        with self.assertRaisesRegex(ValueError, "artifact|output"):
            complete_task(self.root, self.result_for(claim))

    def test_current_inspection_completion_is_report_only(self):
        """Catches inspection minting visual output instead of compact report metadata."""
        self.create_artifact(
            "inspection-report-v1",
            "report",
            1,
            output_contract="motion-preview-v1",
        )
        report_task = self.visual_envelope(
            task_id="image-inspect-report-only", operation="image-inspect"
        )
        create_task(self.root, report_task)
        report_claim = claim_task(self.root, report_task["task_id"], "worker-a")
        self.assertEqual(
            "completed",
            complete_task(
                self.root,
                self.result_for(
                    report_claim,
                    task_id=report_task["task_id"],
                    artifacts=["inspection-report-v1"],
                    visual_media_handoff={
                        "artifact_ids": ["inspection-report-v1"],
                        "paths": ["media/inspection-report-v1.json"],
                        "media": {},
                        "checks": [],
                        "issues": [],
                        "summary": "Inspection report ready.",
                        "review_preview_path": None,
                    },
                ),
            ),
        )

        visual_task = self.visual_envelope(
            task_id="image-inspect-visual-output", operation="image-inspect"
        )
        create_task(self.root, visual_task)
        visual_claim = claim_task(self.root, visual_task["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "report-only"):
            complete_task(
                self.root,
                self.result_for(
                    visual_claim,
                    task_id=visual_task["task_id"],
                    artifacts=["image-preview-S03-v2"],
                    visual_media_handoff={
                        "artifact_ids": ["image-preview-S03-v2"],
                        "paths": ["media/image-preview-S03-v2.png"],
                        "media": {"kind": "image"},
                        "checks": [],
                        "issues": [],
                        "summary": "Unexpected visual output.",
                        "review_preview_path": None,
                    },
                ),
            )

        generation_context = {
            "scope_identity": {
                "kind": "scene-contract",
                "id": "scene-contract-S03-v4",
            },
            "allowed_image_artifact_ids": [],
            "allowed_character_pack_ids": [],
            "forbidden_scene_image_access": True,
            "max_review_previews": 0,
            "context_budget": 4096,
        }
        generation_task = {
            **self.envelope,
            "task_id": "image-generation-without-image-output",
            "capability": "scene.produce",
            "constraints": {
                **self.legacy_constraints(),
                "visual_operation": "image-generation",
                "image_operation": "generate",
                "image_context": generation_context,
            },
        }
        self.persist_legacy_envelope(generation_task)
        generation_claim = claim_task(self.root, generation_task["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "generate.*image|image.*generate"):
            complete_task(
                self.root,
                {
                    **self.result_for(
                        generation_claim, task_id=generation_task["task_id"]
                    ),
                    "image_handoff": {
                        "artifact_ids": ["motion-preview-S03-v2"],
                        "paths": ["media/motion-preview-S03-v2.mp4"],
                        "summary": "Generation returned metadata only.",
                        "status": "succeeded",
                    },
                },
            )

    def test_non_image_result_cannot_attach_an_image_handoff(self):
        """Catches generic workers smuggling image metadata through an optional field."""
        envelope = self.non_visual_envelope(task_id="non-visual-with-image-handoff")
        create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "non-visual"):
            complete_task(
                self.root,
                {
                    "task_id": envelope["task_id"],
                    "status": "blocked",
                    "inputs": envelope["inputs"],
                    "artifacts": [],
                    "checks": [],
                    "warnings": [],
                    **claim,
                    "image_handoff": {"artifact_ids": ["motion-contract-S03-v1"]},
                },
            )

    def test_second_worker_cannot_claim_same_task(self):
        """Catches two workers executing the same isolated task concurrently."""
        self.dispatch_and_claim()

        with self.assertRaises(RuntimeError):
            claim_task(self.root, "preview-S03-v2", "worker-b")

    def test_concurrent_claims_choose_one_worker(self):
        """Catches a claim race giving two workers valid completion authority."""
        create_task(self.root, self.envelope)
        barrier = Barrier(2)

        def claim(worker_id):
            barrier.wait()
            try:
                return claim_task(self.root, "preview-S03-v2", worker_id)
            except RuntimeError:
                return "locked"

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(claim, ("worker-a", "worker-b")))

        self.assertEqual(1, sum(isinstance(claim, dict) for claim in claims))
        self.assertEqual(1, claims.count("locked"))

    def test_claim_rejects_unsafe_worker_id_before_writing_a_claim(self):
        """Catches a worker ID that can claim work but can never complete it safely."""
        create_task(self.root, self.envelope)

        with self.assertRaises(ValueError):
            claim_task(self.root, "preview-S03-v2", "gopher:worker")

        self.assertFalse((self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists())

    def test_completion_requires_the_active_worker_and_claim_token(self):
        """Catches a non-owner completing a task and deleting the real worker's claim."""
        claim = self.dispatch_and_claim("worker-a")

        with self.assertRaises(RuntimeError):
            complete_task(self.root, self.result_for({**claim, "worker_id": "worker-b"}))

        self.assertTrue((self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists())
        self.assertEqual("completed", complete_task(self.root, self.result_for(claim)))

    def test_completed_task_cannot_be_claimed_again(self):
        """Catches a post-completion worker re-claiming an already registered task."""
        claim = self.dispatch_and_claim()
        complete_task(self.root, self.result_for(claim))

        with self.assertRaises(RuntimeError):
            claim_task(self.root, "preview-S03-v2", "worker-b")

    def test_dead_claim_is_reclaimed_without_authorizing_displaced_worker(self):
        """Catches an interrupted worker permanently locking a task or later publishing its result."""
        old_claim = self.dispatch_and_claim("worker-a")
        lock_path = self.root / "tasks" / "locks" / "preview-S03-v2.lock"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["pid"] = 999999
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        with patch("scripts.toolkit.tasks._pid_is_alive", return_value=False):
            new_claim = claim_task(self.root, "preview-S03-v2", "worker-b")

        with self.assertRaises(RuntimeError):
            complete_task(self.root, self.result_for(old_claim))
        self.assertEqual("completed", complete_task(self.root, self.result_for(new_claim)))

    def test_expired_lease_does_not_reclaim_a_live_worker_claim(self):
        """Catches a long-running live worker losing exclusive completion authority at 300 seconds."""
        self.dispatch_and_claim("worker-a")
        lock_path = self.root / "tasks" / "locks" / "preview-S03-v2.lock"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["lease_expires_at"] = 0
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        with self.assertRaises(RuntimeError):
            claim_task(self.root, "preview-S03-v2", "worker-b")

    def test_late_result_cannot_supersede_new_approved_input_lineage(self):
        """Catches an approved v5 lineage leaving a v4 task result eligible to publish."""
        claim = self.dispatch_and_claim()
        self.create_artifact(
            "scene-contract-S03-v5",
            "scene-contract",
            5,
            parents=["scene-contract-S03-v4"],
        )

        status = complete_task(self.root, self.result_for(claim))

        self.assertEqual("stale-result", status)
        self.assertEqual(
            self.result_for(claim),
            json.loads(
                (self.root / "tasks" / "stale-results" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        self.assertFalse((self.root / "tasks" / "results" / "preview-S03-v2.json").exists())

    def test_late_result_is_stale_after_a_new_real_timing_is_published(self):
        """Catches completion reusing timing that ceased to be current after dispatch."""
        claim = self.dispatch_and_claim()
        self.create_artifact(
            "voice-timing-v2",
            "voice-timing",
            2,
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=12000,
            segments=[{"start_ms": 0, "end_ms": 12000, "text": "revised"}],
            keyword_anchors=[],
        )

        self.assertEqual("stale-result", complete_task(self.root, self.result_for(claim)))

    def test_late_result_is_stale_after_a_new_narration_is_published(self):
        """Catches completion deriving narration authority from the task's old timing."""
        claim = self.dispatch_and_claim()
        self.create_artifact(
            "narration-v2",
            "narration",
            2,
            parents=["narration-v1"],
        )

        self.assertEqual("stale-result", complete_task(self.root, self.result_for(claim)))

    def test_stale_result_is_terminal_and_repeated_completion_leaves_no_claim(self):
        """Catches a second stale publication colliding and trapping a reclaimed task lock."""
        claim = self.dispatch_and_claim()
        self.create_artifact(
            "scene-contract-S03-v5",
            "scene-contract",
            5,
            parents=["scene-contract-S03-v4"],
        )
        result = self.result_for(claim)

        self.assertEqual("stale-result", complete_task(self.root, result))
        with self.assertRaises(RuntimeError):
            complete_task(self.root, result)
        with self.assertRaises(RuntimeError):
            claim_task(self.root, "preview-S03-v2", "worker-b")
        self.assertFalse((self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists())

    def test_interrupted_stale_publication_releases_the_terminal_claim(self):
        """Catches an interrupt after stale output publication leaving a reclaimable lock behind."""
        claim = self.dispatch_and_claim()
        self.create_artifact(
            "scene-contract-S03-v5",
            "scene-contract",
            5,
            parents=["scene-contract-S03-v4"],
        )
        publish = tasks._publish_immutable_json

        def publish_then_interrupt(destination, payload):
            publish(destination, payload)
            raise KeyboardInterrupt

        with patch("scripts.toolkit.tasks._publish_immutable_json", side_effect=publish_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                complete_task(self.root, self.result_for(claim))

        self.assertTrue((self.root / "tasks" / "stale-results" / "preview-S03-v2.json").exists())
        self.assertFalse((self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists())

    def test_result_with_different_input_versions_is_stale(self):
        """Catches a worker returning results for inputs other than its immutable envelope."""
        claim = self.dispatch_and_claim()
        result = self.result_for(claim, inputs=["scene-contract-S03-v5", *self.inputs[1:]])

        self.assertEqual("stale-result", complete_task(self.root, result))

    def test_current_result_is_registered_at_task_result_path(self):
        """Catches a valid task result being discarded instead of made available to the coordinator."""
        claim = self.dispatch_and_claim()
        result = self.result_for(claim)

        self.assertEqual("completed", complete_task(self.root, result))
        self.assertEqual(
            result,
            json.loads(
                (self.root / "tasks" / "results" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

    def test_only_succeeded_results_are_terminal(self):
        """Catches wait, failure, cancellation, or blocker checkpoints preventing resume."""
        for status in ("blocked", "waiting_external", "waiting_user", "failed", "cancelled"):
            with self.subTest(status=status), TemporaryDirectory() as folder:
                root = Path(folder)
                shutil.copytree(self.root / "artifacts", root / "artifacts")
                shutil.copytree(self.root / "media", root / "media")
                create_task(root, self.envelope)
                claim = claim_task(root, "preview-S03-v2", "worker-a")
                checkpoint = self.result_for(
                    claim,
                    status=status,
                    artifacts=[],
                    error="adapter_error" if status in {"blocked", "failed", "cancelled"} else None,
                    user_decision_request="choose a direction" if status == "waiting_user" else None,
                )
                checkpoint = {key: value for key, value in checkpoint.items() if value is not None}
                checkpoint["visual_media_handoff"] = {
                    "artifact_ids": [],
                    "paths": [],
                    "media": {},
                    "checks": [],
                    "issues": [],
                    "summary": "Visual task checkpoint recorded.",
                    "review_preview_path": None,
                }

                self.assertEqual("resumable", complete_task(root, checkpoint))
                self.assertFalse((root / "tasks" / "results" / "preview-S03-v2.json").exists())
                self.assertTrue((root / "tasks" / "status" / "preview-S03-v2.json").is_file())
                resumed = claim_task(root, "preview-S03-v2", "worker-b")
                self.assertEqual("worker-b", resumed["worker_id"])

    def test_returned_artifacts_must_exist_and_match_the_envelope_output_contract(self):
        """Catches a succeeded or waiting result publishing invented or wrong-contract output IDs."""
        claim = self.dispatch_and_claim()
        with self.assertRaises(ValueError):
            complete_task(
                self.root,
                self.result_for(claim, status="waiting_external", artifacts=["missing-preview"]),
            )
        self.assertTrue((self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists())

        create_artifact(
            self.root,
            {
                "artifact_id": "wrong-contract-preview",
                "type": "visual-preview",
                "version": 1,
                "status": "approved",
                "parents": self.inputs,
                "path": "media/wrong-contract-preview.json",
                "output_contract": "different-preview-v1",
            },
        )
        with self.assertRaises(ValueError):
            complete_task(
                self.root,
                self.result_for(claim, artifacts=["wrong-contract-preview"]),
            )
        self.assertTrue((self.root / "tasks" / "locks" / "preview-S03-v2.lock").exists())

    def test_succeeded_result_requires_at_least_one_returned_artifact(self):
        """Catches a success marker terminating work without its contracted output."""
        claim = self.dispatch_and_claim()

        with self.assertRaises(ValueError):
            complete_task(self.root, self.result_for(claim, artifacts=[]))

    def test_retry_ledger_enforces_two_attempts_then_one_declared_fallback(self):
        """Catches retry state resetting and repeatedly returning to an earlier adapter."""
        create_task(self.root, self.envelope)

        self.assertEqual(
            {"action": "retry", "adapter": "hyperframes"},
            retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"}),
        )
        self.assertEqual(
            {"action": "switch-adapter", "adapter": "remotion"},
            retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"}),
        )
        self.assertEqual(
            {"action": "retry", "adapter": "remotion"},
            retry_decision(self.root, "preview-S03-v2", {"error": "contract_error"}),
        )
        self.assertEqual(
            {"action": "block", "reason": "retry-budget-exhausted"},
            retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"}),
        )
        self.assertEqual(
            {"hyperframes": 2, "remotion": 2},
            json.loads(
                (self.root / "tasks" / "retries" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            )["attempts"],
        )

    def test_terminal_retry_call_does_not_consume_a_third_attempt(self):
        """Catches a duplicate terminal failure growing an adapter count beyond its cap."""
        create_task(self.root, self.envelope)
        for _ in range(2):
            retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"})
        for _ in range(2):
            retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"})

        self.assertEqual(
            {"action": "block", "reason": "retry-budget-exhausted"},
            retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"}),
        )
        self.assertEqual(
            2,
            json.loads(
                (self.root / "tasks" / "retries" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            )["attempts"]["remotion"],
        )

    def test_retry_uses_only_adapters_declared_by_immutable_envelope(self):
        """Catches a caller injecting an adapter outside the task's declared fallback list."""
        create_task(self.root, self.envelope)

        with self.assertRaises(ValueError):
            retry_decision(
                self.root,
                "preview-S03-v2",
                {"error": "adapter_error", "adapter": "untrusted-renderer"},
            )

    def test_retry_skips_a_preferred_adapter_incompatible_with_the_task_capability(self):
        """Catches motion.preview switching from Hyperframes to VideoShotCraft."""
        envelope = {
            **self.envelope,
            "task_id": "preview-compatible-fallback",
            "adapter_preferences": ["hyperframes", "video-shotcraft", "remotion"],
        }
        create_task(self.root, envelope)

        self.assertEqual(
            {"action": "retry", "adapter": "hyperframes"},
            retry_decision(
                self.root, "preview-compatible-fallback", {"error": "adapter_error"}
            ),
        )
        self.assertEqual(
            {"action": "switch-adapter", "adapter": "remotion"},
            retry_decision(
                self.root, "preview-compatible-fallback", {"error": "adapter_error"}
            ),
        )

    def test_retry_blocks_video_shotcraft_for_a_rendered_video_contract(self):
        """Catches retry bypassing the selected adapter's full routing contract."""
        envelope = {
            **self.envelope,
            "task_id": "produce-rendered-video",
            "capability": "motion.produce",
            "adapter_preferences": ["remotion", "video-shotcraft"],
            "output_contract": "rendered-video",
            "constraints": {
                **self.envelope["constraints"],
                "contract": "scene-contract-v1",
                "output": "rendered-video",
                "editable": True,
                "installed_skills": [
                    "remotion-best-practices",
                    "video-shotcraft:video-shotcraft",
                ],
            },
        }
        create_task(self.root, envelope)

        self.assertEqual(
            {"action": "retry", "adapter": "remotion"},
            retry_decision(
                self.root, "produce-rendered-video", {"error": "adapter_error"}
            ),
        )
        self.assertEqual(
            {"action": "block", "reason": "no-fallback-adapter"},
            retry_decision(
                self.root, "produce-rendered-video", {"error": "adapter_error"}
            ),
        )

    def test_concurrent_retry_updates_do_not_lose_an_attempt(self):
        """Catches two failed attempts racing and both persisting an attempt count of one."""
        create_task(self.root, self.envelope)
        barrier = Barrier(2)

        def decide(_):
            barrier.wait()
            return retry_decision(self.root, "preview-S03-v2", {"error": "adapter_error"})

        with ThreadPoolExecutor(max_workers=2) as executor:
            decisions = list(executor.map(decide, range(2)))

        self.assertEqual({"retry", "switch-adapter"}, {decision["action"] for decision in decisions})
        self.assertEqual(
            2,
            json.loads(
                (self.root / "tasks" / "retries" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            )["attempts"]["hyperframes"],
        )

    def test_retry_requests_user_action_without_consuming_retry_budget(self):
        """Catches malformed inputs or missing direction being retried without user action."""
        create_task(self.root, self.envelope)

        self.assertEqual(
            {"action": "request-user-action", "reason": "input_error"},
            retry_decision(self.root, "preview-S03-v2", {"error": "input_error"}),
        )
        self.assertFalse((self.root / "tasks" / "retries" / "preview-S03-v2.json").exists())


if __name__ == "__main__":
    unittest.main()

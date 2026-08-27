import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from scripts.toolkit.artifacts import create_artifact
from scripts.toolkit import tasks
from scripts.toolkit.tasks import claim_task, complete_task, create_task, retry_decision


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.create_artifact("narration-v1", "narration", 1)
        self.create_artifact(
            "voice-source-v1",
            "voice-source-decision",
            1,
            narration_id="narration-v1",
            mode="tts",
            decision="approved",
        )
        self.create_artifact(
            "voice-profile-v1",
            "voice-profile",
            1,
            mode="tts",
            language="zh-CN",
            provider="chatcut",
            voice_id="narrator-1",
            speaking_rate=1.0,
            emotion="calm",
            pronunciations=[],
            approved=True,
        )
        self.create_artifact(
            "voiceover-v1",
            "voiceover",
            1,
            parents=["narration-v1", "voice-profile-v1"],
            narration_id="narration-v1",
            profile_id="voice-profile-v1",
            media_path="media/voiceover-v1.wav",
            duration_ms=12000,
            provenance="chatcut:voice",
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
            ),
        ]
        self.create_artifact(
            "motion-preview-S03-v2",
            "visual-preview",
            2,
            parents=self.inputs,
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
        return result

    def image_context(self):
        return {
            "allowed_image_artifact_ids": ["scene-S03-v1"],
            "allowed_character_pack_ids": ["host-pack-v1"],
            "forbidden_scene_image_access": True,
            "max_review_previews": 1,
            "context_budget": 4096,
        }

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
        """Catches non-scene tasks persisting an unknown reserved visual mode."""
        with self.assertRaisesRegex(ValueError, "visual_operation"):
            create_task(
                self.root,
                {
                    **self.envelope,
                    "task_id": "project-manage-bogus-visual",
                    "capability": "project.manage",
                    "constraints": {
                        **self.envelope["constraints"],
                        "visual_operation": "bogus",
                    },
                },
            )

    def test_image_operation_conditionally_requires_closed_context(self):
        """Catches image work starting without bounded immutable authority."""
        missing_context = {
            **self.envelope,
            "task_id": "image-inspect-without-context",
            "constraints": {
                **self.envelope["constraints"],
                "image_operation": "image-inspect",
            },
        }
        with self.assertRaisesRegex(ValueError, "image_context"):
            create_task(self.root, missing_context)

        context_without_operation = {
            **self.envelope,
            "task_id": "context-without-image-operation",
            "constraints": {
                **self.envelope["constraints"],
                "image_context": self.image_context(),
            },
        }
        with self.assertRaisesRegex(ValueError, "image_operation"):
            create_task(self.root, context_without_operation)

        null_context = {
            **self.envelope,
            "task_id": "null-image-context",
            "constraints": {
                **self.envelope["constraints"],
                "image_operation": "image-inspect",
                "image_context": None,
            },
        }
        with self.assertRaisesRegex(ValueError, "image_context"):
            create_task(self.root, null_context)

    def test_structure_validation_requires_an_exact_image_operation(self):
        """Catches structural validation silently acquiring image-inspection authority."""
        base = {
            **self.envelope,
            "capability": "structure.validate",
        }
        with self.assertRaisesRegex(ValueError, "image_operation"):
            create_task(self.root, {**base, "task_id": "structure-mode-missing"})

        legacy_inspect = {
            **base,
            "task_id": "structure-mode-legacy",
            "constraints": {**base["constraints"], "image_operation": "inspect"},
        }
        with self.assertRaisesRegex(ValueError, "image_operation"):
            create_task(self.root, legacy_inspect)

        image_without_context = {
            **base,
            "task_id": "structure-image-without-context",
            "constraints": {**base["constraints"], "image_operation": "image-inspect"},
        }
        with self.assertRaisesRegex(ValueError, "image_context"):
            create_task(self.root, image_without_context)

        structure_with_context = {
            **base,
            "task_id": "structure-only-with-context",
            "constraints": {
                **base["constraints"],
                "image_operation": "structure-only",
                "image_context": self.image_context(),
            },
        }
        with self.assertRaisesRegex(ValueError, "structure-only"):
            create_task(self.root, structure_with_context)

        structure_only = {
            **base,
            "task_id": "structure-only-valid",
            "constraints": {**base["constraints"], "image_operation": "structure-only"},
        }
        self.assertEqual(
            self.root / "tasks" / "structure-only-valid.json",
            create_task(self.root, structure_only),
        )

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
            create_task(self.root, image_inspect),
        )

    def test_create_and_claim_enforce_every_declared_image_access(self):
        """Catches metadata authorization existing only as an unused helper."""
        self.create_image_context_artifacts(historical=True)
        envelope = {
            **self.envelope,
            "task_id": "historical-scene-inspect",
            "inputs": [*self.envelope["inputs"], "scene-S03-v1", "host-pack-v1"],
            "constraints": {
                **self.envelope["constraints"],
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        with self.assertRaisesRegex(PermissionError, "historical scene image"):
            create_task(self.root, envelope)

        image_path = self.root / "artifacts" / "scene-image" / "scene-S03-v1.json"
        artifact = json.loads(image_path.read_text(encoding="utf-8"))
        artifact["historical"] = False
        image_path.write_text(json.dumps(artifact), encoding="utf-8")
        create_task(self.root, envelope)

        artifact["historical"] = True
        image_path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "historical scene image"):
            claim_task(self.root, envelope["task_id"], "worker-a")

        artifact.pop("historical")
        image_path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "explicit historical origin"):
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
        with self.assertRaisesRegex(PermissionError, "image_context"):
            create_task(self.root, without_context)

        empty_allowlist = {
            **self.envelope,
            "task_id": "image-input-outside-allowlist",
            "inputs": inputs,
            "constraints": {
                **self.envelope["constraints"],
                "image_operation": "image-inspect",
                "image_context": {
                    **self.image_context(),
                    "allowed_image_artifact_ids": [],
                },
            },
        }
        with self.assertRaisesRegex(PermissionError, "undeclared image"):
            create_task(self.root, empty_allowlist)

    def test_scene_production_requires_an_explicit_visual_operation(self):
        """Catches text-to-image work hiding behind the generic scene route."""
        scene_envelope = {
            **self.envelope,
            "task_id": "scene-without-visual-operation",
            "capability": "scene.produce",
        }
        with self.assertRaisesRegex(ValueError, "visual_operation"):
            create_task(self.root, scene_envelope)

        image_generation = {
            **scene_envelope,
            "task_id": "scene-image-without-context",
            "constraints": {
                **scene_envelope["constraints"],
                "visual_operation": "image-generation",
            },
        }
        with self.assertRaisesRegex(PermissionError, "image_context"):
            create_task(self.root, image_generation)

    def test_generic_media_input_requires_canonical_media_kind(self):
        """Catches unlisted image formats bypassing suffix-based classification."""
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
        with self.assertRaisesRegex(ValueError, "media_kind"):
            create_task(self.root, envelope)

        path = self.root / "artifacts" / "media" / "generic-media-v1.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["media_kind"] = "image"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "image_context"):
            create_task(self.root, {**envelope, "task_id": "generic-image-without-context"})

        self.create_artifact(
            "conflicting-media-v1",
            "media",
            1,
            path="media/conflicting-media-v1.png",
            media_kind="video",
            mime_type=" image/png",
            historical=False,
        )
        conflicting = {
            **self.envelope,
            "task_id": "conflicting-media-kind",
            "inputs": [*self.envelope["inputs"], "conflicting-media-v1"],
        }
        with self.assertRaisesRegex(ValueError, "canonical mime_type|image suffix"):
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
                ValueError, "suffix|extension"
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
            )
            envelope = {
                **self.envelope,
                "task_id": f"task-{artifact_id}",
                "inputs": [*self.envelope["inputs"], artifact_id],
            }
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
            with self.subTest(artifact_id=artifact_id), self.assertRaisesRegex(
                ValueError, "suffix|extension"
            ):
                create_task(
                    self.root,
                    {
                        **self.envelope,
                        "task_id": f"task-{artifact_id}",
                        "inputs": [*self.envelope["inputs"], artifact_id],
                    },
                )

        self.create_artifact(
            "valid-matroska",
            "media",
            1,
            path="media/valid-matroska.mkv",
            media_kind="video",
            mime_type="video/x-matroska",
        )
        valid = {
            **self.envelope,
            "task_id": "task-valid-matroska",
            "inputs": [*self.envelope["inputs"], "valid-matroska"],
        }
        self.assertEqual(
            self.root / "tasks" / "task-valid-matroska.json",
            create_task(self.root, valid),
        )

    def test_declared_data_and_document_media_kinds_have_closed_mappings(self):
        """Catches fail-closed media validation making declared non-AV kinds unusable."""
        valid = (
            ("pdf-document", "media/brief.pdf", "document", "application/pdf"),
            ("text-document", "media/notes.txt", "document", "text/plain"),
            ("markdown-document", "media/outline.md", "document", "text/markdown"),
            ("json-data", "media/manifest.json", "data", "application/json"),
            ("csv-data", "media/cues.csv", "data", "text/csv"),
            ("tsv-data", "media/cues.tsv", "data", "text/tab-separated-values"),
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
                **self.envelope["constraints"],
                "image_operation": "image-inspect",
                "image_context": self.image_context(),
            },
        }
        create_task(self.root, envelope)
        claim = claim_task(self.root, envelope["task_id"], "worker-a")
        result = self.result_for(claim)
        result["task_id"] = envelope["task_id"]
        result["inputs"] = envelope["inputs"]

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
            "paths": ["media/motion-preview-S03-v2.json"],
            "summary": "Structural image QA complete.",
            "metadata": {"width": 1920, "height": 1080},
            "issues": [],
            "status": "succeeded",
            "review_previews": ["previews/motion-preview-S03-v2.jpg"],
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
                    **self.envelope["constraints"],
                    "image_operation": "image-inspect",
                    "image_context": self.image_context(),
                },
            }
            create_task(self.root, envelope)
            claim = claim_task(self.root, task_id, "worker-a")
            result = {
                **self.result_for(claim),
                "task_id": task_id,
                "inputs": envelope["inputs"],
                field: value,
                "image_handoff": {
                    "artifact_ids": ["motion-preview-S03-v2"],
                    "paths": ["media/motion-preview-S03-v2.json"],
                    "summary": "Structural image inspection complete.",
                    "status": "succeeded",
                },
            }
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "image payload|prompt history"
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
                **self.envelope["constraints"],
                "image_operation": "image-inspect",
                "image_context": {**self.image_context(), "context_budget": 512},
            },
        }
        create_task(self.root, envelope)
        claim = claim_task(self.root, task_id, "worker-a")
        result = {
            **self.result_for(claim),
            "task_id": task_id,
            "inputs": envelope["inputs"],
            "checks": ["structural-check-" + "x" * 400],
            "image_handoff": {
                "artifact_ids": ["motion-preview-S03-v2"],
                "paths": ["media/motion-preview-S03-v2.json"],
                "summary": "Structural image inspection complete.",
                "status": "succeeded",
            },
        }

        with self.assertRaisesRegex(ValueError, "context budget"):
            complete_task(self.root, result)

    def test_completion_classifies_every_produced_artifact_against_the_operation(self):
        """Catches image outputs or malformed media emerging from incompatible tasks."""
        self.create_artifact(
            "scene-image-output-v1",
            "scene-image",
            1,
            path="media/scene-image-output-v1.png",
            historical=False,
            output_contract="motion-preview-v1",
        )
        non_image_scene = {
            **self.envelope,
            "task_id": "non-image-scene-output",
            "capability": "scene.produce",
            "constraints": {
                **self.envelope["constraints"],
                "visual_operation": "non-image",
            },
        }
        create_task(self.root, non_image_scene)
        non_image_claim = claim_task(self.root, non_image_scene["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "image artifact|image operation|non-image"):
            complete_task(
                self.root,
                {
                    **self.result_for(non_image_claim),
                    "task_id": non_image_scene["task_id"],
                    "artifacts": ["scene-image-output-v1"],
                },
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
        with self.assertRaisesRegex(ValueError, "suffix"):
            complete_task(
                self.root,
                {
                    **self.result_for(malformed_claim),
                    "task_id": malformed_task["task_id"],
                    "artifacts": ["malformed-media-output-v1"],
                },
            )

        generation_context = {
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
                **self.envelope["constraints"],
                "visual_operation": "image-generation",
                "image_operation": "generate",
                "image_context": generation_context,
            },
        }
        create_task(self.root, generation_task)
        generation_claim = claim_task(self.root, generation_task["task_id"], "worker-a")
        with self.assertRaisesRegex(ValueError, "generate.*image|image.*generate"):
            complete_task(
                self.root,
                {
                    **self.result_for(generation_claim),
                    "task_id": generation_task["task_id"],
                    "image_handoff": {
                        "artifact_ids": ["motion-preview-S03-v2"],
                        "paths": ["media/motion-preview-S03-v2.json"],
                        "summary": "Generation returned metadata only.",
                        "status": "succeeded",
                    },
                },
            )

    def test_non_image_result_cannot_attach_an_image_handoff(self):
        """Catches generic workers smuggling image metadata through an optional field."""
        claim = self.dispatch_and_claim()
        with self.assertRaisesRegex(ValueError, "non-image"):
            complete_task(
                self.root,
                {
                    **self.result_for(claim),
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
                "contract": "scene-contract-v1",
                "output": "rendered-video",
                "editable": True,
                "installed_skills": [
                    "remotion-best-practices",
                    "video-shotcraft:video-shotcraft",
                ],
                "voice_timing_id": "voice-timing-v1",
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

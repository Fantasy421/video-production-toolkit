import json
from pathlib import Path
import shutil
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.toolkit.validation import validate_project
from tests.encoding_boundary_cases import (
    HARMLESS_PROSE_CONTROLS,
    STRUCTURAL_ENCODING_CASES,
    TYPED_CHECKSUM_TEXT_CONTROL,
    TYPED_SAFE_ID_CONTROL,
)


class PersistedVisualMediaValidationTests(unittest.TestCase):
    """Metadata-only recovery checks for immutable visual task records."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "artifacts").mkdir()
        (self.root / "approvals").mkdir()
        (self.root / "tasks").mkdir()
        (self.root / "events").mkdir()
        project = {
            "schema_version": 1,
            "project_id": "persisted-visual-validation",
            "workflow": "knowledge-video",
            "phase": "initialized",
        }
        (self.root / "project.json").write_text(
            json.dumps(project), encoding="utf-8"
        )
        initialized = {
            "event": "project.initialized",
            "schema_version": 1,
            "project_id": project["project_id"],
            "workflow": project["workflow"],
        }
        (self.root / "events" / "events.jsonl").write_text(
            json.dumps(initialized) + "\n", encoding="utf-8"
        )

    def tearDown(self):
        self.folder.cleanup()

    def write_task(self, task):
        path = self.root / "tasks" / f"{task['task_id']}.json"
        path.write_text(json.dumps(task), encoding="utf-8")
        return path

    def write_artifact(self, artifact_id, artifact_type, **metadata):
        artifact = {
            "artifact_id": artifact_id,
            "type": artifact_type,
            "version": 1,
            "status": "approved",
            "parents": [],
            "path": f"metadata/{artifact_id}.json",
            **metadata,
        }
        directory = self.root / "artifacts" / artifact_type
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{artifact_id}.json").write_text(
            json.dumps(artifact), encoding="utf-8"
        )
        return artifact

    def write_result(self, task_id, result, *, directory="results"):
        destination = self.root / "tasks" / directory / f"{task_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result), encoding="utf-8")
        return destination

    @staticmethod
    def scene_context(scene_id="scene-contract-S01-v1", *, allowed=None):
        return {
            "scope_identity": {"kind": "scene-contract", "id": scene_id},
            "allowed_artifact_ids": list(allowed or []),
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 0,
            "context_budget_bytes": 32_768,
        }

    def current_visual_task(self, *, task_id="visual-task", inputs=None, **constraints):
        values = {
            "visual_media_operation": "video-generate",
            "visual_media_context": self.scene_context(),
            "execution_context": "isolated-child-agent",
            **constraints,
        }
        return {
            "task_id": task_id,
            "capability": "visual.preview",
            "inputs": list(inputs or ["scene-contract-S01-v1"]),
            "adapter_preferences": ["chatcut"],
            "output_contract": "scene-video-v1",
            "constraints": values,
        }

    @staticmethod
    def result_for(task_id, artifact_ids, *, handoff=None, **extra):
        result = {
            "task_id": task_id,
            "status": "succeeded",
            "inputs": ["scene-contract-S01-v1"],
            "artifacts": list(artifact_ids),
            "checks": [],
            "warnings": [],
            "worker_id": "isolated-worker",
            "claim_token": "claim-token",
            **extra,
        }
        if handoff is not None:
            result["visual_media_handoff"] = handoff
        return result

    @staticmethod
    def video_handoff(artifact_id="scene-output-v1"):
        return {
            "artifact_ids": [artifact_id],
            "paths": [f"media/{artifact_id}.mp4"],
            "media": {
                "kind": "video",
                "format": "mp4",
                "mime_type": "video/mp4",
            },
            "checks": [],
            "issues": [],
            "summary": "ready",
            "review_preview_path": None,
        }

    def assert_validation_preserves(self, *paths):
        event_path = self.root / "events" / "events.jsonl"
        observed = (event_path, *paths)
        before = {path: path.read_bytes() for path in observed}
        result = validate_project(self.root)
        for path, contents in before.items():
            self.assertEqual(contents, path.read_bytes())
        return result

    def assert_only_issue_for(self, result, path, code):
        self.assertEqual(
            {code},
            {
                issue["code"]
                for issue in result["errors"]
                if issue.get("path") == path.relative_to(self.root).as_posix()
            },
        )

    @staticmethod
    def nonvisual_task(task_id, *, inputs=None):
        return {
            "task_id": task_id,
            "capability": "project.manage",
            "inputs": list(inputs or []),
            "adapter_preferences": ["chatcut"],
            "output_contract": "task-result-v1",
            "constraints": {"visual_media_operation": "none"},
        }

    @staticmethod
    def plain_result(task_id, *, status, inputs=None, artifacts=None):
        return {
            "task_id": task_id,
            "status": status,
            "inputs": list(inputs or []),
            "artifacts": list(artifacts or []),
            "checks": [],
            "warnings": [],
            "worker_id": "worker",
            "claim_token": "claim-token",
        }

    @staticmethod
    def legacy_video_task_without_scope():
        return {
            "task_id": "legacy-video-without-scope",
            "capability": "scene.produce",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "scene-video-v1",
            "constraints": {"visual_operation": "non-image"},
        }

    @staticmethod
    def legacy_image_context():
        return {
            "scope_identity": {
                "kind": "scene-contract",
                "id": "scene-contract-S01-v1",
            },
            "allowed_image_artifact_ids": [],
            "allowed_character_pack_ids": [],
            "forbidden_scene_image_access": True,
            "max_review_previews": 0,
            "context_budget": 1024,
        }

    def test_ambiguous_legacy_visual_task_is_blocked_without_history_rewrite(self):
        """Catches recovery granting visual authority to an unscoped old record."""
        path = self.write_task(self.legacy_video_task_without_scope())
        event_path = self.root / "events" / "events.jsonl"
        before_task = path.read_bytes()
        before_events = event_path.read_bytes()

        result = validate_project(self.root)

        self.assert_only_issue_for(result, path, "legacy-visual-task-blocked")
        self.assertEqual(before_task, path.read_bytes())
        self.assertEqual(before_events, event_path.read_bytes())

    def test_legacy_visual_task_missing_image_context_has_stable_blocked_issue(self):
        """Catches generic envelope validation hiding ambiguous legacy authority."""
        task = self.legacy_video_task_without_scope()
        task["task_id"] = "legacy-generate-without-context"
        task["constraints"] = {
            "visual_operation": "image-generation",
            "image_operation": "generate",
        }
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "legacy-visual-task-blocked")

    def test_clear_persisted_legacy_visual_authority_remains_readable(self):
        """Catches current-only enforcement removing explicit legacy compatibility."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        task = self.legacy_video_task_without_scope()
        task["task_id"] = "legacy-image-generation"
        task["inputs"] = ["scene-contract-S01-v1"]
        task["output_contract"] = "scene-image-v1"
        task["constraints"] = {
            "visual_operation": "image-generation",
            "image_operation": "generate",
            "image_context": self.legacy_image_context(),
        }
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assertNotIn(
            path.relative_to(self.root).as_posix(),
            {issue.get("path") for issue in result["errors"]},
        )

    def test_persisted_record_cannot_mix_current_and_deprecated_visual_authority(self):
        """Catches legacy compatibility broadening a current persisted record."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        task = self.current_visual_task(task_id="mixed-current-deprecated")
        task["constraints"]["visual_operation"] = "non-image"
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "invalid-task-envelope")

    def test_unsafe_tasks_parent_stops_all_result_directory_traversal(self):
        """Catches result recovery following a parent tasks symlink outside root."""
        shutil.rmtree(self.root / "tasks")
        with TemporaryDirectory() as outside_folder:
            outside_tasks = Path(outside_folder) / "tasks"
            (outside_tasks / "results").mkdir(parents=True)
            probe = outside_tasks / "results" / "foreign-probe.json"
            probe.write_text(json.dumps({"external_probe": True}), encoding="utf-8")
            before = probe.read_bytes()
            (self.root / "tasks").symlink_to(
                outside_tasks, target_is_directory=True
            )

            result = validate_project(self.root)

            self.assertEqual(before, probe.read_bytes())
        self.assertIn(
            {"code": "unsafe-runtime-storage", "storage": "tasks"},
            result["errors"],
        )
        self.assertNotIn(
            "tasks/results/foreign-probe.json",
            {issue.get("path") for issue in result["errors"]},
        )

    def test_nondirectory_tasks_storage_is_rejected(self):
        """Catches a regular file silently replacing the tasks storage boundary."""
        shutil.rmtree(self.root / "tasks")
        tasks_path = self.root / "tasks"
        tasks_path.write_text(json.dumps({"not": "task storage"}), encoding="utf-8")
        before = tasks_path.read_bytes()

        result = validate_project(self.root)

        self.assertEqual(before, tasks_path.read_bytes())
        self.assertIn(
            {"code": "unsafe-runtime-storage", "storage": "tasks"},
            result["errors"],
        )

    def test_malformed_visual_scope_has_stable_context_issue(self):
        """Catches recovery collapsing a malformed scope into a generic envelope error."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        task = self.current_visual_task()
        task["constraints"]["visual_media_context"]["scope_identity"] = {
            "kind": "whole-project",
            "id": "project-v1",
        }
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "visual-media-context-invalid")

    def test_visual_task_requires_isolated_child_during_recovery(self):
        """Catches recovery accepting coordinator execution for persisted visual work."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        task = self.current_visual_task(execution_context="primary-coordinator")
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "visual-media-isolation-required")

    def test_historical_scene_video_input_is_forbidden(self):
        """Catches historical scene footage being treated as character continuity."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        self.write_artifact(
            "scene-history-v1",
            "scene-video",
            path="media/scene-history-v1.mp4",
            media_kind="video",
            mime_type="video/mp4",
            historical=True,
        )
        context = self.scene_context(allowed=["scene-history-v1"])
        task = self.current_visual_task(
            inputs=["scene-contract-S01-v1", "scene-history-v1"],
            visual_media_context=context,
        )
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "visual-media-input-forbidden")

    def test_neighboring_scene_scope_is_forbidden(self):
        """Catches one child receiving authority over an adjacent scene contract."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        self.write_artifact("scene-contract-S02-v1", "scene-contract")
        task = self.current_visual_task(
            inputs=["scene-contract-S01-v1", "scene-contract-S02-v1"]
        )
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "visual-media-input-forbidden")

    def test_none_cannot_launder_a_visual_input(self):
        """Catches a persisted none discriminator hiding declared video authority."""
        self.write_artifact(
            "scene-input-v1",
            "scene-video",
            path="media/scene-input-v1.mp4",
            media_kind="video",
            mime_type="video/mp4",
            historical=False,
        )
        task = {
            "task_id": "none-with-video",
            "capability": "project.manage",
            "inputs": ["scene-input-v1"],
            "adapter_preferences": ["chatcut"],
            "output_contract": "task-result-v1",
            "constraints": {"visual_media_operation": "none"},
        }
        path = self.write_task(task)

        result = self.assert_validation_preserves(path)

        self.assert_only_issue_for(result, path, "visual-media-context-invalid")

    def test_undeclared_returned_media_has_stable_result_issue(self):
        """Catches recovery trusting visual output from a persisted non-visual task."""
        self.write_artifact(
            "scene-output-v1",
            "scene-video",
            path="media/scene-output-v1.mp4",
            media_kind="video",
            mime_type="video/mp4",
            historical=False,
            output_contract="task-result-v1",
        )
        task = {
            "task_id": "nonvisual-returned-video",
            "capability": "project.manage",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "task-result-v1",
            "constraints": {"visual_media_operation": "none"},
        }
        task_path = self.write_task(task)
        result_path = self.write_result(
            task["task_id"],
            {
                "task_id": task["task_id"],
                "status": "succeeded",
                "inputs": [],
                "artifacts": ["scene-output-v1"],
                "checks": [],
                "warnings": [],
                "worker_id": "worker",
                "claim_token": "claim-token",
            },
        )

        result = self.assert_validation_preserves(task_path, result_path)

        self.assert_only_issue_for(
            result, result_path, "visual-media-result-invalid"
        )

    def test_leaked_result_payload_has_stable_result_issue(self):
        """Catches recovery accepting embedded media payload fields from disk."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        self.write_artifact(
            "scene-output-v1",
            "scene-video",
            path="media/scene-output-v1.mp4",
            media_kind="video",
            mime_type="video/mp4",
            historical=False,
            output_contract="scene-video-v1",
        )
        task = self.current_visual_task(task_id="visual-result-payload")
        task_path = self.write_task(task)
        persisted_result = self.result_for(
            task["task_id"],
            ["scene-output-v1"],
            handoff=self.video_handoff(),
            video_payload="not-even-media-bytes",
        )
        result_path = self.write_result(task["task_id"], persisted_result)

        result = self.assert_validation_preserves(task_path, result_path)

        self.assert_only_issue_for(
            result, result_path, "visual-media-result-invalid"
        )

    def test_recovery_rejects_structural_encodings_in_persisted_result_text(self):
        """Catches recovery trusting fragmented or low-entropy encoded error text."""
        for index, (name, value) in enumerate(STRUCTURAL_ENCODING_CASES, 1):
            with self.subTest(name=name):
                task = self.nonvisual_task(f"encoded-result-{index}")
                task_path = self.write_task(task)
                result_path = self.write_result(
                    task["task_id"],
                    {
                        **self.plain_result(task["task_id"], status="failed"),
                        "error": value,
                    },
                    directory="status",
                )
                result = self.assert_validation_preserves(task_path, result_path)
                self.assert_only_issue_for(
                    result, result_path, "visual-media-result-invalid"
                )

        for index, (name, prose) in enumerate(HARMLESS_PROSE_CONTROLS):
            task_id = (
                TYPED_SAFE_ID_CONTROL
                if index == 0
                else f"safe-prose-result-{index + 1}"
            )
            safe_task = self.nonvisual_task(task_id)
            safe_task_path = self.write_task(safe_task)
            safe_result_path = self.write_result(
                safe_task["task_id"],
                {
                    **self.plain_result(safe_task["task_id"], status="failed"),
                    "checks": [TYPED_CHECKSUM_TEXT_CONTROL],
                    "warnings": [prose],
                    "error": prose,
                },
                directory="status",
            )
            with self.subTest(control=name):
                validation = self.assert_validation_preserves(
                    safe_task_path, safe_result_path
                )
                self.assertEqual(
                    [],
                    [
                        issue
                        for issue in validation["errors"]
                        if issue.get("path")
                        == safe_result_path.relative_to(self.root).as_posix()
                    ],
                )

    def test_valid_nonvisual_task_and_result_remain_recoverable(self):
        """Catches the visual recovery boundary rejecting ordinary compact results."""
        self.write_artifact(
            "report-v1", "report", output_contract="task-result-v1"
        )
        task = {
            "task_id": "manage-project",
            "capability": "project.manage",
            "inputs": [],
            "adapter_preferences": ["chatcut"],
            "output_contract": "task-result-v1",
            "constraints": {"visual_media_operation": "none"},
        }
        task_path = self.write_task(task)
        result_path = self.write_result(
            task["task_id"],
            {
                "task_id": task["task_id"],
                "status": "succeeded",
                "inputs": [],
                "artifacts": ["report-v1"],
                "checks": ["metadata-valid"],
                "warnings": [],
                "worker_id": "worker",
                "claim_token": "claim-token",
            },
        )

        result = self.assert_validation_preserves(task_path, result_path)

        self.assertNotIn(
            "visual-media-result-invalid",
            {issue["code"] for issue in result["errors"]},
        )

    def test_valid_isolated_visual_task_and_compact_result_remain_recoverable(self):
        """Catches persisted validation rejecting a lifecycle-valid visual handoff."""
        self.write_artifact("scene-contract-S01-v1", "scene-contract")
        self.write_artifact(
            "scene-output-v1",
            "scene-video",
            path="media/scene-output-v1.mp4",
            media_kind="video",
            mime_type="video/mp4",
            historical=False,
            output_contract="scene-video-v1",
        )
        task = self.current_visual_task(task_id="valid-visual-result")
        task_path = self.write_task(task)
        result_path = self.write_result(
            task["task_id"],
            self.result_for(
                task["task_id"],
                ["scene-output-v1"],
                handoff=self.video_handoff(),
            ),
        )

        result = self.assert_validation_preserves(task_path, result_path)

        self.assertNotIn(
            "visual-media-result-invalid",
            {issue["code"] for issue in result["errors"]},
        )

    def test_result_directories_reject_statuses_from_the_wrong_lifecycle(self):
        """Catches terminal and resumable records being accepted in either directory."""
        self.write_artifact(
            "report-v1", "report", output_contract="task-result-v1"
        )
        terminal_task = self.nonvisual_task("failed-in-results")
        resumable_task = self.nonvisual_task("success-in-status")
        terminal_task_path = self.write_task(terminal_task)
        resumable_task_path = self.write_task(resumable_task)
        failed_path = self.write_result(
            terminal_task["task_id"],
            self.plain_result(terminal_task["task_id"], status="failed"),
            directory="results",
        )
        succeeded_path = self.write_result(
            resumable_task["task_id"],
            self.plain_result(
                resumable_task["task_id"],
                status="succeeded",
                artifacts=["report-v1"],
            ),
            directory="status",
        )

        result = self.assert_validation_preserves(
            terminal_task_path,
            resumable_task_path,
            failed_path,
            succeeded_path,
        )

        self.assert_only_issue_for(
            result, failed_path, "visual-media-result-invalid"
        )
        self.assert_only_issue_for(
            result, succeeded_path, "visual-media-result-invalid"
        )

    def test_duplicate_task_result_across_directories_is_rejected(self):
        """Catches one task reaching conflicting persisted lifecycle states."""
        self.write_artifact(
            "report-v1", "report", output_contract="task-result-v1"
        )
        task = self.nonvisual_task("duplicate-result")
        task_path = self.write_task(task)
        result_path = self.write_result(
            task["task_id"],
            self.plain_result(
                task["task_id"],
                status="succeeded",
                artifacts=["report-v1"],
            ),
            directory="results",
        )
        status_path = self.write_result(
            task["task_id"],
            self.plain_result(task["task_id"], status="failed"),
            directory="status",
        )

        result = self.assert_validation_preserves(
            task_path, result_path, status_path
        )

        self.assert_only_issue_for(
            result, result_path, "visual-media-result-invalid"
        )
        self.assert_only_issue_for(
            result, status_path, "visual-media-result-invalid"
        )

    def test_malformed_duplicate_cannot_hide_a_conflicting_valid_result(self):
        """Catches duplicate detection trusting only an invalid record's body ID."""
        self.write_artifact(
            "report-v1", "report", output_contract="task-result-v1"
        )
        task = self.nonvisual_task("duplicate-malformed")
        task_path = self.write_task(task)
        result_path = self.write_result(
            task["task_id"],
            self.plain_result(
                task["task_id"],
                status="succeeded",
                artifacts=["report-v1"],
            ),
            directory="results",
        )
        status_path = self.write_result(
            task["task_id"], {}, directory="status"
        )

        result = self.assert_validation_preserves(
            task_path, result_path, status_path
        )

        self.assert_only_issue_for(
            result, result_path, "visual-media-result-invalid"
        )
        self.assert_only_issue_for(
            result, status_path, "visual-media-result-invalid"
        )

    def test_stale_result_requires_a_noncurrent_input(self):
        """Catches a current-input success being mislabeled as stale recovery."""
        self.write_artifact("input-v1", "input")
        self.write_artifact(
            "report-v1", "report", output_contract="task-result-v1"
        )
        task = self.nonvisual_task("fake-stale", inputs=["input-v1"])
        task_path = self.write_task(task)
        result_path = self.write_result(
            task["task_id"],
            self.plain_result(
                task["task_id"],
                status="succeeded",
                inputs=["input-v1"],
                artifacts=["report-v1"],
            ),
            directory="stale-results",
        )

        result = self.assert_validation_preserves(task_path, result_path)

        self.assert_only_issue_for(
            result, result_path, "visual-media-result-invalid"
        )

    def test_each_result_directory_accepts_its_legal_lifecycle_record(self):
        """Catches lifecycle placement checks rejecting valid persisted recovery."""
        self.write_artifact("stale-input-v1", "input", status="stale")
        for artifact_id in ("terminal-report-v1", "stale-report-v1"):
            self.write_artifact(
                artifact_id, "report", output_contract="task-result-v1"
            )
        terminal = self.nonvisual_task("terminal-result")
        resumable = self.nonvisual_task("resumable-status")
        stale = self.nonvisual_task(
            "real-stale-result", inputs=["stale-input-v1"]
        )
        task_paths = [self.write_task(task) for task in (terminal, resumable, stale)]
        result_paths = [
            self.write_result(
                terminal["task_id"],
                self.plain_result(
                    terminal["task_id"],
                    status="succeeded",
                    artifacts=["terminal-report-v1"],
                ),
                directory="results",
            ),
            self.write_result(
                resumable["task_id"],
                self.plain_result(resumable["task_id"], status="waiting_user"),
                directory="status",
            ),
            self.write_result(
                stale["task_id"],
                self.plain_result(
                    stale["task_id"],
                    status="succeeded",
                    inputs=["stale-input-v1"],
                    artifacts=["stale-report-v1"],
                ),
                directory="stale-results",
            ),
        ]

        result = self.assert_validation_preserves(*task_paths, *result_paths)

        self.assertFalse(
            {
                path.relative_to(self.root).as_posix()
                for path in result_paths
            }
            & {
                issue.get("path")
                for issue in result["errors"]
                if issue["code"] == "visual-media-result-invalid"
            }
        )


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
        self.write_project_history(1)

    def tearDown(self):
        self.folder.cleanup()

    def write_project_history(self, schema_version):
        phases = [
            "content_ready",
            "direction_ready",
            *(["voice_ready"] if schema_version == 2 else []),
            "storyboard_ready",
            "production_ready",
            "assembled",
            "review_ready",
        ]
        events = [
            {
                "event": "project.initialized",
                "schema_version": schema_version,
                "project_id": "validation-test",
                "workflow": "knowledge-video",
            },
            *(
                {"event": "project.phase_changed", "phase": phase}
                for phase in phases
            ),
        ]
        events_root = self.root / "events"
        events_root.mkdir(exist_ok=True)
        (events_root / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

    def write_upgraded_legacy_history(self):
        events = [
            {
                "event": "project.initialized",
                "schema_version": 1,
                "project_id": "validation-test",
                "workflow": "knowledge-video",
            },
            {"event": "project.phase_changed", "phase": "content_ready"},
            {"event": "project.phase_changed", "phase": "direction_ready"},
            {"event": "project.schema_upgraded", "schema_version": 2},
            {"event": "project.phase_changed", "phase": "voice_ready"},
            {"event": "project.phase_changed", "phase": "storyboard_ready"},
            {"event": "project.phase_changed", "phase": "production_ready"},
            {"event": "project.phase_changed", "phase": "assembled"},
            {"event": "project.phase_changed", "phase": "review_ready"},
        ]
        (self.root / "events" / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        project = json.loads((self.root / "project.json").read_text(encoding="utf-8"))
        project["schema_version"] = 2
        (self.root / "project.json").write_text(json.dumps(project), encoding="utf-8")

    def write_voice_bundle(self, *, include_timing_v2=False):
        self.write_artifact(
            "narration-v1", "narration", 1, "approved", "metadata/narration-v1.json"
        )
        self.write_artifact(
            "voice-source-v1",
            "voice-source-decision",
            1,
            "approved",
            "metadata/voice-source-v1.json",
            parents=["narration-v1"],
            narration_id="narration-v1",
            mode="tts",
            decision="approved",
            decision_provenance="user:source-v1",
        )
        self.write_artifact(
            "voice-profile-v1",
            "voice-profile",
            1,
            "approved",
            "metadata/voice-profile-v1.json",
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
        self.write_artifact(
            "voiceover-v1",
            "voiceover",
            1,
            "approved",
            "media/voiceover-v1.wav",
            parents=["narration-v1", "voice-source-v1", "voice-profile-v1"],
            narration_id="narration-v1",
            source_decision_id="voice-source-v1",
            mode="tts",
            profile_id="voice-profile-v1",
            media_path="media/voiceover-v1.wav",
            media_format="wav",
            duration_ms=10_000,
            provenance="test-fixture",
        )
        for version in range(1, 3 if include_timing_v2 else 2):
            self.write_artifact(
                f"voice-timing-v{version}",
                "voice-timing",
                version,
                "approved",
                f"metadata/voice-timing-v{version}.json",
                parents=["voiceover-v1"],
                voiceover_id="voiceover-v1",
                timing_kind="real",
                duration_ms=10_000,
                segments=[
                    {"start_ms": 0, "end_ms": 10_000, "text": f"timing {version}"}
                ],
            )

    def write_wav_header(self, relative, duration_ms):
        """Write a PCM header whose duration is readable without decoding samples."""
        sample_rate = 1_000
        channels = 1
        bytes_per_sample = 2
        frame_count = duration_ms
        data_size = frame_count * channels * bytes_per_sample
        (self.root / relative).write_bytes(
            b"RIFF"
            + struct.pack("<I", 36 + data_size)
            + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, sample_rate * channels * bytes_per_sample, channels * bytes_per_sample, 16)
            + b"data"
            + struct.pack("<I", data_size)
            + (b"\x00" * data_size)
        )

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

    def write_timed_semantic_graph(self):
        self.write_voice_bundle()
        self.write_artifact(
            "semantic-beats-v1",
            "semantic-beats",
            1,
            "approved",
            "metadata/semantic-beats-v1.json",
            parents=["narration-v1"],
            narration_id="narration-v1",
            beats=[
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
        )
        self.write_artifact(
            "timed-semantic-beats-v1",
            "timed-semantic-beats",
            1,
            "approved",
            "metadata/timed-semantic-beats-v1.json",
            parents=["semantic-beats-v1", "voice-timing-v1"],
            semantic_beats_id="semantic-beats-v1",
            voice_timing_id="voice-timing-v1",
            timing_kind="real",
            beats=[
                {
                    "beat_id": "B01",
                    "speech_start_ms": 1000,
                    "speech_end_ms": 2000,
                    "keyword_start_ms": 1200,
                    "keyword_end_ms": 1600,
                    "emphasis_ms": 1400,
                    "visual_window_ms": [1080, 1900],
                }
            ],
        )
        self.write_artifact(
            "scene-timing-contracts-v1",
            "scene-timing-contracts",
            1,
            "approved",
            "metadata/scene-timing-contracts-v1.json",
            parents=["timed-semantic-beats-v1"],
            timed_semantic_beats_id="timed-semantic-beats-v1",
            scenes=[
                {
                    "scene_id": "S01",
                    "scene_window_ms": [1000, 2000],
                    "beat_ids": ["B01"],
                    "primary_carrier": "motion-graphics",
                    "support_layer": "caption-emphasis",
                    "visual_window_ms": [1080, 1900],
                }
            ],
        )

    def timing_artifact_path(self, artifact_type, artifact_id):
        return self.root / "artifacts" / artifact_type / f"{artifact_id}.json"

    def test_timed_semantic_graph_requires_exact_approved_lineage(self):
        """Catches timing artifacts resolving to wrong parents, types, statuses, or beats."""
        cases = (
            (
                "semantic-narration-parent-missing",
                "semantic-beats",
                "semantic-beats-v1",
                lambda record: record.update({"parents": []}),
                "semantic-beats-lineage-mismatch",
            ),
            (
                "unapproved-semantic-source",
                "semantic-beats",
                "semantic-beats-v1",
                lambda record: record.update({"status": "draft"}),
                "timed-semantic-lineage-mismatch",
            ),
            (
                "semantic-parent-missing",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record.update({"parents": ["voice-timing-v1"]}),
                "timed-semantic-lineage-mismatch",
            ),
            (
                "wrong-voice-source-type",
                "voice-timing",
                "voice-timing-v1",
                lambda record: record.update({"type": "narration"}),
                "timed-semantic-lineage-mismatch",
            ),
            (
                "changed-timed-beat-id",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record["beats"][0].update({"beat_id": "B02"}),
                "timed-semantic-beat-ids-mismatch",
            ),
            (
                "missing-scene-parent",
                "scene-timing-contracts",
                "scene-timing-contracts-v1",
                lambda record: record.update({"parents": []}),
                "scene-timing-lineage-mismatch",
            ),
            (
                "scene-beat-outside-timed-source",
                "scene-timing-contracts",
                "scene-timing-contracts-v1",
                lambda record: record["scenes"][0].update({"beat_ids": ["B02"]}),
                "scene-timing-beat-ids-mismatch",
            ),
        )
        for name, artifact_type, artifact_id, mutate, expected in cases:
            with self.subTest(name=name):
                self.write_timed_semantic_graph()
                path = self.timing_artifact_path(artifact_type, artifact_id)
                record = json.loads(path.read_text(encoding="utf-8"))
                mutate(record)
                path.write_text(json.dumps(record), encoding="utf-8")

                result = validate_project(self.root)

                self.assertIn(expected, {item["code"] for item in result["errors"]})

    def test_timed_semantic_graph_rejects_duplicate_ids_and_invalid_windows(self):
        """Catches changed-content duplicate beat IDs and reversed or escaping windows."""
        cases = (
            (
                "changed-semantic-duplicate",
                "semantic-beats",
                "semantic-beats-v1",
                lambda record: record["beats"].append(
                    {**record["beats"][0], "intent": "supporting-detail"}
                ),
                "invalid-artifact-metadata",
            ),
            (
                "changed-timed-duplicate",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record["beats"].append(
                    {**record["beats"][0], "emphasis_ms": 1500}
                ),
                "invalid-artifact-metadata",
            ),
            (
                "reversed-speech-window",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record["beats"][0].update(
                    {"speech_start_ms": 2000, "speech_end_ms": 1000}
                ),
                "invalid-timed-semantic-timing",
            ),
            (
                "keyword-outside-speech",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record["beats"][0].update({"keyword_start_ms": 900}),
                "invalid-timed-semantic-timing",
            ),
            (
                "reversed-visual-window",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record["beats"][0].update(
                    {"visual_window_ms": [1900, 1080]}
                ),
                "invalid-timed-semantic-timing",
            ),
            (
                "scene-window-escape",
                "scene-timing-contracts",
                "scene-timing-contracts-v1",
                lambda record: record["scenes"][0].update(
                    {"visual_window_ms": [900, 2100]}
                ),
                "invalid-scene-timing-window",
            ),
            (
                "timed-window-outside-scene",
                "scene-timing-contracts",
                "scene-timing-contracts-v1",
                lambda record: record["scenes"][0].update(
                    {
                        "scene_window_ms": [1100, 1800],
                        "visual_window_ms": [1200, 1700],
                    }
                ),
                "invalid-scene-timing-window",
            ),
        )
        for name, artifact_type, artifact_id, mutate, expected in cases:
            with self.subTest(name=name):
                self.write_timed_semantic_graph()
                path = self.timing_artifact_path(artifact_type, artifact_id)
                record = json.loads(path.read_text(encoding="utf-8"))
                mutate(record)
                path.write_text(json.dumps(record), encoding="utf-8")

                result = validate_project(self.root)

                self.assertIn(expected, {item["code"] for item in result["errors"]})

    def test_timing_artifact_contracts_reject_invalid_metadata_before_graph_checks(self):
        """Catches persisted timing records bypassing their closed dedicated schema."""
        cases = (
            (
                "semantic-missing-beats",
                "semantic-beats",
                "semantic-beats-v1",
                lambda record: record.pop("beats"),
            ),
            (
                "timed-empty-beats",
                "timed-semantic-beats",
                "timed-semantic-beats-v1",
                lambda record: record.update({"beats": []}),
            ),
            (
                "scene-unexpected-nested-key",
                "scene-timing-contracts",
                "scene-timing-contracts-v1",
                lambda record: record["scenes"][0].update({"unexpected": "metadata"}),
            ),
        )
        for name, artifact_type, artifact_id, mutate in cases:
            with self.subTest(name=name):
                self.write_timed_semantic_graph()
                path = self.timing_artifact_path(artifact_type, artifact_id)
                record = json.loads(path.read_text(encoding="utf-8"))
                mutate(record)
                path.write_text(json.dumps(record), encoding="utf-8")

                result = validate_project(self.root)

                self.assertIn("invalid-artifact-metadata", {item["code"] for item in result["errors"]})

    def write_visual_placeholder(self, relative):
        path = self.root / relative
        path.write_bytes(b"opaque visual fixture; structural validation must not read it")
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

    def test_structural_validation_never_reads_or_decodes_visual_media(self):
        """Catches metadata-only recovery reopening pixels for alpha inspection."""
        relative = "media/presenter_points-right_right_v01.png"
        target = self.root / relative
        target.write_bytes(b"visual bytes must remain opaque to this validator")
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["validation_evidence"].append(
            "isolated-image-inspect:alpha-transparency-present"
        )
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            relative,
            **metadata,
        )
        original_read_bytes = Path.read_bytes

        def guarded_read_bytes(path):
            if path == target:
                raise AssertionError("structural validator read visual bytes")
            return original_read_bytes(path)

        with patch.object(
            Path, "read_bytes", autospec=True, side_effect=guarded_read_bytes
        ):
            result = validate_project(self.root)

        self.assertNotIn(
            "promoted-character-action-alpha-inspection-required",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_alpha_requires_isolated_inspection_evidence(self):
        """Catches an alpha claim passing without isolated image-inspect evidence."""
        relative = "media/presenter_points-right_right_v01.png"
        (self.root / relative).write_bytes(b"opaque structural fixture")
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            relative,
            **self.promoted_character_metadata(),
        )

        result = validate_project(self.root)

        self.assertIn(
            "promoted-character-action-alpha-inspection-required",
            {item["code"] for item in result["errors"]},
        )

    def test_promoted_character_action_with_isolated_alpha_evidence_passes(self):
        """Catches compact isolated inspection evidence being ignored."""
        self.write_visual_placeholder("media/presenter_points-right_right_v01.png")
        metadata = self.promoted_character_metadata()
        metadata["promotion"]["validation_evidence"].append(
            "isolated-image-inspect:alpha-transparency-present"
        )
        self.write_artifact(
            "promoted-character-v1",
            "promoted-asset",
            1,
            "approved",
            "media/presenter_points-right_right_v01.png",
            **metadata,
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
        self.write_visual_placeholder("media/presenter_points-right_right_v01.png")
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
        self.write_visual_placeholder("media/presenter_points-right_right_v01.png")
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
        self.write_visual_placeholder("media/presenter_points-right_right_v01.png")
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

    def test_promoted_character_name_rejects_project_coupling(self):
        """Catches legacy shot identifiers in promoted character filenames."""
        path = "media/复利效应_S004_灰发猫耳少年_讲解_右侧_v01.png"
        self.write_visual_placeholder(path)
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
        self.write_visual_placeholder(path)
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
        self.write_visual_placeholder(path)
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
        self.write_visual_placeholder("media/presenter_points-right_right_v01.png")
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
        event_log = events / "events.jsonl"
        event_log.write_text(
            event_log.read_text(encoding="utf-8")
            + json.dumps(
                {
                    "event": "artifacts.invalidated",
                    "changed_id": "scene-S01-v1",
                    "artifact_ids": ["scene-S01-v1"],
                }
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

    def test_validator_rejects_malformed_conditional_image_context(self):
        """Catches persisted image tasks bypassing the runtime's closed context."""
        tasks = self.root / "tasks"
        tasks.mkdir()
        task_id = "image-task-null-context"
        (tasks / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "capability": "structure.validate",
                    "inputs": [],
                    "adapter_preferences": ["chatcut"],
                    "output_contract": "task-result-v1",
                    "constraints": {
                        "image_operation": "image-inspect",
                        "image_context": None,
                    },
                }
            ),
            encoding="utf-8",
        )

        result = validate_project(self.root)

        self.assertIn("invalid-task-envelope", {item["code"] for item in result["errors"]})

    def test_validator_rejects_scene_scope_with_an_unlisted_character_pack(self):
        """Catches persisted scene tasks acquiring an independent pack scope."""
        contract_path = self.root / "contracts" / "S01.json"
        bound_contract_path = self.root / "contracts" / "scene-contract-S01-v1.json"
        contract_path.rename(bound_contract_path)
        artifact_path = (
            self.root
            / "artifacts"
            / "scene-contract"
            / "scene-contract-S01-v1.json"
        )
        scene_contract = json.loads(artifact_path.read_text(encoding="utf-8"))
        scene_contract["path"] = "contracts/scene-contract-S01-v1.json"
        artifact_path.write_text(json.dumps(scene_contract), encoding="utf-8")
        self.write_artifact(
            "unlisted-pack-a",
            "character-pack",
            1,
            "approved",
            "metadata/unlisted-pack-a.json",
            identity_provenance="unlisted-pack-v1",
        )
        tasks = self.root / "tasks"
        tasks.mkdir()
        task_id = "scene-scope-with-unlisted-pack"
        (tasks / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "capability": "structure.validate",
                    "inputs": ["scene-contract-S01-v1", "unlisted-pack-a"],
                    "adapter_preferences": ["chatcut"],
                    "output_contract": "task-result-v1",
                    "constraints": {
                        "image_operation": "image-inspect",
                        "image_context": {
                            "scope_identity": {
                                "kind": "scene-contract",
                                "id": "scene-contract-S01-v1",
                            },
                            "allowed_image_artifact_ids": [],
                            "allowed_character_pack_ids": [],
                            "forbidden_scene_image_access": True,
                            "max_review_previews": 0,
                            "context_budget": 1024,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        result = validate_project(self.root)

        self.assertIn(
            "tasks/scene-scope-with-unlisted-pack.json",
            {
                item["path"]
                for item in result["errors"]
                if item["code"] == "visual-media-input-forbidden"
            },
        )

    def test_validator_requires_exact_structure_validation_image_operation(self):
        """Catches persisted structure validators bypassing the inspection discriminator."""
        tasks = self.root / "tasks"
        tasks.mkdir()
        records = (
            ("structure-mode-missing", {}),
            ("structure-mode-legacy", {"image_operation": "inspect"}),
            (
                "structure-only-with-context",
                {
                    "image_operation": "structure-only",
                    "image_context": {
                        "allowed_image_artifact_ids": [],
                        "allowed_character_pack_ids": [],
                        "forbidden_scene_image_access": True,
                        "max_review_previews": 0,
                        "context_budget": 1024,
                    },
                },
            ),
        )
        for task_id, constraints in records:
            (tasks / f"{task_id}.json").write_text(
                json.dumps(
                    {
                        "task_id": task_id,
                        "capability": "structure.validate",
                        "inputs": [],
                        "adapter_preferences": ["chatcut"],
                        "output_contract": "task-result-v1",
                        "constraints": constraints,
                    }
                ),
                encoding="utf-8",
            )

        result = validate_project(self.root)

        invalid_paths = {
            item["path"]
            for item in result["errors"]
            if item["code"] == "invalid-task-envelope"
        }
        self.assertEqual(
            {
                "tasks/structure-mode-missing.json",
                "tasks/structure-mode-legacy.json",
                "tasks/structure-only-with-context.json",
            },
            invalid_paths,
        )

    def test_validator_rejects_unknown_task_capability(self):
        """Catches structural validation accepting a route no child skill owns."""
        tasks = self.root / "tasks"
        tasks.mkdir()
        task_id = "unknown-capability"
        (tasks / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "capability": "unknown.route",
                    "inputs": [],
                    "adapter_preferences": ["chatcut"],
                    "output_contract": "task-result-v1",
                    "constraints": {},
                }
            ),
            encoding="utf-8",
        )

        result = validate_project(self.root)

        self.assertIn(
            "tasks/unknown-capability.json",
            {
                item["path"]
                for item in result["errors"]
                if item["code"] == "invalid-task-envelope"
            },
        )

    def test_validator_rejects_unknown_reserved_visual_operation(self):
        """Catches persisted non-scene tasks bypassing the reserved visual enum."""
        tasks = self.root / "tasks"
        tasks.mkdir()
        task_id = "project-manage-bogus-visual"
        (tasks / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "capability": "project.manage",
                    "inputs": [],
                    "adapter_preferences": ["chatcut"],
                    "output_contract": "task-result-v1",
                    "constraints": {"visual_operation": "bogus"},
                }
            ),
            encoding="utf-8",
        )

        result = validate_project(self.root)

        self.assertIn(
            "tasks/project-manage-bogus-visual.json",
            {
                item["path"]
                for item in result["errors"]
                if item["code"] == "invalid-task-envelope"
            },
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
        self.write_project_history(2)
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

    def test_snapshot_downgrade_cannot_enable_legacy_unresolved_timing(self):
        """Catches mutable project.json claiming legacy compatibility over v2 replay."""
        self.write_project_history(2)

        result = validate_project(self.root)

        codes = {item["code"] for item in result["errors"]}
        self.assertIn("project-state-mismatch", codes)
        self.assertIn("invalid-scene-contract", codes)

    def test_scene_contract_requires_the_authoritative_current_timing(self):
        """Catches a valid historical timing remaining eligible after timing v2."""
        project_path = self.root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["schema_version"] = 2
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.write_project_history(2)
        self.write_voice_bundle(include_timing_v2=True)

        result = validate_project(self.root)

        self.assertIn(
            "invalid-scene-contract",
            {item["code"] for item in result["errors"]},
        )

    def test_voice_timing_beyond_audio_duration_is_structural_error(self):
        """Catches metadata timing being trusted past the actual audio header duration."""
        project_path = self.root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["schema_version"] = 2
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.write_project_history(2)
        self.write_voice_bundle()
        self.write_wav_header("media/voiceover-v1.wav", 9_000)

        result = validate_project(self.root)

        self.assertIn(
            "voice-timing-out-of-bounds",
            {item["code"] for item in result["errors"]},
        )

    def test_upgraded_legacy_origin_runs_canonical_file_backed_voice_validation(self):
        """Catches schema-origin v1 permanently bypassing real audio authority."""
        self.write_upgraded_legacy_history()
        self.write_voice_bundle()
        self.write_wav_header("media/voiceover-v1.wav", 9_000)

        result = validate_project(self.root)

        codes = {item["code"] for item in result["errors"]}
        self.assertIn("voiceover-duration-mismatch", codes)
        self.assertIn("voice-timing-out-of-bounds", codes)

    def test_upgraded_legacy_origin_no_longer_relaxes_scene_timing_authority(self):
        """Catches an upgraded v1 project retaining unresolved Scene Contract rules."""
        self.write_upgraded_legacy_history()
        self.write_voice_bundle()
        self.write_wav_header("media/voiceover-v1.wav", 10_000)
        contract_path = self.root / "contracts" / "S01.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["voice_timing_id"] = "legacy-estimate-v1"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn(
            "invalid-scene-contract",
            {item["code"] for item in result["errors"]},
        )

    def test_voiceover_media_existence_duration_and_lineage_are_structural_issues(self):
        """Catches current voice metadata that cannot safely produce a real audio reference."""
        project_path = self.root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["schema_version"] = 2
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.write_project_history(2)
        self.write_voice_bundle()

        missing_result = validate_project(self.root)
        self.assertIn(
            "voiceover-media-missing",
            {item["code"] for item in missing_result["errors"]},
        )

        voiceover_path = self.root / "artifacts" / "voiceover" / "voiceover-v1.json"
        voiceover = json.loads(voiceover_path.read_text(encoding="utf-8"))
        voiceover["parents"] = ["narration-v1"]
        voiceover_path.write_text(json.dumps(voiceover), encoding="utf-8")

        result = validate_project(self.root)

        codes = {item["code"] for item in result["errors"]}
        self.assertIn("voiceover-lineage-mismatch", codes)

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

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

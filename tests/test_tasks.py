import json
import os
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
        self.inputs = [
            self.create_artifact("scene-contract-S03-v4", "scene-contract", 4),
            self.create_artifact("style-v3", "style-pack", 3),
            self.create_artifact("layout-v2", "layout-pack", 2),
        ]
        self.envelope = {
            "task_id": "preview-S03-v2",
            "capability": "motion.preview",
            "inputs": self.inputs,
            "adapter_preferences": ["hyperframes", "remotion"],
            "output_contract": "motion-preview-v1",
            "constraints": {"do_not_rewrite_script": True, "max_attempts": 2},
        }

    def tearDown(self):
        self.folder.cleanup()

    def create_artifact(self, artifact_id, artifact_type, version, status="approved", parents=None):
        create_artifact(
            self.root,
            {
                "artifact_id": artifact_id,
                "type": artifact_type,
                "version": version,
                "status": status,
                "parents": [] if parents is None else parents,
                "path": f"media/{artifact_id}.json",
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

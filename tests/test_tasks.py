import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.toolkit.artifacts import create_artifact
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
        self.result_for_v4 = {
            "task_id": "preview-S03-v2",
            "status": "succeeded",
            "inputs": self.inputs,
            "artifacts": ["motion-preview-S03-v2"],
            "checks": ["duration-valid"],
            "warnings": [],
        }

    def tearDown(self):
        self.folder.cleanup()

    def create_artifact(self, artifact_id, artifact_type, version, status="approved"):
        create_artifact(
            self.root,
            {
                "artifact_id": artifact_id,
                "type": artifact_type,
                "version": version,
                "status": status,
                "parents": [],
                "path": f"media/{artifact_id}.json",
            },
        )
        return artifact_id

    def set_active_input(self, artifact_id):
        artifact_path = self.root / "artifacts" / "scene-contract" / "scene-contract-S03-v4.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["status"] = "stale"
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
        self.create_artifact(artifact_id, "scene-contract", 5)

    def test_create_task_persists_immutable_envelope_at_task_id_path(self):
        """Catches a task dispatch that loses its contracted input versions."""
        path = create_task(self.root, self.envelope)

        self.assertEqual(self.root / "tasks" / "preview-S03-v2.json", path)
        self.assertEqual(self.envelope, json.loads(path.read_text(encoding="utf-8")))
        with self.assertRaises(FileExistsError):
            create_task(self.root, self.envelope)

    def test_second_worker_cannot_claim_same_task(self):
        """Catches two workers executing the same isolated task concurrently."""
        create_task(self.root, self.envelope)
        claim_task(self.root, "preview-S03-v2", "worker-a")

        with self.assertRaises(RuntimeError):
            claim_task(self.root, "preview-S03-v2", "worker-b")

    def test_late_result_cannot_supersede_new_input_version(self):
        """Catches a completed task publishing output after one of its inputs went stale."""
        create_task(self.root, self.envelope)
        self.set_active_input("scene-contract-S03-v5")

        status = complete_task(self.root, self.result_for_v4)

        self.assertEqual("stale-result", status)
        self.assertEqual(
            self.result_for_v4,
            json.loads(
                (self.root / "tasks" / "stale-results" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        self.assertFalse((self.root / "tasks" / "results" / "preview-S03-v2.json").exists())

    def test_result_with_different_input_versions_is_stale(self):
        """Catches a worker returning results for inputs other than its immutable envelope."""
        create_task(self.root, self.envelope)
        result = {**self.result_for_v4, "inputs": ["scene-contract-S03-v5", *self.inputs[1:]]}

        self.assertEqual("stale-result", complete_task(self.root, result))

    def test_current_result_is_registered_at_task_result_path(self):
        """Catches a valid task result being discarded instead of made available to the coordinator."""
        create_task(self.root, self.envelope)

        self.assertEqual("completed", complete_task(self.root, self.result_for_v4))
        self.assertEqual(
            self.result_for_v4,
            json.loads(
                (self.root / "tasks" / "results" / "preview-S03-v2.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

    def test_retry_stops_after_two_attempts_and_one_fallback(self):
        """Catches adapter failures causing an unbounded retry or fallback loop."""
        decision = retry_decision(
            {"attempt": 2, "adapter": "hyperframes"},
            {"error": "adapter_error"},
            ["hyperframes", "remotion"],
        )
        self.assertEqual("switch-adapter", decision["action"])
        self.assertEqual("remotion", decision["adapter"])

        blocked = retry_decision(
            {"attempt": 2, "fallback_used": True},
            {"error": "adapter_error"},
            ["hyperframes", "remotion"],
        )
        self.assertEqual("block", blocked["action"])

    def test_retry_only_retries_classified_contract_or_adapter_errors(self):
        """Catches malformed inputs or missing direction being retried without user action."""
        for error in ("input_error", "direction_error"):
            with self.subTest(error=error):
                self.assertEqual(
                    "request-user-action",
                    retry_decision({"attempt": 1}, {"error": error}, ["hyperframes"])["action"],
                )

        self.assertEqual(
            "retry",
            retry_decision(
                {"attempt": 1, "adapter": "hyperframes"},
                {"error": "contract_error"},
                ["hyperframes", "remotion"],
            )["action"],
        )


if __name__ == "__main__":
    unittest.main()

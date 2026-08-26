import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.toolkit import artifacts
from scripts.toolkit.artifacts import approve_artifact, create_artifact


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

    def test_serialization_failure_leaves_no_artifact_and_retry_succeeds(self):
        """Catches a failed JSON write reserving an ID or publishing a partial file."""
        invalid = {**self.artifact, "payload": object()}

        with self.assertRaises(TypeError):
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

    def test_approval_serialization_failure_leaves_no_partial_file(self):
        """Catches approval publication beginning before its JSON is complete."""
        create_artifact(self.root, self.artifact)

        with patch("scripts.toolkit.artifacts.json.dumps", side_effect=TypeError("bad JSON")):
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

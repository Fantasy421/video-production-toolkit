import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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
                "notes": "approved",
            },
            json.loads(approval_path.read_text(encoding="utf-8")),
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


if __name__ == "__main__":
    unittest.main()

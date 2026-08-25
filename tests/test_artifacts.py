import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()

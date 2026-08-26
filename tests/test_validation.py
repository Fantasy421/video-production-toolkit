import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.toolkit.validation import validate_project


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "artifacts" / "timeline").mkdir(parents=True)
        (self.root / "artifacts" / "scene-media").mkdir(parents=True)
        (self.root / "timeline").mkdir()
        (self.root / "media").mkdir()
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
            "scene-S01-v1", "scene-media", 1, "approved", "media/scene-S01.mp4"
        )
        self.write_artifact(
            "timeline-v1",
            "timeline",
            1,
            "approved",
            "timeline/timeline-v1.json",
            parents=["scene-S01-v1"],
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

    def tearDown(self):
        self.folder.cleanup()

    def write_artifact(self, artifact_id, artifact_type, version, status, path, parents=None):
        artifact = {
            "artifact_id": artifact_id,
            "type": artifact_type,
            "version": version,
            "status": status,
            "parents": parents or [],
            "path": path,
        }
        destination = self.root / "artifacts" / artifact_type / f"{artifact_id}.json"
        destination.write_text(json.dumps(artifact), encoding="utf-8")

    def test_stale_artifact_on_active_timeline_is_error(self):
        self.write_artifact(
            "scene-S01-v2",
            "scene-media",
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
        artifact_path = self.root / "artifacts" / "scene-media" / "scene-S01-v1.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["path"] = str(self.root / "media" / "scene-S01.mp4")
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

        result = validate_project(self.root)

        self.assertIn("unsafe-artifact-path", {item["code"] for item in result["errors"]})


if __name__ == "__main__":
    unittest.main()

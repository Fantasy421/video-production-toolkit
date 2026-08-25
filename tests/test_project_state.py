import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.toolkit.project_state import initialize_project, append_event, replay_events


RUNTIME_DIRECTORIES = {
    "artifacts",
    "tasks",
    "events",
    "approvals",
    "previews",
    "media",
    "timeline",
}
ROOT = Path(__file__).parents[1]


class ProjectStateTests(unittest.TestCase):
    def test_initialize_creates_compact_project_and_initial_event_log(self):
        """Catches a missing runtime directory, state field, or initial event."""
        with TemporaryDirectory() as folder:
            root = Path(folder)

            state = initialize_project(root, "kv-001", "knowledge-video")

            self.assertEqual(
                {
                    "schema_version": 1,
                    "project_id": "kv-001",
                    "workflow": "knowledge-video",
                    "phase": "initialized",
                },
                state,
            )
            self.assertEqual(RUNTIME_DIRECTORIES, {path.name for path in root.iterdir() if path.is_dir()})
            self.assertEqual(state, json.loads((root / "project.json").read_text(encoding="utf-8")))
            self.assertEqual(
                {
                    "event": "project.initialized",
                    "schema_version": 1,
                    "project_id": "kv-001",
                    "workflow": "knowledge-video",
                },
                json.loads((root / "events" / "events.jsonl").read_text(encoding="utf-8")),
            )

    def test_replay_restores_last_phase_change_from_append_only_events(self):
        """Catches replay ignoring a later phase-change event or overwriting the log."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_project(root, "kv-001", "knowledge-video")
            append_event(root, {"event": "project.phase_changed", "phase": "content_ready"})
            append_event(root, {"event": "project.phase_changed", "phase": "direction_ready"})

            self.assertEqual("direction_ready", replay_events(root)["phase"])
            self.assertEqual(3, len((root / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()))

    def test_cli_prints_project_path_and_id_for_initialized_project(self):
        """Catches a CLI that initializes elsewhere or emits non-contract output."""
        with TemporaryDirectory() as folder:
            target = Path(folder) / "new-project"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/init_project.py",
                    str(target),
                    "--project-id",
                    "kv-cli",
                ],
                cwd=ROOT,
                capture_output=True,
                check=False,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual([str((target / "project.json").resolve()), "kv-cli"], result.stdout.splitlines())
            self.assertEqual("initialized", replay_events(target)["phase"])


if __name__ == "__main__":
    unittest.main()

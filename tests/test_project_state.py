import json
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.toolkit.project_state import (
    append_event,
    initialize_project,
    replay_events,
    set_active_timeline,
)


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
    def test_runtime_root_and_event_storage_reject_symlinks(self):
        """Catches project snapshots or events escaping through runtime symlinks."""
        with TemporaryDirectory() as folder, TemporaryDirectory() as outside_folder:
            link = Path(folder) / "project-link"
            outside = Path(outside_folder)
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                initialize_project(link, "kv-link", "knowledge-video")
            self.assertFalse((outside / "project.json").exists())

        with TemporaryDirectory() as folder, TemporaryDirectory() as outside_folder:
            root = Path(folder)
            initialize_project(root, "kv-events", "knowledge-video")
            real_events = root / "events-real"
            (root / "events").rename(real_events)
            (root / "events").symlink_to(
                Path(outside_folder), target_is_directory=True
            )
            with self.assertRaises(ValueError):
                append_event(
                    root,
                    {"event": "project.phase_changed", "phase": "content_ready"},
                )

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

    def test_phase_events_reject_unknown_and_out_of_order_transitions(self):
        """Catches arbitrary strings, skipped phases, and backwards phase movement."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_project(root, "kv-phase", "knowledge-video")

            for phase in ("not-a-phase", "direction_ready"):
                with self.subTest(phase=phase), self.assertRaises(ValueError):
                    append_event(root, {"event": "project.phase_changed", "phase": phase})
            self.assertEqual("initialized", replay_events(root)["phase"])
            self.assertEqual(1, len((root / "events" / "events.jsonl").read_text().splitlines()))

            append_event(root, {"event": "project.phase_changed", "phase": "content_ready"})
            with self.assertRaises(ValueError):
                append_event(root, {"event": "project.phase_changed", "phase": "initialized"})
            self.assertEqual("content_ready", replay_events(root)["phase"])

    def test_replay_rejects_a_persisted_invalid_phase_event(self):
        """Catches replay copying an invalid phase into project.json."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            event_log = root / "events" / "events.jsonl"
            event_log.parent.mkdir(parents=True)
            event_log.write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "event": "project.initialized",
                                "schema_version": 1,
                                "project_id": "kv-invalid",
                                "workflow": "knowledge-video",
                            }
                        ),
                        json.dumps(
                            {"event": "project.phase_changed", "phase": "not-a-phase"}
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                replay_events(root)

    def test_initial_event_is_durable_before_snapshot_publication(self):
        """Catches an initialization crash leaving only project.json and no replay source."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with patch(
                "scripts.toolkit.project_state._write_project_atomically",
                side_effect=OSError("simulated snapshot failure"),
            ):
                with self.assertRaises(OSError):
                    initialize_project(root, "kv-crash", "knowledge-video")

            self.assertEqual("initialized", replay_events(root)["phase"])
            self.assertFalse((root / "project.json").exists())

    def test_concurrent_event_appends_preserve_log_and_snapshot_replay_equivalence(self):
        """Catches interleaved JSONL writes or an older replay overwriting a newer snapshot."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_project(root, "kv-concurrent", "knowledge-video")

            def select(number):
                append_event(
                    root,
                    {
                        "event": "project.active_timeline_changed",
                        "active_timeline_id": f"timeline-{number:03d}",
                    },
                )

            with ThreadPoolExecutor(max_workers=16) as executor:
                list(executor.map(select, range(64)))

            lines = (root / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(65, len(lines))
            self.assertTrue(all(isinstance(json.loads(line), dict) for line in lines))
            self.assertEqual(
                replay_events(root),
                json.loads((root / "project.json").read_text(encoding="utf-8")),
            )

    def test_event_schema_is_discriminated_by_supported_event_type(self):
        """Catches a generic event object accepting arbitrary persisted mutations."""
        schema = json.loads(
            (ROOT / "references" / "schemas" / "event.schema.json").read_text(
                encoding="utf-8"
            )
        )

        event_names = {
            branch["properties"]["event"]["const"] for branch in schema["oneOf"]
        }
        self.assertEqual(
            {
                "project.initialized",
                "project.phase_changed",
                "project.active_timeline_changed",
                "artifacts.invalidated",
            },
            event_names,
        )

    def test_active_timeline_event_updates_snapshot_and_replay(self):
        """Catches a review timeline pointer that disappears after project recovery."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_project(root, "kv-001", "knowledge-video")

            state = set_active_timeline(root, "timeline-v2")

            snapshot = json.loads((root / "project.json").read_text(encoding="utf-8"))
            replayed = replay_events(root)
            self.assertEqual("timeline-v2", state["active_timeline_id"])
            self.assertEqual(state, snapshot)
            self.assertEqual(snapshot, replayed)
            self.assertEqual(
                {"event": "project.active_timeline_changed", "active_timeline_id": "timeline-v2"},
                json.loads((root / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1]),
            )
            event_schema = json.loads(
                (ROOT / "references" / "schemas" / "event.schema.json").read_text(encoding="utf-8")
            )
            timeline_branch = next(
                branch
                for branch in event_schema["oneOf"]
                if branch["properties"]["event"]["const"]
                == "project.active_timeline_changed"
            )
            self.assertEqual(
                {"type": "string", "minLength": 1},
                timeline_branch["properties"]["active_timeline_id"],
            )

    def test_replay_of_legacy_events_keeps_the_legacy_snapshot_shape(self):
        """Catches the optional timeline event making older project logs unreadable."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            event_log = root / "events" / "events.jsonl"
            event_log.parent.mkdir(parents=True)
            event_log.write_text(
                "\n".join(
                    [
                        json.dumps({"event": "project.initialized", "schema_version": 1, "project_id": "kv-legacy", "workflow": "knowledge-video"}),
                        json.dumps({"event": "project.phase_changed", "phase": "content_ready"}),
                    ]
                ) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(
                {"schema_version": 1, "project_id": "kv-legacy", "workflow": "knowledge-video", "phase": "content_ready"},
                replay_events(root),
            )

    def test_initialize_rejects_any_existing_state_file_before_writing(self):
        """Catches reinitialization deleting an existing project snapshot or event log."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            project_path = root / "project.json"
            project_path.write_text('{"project_id":"original"}\n', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                initialize_project(root, "kv-new", "knowledge-video")

            self.assertEqual('{"project_id":"original"}\n', project_path.read_text(encoding="utf-8"))
            self.assertFalse((root / "events").exists())

        with TemporaryDirectory() as folder:
            root = Path(folder)
            event_log = root / "events" / "events.jsonl"
            event_log.parent.mkdir()
            event_log.write_text('{"event":"project.initialized","project_id":"original"}\n', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                initialize_project(root, "kv-new", "knowledge-video")

            self.assertEqual(
                '{"event":"project.initialized","project_id":"original"}\n',
                event_log.read_text(encoding="utf-8"),
            )
            self.assertFalse((root / "project.json").exists())

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

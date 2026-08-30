import json
import struct
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.toolkit.artifacts import create_artifact
from scripts.toolkit.project_state import (
    append_event,
    initialize_project,
    project_recovery_view,
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
    def setUp(self):
        self._temporary_directory = TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)

    def tearDown(self):
        self._temporary_directory.cleanup()

    def advance_to(self, phase):
        initialize_project(self.root, "kv-phase", "knowledge-video")
        phases = (
            "content_ready",
            "direction_ready",
            "voice_ready",
            "storyboard_ready",
            "production_ready",
            "assembled",
            "review_ready",
            "handoff_ready",
        )
        for next_phase in phases[: phases.index(phase) + 1]:
            append_event(
                self.root,
                {"event": "project.phase_changed", "phase": next_phase},
            )

    def write_pre_voice_event_log(self, *, final_phase):
        event_log = self.root / "events" / "events.jsonl"
        event_log.parent.mkdir(parents=True)
        legacy_phases = (
            "content_ready",
            "direction_ready",
            "storyboard_ready",
            "production_ready",
            "assembled",
            "review_ready",
            "handoff_ready",
        )
        events = [
            {
                "event": "project.initialized",
                "schema_version": 1,
                "project_id": "kv-legacy",
                "workflow": "knowledge-video",
            },
            *(
                {"event": "project.phase_changed", "phase": phase}
                for phase in legacy_phases[: legacy_phases.index(final_phase) + 1]
            ),
        ]
        event_log.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        self.event_log = event_log
        self.original_events = event_log.read_bytes()

    def seed_voice_bundle(self, *, write_audio=True):
        records = (
            {
                "artifact_id": "narration-v1", "type": "narration", "version": 1,
                "status": "approved", "parents": [], "path": "metadata/narration-v1.json",
            },
            {
                "artifact_id": "source-v1", "type": "voice-source-decision", "version": 1,
                "status": "approved", "parents": ["narration-v1"],
                "path": "metadata/source-v1.json", "narration_id": "narration-v1",
                "mode": "tts", "decision": "approved",
                "decision_provenance": "user:source-v1",
            },
            {
                "artifact_id": "profile-v1", "type": "voice-profile", "version": 1,
                "status": "approved", "parents": ["narration-v1", "source-v1"],
                "path": "metadata/profile-v1.json", "narration_id": "narration-v1",
                "source_decision_id": "source-v1", "mode": "tts", "language": "zh-CN",
                "provider": "chatcut", "voice_id": "narrator-1", "speaking_rate": 1.0,
                "emotion": "calm", "pronunciations": [], "approved": True,
                "consent_provenance": "user:consent-v1",
                "profile_provenance": "user:profile-v1",
            },
            {
                "artifact_id": "voiceover-v1", "type": "voiceover", "version": 1,
                "status": "approved",
                "parents": ["narration-v1", "source-v1", "profile-v1"],
                "path": "metadata/voiceover-v1.json", "narration_id": "narration-v1",
                "source_decision_id": "source-v1", "mode": "tts",
                "profile_id": "profile-v1", "media_path": "media/voiceover-v1.wav",
                "media_format": "wav", "duration_ms": 1_000,
                "provenance": "chatcut:voice",
            },
            {
                "artifact_id": "voice-timing-v1", "type": "voice-timing", "version": 1,
                "status": "approved", "parents": ["voiceover-v1"],
                "path": "metadata/voice-timing-v1.json", "voiceover_id": "voiceover-v1",
                "timing_kind": "real", "duration_ms": 1_000,
                "segments": [{"start_ms": 0, "end_ms": 1_000, "text": "voice"}],
                "keyword_anchors": [],
            },
        )
        for record in records:
            create_artifact(self.root, record)
        if write_audio:
            sample_rate = 8_000
            audio = b"\0\0" * sample_rate
            (self.root / "media").mkdir(exist_ok=True)
            (self.root / "media/voiceover-v1.wav").write_bytes(
                b"RIFF" + struct.pack("<I", 36 + len(audio)) + b"WAVEfmt "
                + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
                + b"data" + struct.pack("<I", len(audio)) + audio
            )
        return records

    def test_direction_advances_to_voice_before_storyboard(self):
        """Catches a new project jumping from direction directly to storyboarding."""
        self.advance_to("direction_ready")
        self.seed_voice_bundle()

        append_event(
            self.root,
            {"event": "project.phase_changed", "phase": "voice_ready"},
        )

        self.assertEqual("voice_ready", replay_events(self.root)["phase"])

    def test_v3_projects_replay_the_voice_timed_phase_order(self):
        """V3 starts at script confirmation and keeps preview optional."""
        initialize_project(
            self.root, "kv-v3", "knowledge-video", schema_version=3
        )
        for phase in (
            "semantic_beats_confirmed",
            "voiceover_ready",
            "timing_bound",
            "storyboard_timed",
            "representative_scene_ready",
        ):
            append_event(
                self.root, {"event": "project.phase_changed", "phase": phase}
            )
        self.assertEqual("representative_scene_ready", replay_events(self.root)["phase"])

    def test_v3_visual_preview_cannot_skip_timing(self):
        initialize_project(
            self.root, "kv-v3-preview", "knowledge-video", schema_version=3
        )
        append_event(
            self.root,
            {"event": "project.phase_changed", "phase": "semantic_beats_confirmed"},
        )
        append_event(
            self.root,
            {"event": "project.phase_changed", "phase": "visual_direction_previewed"},
        )
        with self.assertRaisesRegex(ValueError, "illegal project phase transition"):
            append_event(
                self.root,
                {"event": "project.phase_changed", "phase": "storyboard_timed"},
            )

    def test_v3_production_ready_requires_the_current_timing_chain(self):
        initialize_project(
            self.root, "kv-v3-production", "knowledge-video", schema_version=3
        )
        for phase in (
            "semantic_beats_confirmed",
            "voiceover_ready",
            "timing_bound",
            "storyboard_timed",
            "representative_scene_ready",
        ):
            append_event(
                self.root, {"event": "project.phase_changed", "phase": phase}
            )
        with self.assertRaisesRegex(ValueError, "current real voice timing"):
            append_event(
                self.root,
                {"event": "project.phase_changed", "phase": "production_ready"},
            )

    def test_v3_recovery_is_read_only_and_reports_compact_timing_blocker(self):
        event_log = self.root / "events" / "events.jsonl"
        event_log.parent.mkdir(parents=True)
        events = [
            {
                "event": "project.initialized",
                "schema_version": 3,
                "project_id": "kv-v3-recovery",
                "workflow": "knowledge-video",
            },
            *(
                {"event": "project.phase_changed", "phase": phase}
                for phase in (
                    "semantic_beats_confirmed",
                    "voiceover_ready",
                    "timing_bound",
                    "storyboard_timed",
                    "representative_scene_ready",
                    "production_ready",
                )
            ),
        ]
        event_log.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
        )
        original = event_log.read_bytes()
        view = project_recovery_view(self.root, artifacts=[])
        self.assertEqual("semantic_beats_confirmed", view["phase"])
        self.assertEqual("timing-recovery-blocked", view["migration_requirement"]["code"])
        self.assertEqual(original, event_log.read_bytes())

    def test_direction_cannot_skip_voice_ready(self):
        """Catches a new phase event using the pre-voice transition order."""
        self.advance_to("direction_ready")
        self.assertEqual(2, replay_events(self.root)["schema_version"])

        with self.assertRaisesRegex(ValueError, "illegal project phase transition"):
            append_event(
                self.root,
                {"event": "project.phase_changed", "phase": "storyboard_ready"},
            )

    def test_voice_ready_transition_rejects_metadata_without_header_verified_audio(self):
        """Catches phase order alone authorizing metadata-only narration."""
        self.advance_to("direction_ready")
        self.seed_voice_bundle(write_audio=False)

        with self.assertRaisesRegex(ValueError, "voice_ready.*audio|voice bundle"):
            append_event(
                self.root,
                {"event": "project.phase_changed", "phase": "voice_ready"},
            )

        self.assertEqual("direction_ready", replay_events(self.root)["phase"])

    def test_v2_replay_rejects_a_tampered_direct_storyboard_transition(self):
        """Catches v2 replay incorrectly applying the v1 phase compatibility rule."""
        event_log = self.root / "events" / "events.jsonl"
        event_log.parent.mkdir(parents=True)
        event_log.write_text(
            "\n".join(
                (
                    json.dumps(
                        {
                            "event": "project.initialized",
                            "schema_version": 2,
                            "project_id": "kv-current",
                            "workflow": "knowledge-video",
                        }
                    ),
                    json.dumps(
                        {"event": "project.phase_changed", "phase": "content_ready"}
                    ),
                    json.dumps(
                        {"event": "project.phase_changed", "phase": "direction_ready"}
                    ),
                    json.dumps(
                        {"event": "project.phase_changed", "phase": "storyboard_ready"}
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "illegal project phase transition"):
            replay_events(self.root)

    def test_legacy_production_snapshot_without_voice_projects_to_direction_ready(self):
        """Catches recovery treating a legacy late-phase snapshot as voice-ready."""
        self.write_pre_voice_event_log(final_phase="production_ready")

        view = project_recovery_view(self.root, artifacts=[])

        self.assertEqual("direction_ready", view["phase"])
        self.assertEqual("voice-artifacts-required", view["migration_requirement"]["code"])
        self.assertEqual(self.original_events, self.event_log.read_bytes())

    def test_legacy_voice_timing_project_recovery_remains_readable(self):
        """Catches recovery demoting a valid persisted pre-anchor voice bundle."""
        self.write_pre_voice_event_log(final_phase="production_ready")
        records = self.seed_voice_bundle()
        records[-1].pop("keyword_anchors")

        view = project_recovery_view(self.root, artifacts=records)

        self.assertEqual("production_ready", view["phase"])

    def test_legacy_direction_project_upgrades_by_appending_before_voice_ready(self):
        """Catches an old log producing a v2 snapshot without a replayable upgrade."""
        self.write_pre_voice_event_log(final_phase="direction_ready")
        self.seed_voice_bundle()

        append_event(
            self.root,
            {"event": "project.phase_changed", "phase": "voice_ready"},
        )

        self.assertTrue(self.event_log.read_bytes().startswith(self.original_events))
        self.assertEqual(
            [
                {"event": "project.schema_upgraded", "schema_version": 2},
                {"event": "project.phase_changed", "phase": "voice_ready"},
            ],
            [
                json.loads(line)
                for line in self.event_log.read_text(encoding="utf-8").splitlines()[-2:]
            ],
        )
        self.assertEqual(
            {
                "schema_version": 2,
                "project_id": "kv-legacy",
                "workflow": "knowledge-video",
                "phase": "voice_ready",
            },
            replay_events(self.root),
        )

    def test_rejected_legacy_voice_event_does_not_append_an_upgrade(self):
        """Catches a malformed requested event partially upgrading a legacy log."""
        self.write_pre_voice_event_log(final_phase="direction_ready")

        with self.assertRaisesRegex(ValueError, "event does not match"):
            append_event(
                self.root,
                {
                    "event": "project.phase_changed",
                    "phase": "voice_ready",
                    "untrusted": True,
                },
            )

        self.assertEqual(self.original_events, self.event_log.read_bytes())

    def test_legacy_replay_does_not_relax_the_phase_event_contract(self):
        """Catches compatibility accepting a tampered old phase event."""
        event_log = self.root / "events" / "events.jsonl"
        event_log.parent.mkdir(parents=True)
        event_log.write_text(
            "\n".join(
                (
                    json.dumps(
                        {
                            "event": "project.initialized",
                            "schema_version": 1,
                            "project_id": "kv-legacy",
                            "workflow": "knowledge-video",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "project.phase_changed",
                            "phase": "content_ready",
                            "untrusted": True,
                        }
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "event does not match"):
            replay_events(self.root)

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
                    "schema_version": 2,
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
                    "schema_version": 2,
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
                "project.schema_upgraded",
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

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

import scripts.verify_installation as installation_verifier
from scripts.install_personal_plugin import install_personal_plugin
from scripts.migration_audit import DISPOSITIONS
from scripts.retire_legacy_skill import (
    _distributable_hashes,
    _installed_plugin_candidate,
    _run_installed_verifier,
    retire_legacy_skill,
)
from scripts.toolkit.artifacts import approve_artifact, create_artifact
from scripts.toolkit.orchestrator import (
    calculate_ready_tasks,
    invalidate_artifact_descendants,
    resume_project,
)
from scripts.toolkit.project_state import (
    LEGACY_PHASES,
    PHASES,
    append_event,
    initialize_project,
)
from scripts.toolkit.tasks import claim_task, complete_task, create_task
from scripts.validate_package import _release_fingerprint
from scripts.verify_installation import (
    _candidate as smoke_candidate,
    _run_resume_scenario,
    run_smoke,
    verify_installation,
)


ROOT = Path(__file__).parents[1]
SHIPPED_INVALIDATION = json.loads(
    (ROOT / "references/policies/invalidation.json").read_text(encoding="utf-8")
)
FIXTURE = ROOT / "tests" / "fixtures" / "knowledge-video-minimal"
LEGACY = Path.home() / ".codex" / "skills" / "knowledge-video-visual-director"
ROUTING_SCENE_SCOPE_ID = "routing-scene-contract-v1"


def advance_project(project, target_phase):
    """Advance a fixture through the same legal phase events used in production."""
    for phase in PHASES[1 : PHASES.index(target_phase) + 1]:
        append_event(project, {"event": "project.phase_changed", "phase": phase})


def write_legacy_phase(project, target_phase):
    """Replace a fixture's state with one genuine immutable v1 event history."""
    events = [
        {
            "event": "project.initialized",
            "schema_version": 1,
            "project_id": "legacy-recovery-fixture",
            "workflow": "knowledge-video",
        },
        *(
            {"event": "project.phase_changed", "phase": phase}
            for phase in LEGACY_PHASES[1 : LEGACY_PHASES.index(target_phase) + 1]
        ),
    ]
    (Path(project) / "events" / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    (Path(project) / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "legacy-recovery-fixture",
                "workflow": "knowledge-video",
                "phase": target_phase,
            }
        ),
        encoding="utf-8",
    )


def activate_personal_plugin(home, source):
    """Simulate the host's documented install cache and enabled config state."""
    install_personal_plugin(source, home=home, mode="link")
    cache = (
        home
        / ".codex"
        / "plugins"
        / "cache"
        / "personal"
        / "video-production-toolkit"
        / "local"
    )
    shutil.copytree(
        source,
        cache,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git", ".worktrees", ".superpowers", "__pycache__", "*.pyc"
        ),
    )
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        '[plugins."video-production-toolkit@personal"]\nenabled = true\n',
        encoding="utf-8",
    )
    return cache


def activate_versioned_personal_plugin(home, source):
    """Simulate the versioned cache layout used by current Codex hosts."""
    install_personal_plugin(source, home=home, mode="link")
    manifest = json.loads(
        (Path(source) / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    cache = (
        Path(home)
        / ".codex"
        / "plugins"
        / "cache"
        / "personal"
        / "video-production-toolkit"
        / manifest["version"]
    )
    shutil.copytree(
        source,
        cache,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git", ".worktrees", ".superpowers", "__pycache__", "*.pyc"
        ),
    )
    config = Path(home) / ".codex" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        '[plugins."video-production-toolkit@personal"]\nenabled = true\n',
        encoding="utf-8",
    )
    return cache


def add_cached_plugin_skill(
    home,
    *,
    marketplace,
    plugin,
    skill,
    frontmatter_name=None,
    enabled=None,
):
    """Create an isolated plugin-cache skill and optionally configure activation."""
    path = (
        Path(home)
        / ".codex"
        / "plugins"
        / "cache"
        / marketplace
        / plugin
        / "1.0.0"
        / "skills"
        / skill
        / "SKILL.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {frontmatter_name or skill}\ndescription: test fixture\n---\n",
        encoding="utf-8",
    )
    if enabled is not None:
        config = Path(home) / ".codex" / "config.toml"
        with config.open("a", encoding="utf-8") as stream:
            stream.write(
                f'\n[plugins."{plugin}@{marketplace}"]\nenabled = '
                f"{'true' if enabled else 'false'}\n"
            )
    return path


def enable_retirement_chatcut(home, *, include_voice=True):
    add_cached_plugin_skill(
        home,
        marketplace="chatcut-inc",
        plugin="chatcut",
        skill="chatcut-plugin-basics",
        frontmatter_name="chatcut:chatcut-plugin-basics",
        enabled=True,
    )
    if include_voice:
        add_cached_plugin_skill(
            home,
            marketplace="chatcut-inc",
            plugin="chatcut",
            skill="voice",
            frontmatter_name="chatcut:voice",
        )


def populate_auditable_legacy(repo, legacy):
    """Build an isolated legacy tree and matching baseline for retirement tests."""
    entries = []
    for relative in sorted(DISPOSITIONS):
        payload = (
            b"#!/usr/bin/env python3\n"
            if relative.startswith("scripts/")
            else f"fixture:{relative}\n".encode("utf-8")
        )
        path = Path(legacy) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        entries.append(
            {"path": relative, "sha256": hashlib.sha256(payload).hexdigest()}
        )
    baseline = (
        Path(repo)
        / "references"
        / "policies"
        / "knowledge-video-visual-director-baseline.json"
    )
    baseline.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "legacy_skill": "knowledge-video-visual-director",
                "files": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def artifact(
    artifact_id,
    artifact_type,
    *,
    version=1,
    status="approved",
    parents=None,
    path=None,
    **metadata,
):
    if artifact_type == "media":
        metadata.setdefault("media_kind", "video")
        metadata.setdefault("mime_type", "video/mp4")
    if artifact_type in {"media", "storyboard"}:
        metadata.setdefault("historical", False)
    default_path = (
        f"metadata/{artifact_id}"
        if artifact_type in {"media", "storyboard"}
        else f"metadata/{artifact_id}.json"
    )
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "version": version,
        "status": status,
        "parents": list(parents or []),
        "path": path or default_path,
        **metadata,
    }


def candidate(task_id, capability, inputs, gate, target_id, **constraints):
    inputs = list(inputs)
    visual_operation = {
        "visual.preview": "image-generate",
        "scene.produce": "video-generate",
        "motion.preview": "video-generate",
        "motion.produce": "video-render",
        "timeline.assemble": "video-edit",
        "review.package": "video-inspect",
    }.get(capability)
    if visual_operation is None:
        constraints.setdefault("visual_media_operation", "none")
    else:
        constraints.setdefault("visual_media_operation", visual_operation)
        constraints.setdefault("execution_context", "isolated-child-agent")
        if "visual_media_context" not in constraints:
            scope_id = next(
                (
                    artifact_id
                    for artifact_id in inputs
                    if "contract" in artifact_id.casefold()
                ),
                ROUTING_SCENE_SCOPE_ID,
            )
            if scope_id not in inputs:
                inputs.append(scope_id)
            continuity_id = next(
                (
                    artifact_id
                    for artifact_id in inputs
                    if artifact_id != scope_id
                    and any(
                        marker in artifact_id.casefold()
                        for marker in (
                            "storyboard",
                            "scene-",
                            "preview",
                            "image",
                            "video",
                            "screen",
                        )
                    )
                ),
                None,
            )
            constraints["visual_media_context"] = {
                "scope_identity": {"kind": "scene-contract", "id": scope_id},
                "allowed_artifact_ids": [],
                "historical_access": "character-only",
                "continuity_exception": (
                    {
                        "artifact_id": continuity_id,
                        "user_requested": True,
                        "reason": "Use this exact current visual production input.",
                    }
                    if continuity_id is not None
                    else None
                ),
                "max_review_previews": 1,
                "context_budget_bytes": 32_768,
            }
    if capability in {
        "storyboard.plan",
        "scene.produce",
        "motion.preview",
        "motion.produce",
        "timeline.assemble",
        "captions.produce",
        "representative-slice.produce",
    }:
        voice_timing_id = constraints.setdefault(
            "voice_timing_id", "voice-timing-v1"
        )
        if voice_timing_id not in inputs:
            inputs.append(voice_timing_id)
    return {
        "task_id": task_id,
        "capability": capability,
        "inputs": inputs,
        "adapter_preferences": ["chatcut"],
        "output_contract": "task-result-v1",
        "constraints": {
            "required_gate": gate,
            "gate_target_id": target_id,
            **constraints,
        },
    }


def voice_bundle(*, timing_id="voice-timing-v1", timing_status="approved"):
    """Return one hand-checked, real timing lineage for coordinator tests."""
    return [
        artifact("narration-v1", "narration"),
        artifact(
            "voice-source-v1",
            "voice-source-decision",
            parents=["narration-v1"],
            narration_id="narration-v1",
            mode="tts",
            decision="approved",
            decision_provenance="user:source-v1",
        ),
        artifact(
            "voice-profile-v1",
            "voice-profile",
            parents=["narration-v1", "voice-source-v1"],
            narration_id="narration-v1",
            source_decision_id="voice-source-v1",
            mode="tts",
            language="zh-CN",
            provider="chatcut",
            voice_id="narrator-1",
            speaking_rate=1.0,
            emotion="calm",
            pronunciations=[],
            approved=True,
            consent_provenance="user:consent-v1",
            profile_provenance="user:profile-v1",
        ),
        artifact(
            "voiceover-v1",
            "voiceover",
            parents=["narration-v1", "voice-source-v1", "voice-profile-v1"],
            narration_id="narration-v1",
            source_decision_id="voice-source-v1",
            mode="tts",
            profile_id="voice-profile-v1",
            media_path="media/voiceover-v1.wav",
            media_format="wav",
            duration_ms=12000,
            provenance="chatcut:voice",
        ),
        artifact(
            timing_id,
            "voice-timing",
            status=timing_status,
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=12000,
            segments=[
                {"start_ms": 0, "end_ms": 6000, "text": "first"},
                {"start_ms": 6000, "end_ms": 12000, "text": "second"},
            ],
        ),
    ]


def create_voice_bundle(project):
    media = Path(project) / "media" / "voiceover-v1.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(synthetic_wav(12_000))
    for record in voice_bundle():
        create_artifact(project, record)


def synthetic_wav(duration_ms, sample_rate=8_000):
    sample_count = duration_ms * sample_rate // 1_000
    audio = b"\0\0" * sample_count
    return (
        b"RIFF" + struct.pack("<I", 36 + len(audio)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(audio)) + audio
    )


class SmokeFixtureMetadataTests(unittest.TestCase):
    def test_candidate_declares_current_visual_authority_by_capability(self):
        """Catches smoke records retaining ambiguous pre-isolation authority."""
        visual = smoke_candidate(
            "produce-S01",
            "scene.produce",
            ["contract-S01-v1"],
            "storyboard-and-cost",
            "storyboard-v1",
        )
        nonvisual = smoke_candidate(
            "manage-project",
            "project.manage",
            [],
            None,
            "project-v1",
        )

        expected_visual = {
            "visual_media_operation": "video-generate",
            "execution_context": "isolated-child-agent",
        }
        self.assertEqual(
            expected_visual,
            {
                key: visual["constraints"][key]
                for key in expected_visual
                if key in visual["constraints"]
            },
        )
        self.assertNotIn("visual_operation", visual["constraints"])
        self.assertEqual(
            {"visual_media_operation": "none"},
            {
                key: nonvisual["constraints"][key]
                for key in ("visual_media_operation",)
                if key in nonvisual["constraints"]
            },
        )

    def test_orchestrator_validates_current_candidates_without_legacy_fallback(self):
        """Catches candidate routing reopening read-only legacy task authority."""
        current = smoke_candidate(
            "manage-project",
            "project.manage",
            [],
            None,
            "project-v1",
        )
        legacy = json.loads(json.dumps(current))
        legacy["constraints"].pop("visual_media_operation")
        legacy["constraints"]["image_operation"] = "structure-only"

        self.assertEqual(
            ["project.manage"],
            calculate_ready_tasks(
                {"phase": "initialized", "candidate_tasks": [current]}, [], []
            ),
        )
        with self.assertRaisesRegex(ValueError, "legacy image authority is read-only"):
            calculate_ready_tasks(
                {"phase": "initialized", "candidate_tasks": [legacy]}, [], []
            )

    def test_orchestrator_rejects_every_deprecated_current_authority_key(self):
        """Catches current candidate routing accepting any read-only authority key."""
        for key, value in (
            ("visual_operation", "non-image"),
            ("image_operation", "structure-only"),
            ("image_context", {}),
        ):
            with self.subTest(key=key):
                candidate_record = smoke_candidate(
                    f"deprecated-{key}",
                    "project.manage",
                    [],
                    None,
                    "project-v1",
                )
                candidate_record["constraints"].pop("visual_media_operation")
                candidate_record["constraints"][key] = value

                with self.assertRaisesRegex(
                    ValueError, "legacy .* authority is read-only"
                ):
                    calculate_ready_tasks(
                        {
                            "phase": "initialized",
                            "candidate_tasks": [candidate_record],
                        },
                        [],
                        [],
                    )

    def test_orchestrator_construction_applies_shared_visual_artifact_authority(self):
        """Catches readiness validating envelope shape without its Artifact scope."""
        task = smoke_candidate(
            "launder-current-visual",
            "project.manage",
            ["screen-v1"],
            None,
            "project-v1",
        )
        screenshot = artifact(
            "screen-v1",
            "browser-screenshot",
            path="media/screen-v1.png",
            media_kind="image",
            historical=False,
        )

        with self.assertRaisesRegex(ValueError, "visual media.*none"):
            calculate_ready_tasks(
                {"phase": "initialized", "candidate_tasks": [task]},
                [screenshot],
                [],
            )


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self._routing_folder = TemporaryDirectory()
        self.routing_root = Path(self._routing_folder.name)
        media = self.routing_root / "media/voiceover-v1.wav"
        media.parent.mkdir(parents=True)
        media.write_bytes(synthetic_wav(12_000))

    def tearDown(self):
        self._routing_folder.cleanup()

    def ready_tasks(self, state, artifacts, approvals):
        artifacts = list(artifacts)
        if any(
            ROUTING_SCENE_SCOPE_ID in task.get("inputs", [])
            for task in state.get("candidate_tasks", [])
            if isinstance(task, dict)
        ) and not any(
            item.get("artifact_id") == ROUTING_SCENE_SCOPE_ID
            for item in artifacts
        ):
            artifacts.append(
                artifact(ROUTING_SCENE_SCOPE_ID, "scene-contract")
            )
        return calculate_ready_tasks(
            state, artifacts, approvals, root=self.routing_root
        )

    def test_direction_ready_routes_voice_prepare_and_blocks_storyboard(self):
        """Catches direction approval dispatching storyboard before narration exists."""
        style = artifact("style-v1", "style-pack")
        narration = artifact("narration-v1", "narration")
        source = artifact("source-v1", "voice-source-decision")
        profile = artifact("profile-v1", "voice-profile")
        voice_task = candidate(
            "voice-prepare-v1",
            "voice.prepare",
            ["narration-v1", "style-v1", "source-v1", "profile-v1"],
            "visual-direction",
            "style-v1",
        )
        storyboard_task = candidate(
            "storyboard-v1",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
            voice_timing_id="voice-timing-v1",
        )
        approval = {
            "target_id": "style-v1",
            "scope": "visual-direction",
            "decision": "approved",
        }

        self.assertEqual(
            ["voice.prepare"],
            self.ready_tasks(
                {
                    "phase": "direction_ready",
                    "candidate_tasks": [storyboard_task, voice_task],
                },
                [style, narration, source, profile],
                [approval],
            ),
        )

    def test_voice_ready_routes_storyboard_with_current_real_timing(self):
        """Catches the new voice-ready phase having no legal storyboard action."""
        task = candidate(
            "storyboard-v1",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
            voice_timing_id="voice-timing-v1",
        )
        artifacts = [artifact("style-v1", "style-pack"), *voice_bundle()]

        self.assertEqual(
            ["storyboard.plan"],
            self.ready_tasks(
                {"phase": "voice_ready", "candidate_tasks": [task]},
                artifacts,
                [
                    {
                        "target_id": "style-v1",
                        "scope": "visual-direction",
                        "decision": "approved",
                    }
                ],
            ),
        )

    def test_voice_ready_routing_fails_closed_without_project_audio_authority(self):
        """Catches metadata-only callers bypassing the project audio gate."""
        task = candidate(
            "storyboard-no-root",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
        )

        self.assertEqual(
            [],
            calculate_ready_tasks(
                {"phase": "voice_ready", "candidate_tasks": [task]},
                [artifact("style-v1", "style-pack"), *voice_bundle()],
                [
                    {
                        "target_id": "style-v1",
                        "scope": "visual-direction",
                        "decision": "approved",
                    }
                ],
            ),
        )

    def test_voice_ready_rejects_storyboard_with_stale_timing_input(self):
        """Catches an approved but superseded timing input authorizing storyboard."""
        task = candidate(
            "storyboard-v1",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
            voice_timing_id="voice-timing-v1",
        )
        current_bundle = voice_bundle(timing_id="voice-timing-v2")
        old_timing = artifact(
            "voice-timing-v1",
            "voice-timing",
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=12000,
            segments=[{"start_ms": 0, "end_ms": 12000, "text": "old"}],
        )

        self.assertEqual(
            [],
            self.ready_tasks(
                {"phase": "voice_ready", "candidate_tasks": [task]},
                [artifact("style-v1", "style-pack"), *current_bundle, old_timing],
                [
                    {
                        "target_id": "style-v1",
                        "scope": "visual-direction",
                        "decision": "approved",
                    }
                ],
            ),
        )

    def test_voice_ready_rejects_voice_for_a_superseded_narration(self):
        """Catches routing deriving narration authority from the candidate timing."""
        task = candidate(
            "storyboard-v1",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
        )
        artifacts = [
            artifact("style-v1", "style-pack"),
            *voice_bundle(),
            artifact(
                "narration-v2",
                "narration",
                version=2,
                parents=["narration-v1"],
            ),
        ]

        self.assertEqual(
            [],
            self.ready_tasks(
                {"phase": "voice_ready", "candidate_tasks": [task]},
                artifacts,
                [
                    {
                        "target_id": "style-v1",
                        "scope": "visual-direction",
                        "decision": "approved",
                    }
                ],
            ),
        )

    def test_production_ready_without_voice_bundle_recovers_at_direction(self):
        """Catches resume trusting a late phase that has no real voice lineage."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-no-voice", "knowledge-video")
            write_legacy_phase(project, "production_ready")
            event_log = project / "events" / "events.jsonl"
            original_events = event_log.read_bytes()

            resumed = resume_project(project)

            self.assertEqual("direction_ready", resumed["phase"])
            self.assertEqual([], resumed["ready_tasks"])
            self.assertEqual(
                "voice-artifacts-required",
                resumed["migration_requirement"]["code"],
            )
            self.assertEqual(original_events, event_log.read_bytes())

    def test_production_ready_with_only_superseded_narration_voice_recovers_at_direction(self):
        """Catches recovery accepting any historical complete voice bundle."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-old-voice", "knowledge-video")
            create_voice_bundle(project)
            create_artifact(
                project,
                artifact(
                    "narration-v2",
                    "narration",
                    version=2,
                    parents=["narration-v1"],
                ),
            )
            write_legacy_phase(project, "production_ready")

            resumed = resume_project(project)

            self.assertEqual("direction_ready", resumed["phase"])
            self.assertEqual(
                "voice-artifacts-required",
                resumed["migration_requirement"]["code"],
            )

    def test_coordinator_routes_capabilities_only_in_legal_project_phases(self):
        """Catches a valid envelope running before its workflow phase is ready."""
        task = candidate(
            "produce-S01",
            "scene.produce",
            ["storyboard-v1"],
            "storyboard-and-cost",
            "storyboard-v1",
            production_scope="representative-slice",
            scene_id="S01",
        )
        artifacts = [artifact("storyboard-v1", "storyboard"), *voice_bundle()]
        approvals = [
            {
                "target_id": "storyboard-v1",
                "scope": "storyboard-and-cost",
                "decision": "approved",
            }
        ]

        self.assertEqual(
            [],
            self.ready_tasks(
                {"phase": "initialized", "candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                approvals,
            ),
        )
        self.assertEqual(
            ["scene.produce:S01"],
            self.ready_tasks(
                {"phase": "storyboard_ready", "candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                approvals,
            ),
        )
        with self.assertRaises(ValueError):
            self.ready_tasks(
                {"phase": "not-a-phase", "candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                approvals,
            )

    def test_coordinator_routes_captions_and_representative_slice_explicitly(self):
        """Catches schema-valid timing consumers having no coordinator owner."""
        storyboard = artifact("storyboard-v1", "storyboard")
        approval = {
            "target_id": "storyboard-v1",
            "scope": "storyboard-and-cost",
            "decision": "approved",
        }
        contract = artifact(
            "scene-contract-v1",
            "scene-contract",
            parents=["storyboard-v1"],
        )
        artifacts = [storyboard, contract, *voice_bundle()]
        cases = (
            ("captions.produce", "captions.produce"),
            ("representative-slice.produce", "representative-slice.produce"),
        )
        for capability, expected in cases:
            with self.subTest(capability=capability):
                task = candidate(
                    f"{capability}-v1",
                    capability,
                    ["scene-contract-v1"],
                    "storyboard-and-cost",
                    "storyboard-v1",
                    production_scope="representative-slice",
                )
                self.assertEqual(
                    [],
                    self.ready_tasks(
                        {"phase": "voice_ready", "candidate_tasks": [task]},
                        artifacts,
                        [approval],
                    ),
                )
                self.assertEqual(
                    [expected],
                    self.ready_tasks(
                        {"phase": "storyboard_ready", "candidate_tasks": [task]},
                        artifacts,
                        [approval],
                    ),
                )

    def test_full_production_captions_route_only_at_production_ready(self):
        """Catches expanded captions running in the representative-slice phase."""
        task = candidate(
            "captions-full-v1",
            "captions.produce",
            ["slice-v1"],
            "representative-slice-and-final-draft",
            "slice-v1",
            production_scope="full-production",
        )
        artifacts = [artifact("slice-v1", "representative-slice"), *voice_bundle()]
        approval = {
            "target_id": "slice-v1",
            "scope": "representative-slice-and-final-draft",
            "decision": "approved",
        }

        self.assertEqual(
            [],
            self.ready_tasks(
                {"phase": "storyboard_ready", "candidate_tasks": [task]},
                artifacts,
                [approval],
            ),
        )
        self.assertEqual(
            ["captions.produce"],
            self.ready_tasks(
                {"phase": "production_ready", "candidate_tasks": [task]},
                artifacts,
                [approval],
            ),
        )

    def test_all_four_gates_require_an_exact_durable_approval(self):
        """Catches wrong-scope, wrong-type, or unrelated approvals advancing work."""
        cases = (
            ("narration.plan", "content", "decision-pack", {}),
            ("storyboard.plan", "visual-direction", "style-pack", {}),
            (
                "scene.produce",
                "storyboard-and-cost",
                "storyboard",
                {"production_scope": "representative-slice"},
            ),
            (
                "scene.produce",
                "representative-slice-and-final-draft",
                "representative-slice",
                {"production_scope": "full-production"},
            ),
        )
        for index, (capability, gate, target_type, extra) in enumerate(cases, 1):
            with self.subTest(gate=gate):
                target_id = (
                    f"storyboard-gate-{index}"
                    if target_type == "storyboard"
                    else f"gate-target-{index}"
                )
                task = candidate(
                    f"task-{index}",
                    capability,
                    [target_id],
                    gate,
                    target_id,
                    **extra,
                )
                gate_voice = (
                    voice_bundle()
                    if capability
                    in {
                        "storyboard.plan",
                        "scene.produce",
                        "motion.preview",
                        "motion.produce",
                        "timeline.assemble",
                    }
                    else []
                )
                artifacts = [artifact(target_id, target_type), *gate_voice]
                state = {"candidate_tasks": [task], "locked_task_ids": []}

                self.assertEqual([], self.ready_tasks(state, artifacts, []))
                self.assertEqual(
                    [],
                    self.ready_tasks(
                        state,
                        artifacts,
                        [{"target_id": target_id, "scope": f"wrong-{gate}", "decision": "approved"}],
                    ),
                )
                approval = {
                    "target_id": target_id,
                    "scope": gate,
                    "decision": "approved",
                }
                self.assertEqual(
                    [],
                    self.ready_tasks(
                        state,
                        [artifact(target_id, "unrelated-review-artifact"), *gate_voice],
                        [approval],
                    ),
                    "the gate must reject an approval targeting the wrong artifact type",
                )
                self.assertEqual(
                    [capability],
                    self.ready_tasks(
                        state,
                        artifacts,
                        [approval],
                    ),
                )

                descendant_id = (
                    f"storyboard-input-{index}"
                    if target_type == "storyboard"
                    else f"gate-input-{index}"
                )
                unrelated_task = candidate(
                    f"unrelated-task-{index}",
                    capability,
                    [descendant_id],
                    gate,
                    target_id,
                    **extra,
                )
                unrelated_state = {
                    "candidate_tasks": [unrelated_task],
                    "locked_task_ids": [],
                }
                self.assertEqual(
                    [],
                    self.ready_tasks(
                        unrelated_state,
                        [
                            artifacts[0],
                            artifact(
                                descendant_id,
                                "storyboard" if target_type == "storyboard" else "task-input",
                            ),
                            *gate_voice,
                        ],
                        [approval],
                    ),
                    "an artifact of the right type must not approve another lineage",
                )
                self.assertEqual(
                    [capability],
                    self.ready_tasks(
                        unrelated_state,
                        [
                            artifacts[0],
                            artifact(
                                descendant_id,
                                "storyboard" if target_type == "storyboard" else "task-input",
                                parents=[target_id],
                            ),
                            *gate_voice,
                        ],
                        [approval],
                    ),
                )

    def test_representative_slice_approval_is_required_before_expansion(self):
        """Catches full production starting from storyboard approval alone."""
        task = candidate(
            "expand-S01",
            "scene.produce",
            ["slice-v1"],
            "representative-slice-and-final-draft",
            "slice-v1",
            production_scope="full-production",
            scene_id="S01",
        )
        state = {"candidate_tasks": [task], "locked_task_ids": []}
        artifacts = [artifact("slice-v1", "representative-slice"), *voice_bundle()]

        self.assertEqual(
            [],
            self.ready_tasks(
                state,
                artifacts,
                [{"target_id": "storyboard-v1", "scope": "storyboard-and-cost", "decision": "approved"}],
            ),
        )
        self.assertEqual(
            ["scene.produce:S01"],
            self.ready_tasks(
                state,
                artifacts,
                [
                    {
                        "target_id": "slice-v1",
                        "scope": "representative-slice-and-final-draft",
                        "decision": "approved",
                    }
                ],
            ),
        )

    def test_representative_slice_assembly_precedes_its_own_approval(self):
        """Catches a circular gate that requires slice approval before assembly."""
        task = candidate(
            "assemble-slice",
            "timeline.assemble",
            ["storyboard-v1"],
            "storyboard-and-cost",
            "storyboard-v1",
            production_scope="representative-slice",
        )

        self.assertEqual(
            ["timeline.assemble"],
            self.ready_tasks(
                {"candidate_tasks": [task], "locked_task_ids": []},
                [artifact("storyboard-v1", "storyboard"), *voice_bundle()],
                [
                    {
                        "target_id": "storyboard-v1",
                        "scope": "storyboard-and-cost",
                        "decision": "approved",
                    }
                ],
            ),
        )

    def test_coordinator_returns_one_action_and_respects_parent_status_and_locks(self):
        """Catches coordinator fan-out, stale-input dispatch, and duplicate execution."""
        approvals = [
            {
                "target_id": "storyboard-v1",
                "scope": "storyboard-and-cost",
                "decision": "approved",
            }
        ]
        tasks = [
            candidate(
                "produce-S02",
                "scene.produce",
                ["contract-S02-v1", "storyboard-v1"],
                "storyboard-and-cost",
                "storyboard-v1",
                production_scope="representative-slice",
                scene_id="S02",
            ),
            candidate(
                "produce-S01",
                "scene.produce",
                ["contract-S01-v1", "storyboard-v1"],
                "storyboard-and-cost",
                "storyboard-v1",
                production_scope="representative-slice",
                scene_id="S01",
            ),
        ]
        artifacts = [
            artifact("storyboard-v1", "storyboard"),
            artifact("contract-S01-v1", "scene-contract", status="stale"),
            artifact("contract-S02-v1", "scene-contract"),
            *voice_bundle(),
        ]

        self.assertEqual(
            ["scene.produce:S02"],
            self.ready_tasks(
                {"candidate_tasks": tasks, "locked_task_ids": []}, artifacts, approvals
            ),
        )
        self.assertEqual(
            [],
            self.ready_tasks(
                {"candidate_tasks": tasks, "locked_task_ids": ["produce-S02"]},
                artifacts,
                approvals,
            ),
        )

    def test_task_cannot_self_declare_a_weaker_gate(self):
        """Catches an envelope bypassing the policy-derived production gate."""
        task = candidate(
            "expand-S01",
            "scene.produce",
            ["slice-v1"],
            "storyboard-and-cost",
            "slice-v1",
            production_scope="full-production",
            scene_id="S01",
        )

        with self.assertRaises(ValueError):
            self.ready_tasks(
                {"candidate_tasks": [task], "locked_task_ids": []},
                [artifact("slice-v1", "representative-slice"), *voice_bundle()],
                [{"target_id": "slice-v1", "scope": "storyboard-and-cost", "decision": "approved"}],
            )

    def test_full_production_gate_requires_a_representative_slice_target(self):
        """Catches arbitrary approved metadata authorizing full-production expansion."""
        task = candidate(
            "expand-S01",
            "scene.produce",
            ["storyboard-v1"],
            "representative-slice-and-final-draft",
            "storyboard-v1",
            production_scope="full-production",
            scene_id="S01",
        )
        approval = {
            "target_id": "storyboard-v1",
            "scope": "representative-slice-and-final-draft",
            "decision": "approved",
        }

        self.assertEqual(
            [],
            self.ready_tasks(
                {"candidate_tasks": [task], "locked_task_ids": []},
                [artifact("storyboard-v1", "storyboard"), *voice_bundle()],
                [approval],
            ),
        )

    def test_gate_target_must_be_an_input_or_ancestor_of_an_input(self):
        """Catches an unrelated approved slice authorizing another production lineage."""
        task = candidate(
            "expand-S01",
            "scene.produce",
            ["scene-S01-v1"],
            "representative-slice-and-final-draft",
            "slice-unrelated-v1",
            production_scope="full-production",
            scene_id="S01",
        )
        artifacts = [
            artifact("slice-S01-v1", "representative-slice"),
            artifact(
                "scene-S01-v1",
                "media",
                parents=["slice-S01-v1"],
                scene_id="S01",
            ),
            artifact("slice-unrelated-v1", "representative-slice"),
            *voice_bundle(),
        ]
        approval = {
            "target_id": "slice-unrelated-v1",
            "scope": "representative-slice-and-final-draft",
            "decision": "approved",
        }

        self.assertEqual(
            [],
            self.ready_tasks(
                {"candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                [approval],
            ),
        )

        task["constraints"]["gate_target_id"] = "slice-S01-v1"
        approval["target_id"] = "slice-S01-v1"
        self.assertEqual(
            ["scene.produce:S01"],
            self.ready_tasks(
                {"candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                [approval],
            ),
        )

    def test_final_handoff_and_export_scopes_require_a_final_draft_target(self):
        """Catches a representative slice being reused after final-draft review is due."""
        for scope in ("final-draft", "handoff", "export"):
            with self.subTest(scope=scope):
                task = candidate(
                    f"{scope}-task",
                    "review.package",
                    ["final-v1"],
                    "representative-slice-and-final-draft",
                    "slice-v1",
                    production_scope=scope,
                )
                artifacts = [
                    artifact("slice-v1", "representative-slice"),
                    artifact("final-v1", "final-draft", parents=["slice-v1"]),
                ]
                slice_approval = {
                    "target_id": "slice-v1",
                    "scope": "representative-slice-and-final-draft",
                    "decision": "approved",
                }

                self.assertEqual(
                    [],
                    self.ready_tasks(
                        {"candidate_tasks": [task], "locked_task_ids": []},
                        artifacts,
                        [slice_approval],
                    ),
                )

                task["constraints"]["gate_target_id"] = "final-v1"
                final_approval = {**slice_approval, "target_id": "final-v1"}
                self.assertEqual(
                    ["review.package"],
                    self.ready_tasks(
                        {"candidate_tasks": [task], "locked_task_ids": []},
                        artifacts,
                        [final_approval],
                    ),
                )

    def test_project_resumes_and_rebuilds_only_the_changed_scene(self):
        """Catches interruption recovery rebuilding approved unrelated scenes."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-e2e", "knowledge-video")
            create_voice_bundle(project)
            create_artifact(project, artifact("storyboard-v1", "storyboard"))
            create_artifact(
                project,
                artifact(
                    "contract-S01-v1",
                    "scene-contract",
                    parents=["storyboard-v1"],
                    scene_id="S01",
                ),
            )
            create_artifact(
                project,
                artifact(
                    "contract-S02-v1",
                    "scene-contract",
                    parents=["storyboard-v1"],
                    scene_id="S02",
                ),
            )
            create_artifact(
                project,
                artifact(
                    "scene-S01-v1",
                    "media",
                    parents=["contract-S01-v1"],
                    scene_id="S01",
                ),
            )
            scene_s02_path = create_artifact(
                project,
                artifact(
                    "scene-S02-v1",
                    "media",
                    parents=["contract-S02-v1"],
                    scene_id="S02",
                ),
            )
            create_artifact(
                project,
                artifact(
                    "contract-S02-v2",
                    "scene-contract",
                    version=2,
                    parents=["storyboard-v1"],
                    scene_id="S02",
                ),
            )
            approve_artifact(
                project,
                "storyboard-v1",
                "storyboard-and-cost",
                "approved for representative production",
            )
            create_task(
                project,
                candidate(
                    "rebuild-S02",
                    "scene.produce",
                    ["contract-S02-v2", "storyboard-v1"],
                    "storyboard-and-cost",
                    "storyboard-v1",
                    production_scope="representative-slice",
                    scene_id="S02",
                    visual_media_context={
                        "scope_identity": {
                            "kind": "scene-contract",
                            "id": "contract-S02-v2",
                        },
                        "allowed_artifact_ids": [],
                        "historical_access": "character-only",
                        "continuity_exception": {
                            "artifact_id": "storyboard-v1",
                            "user_requested": True,
                            "reason": "Use this exact current storyboard input.",
                        },
                        "max_review_previews": 0,
                        "context_budget_bytes": 32_768,
                    },
                ),
            )
            advance_project(project, "storyboard_ready")

            stale = invalidate_artifact_descendants(
                project,
                "contract-S02-v1",
                SHIPPED_INVALIDATION,
            )
            resumed = resume_project(project)
            resumed_again = resume_project(project)
            by_id = {item["artifact_id"]: item for item in resumed["artifacts"]}

            self.assertEqual(["scene-S02-v1"], stale)
            self.assertEqual("approved", by_id["scene-S01-v1"]["status"])
            self.assertEqual("stale", by_id["scene-S02-v1"]["status"])
            self.assertEqual(["scene.produce:S02"], resumed["ready_tasks"])
            self.assertEqual(resumed, resumed_again)
            self.assertEqual(
                "approved",
                json.loads(scene_s02_path.read_text(encoding="utf-8"))["status"],
                "invalidation must remain an event overlay, not rewrite immutable metadata",
            )
            self.assertEqual(
                ["voiceover-v1.wav"],
                sorted(path.name for path in (project / "media").iterdir()),
            )

    def test_running_task_result_is_stale_after_event_overlay_invalidation(self):
        """Catches late work publishing after an input became stale in the event log."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-stale-result", "knowledge-video")
            create_artifact(project, artifact("storyboard-v1", "storyboard"))
            create_artifact(
                project,
                artifact(
                    "contract-S02-v1",
                    "scene-contract",
                    parents=["storyboard-v1"],
                    scene_id="S02",
                ),
            )
            create_artifact(
                project,
                artifact(
                    "scene-S02-v1",
                    "media",
                    parents=["contract-S02-v1"],
                    path="media/scene-S02-v1.mp4",
                    scene_id="S02",
                ),
            )
            envelope = candidate(
                "review-S02",
                "review.package",
                ["scene-S02-v1"],
                "storyboard-and-cost",
                "scene-S02-v1",
                production_scope="representative-slice",
                scene_id="S02",
                visual_media_context={
                    "scope_identity": {
                        "kind": "review-batch",
                        "id": ["scene-S02-v1"],
                    },
                    "allowed_artifact_ids": [],
                    "historical_access": "character-only",
                    "continuity_exception": None,
                    "max_review_previews": 1,
                    "context_budget_bytes": 32_768,
                },
            )
            create_task(project, envelope)
            create_artifact(
                project,
                artifact(
                    "review-S02-v1",
                    "review-pack",
                    parents=["scene-S02-v1"],
                    path="artifacts/review-pack/review-S02-v1.json",
                    output_contract="task-result-v1",
                ),
            )
            claim = claim_task(project, "review-S02", "worker-a")

            invalidate_artifact_descendants(
                project,
                "contract-S02-v1",
                SHIPPED_INVALIDATION,
            )
            with self.assertRaisesRegex(ValueError, "current approved output"):
                complete_task(
                    project,
                    {
                        "task_id": "review-S02",
                        "status": "succeeded",
                        "inputs": ["scene-S02-v1"],
                        "artifacts": ["review-S02-v1"],
                        "checks": ["review-ready"],
                        "warnings": [],
                        "visual_media_handoff": {
                            "artifact_ids": ["review-S02-v1"],
                            "paths": ["artifacts/review-pack/review-S02-v1.json"],
                            "media": {},
                            "checks": ["review-ready"],
                            "issues": [],
                            "summary": "review ready",
                            "review_preview_path": None,
                        },
                        **claim,
                    },
                )

            self.assertFalse(
                (project / "tasks" / "stale-results" / "review-S02.json").exists()
            )
            self.assertFalse(
                (project / "tasks" / "results" / "review-S02.json").exists()
            )

    def test_resume_reclaims_a_dead_worker_lock_before_routing(self):
        """Catches a crashed worker permanently hiding an otherwise ready task."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-dead-lock", "knowledge-video")
            create_voice_bundle(project)
            create_artifact(project, artifact("storyboard-v1", "storyboard"))
            create_artifact(
                project,
                artifact(
                    "contract-S02-v1",
                    "scene-contract",
                    parents=["storyboard-v1"],
                    scene_id="S02",
                ),
            )
            approve_artifact(
                project,
                "storyboard-v1",
                "storyboard-and-cost",
                "approved for representative production",
            )
            create_task(
                project,
                candidate(
                    "produce-S02",
                    "scene.produce",
                    ["contract-S02-v1", "storyboard-v1"],
                    "storyboard-and-cost",
                    "storyboard-v1",
                    production_scope="representative-slice",
                    scene_id="S02",
                    visual_media_context={
                        "scope_identity": {
                            "kind": "scene-contract",
                            "id": "contract-S02-v1",
                        },
                            "allowed_artifact_ids": [],
                            "historical_access": "character-only",
                            "continuity_exception": {
                                "artifact_id": "storyboard-v1",
                                "user_requested": True,
                                "reason": "Use this exact current storyboard input.",
                            },
                        "max_review_previews": 0,
                        "context_budget_bytes": 32_768,
                    },
                ),
            )
            advance_project(project, "storyboard_ready")
            claim_task(project, "produce-S02", "crashed-worker")
            lock_path = project / "tasks" / "locks" / "produce-S02.lock"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["pid"] = 999999
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            with patch("scripts.toolkit.tasks._pid_is_alive", return_value=False):
                resumed = resume_project(project)

            self.assertEqual(["scene.produce:S02"], resumed["ready_tasks"])
            self.assertEqual([], resumed["locked_task_ids"])
            self.assertFalse(lock_path.exists())

    def test_resume_blocks_invalid_visual_tasks_in_a_safe_recovery_view(self):
        """Catches malformed persisted authority crashing or routing production."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-invalid-resume", "knowledge-video")
            malformed = {
                "task_id": "invalid-visual-v1",
                "capability": "project.manage",
                "inputs": [],
                "adapter_preferences": ["chatcut"],
                "output_contract": "scene-video-v1",
                "constraints": {
                    "visual_media_operation": "video-render",
                    "execution_context": "isolated-child-agent",
                },
            }
            (project / "tasks" / "invalid-visual-v1.json").write_text(
                json.dumps(malformed), encoding="utf-8"
            )

            resumed = resume_project(project)

            self.assertEqual("initialized", resumed["phase"])
            self.assertEqual([], resumed["ready_tasks"])
            self.assertEqual([], resumed["candidate_tasks"])
            self.assertEqual(
                "visual-media-recovery-blocked",
                resumed["migration_requirement"]["code"],
            )
            self.assertIn(
                "visual-media-context-invalid",
                {issue["code"] for issue in resumed["recovery_issues"]},
            )

    def test_resume_reads_valid_legacy_authority_without_minting_it(self):
        """Catches current construction validation making legacy recovery unreadable."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-legacy-task", "knowledge-video")
            create_artifact(project, artifact("contract-S01-v1", "scene-contract"))
            legacy = {
                "task_id": "legacy-inspect-S01",
                "capability": "structure.validate",
                "inputs": ["contract-S01-v1"],
                "adapter_preferences": ["chatcut"],
                "output_contract": "image-report-v1",
                "constraints": {
                    "image_operation": "image-inspect",
                    "image_context": {
                        "scope_identity": {
                            "kind": "scene-contract",
                            "id": "contract-S01-v1",
                        },
                        "allowed_image_artifact_ids": [],
                        "allowed_character_pack_ids": [],
                        "forbidden_scene_image_access": True,
                        "max_review_previews": 1,
                        "context_budget": 4096,
                    },
                },
            }
            (project / "tasks" / "legacy-inspect-S01.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )

            resumed = resume_project(project)

            self.assertEqual([legacy], resumed["candidate_tasks"])
            self.assertEqual([], resumed["ready_tasks"])

    def test_resume_returns_only_coordinator_safe_artifact_projection(self):
        """Catches safe-but-arbitrary Artifact extras expanding coordinator context."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-projection", "knowledge-video")
            create_artifact(
                project,
                artifact(
                    "license-v1",
                    "license-document",
                    path="artifacts/licenses/source.json",
                    checksum="0123456789abcdef",
                    license={
                        "owner": "Example Studio",
                        "territories": ["global"],
                    },
                ),
            )

            resumed = resume_project(project)
            projected = resumed["artifacts"][0]

            self.assertEqual("license-v1", projected["artifact_id"])
            self.assertEqual("0123456789abcdef", projected["checksum"])
            self.assertNotIn("license", projected)

    def test_resume_blocks_a_tampered_unsafe_artifact_without_exposing_it(self):
        """Catches recovery trusting an Artifact payload added after publication."""
        with TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-tampered-artifact", "knowledge-video")
            path = create_artifact(
                project,
                artifact(
                    "tampered-v1",
                    "report",
                    path="artifacts/reports/tampered-v1.json",
                ),
            )
            record = json.loads(path.read_text(encoding="utf-8"))
            record["metadata"] = {"thumbnail": "inline-payload"}
            path.write_text(json.dumps(record), encoding="utf-8")

            resumed = resume_project(project)

            self.assertEqual([], resumed["artifacts"])
            self.assertEqual([], resumed["ready_tasks"])
            self.assertEqual(
                "visual-media-recovery-blocked",
                resumed["migration_requirement"]["code"],
            )
            self.assertIn(
                "invalid-artifact-metadata",
                {issue["code"] for issue in resumed["recovery_issues"]},
            )

    def test_resume_rejects_a_symlinked_task_result_directory(self):
        """Catches completed-task discovery following storage outside the project."""
        with TemporaryDirectory() as folder, TemporaryDirectory() as outside_folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-result-symlink", "knowledge-video")
            outside = Path(outside_folder)
            (outside / "foreign.json").write_text("{}", encoding="utf-8")
            (project / "tasks" / "results").symlink_to(
                outside, target_is_directory=True
            )

            with self.assertRaises(ValueError):
                resume_project(project)

    def test_resume_rejects_a_symlinked_task_result_record(self):
        """Catches a foreign result being counted terminally by its symlink name."""
        with TemporaryDirectory() as folder, TemporaryDirectory() as outside_folder:
            project = Path(folder) / "project"
            initialize_project(project, "kv-result-record-symlink", "knowledge-video")
            results = project / "tasks" / "results"
            results.mkdir()
            foreign = Path(outside_folder) / "foreign.json"
            foreign.write_text("{}", encoding="utf-8")
            (results / "foreign.json").symlink_to(foreign)

            with self.assertRaises(ValueError):
                resume_project(project)


class SmokeAndInstallationTests(unittest.TestCase):
    def test_new_cli_entrypoints_run_directly(self):
        """Catches repository imports failing when Python starts inside scripts/."""
        for script in (
            "scripts/install_personal_plugin.py",
            "scripts/verify_installation.py",
            "scripts/retire_legacy_skill.py",
        ):
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, script, "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_resume_smoke_requires_the_completed_migration_audit_and_slice(self):
        """Catches retirement readiness without migration or representative risk coverage."""
        result = run_smoke(ROOT)

        self.assertTrue(result["ok"], result)
        self.assertEqual("passed", result["checks"]["migration_audit"])
        self.assertEqual("passed", result["checks"]["resume_local_invalidation"])
        self.assertEqual("passed", result["checks"]["four_approval_gates"])
        self.assertEqual("passed", result["checks"]["representative_slice"])
        self.assertGreaterEqual(result["representative_slice"]["duration_ms"], 10000)
        self.assertLessEqual(result["representative_slice"]["duration_ms"], 20000)

        with TemporaryDirectory() as folder:
            incomplete = Path(folder) / "repo"
            shutil.copytree(ROOT, incomplete, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            (incomplete / "docs" / "migration" / "knowledge-video-visual-director.md").unlink()

            blocked = run_smoke(incomplete, legacy_root=Path(folder) / "missing-legacy")

            self.assertFalse(blocked["ok"])
            self.assertEqual("failed", blocked["checks"]["migration_audit"])
            self.assertEqual("migration-audit-required", blocked["blocker"]["code"])

    def test_resume_smoke_requires_voice_before_representative_slice(self):
        """Catches a smoke report that omits voice evidence after legacy retirement."""
        result = run_smoke(ROOT)

        self.assertTrue(result["ok"], result)
        self.assertEqual("passed", result["checks"]["direction_ready_blocks_production"])
        self.assertEqual("passed", result["checks"]["voice_source_decision"])
        self.assertEqual("passed", result["checks"]["real_voice_timing"])
        self.assertEqual("passed", result["checks"]["voice_ready_storyboard"])
        self.assertEqual("passed", result["checks"]["voice_timing_revision"])
        self.assertEqual(
            "voice-timing-v1", result["representative_slice"]["voice_timing_id"]
        )

    def test_resume_smoke_rejects_voice_metadata_that_disagrees_with_audio_file(self):
        """Catches real voice readiness trusting declared durations over the WAV header."""
        cases = (
            (
                {
                    "voiceover_duration_ms": 14_000,
                    "voice_timing_duration_ms": 14_000,
                },
                {"voiceover-duration-mismatch", "voice-timing-out-of-bounds"},
            ),
            (
                {"voice_timing_duration_ms": 14_000},
                {"voice-timing-duration-mismatch"},
            ),
            (
                {"voice_fixture": b"not-a-wave-file"},
                {"voiceover-media-duration-unverifiable"},
            ),
        )
        for overrides, expected_issues in cases:
            with self.subTest(overrides=overrides):
                result = _run_resume_scenario(**overrides)

                self.assertLessEqual(
                    expected_issues,
                    set(
                        result["voice_timing_revision"][
                            "voice_validation_issue_codes"
                        ]
                    ),
                )

    def test_resume_smoke_returns_the_post_timing_revision_recovery(self):
        """Catches the reported recovery snapshot hiding v2 invalidation effects."""
        result = _run_resume_scenario()
        artifacts = {item["artifact_id"]: item for item in result["artifacts"]}

        self.assertEqual(
            "voice-timing-v2",
            result["voice_timing_revision"]["current_voice_timing_id"],
        )
        self.assertEqual("approved", artifacts["voice-timing-v2"]["status"])
        self.assertEqual("approved", artifacts["style-v1"]["status"])
        for artifact_id in result["voice_timing_revision"]["declared_descendant_ids"]:
            self.assertEqual("stale", artifacts[artifact_id]["status"])

    def test_resume_smoke_seeds_and_preserves_the_declared_voice_fixture(self):
        """Catches metadata-only voiceover smoke passing without real audio bytes."""
        observed = []
        real_resume = resume_project

        def observe_voice_fixture(project):
            fixture = project / "media" / "voiceover-v1.wav"
            observed.append(fixture.read_bytes())
            return real_resume(project)

        with patch(
            "scripts.verify_installation.resume_project",
            side_effect=observe_voice_fixture,
        ):
            result = _run_resume_scenario()

        self.assertEqual(3, len(observed))
        self.assertGreater(len(observed[0]), 44)
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[1], observed[2])
        self.assertEqual(["voiceover-v1.wav"], result["media_files"])
        self.assertEqual(["voiceover-v1.wav"], result["seeded_media_files"])
        self.assertTrue(result["voice_fixture_unchanged"])
        wav = observed[0]
        self.assertEqual(b"RIFF", wav[:4])
        self.assertEqual(b"WAVEfmt ", wav[8:16])
        bits_per_sample = struct.unpack("<H", wav[34:36])[0]
        self.assertIn(bits_per_sample, {8, 16})
        data_size = struct.unpack("<I", wav[40:44])[0]
        audio = wav[44 : 44 + data_size]
        if bits_per_sample == 8:
            samples = (sample - 128 for sample in audio)
        else:
            samples = (
                sample[0]
                for sample in struct.iter_unpack("<h", audio)
            )
        self.assertTrue(any(sample != 0 for sample in samples), "fixture must be audible PCM")

    def test_resume_smoke_exercises_gate_type_and_lineage_counterexamples(self):
        """Catches an installed smoke accepting any same-scope approval token."""

        def weak_gate_router(state, artifacts, approvals, *, root=None):
            if not approvals:
                return []
            task = state["candidate_tasks"][0]
            capability = task["capability"]
            scene_id = task["constraints"].get("scene_id")
            return [capability if scene_id is None else f"{capability}:{scene_id}"]

        with patch(
            "scripts.verify_installation.calculate_ready_tasks",
            side_effect=weak_gate_router,
        ):
            result = run_smoke(ROOT)

        self.assertFalse(result["ok"])
        self.assertEqual("approval-gate-failed", result["blocker"]["code"])

    def test_installer_registers_a_personal_marketplace_without_overwriting_other_plugins(self):
        """Catches install copying over unrelated targets or dropping marketplace entries."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            marketplace = home / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(
                json.dumps(
                    {
                        "name": "personal",
                        "interface": {"displayName": "Personal"},
                        "plugins": [
                            {
                                "name": "unrelated",
                                "source": {"source": "local", "path": "./plugins/unrelated"},
                                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                                "category": "Productivity",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            installed = install_personal_plugin(ROOT, home=home, mode="link")
            target = Path(installed["plugin_path"])
            catalog = json.loads(marketplace.read_text(encoding="utf-8"))
            manifest = json.loads(
                (ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
            )

            self.assertTrue(target.is_symlink())
            self.assertEqual(ROOT.resolve(), target.resolve())
            self.assertEqual("0.1.4", installed.get("plugin_version"))
            self.assertEqual(
                manifest["release_fingerprint"], installed.get("release_fingerprint")
            )
            self.assertEqual(
                {"unrelated", "video-production-toolkit"},
                {entry["name"] for entry in catalog["plugins"]},
            )
            with self.assertRaises(FileExistsError):
                install_personal_plugin(ROOT, home=home, mode="link")

            replaced = install_personal_plugin(ROOT, home=home, mode="link", replace=True)
            backup = Path(replaced["backup_path"])
            self.assertTrue(backup.is_symlink())
            self.assertEqual(ROOT.resolve(), backup.resolve())

    def test_verifier_discovers_required_skill_and_reports_each_optional_adapter(self):
        """Catches repo-only validation being mistaken for host discoverability."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            cache = activate_personal_plugin(home, ROOT)

            result = verify_installation(
                repo=None,
                home=home,
                require_skill="video-director",
                check_external_skills=True,
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual("host-installed", result["plugin"]["discovery"])
            self.assertEqual(cache.resolve(), Path(result["plugin"]["root"]).resolve())
            self.assertEqual(
                {"hyperframes", "remotion", "video-shotcraft", "chatcut"},
                set(result["external_adapters"]),
            )
            self.assertTrue(result["warnings"])

    def test_verifier_reports_chatcut_voice_capabilities(self):
        """Catches voice-capable ChatCut installs being hidden behind its base Skill."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            activate_personal_plugin(home, ROOT)
            add_cached_plugin_skill(
                home,
                marketplace="chatcut-inc",
                plugin="chatcut",
                skill="voice",
                frontmatter_name="chatcut:voice",
                enabled=True,
            )

            result = verify_installation(
                repo=None,
                home=home,
                check_external_skills=True,
            )

            capabilities = result["external_adapters"]["chatcut"]["capabilities"]
            self.assertTrue(capabilities["voice.synthesize"]["available"])
            self.assertTrue(capabilities["voice.time"]["available"])
            self.assertEqual("chatcut:voice", capabilities["voice.time"]["installed_skill"])

    def test_verifier_discovers_current_versioned_personal_plugin_cache(self):
        """Catches current Codex version caches being mistaken for missing installs."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            cache = activate_versioned_personal_plugin(home, ROOT)

            result = verify_installation(
                repo=None,
                home=home,
                require_skill="video-director",
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(cache.resolve(), Path(result["plugin"]["root"]).resolve())

    def test_host_cache_visual_isolation_smoke_uses_only_public_metadata_runtime(self):
        """Catches repo imports or visual operations masking a broken installed boundary."""
        runner = getattr(
            installation_verifier, "run_installed_visual_media_smoke", None
        )
        self.assertIsNotNone(runner)
        if runner is None:
            return

        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            cache = activate_versioned_personal_plugin(home, ROOT)

            smoke = runner(cache)
            verified = verify_installation(
                repo=None,
                home=home,
                require_visual_media_smoke=True,
            )

            self.assertTrue(smoke["ok"], smoke)
            self.assertEqual("0.1.4", smoke["plugin_version"])
            self.assertEqual(
                cache.resolve(), Path(smoke["runtime_module_path"]).parents[2]
            )
            self.assertEqual(
                {
                    "child_only_routing": "passed",
                    "none_laundering": "passed",
                    "universal_scrub": "passed",
                    "exact_scope": "passed",
                    "legacy_projection": "passed",
                    "one_preview_relay": "passed",
                    "json_metadata_only": "passed",
                },
                smoke["checks"],
            )
            self.assertEqual(
                {
                    "child_only_routing": "visual media task requires an isolated child agent",
                    "none_laundering": "visual media task cannot declare operation none",
                    "universal_scrub": "visual media result must not contain an image payload or other media payload",
                    "exact_scope": "visual media task requires exactly one scene-contract scope and no neighbor",
                },
                smoke["stable_errors"],
            )
            self.assertTrue(verified["ok"], verified)
            self.assertEqual(smoke["checks"], verified["visual_media_smoke"]["checks"])

    def test_verifier_does_not_treat_marketplace_registration_as_host_installation(self):
        """Catches an available catalog source being reported as installed and active."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            install_personal_plugin(ROOT, home=home, mode="link")

            result = verify_installation(
                repo=None,
                home=home,
                require_skill="video-director",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("missing", result["plugin"]["discovery"])
            self.assertTrue(
                any("host-installed" in error for error in result["errors"]),
                result,
            )

    def test_verifier_does_not_confuse_plugin_namespaces_with_matching_skill_names(self):
        """Catches another plugin's same-named skill satisfying ChatCut availability."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            activate_personal_plugin(home, ROOT)
            skill = (
                home
                / ".codex"
                / "plugins"
                / "cache"
                / "unrelated-owner"
                / "unrelated-plugin"
                / "0.2.25"
                / "skills"
                / "chatcut-plugin-basics"
                / "SKILL.md"
            )
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: chatcut-plugin-basics\ndescription: test fixture\n---\n",
                encoding="utf-8",
            )

            result = verify_installation(
                repo=None,
                home=home,
                check_external_skills=True,
            )

            self.assertFalse(result["external_adapters"]["chatcut"]["available"])

    def test_verifier_accepts_a_direct_skill_for_a_namespaced_adapter_requirement(self):
        """Catches a usable direct VideoShotCraft install being reported unavailable."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            activate_personal_plugin(home, ROOT)
            skill = home / ".codex" / "skills" / "video-shotcraft" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: video-shotcraft\ndescription: test fixture\n---\n",
                encoding="utf-8",
            )

            result = verify_installation(
                repo=None,
                home=home,
                check_external_skills=True,
            )

            self.assertTrue(result["external_adapters"]["video-shotcraft"]["available"])

    def test_verifier_uses_only_enabled_plugin_caches_for_adapter_availability(self):
        """Catches disabled and unconfigured cache residue being reported available."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            activate_personal_plugin(home, ROOT)
            add_cached_plugin_skill(
                home,
                marketplace="chatcut-inc",
                plugin="chatcut",
                skill="chatcut-plugin-basics",
                enabled=False,
            )
            add_cached_plugin_skill(
                home,
                marketplace="stale-marketplace",
                plugin="video-shotcraft",
                skill="video-shotcraft",
            )

            result = verify_installation(
                repo=None,
                home=home,
                check_external_skills=True,
            )

            self.assertFalse(result["external_adapters"]["chatcut"]["available"])
            self.assertFalse(
                result["external_adapters"]["video-shotcraft"]["available"]
            )

    def test_verifier_matches_canonical_skill_to_its_enabled_plugin_namespace(self):
        """Catches an enabled remotion:skill cache missing its canonical manifest name."""
        with TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            activate_personal_plugin(home, ROOT)
            add_cached_plugin_skill(
                home,
                marketplace="unrelated-owner",
                plugin="not-remotion",
                skill="remotion-best-practices",
                enabled=True,
            )

            unrelated = verify_installation(
                repo=None,
                home=home,
                check_external_skills=True,
            )
            self.assertFalse(
                unrelated["external_adapters"]["remotion"]["available"],
                "a matching skill name from another enabled plugin is not Remotion",
            )

            add_cached_plugin_skill(
                home,
                marketplace="openai-bundled",
                plugin="remotion",
                skill="remotion-best-practices",
                frontmatter_name="remotion:remotion-best-practices",
                enabled=True,
            )
            result = verify_installation(
                repo=None,
                home=home,
                check_external_skills=True,
            )

            self.assertTrue(result["external_adapters"]["remotion"]["available"])


class RetirementSafetyTests(unittest.TestCase):
    def isolated_retirement_fixture(self, root, *, versioned=False, include_voice=True):
        repo = Path(root) / "repo"
        legacy = (
            Path(root)
            / ".codex"
            / "skills"
            / "knowledge-video-visual-director"
        )
        shutil.copytree(
            ROOT,
            repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__"),
        )
        populate_auditable_legacy(repo, legacy)
        installed = (
            activate_versioned_personal_plugin(root, repo)
            if versioned
            else activate_personal_plugin(root, repo)
        )
        enable_retirement_chatcut(root, include_voice=include_voice)
        return repo, legacy, installed

    def test_retirement_discovers_the_manifest_versioned_installed_cache(self):
        """Catches retirement hard-coding the obsolete literal local cache."""
        with TemporaryDirectory() as folder:
            home = Path(folder)
            cache = activate_versioned_personal_plugin(home, ROOT)

            self.assertEqual(cache.resolve(), _installed_plugin_candidate(home))

    def test_installed_verifier_requires_chatcut_base_and_voice_capabilities(self):
        """Catches retirement accepting smoke success without its voice provider."""
        installed = ROOT.resolve()
        fake = {
            "ok": True,
            "plugin": {
                "root": str(installed),
                "discovery": "host-installed",
                "valid": True,
            },
            "resume_smoke": {
                "ok": True,
                "checks": {"migration_audit": "passed"},
            },
            "external_adapters": {
                "chatcut": {
                    "available": True,
                    "capabilities": {
                        "voice.synthesize": {
                            "available": False,
                            "installed_skill": "chatcut:voice",
                        },
                        "voice.time": {
                            "available": False,
                            "installed_skill": "chatcut:voice",
                        },
                    },
                }
            },
            "errors": [],
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(fake), stderr=""
        )

        with patch("scripts.retire_legacy_skill.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "ChatCut Voice"):
                _run_installed_verifier(installed, Path.home(), LEGACY)

    def test_retirement_runs_smoke_from_the_installed_plugin_in_isolation(self):
        """Catches repository imports masking a broken installed orchestrator."""
        with TemporaryDirectory() as folder:
            repo, legacy, installed = self.isolated_retirement_fixture(Path(folder))
            for root in (repo, installed):
                (root / "scripts" / "toolkit" / "orchestrator.py").write_text(
                    "raise RuntimeError('broken installed orchestrator')\n",
                    encoding="utf-8",
                )
                manifest_path = root / ".codex-plugin" / "plugin.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["release_fingerprint"] = _release_fingerprint(root)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "installed"):
                retire_legacy_skill(
                    legacy,
                    repo,
                    confirmation=None,
                    dry_run=True,
                )

            self.assertTrue(legacy.is_dir())

    def test_retirement_requires_installed_runtime_content_to_match_repository(self):
        """Catches manifest-only equality accepting a modified installed package."""
        with TemporaryDirectory() as folder:
            repo, legacy, installed = self.isolated_retirement_fixture(Path(folder))
            skill = installed / "skills" / "video-director" / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8") + "\nmodified installed content\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "content|match"):
                retire_legacy_skill(
                    legacy,
                    repo,
                    confirmation=None,
                    dry_run=True,
                )

            self.assertTrue(legacy.is_dir())

    def test_retirement_requires_installed_review_pack_template(self):
        """Catches a missing distributable review-pack index reaching retirement."""
        with TemporaryDirectory() as folder:
            repo, legacy, installed = self.isolated_retirement_fixture(Path(folder))
            template = (
                installed
                / "assets"
                / "project-template"
                / "review-pack"
                / "index.html"
            )
            template.unlink()

            with self.assertRaisesRegex(RuntimeError, "index.html"):
                retire_legacy_skill(
                    legacy,
                    repo,
                    confirmation=None,
                    dry_run=True,
                )

            self.assertTrue(legacy.is_dir())

    def test_retirement_rejects_modified_installed_project_template_content(self):
        """Catches changed distributable project-template content being ignored."""
        with TemporaryDirectory() as folder:
            repo, legacy, installed = self.isolated_retirement_fixture(Path(folder))
            template = installed / "assets" / "project-template" / "project.json"
            template.write_text(
                '{"schema_version":1,"project_id":"modified"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "project.json"):
                retire_legacy_skill(
                    legacy,
                    repo,
                    confirmation=None,
                    dry_run=True,
                )

            self.assertTrue(legacy.is_dir())

    def test_retirement_requires_critical_runtime_files_in_both_package_copies(self):
        """Catches matching but incomplete packages reaching the installed verifier."""
        with TemporaryDirectory() as folder:
            repo, legacy, installed = self.isolated_retirement_fixture(Path(folder))
            for root in (repo, installed):
                (root / "scripts" / "verify_installation.py").unlink()

            with self.assertRaisesRegex(RuntimeError, "required runtime files"):
                retire_legacy_skill(
                    legacy,
                    repo,
                    confirmation=None,
                    dry_run=True,
                )

            self.assertTrue(legacy.is_dir())

    def test_runtime_fingerprint_requires_voice_ready_release_contracts(self):
        """Catches a distributable fingerprint that omits voice-ready runtime files."""
        required = (
            "skills/voiceover-producer/SKILL.md",
            "references/schemas/voice-source-decision.schema.json",
            "references/schemas/voice-profile.schema.json",
            "references/schemas/voiceover.schema.json",
            "references/schemas/voice-timing.schema.json",
            "scripts/toolkit/voice.py",
            "scripts/toolkit/voice_tasks.py",
            "scripts/toolkit/adapters.py",
            "scripts/toolkit/validation.py",
            "scripts/build_review_pack.py",
            "references/policies/decision-gates.md",
            "references/policies/invalidation.json",
            "scripts/toolkit/image_context.py",
            "references/policies/project-assets.md",
            "references/schemas/image-task-context.schema.json",
            "references/schemas/project.schema.json",
            "references/schemas/event.schema.json",
            "references/schemas/task-envelope.schema.json",
            "references/schemas/task-result.schema.json",
            "skills/scene-producer/SKILL.md",
            "skills/structural-validator/SKILL.md",
            "skills/timeline-assembler/SKILL.md",
            "registries/adapters/chatcut.json",
        )
        with TemporaryDirectory() as folder:
            repo = Path(folder) / "repo"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            for relative in required:
                (repo / relative).unlink()

            with self.assertRaisesRegex(RuntimeError, "required runtime files") as error:
                _distributable_hashes(repo, "replacement repository")

            for relative in required:
                self.assertIn(relative, str(error.exception))

    def test_retirement_refuses_missing_confirmation_and_symlinks(self):
        """Catches an unapproved or redirected path reaching recursive deletion."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / ".codex" / "skills" / "knowledge-video-visual-director"
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text("legacy\n", encoding="utf-8")

            with self.assertRaises(PermissionError):
                retire_legacy_skill(legacy, ROOT, confirmation=None)
            self.assertTrue(legacy.is_dir())

            link = root / "other" / "skills" / "knowledge-video-visual-director"
            link.parent.mkdir(parents=True)
            link.symlink_to(legacy, target_is_directory=True)
            with self.assertRaises(ValueError):
                retire_legacy_skill(link, ROOT, confirmation=str(link))
            self.assertTrue(legacy.is_dir())

    def test_retirement_requires_a_live_migration_audit_before_deletion(self):
        """Catches a matching basename bypassing the migration inventory gate."""
        with TemporaryDirectory() as folder:
            home = Path(folder)
            legacy = home / ".codex" / "skills" / "knowledge-video-visual-director"
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text("unreviewed legacy\n", encoding="utf-8")
            activate_personal_plugin(home, ROOT)

            with self.assertRaises(RuntimeError):
                retire_legacy_skill(
                    legacy,
                    ROOT,
                    confirmation=str(legacy.resolve()),
                )

            self.assertTrue(legacy.is_dir())

    def test_retirement_can_delete_only_a_verified_temporary_copy(self):
        """Catches retirement reporting success without exact audit, smoke, and deletion."""
        if not LEGACY.is_dir():
            self.skipTest("installed legacy skill is already absent")
        with TemporaryDirectory() as folder:
            temp = Path(folder)
            repo = temp / "repo"
            legacy = temp / ".codex" / "skills" / "knowledge-video-visual-director"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            shutil.copytree(LEGACY, legacy)
            activate_personal_plugin(temp, repo)
            enable_retirement_chatcut(temp)
            installed_snapshot = sorted(path.relative_to(LEGACY) for path in LEGACY.rglob("*") if path.is_file())

            dry_run = retire_legacy_skill(legacy, repo, confirmation=None, dry_run=True)
            self.assertEqual("ready", dry_run["status"])
            self.assertTrue(legacy.is_dir())

            result = retire_legacy_skill(
                legacy,
                repo,
                confirmation=str(legacy.resolve()),
            )

            self.assertEqual("retired", result["status"])
            self.assertFalse(legacy.exists())
            report = (repo / "docs" / "migration" / "knowledge-video-visual-director.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("## Retirement events", report)
            self.assertEqual(
                installed_snapshot,
                sorted(path.relative_to(LEGACY) for path in LEGACY.rglob("*") if path.is_file()),
                "the installed legacy directory must remain untouched",
            )

    def test_retirement_requires_a_host_installed_active_replacement(self):
        """Catches marketplace registration alone authorizing legacy retirement."""
        if not LEGACY.is_dir():
            self.skipTest("installed legacy skill is already absent")
        with TemporaryDirectory() as folder:
            temp = Path(folder)
            repo = temp / "repo"
            legacy = temp / ".codex" / "skills" / "knowledge-video-visual-director"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            shutil.copytree(LEGACY, legacy)
            install_personal_plugin(repo, home=temp, mode="link")

            with self.assertRaisesRegex(RuntimeError, "host-installed"):
                retire_legacy_skill(legacy, repo, confirmation=None, dry_run=True)

            self.assertTrue(legacy.is_dir())

    def test_unsafe_retirement_report_blocks_before_deleting_the_target(self):
        """Catches deletion completing before the required retirement event can publish."""
        if not LEGACY.is_dir():
            self.skipTest("installed legacy skill is already absent")
        with TemporaryDirectory() as folder:
            temp = Path(folder)
            repo = temp / "repo"
            legacy = temp / ".codex" / "skills" / "knowledge-video-visual-director"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            shutil.copytree(LEGACY, legacy)
            activate_personal_plugin(temp, repo)
            enable_retirement_chatcut(temp)
            report = repo / "docs" / "migration" / "knowledge-video-visual-director.md"
            external = temp / "external-report.md"
            external.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
            report.unlink()
            report.symlink_to(external)

            with self.assertRaises(RuntimeError):
                retire_legacy_skill(
                    legacy,
                    repo,
                    confirmation=str(legacy.resolve()),
                )

            self.assertTrue(legacy.is_dir())

    def test_report_publication_failure_restores_quarantined_legacy_directory(self):
        """Catches an event write failure leaving an unrecorded irreversible deletion."""
        if not LEGACY.is_dir():
            self.skipTest("installed legacy skill is already absent")
        with TemporaryDirectory() as folder:
            temp = Path(folder)
            repo = temp / "repo"
            legacy = temp / ".codex" / "skills" / "knowledge-video-visual-director"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            shutil.copytree(LEGACY, legacy)
            activate_personal_plugin(temp, repo)
            enable_retirement_chatcut(temp)
            original_files = sorted(
                path.relative_to(legacy) for path in legacy.rglob("*") if path.is_file()
            )

            with patch(
                "scripts.retire_legacy_skill._append_retirement_event",
                side_effect=OSError("simulated report write failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated report write failure"):
                    retire_legacy_skill(
                        legacy,
                        repo,
                        confirmation=str(legacy.resolve()),
                    )

            self.assertTrue(legacy.is_dir())
            self.assertEqual(
                original_files,
                sorted(path.relative_to(legacy) for path in legacy.rglob("*") if path.is_file()),
            )
            self.assertEqual([], list(legacy.parent.glob(".knowledge-video-visual-director.retiring-*")))


if __name__ == "__main__":
    unittest.main()

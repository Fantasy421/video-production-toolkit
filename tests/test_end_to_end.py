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

from scripts.install_personal_plugin import install_personal_plugin
from scripts.migration_audit import DISPOSITIONS
from scripts.retire_legacy_skill import retire_legacy_skill
from scripts.toolkit.artifacts import approve_artifact, create_artifact
from scripts.toolkit.orchestrator import (
    calculate_ready_tasks,
    invalidate_artifact_descendants,
    resume_project,
)
from scripts.toolkit.project_state import PHASES, append_event, initialize_project
from scripts.toolkit.tasks import claim_task, complete_task, create_task
from scripts.verify_installation import _run_resume_scenario, run_smoke, verify_installation


ROOT = Path(__file__).parents[1]
SHIPPED_INVALIDATION = json.loads(
    (ROOT / "references/policies/invalidation.json").read_text(encoding="utf-8")
)
FIXTURE = ROOT / "tests" / "fixtures" / "knowledge-video-minimal"
LEGACY = Path.home() / ".codex" / "skills" / "knowledge-video-visual-director"


def advance_project(project, target_phase):
    """Advance a fixture through the same legal phase events used in production."""
    for phase in PHASES[1 : PHASES.index(target_phase) + 1]:
        append_event(project, {"event": "project.phase_changed", "phase": phase})


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
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "version": version,
        "status": status,
        "parents": list(parents or []),
        "path": path or f"metadata/{artifact_id}.json",
        **metadata,
    }


def candidate(task_id, capability, inputs, gate, target_id, **constraints):
    inputs = list(inputs)
    if capability == "scene.produce":
        constraints.setdefault("visual_operation", "non-image")
    if capability in {
        "storyboard.plan",
        "scene.produce",
        "motion.preview",
        "motion.produce",
        "timeline.assemble",
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
            narration_id="narration-v1",
            mode="tts",
            decision="approved",
        ),
        artifact(
            "voice-profile-v1",
            "voice-profile",
            mode="tts",
            language="zh-CN",
            provider="chatcut",
            voice_id="narrator-1",
            speaking_rate=1.0,
            emotion="calm",
            pronunciations=[],
            approved=True,
        ),
        artifact(
            "voiceover-v1",
            "voiceover",
            parents=["narration-v1", "voice-profile-v1"],
            narration_id="narration-v1",
            profile_id="voice-profile-v1",
            media_path="media/voiceover-v1.wav",
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
    for record in voice_bundle():
        create_artifact(project, record)


class CoordinatorTests(unittest.TestCase):
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
            calculate_ready_tasks(
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
            calculate_ready_tasks(
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
            calculate_ready_tasks(
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
            calculate_ready_tasks(
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
            advance_project(project, "production_ready")
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
            advance_project(project, "production_ready")

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
            calculate_ready_tasks(
                {"phase": "initialized", "candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                approvals,
            ),
        )
        self.assertEqual(
            ["scene.produce:S01"],
            calculate_ready_tasks(
                {"phase": "storyboard_ready", "candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                approvals,
            ),
        )
        with self.assertRaises(ValueError):
            calculate_ready_tasks(
                {"phase": "not-a-phase", "candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                approvals,
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
                target_id = f"gate-target-{index}"
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

                self.assertEqual([], calculate_ready_tasks(state, artifacts, []))
                self.assertEqual(
                    [],
                    calculate_ready_tasks(
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
                    calculate_ready_tasks(
                        state,
                        [artifact(target_id, "unrelated-review-artifact"), *gate_voice],
                        [approval],
                    ),
                    "the gate must reject an approval targeting the wrong artifact type",
                )
                self.assertEqual(
                    [capability],
                    calculate_ready_tasks(
                        state,
                        artifacts,
                        [approval],
                    ),
                )

                descendant_id = f"gate-input-{index}"
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
                    calculate_ready_tasks(
                        unrelated_state,
                        [artifacts[0], artifact(descendant_id, "task-input"), *gate_voice],
                        [approval],
                    ),
                    "an artifact of the right type must not approve another lineage",
                )
                self.assertEqual(
                    [capability],
                    calculate_ready_tasks(
                        unrelated_state,
                        [
                            artifacts[0],
                            artifact(
                                descendant_id,
                                "task-input",
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
            calculate_ready_tasks(
                state,
                artifacts,
                [{"target_id": "storyboard-v1", "scope": "storyboard-and-cost", "decision": "approved"}],
            ),
        )
        self.assertEqual(
            ["scene.produce:S01"],
            calculate_ready_tasks(
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
            calculate_ready_tasks(
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
            calculate_ready_tasks(
                {"candidate_tasks": tasks, "locked_task_ids": []}, artifacts, approvals
            ),
        )
        self.assertEqual(
            [],
            calculate_ready_tasks(
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
            calculate_ready_tasks(
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
            calculate_ready_tasks(
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
            calculate_ready_tasks(
                {"candidate_tasks": [task], "locked_task_ids": []},
                artifacts,
                [approval],
            ),
        )

        task["constraints"]["gate_target_id"] = "slice-S01-v1"
        approval["target_id"] = "slice-S01-v1"
        self.assertEqual(
            ["scene.produce:S01"],
            calculate_ready_tasks(
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
                    calculate_ready_tasks(
                        {"candidate_tasks": [task], "locked_task_ids": []},
                        artifacts,
                        [slice_approval],
                    ),
                )

                task["constraints"]["gate_target_id"] = "final-v1"
                final_approval = {**slice_approval, "target_id": "final-v1"}
                self.assertEqual(
                    ["review.package"],
                    calculate_ready_tasks(
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
            self.assertEqual([], list((project / "media").iterdir()))

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
            )
            create_task(project, envelope)
            create_artifact(
                project,
                artifact(
                    "review-S02-v1",
                    "review-pack",
                    parents=["scene-S02-v1"],
                    output_contract="task-result-v1",
                ),
            )
            claim = claim_task(project, "review-S02", "worker-a")

            invalidate_artifact_descendants(
                project,
                "contract-S02-v1",
                SHIPPED_INVALIDATION,
            )
            status = complete_task(
                project,
                {
                    "task_id": "review-S02",
                    "status": "succeeded",
                    "inputs": ["scene-S02-v1"],
                    "artifacts": ["review-S02-v1"],
                    "checks": ["review-ready"],
                    "warnings": [],
                    **claim,
                },
            )

            self.assertEqual("stale-result", status)
            self.assertTrue(
                (project / "tasks" / "stale-results" / "review-S02.json").is_file()
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
                    ["storyboard-v1"],
                    "storyboard-and-cost",
                    "storyboard-v1",
                    production_scope="representative-slice",
                    scene_id="S02",
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

        self.assertEqual(2, len(observed))
        self.assertGreater(len(observed[0]), 44)
        self.assertEqual(observed[0], observed[1])
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

        def weak_gate_router(state, artifacts, approvals):
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

            self.assertTrue(target.is_symlink())
            self.assertEqual(ROOT.resolve(), target.resolve())
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
    def isolated_retirement_fixture(self, root):
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
        installed = activate_personal_plugin(root, repo)
        return repo, legacy, installed

    def test_retirement_runs_smoke_from_the_installed_plugin_in_isolation(self):
        """Catches repository imports masking a broken installed orchestrator."""
        with TemporaryDirectory() as folder:
            repo, legacy, installed = self.isolated_retirement_fixture(Path(folder))
            for root in (repo, installed):
                (root / "scripts" / "toolkit" / "orchestrator.py").write_text(
                    "raise RuntimeError('broken installed orchestrator')\n",
                    encoding="utf-8",
                )

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

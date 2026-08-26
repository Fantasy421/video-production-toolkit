import json
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.install_personal_plugin import install_personal_plugin
from scripts.retire_legacy_skill import retire_legacy_skill
from scripts.toolkit.artifacts import approve_artifact, create_artifact
from scripts.toolkit.orchestrator import (
    calculate_ready_tasks,
    invalidate_artifact_descendants,
    resume_project,
)
from scripts.toolkit.project_state import initialize_project
from scripts.toolkit.tasks import claim_task, complete_task, create_task
from scripts.verify_installation import run_smoke, verify_installation


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "knowledge-video-minimal"
LEGACY = Path.home() / ".codex" / "skills" / "knowledge-video-visual-director"


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


class CoordinatorTests(unittest.TestCase):
    def test_all_four_gates_require_an_exact_durable_approval(self):
        """Catches any creative stage advancing on silence or the wrong scope."""
        cases = (
            ("narration.plan", "content", "decision-pack", {}),
            ("storyboard.plan", "visual-direction", "decision-pack", {}),
            (
                "scene.produce",
                "storyboard-and-cost",
                "decision-pack",
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
                artifacts = [artifact(target_id, target_type)]
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
                self.assertEqual(
                    [capability],
                    calculate_ready_tasks(
                        state,
                        artifacts,
                        [{"target_id": target_id, "scope": gate, "decision": "approved"}],
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
        artifacts = [artifact("slice-v1", "representative-slice")]

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
                [artifact("storyboard-v1", "storyboard")],
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
                [artifact("slice-v1", "representative-slice")],
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
                [artifact("storyboard-v1", "storyboard")],
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

            stale = invalidate_artifact_descendants(
                project,
                "contract-S02-v1",
                {"scene-contract": ["media", "timeline", "review-pack"]},
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
            claim = claim_task(project, "review-S02", "worker-a")

            invalidate_artifact_descendants(
                project,
                "contract-S02-v1",
                {"scene-contract": ["media", "timeline", "review-pack"]},
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


class RetirementSafetyTests(unittest.TestCase):
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

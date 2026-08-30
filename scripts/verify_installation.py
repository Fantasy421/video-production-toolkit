#!/usr/bin/env python3
"""Verify plugin packaging, personal discovery, adapters, and recovery smoke."""

import argparse
import inspect
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.migration_audit import audit_legacy
from scripts.plan_representative_slice import select_representative_slice
from scripts.toolkit.artifacts import approve_artifact, create_artifact
from scripts.toolkit.orchestrator import (
    _capability_is_legal_in_phase,
    _has_gate_approval,
    calculate_ready_tasks,
    invalidate_artifact_descendants,
    resume_project,
)
from scripts.toolkit.project_state import append_event, initialize_project
from scripts.toolkit.tasks import create_task
from scripts.toolkit.validation import validate_project
from scripts.toolkit.visual_media_context import (
    compact_visual_media_result,
    project_legacy_image_context,
    validate_result_envelope,
)
from scripts.toolkit.voice import (
    validate_authoritative_voice_bundle,
    validate_project_authoritative_voice_bundle,
)
from scripts.toolkit.semantic_beats import (
    freeze_semantic_beats,
    project_legacy_timed_beats,
)
from scripts.toolkit.timed_semantic_beats import bind_semantic_beats
from scripts.toolkit.timing_validation import validate_timing_rows
from scripts.validate_package import PLUGIN_VERSION, validate_package


PLUGIN_ID = "video-production-toolkit"
LEGACY_SKILL = "knowledge-video-visual-director"
MIGRATION_REPORT = Path("docs/migration/knowledge-video-visual-director.md")
BASELINE = Path("references/policies/knowledge-video-visual-director-baseline.json")
_PLUGIN_TABLE = re.compile(
    r"^\[\s*plugins\s*\.\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_.-]+))\s*\]\s*(?:#.*)?$"
)
_ENABLED_VALUE = re.compile(r"^enabled\s*=\s*(true|false)\s*(?:#.*)?$", re.IGNORECASE)


def run_smoke(root: Path, *, legacy_root: Optional[Path] = None) -> dict[str, Any]:
    """Run a metadata-only resume, invalidation, gate, and slice scenario."""
    root = Path(root).resolve()
    checks = {
        "migration_audit": "failed",
        "direction_ready_blocks_production": "not-run",
        "voice_source_decision": "not-run",
        "real_voice_timing": "not-run",
        "voice_ready_storyboard": "not-run",
        "voice_timing_revision": "not-run",
        "resume_local_invalidation": "not-run",
        "four_approval_gates": "not-run",
        "representative_slice": "not-run",
        "one_action_only": "not-run",
        "no_media_generation": "not-run",
    }
    migration = _migration_prerequisite(root, legacy_root)
    if not migration["ok"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "migration-audit-required",
                "detail": migration["detail"],
            },
        }
    checks["migration_audit"] = "passed"

    try:
        gates_ok = _check_four_gates()
        resumed = _run_resume_scenario()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "resume-smoke-failed", "detail": str(error)},
        }
    if not gates_ok:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "approval-gate-failed",
                "detail": "a gate advanced without exact approval",
            },
        }
    checks["four_approval_gates"] = "passed"
    if resumed["direction_ready_actions"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "direction-ready-production-not-blocked",
                "detail": resumed["direction_ready_actions"],
            },
        }
    checks["direction_ready_blocks_production"] = "passed"

    pre_revision = resumed["pre_timing_revision"]
    records = pre_revision["artifacts"]
    voice_records = pre_revision["voice_artifacts"]
    voice_source = [
        item
        for item in voice_records
        if item.get("type") == "voice-source-decision"
        and item.get("status") == "approved"
        and item.get("mode") in {"tts", "uploaded-voice"}
        and item.get("decision") == "approved"
    ]
    if len(voice_source) != 1:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "voice-source-decision-missing",
                "detail": voice_source,
            },
        }
    checks["voice_source_decision"] = "passed"
    bundle = validate_authoritative_voice_bundle(voice_records)
    validation_issues = resumed["voice_timing_revision"]["voice_validation_issue_codes"]
    if (
        not bundle["ok"]
        or bundle["voice_timing_id"] != "voice-timing-v1"
        or validation_issues
    ):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "real-voice-timing-required",
                "detail": {
                    "lineage_issues": bundle["issues"],
                    "file_duration_issues": validation_issues,
                },
            },
        }
    checks["real_voice_timing"] = "passed"
    if (
        resumed["voice_ready_phase"] != "voice_ready"
        or resumed["voice_ready_actions"] != ["storyboard.plan"]
    ):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "voice-ready-storyboard-not-routable",
                "detail": {
                    "phase": resumed["voice_ready_phase"],
                    "actions": resumed["voice_ready_actions"],
                },
            },
        }
    checks["voice_ready_storyboard"] = "passed"
    revision = resumed["voice_timing_revision"]
    if (
        revision["invalidated_artifact_ids"] != revision["declared_descendant_ids"]
        or revision["preserved_artifact_ids"]
        != ["semantic-beats-v1", "style-v1", "voice-timing-v2"]
        or revision["current_voice_timing_id"] != "voice-timing-v2"
        or revision["style_status"] != "approved"
        or revision["stale_descendant_ids"] != revision["declared_descendant_ids"]
    ):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "voice-timing-invalidation-failed", "detail": revision},
        }
    checks["voice_timing_revision"] = "passed"

    contracts_path = root / "tests" / "fixtures" / "knowledge-video-minimal" / "scene-contracts.json"
    try:
        contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
        selected_slice = select_representative_slice(
            contracts,
            voice_records,
            allow_legacy_unresolved_timing=True,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "representative-slice-fixture-invalid", "detail": str(error)},
        }
    if selected_slice.blocked or not (10000 <= selected_slice.duration_ms <= 20000):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "representative-slice-unavailable",
                "detail": selected_slice.blocker,
            },
        }
    selected_contracts = {
        item["primary_carrier"] for item in contracts if item["scene_id"] in selected_slice
    }
    if not {"scene", "motion-graphics"}.issubset(selected_contracts):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "representative-slice-risk-missing",
                "detail": sorted(selected_contracts),
            },
        }
    checks["representative_slice"] = "passed"
    if pre_revision["ready_tasks"] != ["scene.produce:S02"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "local-rebuild-failed",
                "detail": pre_revision["ready_tasks"],
            },
        }
    effective = {item["artifact_id"]: item for item in pre_revision["artifacts"]}
    if (
        effective["scene-S01-v1"]["status"] != "approved"
        or effective["scene-S02-v1"]["status"] != "stale"
    ):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "local-invalidation-failed", "detail": effective},
        }
    checks["resume_local_invalidation"] = "passed"
    checks["one_action_only"] = "passed"
    generated_media = sorted(
        set(resumed["media_files"]) - set(resumed["seeded_media_files"])
    )
    if generated_media or not resumed["voice_fixture_unchanged"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "coordinator-generated-media",
                "detail": {
                    "generated": generated_media,
                    "voice_fixture_unchanged": resumed["voice_fixture_unchanged"],
                },
            },
        }
    checks["no_media_generation"] = "passed"
    return {
        "ok": True,
        "checks": checks,
        "ready_tasks": resumed["ready_tasks"],
        "representative_slice": {
            "scene_ids": list(selected_slice),
            "ranges": [list(item) for item in selected_slice.ranges],
            "duration_ms": selected_slice.duration_ms,
            "composite": selected_slice.composite,
            "voice_timing_id": selected_slice.voice_timing_id,
        },
    }


def run_installed_visual_media_smoke(root: Path) -> dict[str, Any]:
    """Run the installed copy's public metadata runtime in an isolated process."""
    root = Path(root).resolve()
    verifier = root / "scripts" / "verify_installation.py"
    if not verifier.is_file():
        return {
            "ok": False,
            "blocker": {
                "code": "installed-visual-smoke-missing",
                "detail": str(verifier),
            },
        }
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(verifier),
            "--visual-media-smoke-root",
            str(root),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {
            "ok": False,
            "blocker": {
                "code": "installed-visual-smoke-invalid-output",
                "detail": completed.stderr.strip() or completed.stdout.strip(),
            },
        }
    if not isinstance(result, dict):
        return {
            "ok": False,
            "blocker": {
                "code": "installed-visual-smoke-invalid-output",
                "detail": "smoke result must be an object",
            },
        }
    if completed.returncode and result.get("ok"):
        result = {
            "ok": False,
            "blocker": {
                "code": "installed-visual-smoke-process-failed",
                "detail": completed.stderr.strip(),
            },
        }
    return result


def run_installed_timing_smoke(root: Path) -> dict[str, Any]:
    """Run the installed timing runtime in a clean Python process.

    The child receives only the installed cache path.  It exercises compact
    timing metadata and never opens audio or visual payloads, so repository
    imports cannot mask a broken installed package.
    """
    root = Path(root).resolve()
    verifier = root / "scripts" / "verify_installation.py"
    if not verifier.is_file():
        return {
            "ok": False,
            "blocker": {
                "code": "installed-timing-smoke-missing",
                "detail": str(verifier),
            },
        }
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(verifier),
            "--timing-smoke-root",
            str(root),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {
            "ok": False,
            "blocker": {
                "code": "installed-timing-smoke-invalid-output",
                "detail": completed.stderr.strip() or completed.stdout.strip(),
            },
        }
    if not isinstance(result, dict):
        return {
            "ok": False,
            "blocker": {
                "code": "installed-timing-smoke-invalid-output",
                "detail": "smoke result must be an object",
            },
        }
    if completed.returncode and result.get("ok"):
        return {
            "ok": False,
            "blocker": {
                "code": "installed-timing-smoke-process-failed",
                "detail": completed.stderr.strip(),
            },
        }
    return result


def _run_timing_smoke_in_process(root: Path) -> dict[str, Any]:
    """Exercise the installed timing APIs using JSON-shaped metadata only."""
    root = Path(root).resolve()
    checks = {
        "installed_module": "not-run",
        "frozen_semantic_beats": "not-run",
        "real_timing_binding": "not-run",
        "storyboard_gate": "not-run",
        "compact_validation": "not-run",
        "stale_timing_recovery": "not-run",
        "v2_compatibility": "not-run",
        "json_metadata_only": "not-run",
    }
    try:
        manifest = json.loads(
            (root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        plugin_version = manifest.get("version") if isinstance(manifest, dict) else None
        if plugin_version != PLUGIN_VERSION:
            raise ValueError(
                f"installed timing smoke requires plugin version {PLUGIN_VERSION}"
            )
        module_paths = {
            Path(inspect.getfile(freeze_semantic_beats)).resolve(),
            Path(inspect.getfile(bind_semantic_beats)).resolve(),
            Path(inspect.getfile(validate_timing_rows)).resolve(),
        }
        expected_root = (root / "scripts" / "toolkit").resolve()
        if not module_paths or any(path.parent != expected_root for path in module_paths):
            raise ValueError("timing runtime was not loaded from the installed cache")
        checks["installed_module"] = "passed"

        candidates = [
            {
                "beat_id": "B01",
                "text_ref": "narration-v1:S01:L1",
                "keyword": "timing",
                "intent": "core-concept-emphasis",
                "priority": "primary",
                "preferred_carrier": "motion-graphics",
            }
        ]
        semantic = freeze_semantic_beats(
            "narration-v1",
            candidates,
            {
                "decision": "approved",
                "provenance": "user:timing-smoke-v1",
                "keywords": ["timing"],
            },
        )
        if (
            semantic.get("narration_id") != "narration-v1"
            or "voice_timing_id" in semantic
            or "keyword_start_ms" in json.dumps(semantic)
        ):
            raise ValueError("semantic beat freeze was not untimed and compact")
        checks["frozen_semantic_beats"] = "passed"

        anchor = {
            "beat_id": "B01",
            "keyword": "timing",
            "start_ms": 1_200,
            "end_ms": 1_500,
        }
        timing = _artifact(
            "voice-timing-v1",
            "voice-timing",
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=2_400,
            segments=[{"start_ms": 0, "end_ms": 2_400, "text": "segment"}],
            keyword_anchors=[anchor],
        )
        timed = bind_semantic_beats(semantic, timing, [anchor])
        if timed.get("timing_kind") != "real" or timed.get("voice_timing_id") != timing[
            "artifact_id"
        ]:
            raise ValueError("real timing binding did not preserve authoritative lineage")
        checks["real_timing_binding"] = "passed"

        # Test the storyboard gate directly against compact coordinator inputs;
        # routing this check through a project would require an audio file.
        storyboard = _candidate(
            "timing-smoke-storyboard",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
        )
        gate_artifacts = {
            "style-v1": _artifact("style-v1", "style-pack"),
            "voice-timing-v1": timing,
            "smoke-routing-scene-contract-v1": _artifact(
                "smoke-routing-scene-contract-v1", "scene-contract"
            ),
        }
        if not _capability_is_legal_in_phase(storyboard, "timing_bound"):
            raise ValueError("storyboard gate is not legal at timing_bound")
        if _has_gate_approval(
            storyboard, "visual-direction", gate_artifacts, []
        ) or not _has_gate_approval(
            storyboard,
            "visual-direction",
            gate_artifacts,
            [{"target_id": "style-v1", "scope": "visual-direction", "decision": "approved"}],
        ):
            raise ValueError("storyboard gate did not require exact approval")
        checks["storyboard_gate"] = "passed"

        valid_row = {
            "beat_id": "B01",
            "scene_id": "S01",
            "keyword_anchor_ms": [1_200, 1_500],
            "visual_window_ms": [1_080, 1_700],
            "scene_window_ms": [0, 2_400],
            "primary_carrier": "motion-graphics",
            "support_layer": "caption-emphasis",
            "timing_kind": "real",
            "voice_timing_id": "voice-timing-v1",
            "current_voice_timing_id": "voice-timing-v1",
        }
        compact = validate_timing_rows([valid_row], minimum_readable_duration_ms=500)
        if compact.get("status") != "passed" or set(compact) != {"status", "checks_run"}:
            raise ValueError("compact timing validation did not pass")
        checks["compact_validation"] = "passed"

        stale = dict(valid_row)
        stale["voice_timing_status"] = "stale"
        stale_result = validate_timing_rows([stale], minimum_readable_duration_ms=500)
        if (
            stale_result.get("status") != "blocked"
            or stale_result.get("issue_counts", {}).get("STALE_VOICE_TIMING") != 1
        ):
            raise ValueError("stale timing was not blocked during recovery")
        checks["stale_timing_recovery"] = "passed"

        legacy = {
            "artifact_id": "semantic-beats-v0",
            "type": "semantic-beats",
            "version": 1,
            "status": "approved",
            "parents": ["voice-timing-v0"],
            "path": "metadata/semantic-beats-v0.json",
            "voice_timing_id": "voice-timing-v0",
        }
        if project_legacy_timed_beats(legacy) != legacy:
            raise ValueError("v2 semantic timing projection was not preserved")
        checks["v2_compatibility"] = "passed"

        with TemporaryDirectory() as folder:
            metadata_root = Path(folder) / "metadata-only"
            initialize_project(metadata_root, "timing-smoke", "knowledge-video")
            suffixes = {
                ".aac", ".avi", ".flac", ".jpg", ".m4a", ".mkv", ".mov",
                ".mp3", ".mp4", ".png", ".wav", ".webm",
            }
            created = sorted(
                path.relative_to(metadata_root).as_posix()
                for path in metadata_root.rglob("*")
                if path.is_file() and path.suffix.lower() in suffixes
            )
            if created:
                raise ValueError(f"timing smoke created media files: {created}")
        checks["json_metadata_only"] = "passed"
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        return {
            "ok": False,
            "plugin_version": locals().get("plugin_version"),
            "runtime_module_path": str(sorted(module_paths)[0])
            if "module_paths" in locals()
            else "",
            "checks": checks,
            "blocker": {
                "code": "timing-smoke-failed",
                "detail": str(error),
            },
        }
    return {
        "ok": True,
        "plugin_version": plugin_version,
        "runtime_module_path": str(sorted(module_paths)[0]),
        "checks": checks,
    }


def _run_visual_media_smoke_in_process(root: Path) -> dict[str, Any]:
    """Exercise only JSON-shaped public runtime boundaries from this package copy."""
    root = Path(root).resolve()
    checks = {
        "child_only_routing": "not-run",
        "none_laundering": "not-run",
        "universal_scrub": "not-run",
        "exact_scope": "not-run",
        "legacy_projection": "not-run",
        "one_preview_relay": "not-run",
        "json_metadata_only": "not-run",
    }
    stable_errors: dict[str, str] = {}
    try:
        manifest = json.loads(
            (root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        plugin_version = manifest.get("version") if isinstance(manifest, dict) else None
        if plugin_version != PLUGIN_VERSION:
            raise ValueError(
                f"installed visual smoke requires plugin version {PLUGIN_VERSION}"
            )
        module_path = Path(inspect.getfile(validate_result_envelope)).resolve()
        expected_module = (
            root / "scripts" / "toolkit" / "visual_media_context.py"
        ).resolve()
        if module_path != expected_module:
            raise ValueError("visual media runtime was not loaded from the installed cache")

        def capture_error(name: str, action: Any, expected: str) -> None:
            try:
                action()
            except (PermissionError, ValueError) as error:
                stable_errors[name] = str(error)
            else:
                raise RuntimeError(f"{name} malformed record was accepted")
            if stable_errors[name] != expected:
                raise RuntimeError(
                    f"{name} returned unstable error: {stable_errors[name]}"
                )
            checks[name] = "passed"

        with TemporaryDirectory() as folder:
            project = Path(folder) / "metadata-smoke"
            initialize_project(project, "visual-isolation-smoke", "knowledge-video")

            def artifact_record(
                artifact_id: str, artifact_type: str, **metadata: Any
            ) -> dict[str, Any]:
                return json.loads(
                    json.dumps(
                        {
                            "artifact_id": artifact_id,
                            "type": artifact_type,
                            "version": 1,
                            "status": "approved",
                            "parents": [],
                            "path": f"metadata/{artifact_id}.json",
                            **metadata,
                        }
                    )
                )

            for record in (
                artifact_record("scene-one", "scene-contract"),
                artifact_record("scene-two", "scene-contract"),
                artifact_record(
                    "current-frame",
                    "scene-image",
                    historical=False,
                    path="metadata/current-frame",
                ),
            ):
                create_artifact(project, record)

            context = {
                "scope_identity": {"kind": "scene-contract", "id": "scene-one"},
                "allowed_artifact_ids": [],
                "historical_access": "character-only",
                "continuity_exception": None,
                "max_review_previews": 1,
                "context_budget_bytes": 32768,
            }

            def envelope(
                task_id: str,
                capability: str,
                inputs: list[str],
                operation: str,
                *,
                child: bool = False,
                visual_context: Optional[dict[str, Any]] = None,
            ) -> dict[str, Any]:
                constraints: dict[str, Any] = {
                    "visual_media_operation": operation
                }
                if child:
                    constraints["execution_context"] = "isolated-child-agent"
                if visual_context is not None:
                    constraints["visual_media_context"] = visual_context
                return json.loads(
                    json.dumps(
                        {
                            "task_id": task_id,
                            "capability": capability,
                            "inputs": inputs,
                            "adapter_preferences": ["chatcut"],
                            "output_contract": "task-result-v1",
                            "constraints": constraints,
                        }
                    )
                )

            valid = envelope(
                "visual-child",
                "visual.preview",
                ["scene-one"],
                "image-generate",
                child=True,
                visual_context=context,
            )
            create_task(project, valid)

            capture_error(
                "child_only_routing",
                lambda: create_task(
                    project,
                    envelope(
                        "visual-primary",
                        "visual.preview",
                        ["scene-one"],
                        "image-generate",
                        visual_context=context,
                    ),
                ),
                "visual media task requires an isolated child agent",
            )
            capture_error(
                "none_laundering",
                lambda: create_task(
                    project,
                    envelope(
                        "laundered-none",
                        "project.manage",
                        ["current-frame"],
                        "none",
                    ),
                ),
                "visual media task cannot declare operation none",
            )
            capture_error(
                "exact_scope",
                lambda: create_task(
                    project,
                    envelope(
                        "neighboring-scene",
                        "visual.preview",
                        ["scene-one", "scene-two"],
                        "image-generate",
                        child=True,
                        visual_context=context,
                    ),
                ),
                "visual media task requires exactly one scene-contract scope and no neighbor",
            )
            capture_error(
                "universal_scrub",
                lambda: validate_result_envelope(
                    {"task_id": "scrubbed", "checks": {"nested": {"payload": "x"}}}
                ),
                "visual media result must not contain an image payload or other media payload",
            )

            legacy = project_legacy_image_context(
                {
                    "constraints": {
                        "image_operation": "image-inspect",
                        "image_context": {
                            "scope_identity": {
                                "kind": "scene-contract",
                                "id": "scene-one",
                            },
                            "allowed_image_artifact_ids": [],
                            "allowed_character_pack_ids": [],
                            "forbidden_scene_image_access": True,
                            "max_review_previews": 1,
                            "context_budget": 32768,
                        },
                    }
                }
            )
            if legacy != context:
                raise RuntimeError("legacy image authority projection changed")
            checks["legacy_projection"] = "passed"

            compact = compact_visual_media_result(
                context,
                {
                    "artifact_ids": ["scene-output"],
                    "paths": ["media/scene-output.json"],
                    "media": {
                        "kind": "video",
                        "format": "metadata-only",
                        "mime_type": "video/mp4",
                        "width": 1920,
                        "height": 1080,
                        "duration_ms": 1000,
                        "fps": 24,
                        "readiness": "user-review",
                        "checksum": "0123456789abcdef",
                    },
                    "checks": ["structure-only"],
                    "issues": [],
                    "summary": "metadata relay",
                    "review_preview_path": "previews/scene-output.html",
                },
            )
            if compact["review_preview_path"] != "previews/scene-output.html":
                raise RuntimeError("one review preview was not relayed exactly")
            checks["one_preview_relay"] = "passed"

            visual_suffixes = {
                ".apng",
                ".avif",
                ".avi",
                ".bmp",
                ".gif",
                ".heic",
                ".heif",
                ".jpeg",
                ".jpg",
                ".m4v",
                ".mkv",
                ".mov",
                ".mp4",
                ".mpeg",
                ".mpg",
                ".png",
                ".svg",
                ".tif",
                ".tiff",
                ".webm",
                ".webp",
            }
            created_visual_files = sorted(
                path.relative_to(project).as_posix()
                for path in project.rglob("*")
                if path.is_file() and path.suffix.lower() in visual_suffixes
            )
            if created_visual_files:
                raise RuntimeError(
                    f"visual smoke created visual files: {created_visual_files}"
                )
            checks["json_metadata_only"] = "passed"
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        return {
            "ok": False,
            "plugin_version": locals().get("plugin_version"),
            "runtime_module_path": str(locals().get("module_path", "")),
            "checks": checks,
            "stable_errors": stable_errors,
            "blocker": {
                "code": "visual-media-isolation-smoke-failed",
                "detail": str(error),
            },
        }
    return {
        "ok": True,
        "plugin_version": plugin_version,
        "runtime_module_path": str(module_path),
        "checks": checks,
        "stable_errors": stable_errors,
    }


def verify_installation(
    *,
    repo: Optional[Path] = None,
    home: Optional[Path] = None,
    require_skill: Optional[str] = None,
    forbid_skill: Optional[str] = None,
    check_external_skills: bool = False,
    require_resume_smoke: bool = False,
    require_visual_media_smoke: bool = False,
    require_timing_smoke: bool = False,
    legacy_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Return structured package, discovery, external, and smoke status."""
    personal_home = (Path.home() if home is None else Path(home)).resolve()
    warnings: list[str] = []
    errors: list[str] = []
    if repo is None:
        try:
            plugin_root = discover_host_installed_plugin(personal_home, PLUGIN_ID)
            discovery = "host-installed"
        except ValueError as error:
            return {
                "ok": False,
                "plugin": {"id": PLUGIN_ID, "discovery": "missing", "root": None},
                "external_adapters": {},
                "warnings": [],
                "errors": [str(error)],
            }
    else:
        plugin_root = Path(repo).resolve()
        discovery = "repo"
    package_issues = validate_package(plugin_root)
    errors.extend(package_issues)
    skill_names = _plugin_skill_names(plugin_root)
    if require_skill and require_skill not in skill_names:
        errors.append(f"required skill is not discoverable: {require_skill}")
    if forbid_skill and _skill_is_discoverable(personal_home, plugin_root, forbid_skill):
        errors.append(f"forbidden skill remains discoverable: {forbid_skill}")

    external: dict[str, dict[str, Any]] = {}
    if check_external_skills:
        try:
            discovered = _all_personal_skill_names(personal_home)
        except ValueError as error:
            errors.append(str(error))
            discovered = set()
        adapters_root = plugin_root / "registries" / "adapters"
        for path in sorted(adapters_root.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                errors.append(f"invalid adapter manifest: {path.name}: {error}")
                continue
            adapter_id = manifest.get("id", path.stem)
            required = manifest.get("installed_skill")
            available = _matches_installed_skill(required, discovered, adapter_id)
            capability_skills = manifest.get("capability_skills", {})
            capabilities: dict[str, dict[str, Any]] = {}
            if not isinstance(capability_skills, dict):
                errors.append(f"invalid adapter capability skills: {path.name}")
                capability_skills = {}
            for capability, capability_skill in sorted(capability_skills.items()):
                if not isinstance(capability, str) or not capability:
                    errors.append(f"invalid adapter capability name: {path.name}")
                    continue
                capabilities[capability] = {
                    "installed_skill": capability_skill,
                    "available": _matches_installed_skill(
                        capability_skill, discovered, adapter_id
                    ),
                    "required": False,
                }
                if not capabilities[capability]["available"]:
                    warnings.append(
                        "optional external capability unavailable: "
                        f"{adapter_id}/{capability}: {capability_skill}"
                    )
            external[adapter_id] = {
                "installed_skill": required,
                "available": available,
                "required": False,
                "capabilities": capabilities,
            }
            if not available:
                warnings.append(f"optional external skill unavailable: {required}")

    smoke: Optional[dict[str, Any]] = None
    if require_resume_smoke:
        effective_legacy = legacy_root
        if effective_legacy is None:
            candidate = personal_home / ".codex" / "skills" / LEGACY_SKILL
            effective_legacy = candidate if candidate.exists() else None
        smoke = run_smoke(plugin_root, legacy_root=effective_legacy)
        if not smoke["ok"]:
            errors.append(f"resume smoke failed: {smoke.get('blocker')}")

    visual_media_smoke: Optional[dict[str, Any]] = None
    if require_visual_media_smoke:
        visual_media_smoke = run_installed_visual_media_smoke(plugin_root)
        if not visual_media_smoke["ok"]:
            errors.append(
                "visual media isolation smoke failed: "
                f"{visual_media_smoke.get('blocker')}"
            )

    timing_smoke: Optional[dict[str, Any]] = None
    if require_timing_smoke:
        timing_smoke = run_installed_timing_smoke(plugin_root)
        if not timing_smoke["ok"]:
            errors.append(
                "timing smoke failed: " f"{timing_smoke.get('blocker')}"
            )

    return {
        "ok": not errors,
        "plugin": {
            "id": PLUGIN_ID,
            "discovery": discovery,
            "root": str(plugin_root),
            "valid": not package_issues,
            "skills": sorted(skill_names),
        },
        "external_adapters": external,
        "resume_smoke": smoke,
        "visual_media_smoke": visual_media_smoke,
        "timing_smoke": timing_smoke,
        "warnings": warnings,
        "errors": errors,
    }


def discover_host_installed_plugin(home: Path, plugin_id: str = PLUGIN_ID) -> Path:
    """Resolve one enabled host cache copy, not merely its marketplace source."""
    home = Path(home).resolve()
    if not _safe_component(plugin_id):
        raise ValueError("plugin id is not a safe component")
    source_root = _discover_personal_plugin(home, plugin_id)
    catalog = _read_personal_marketplace(home)
    marketplace_name = catalog.get("name")
    if not _safe_component(marketplace_name):
        raise ValueError("personal marketplace name is not a safe component")
    config = home / ".codex" / "config.toml"
    if config.is_symlink() or not config.is_file():
        raise ValueError("plugin is not host-installed and enabled")
    plugin_key = f"{plugin_id}@{marketplace_name}"
    if not _plugin_is_enabled(config, plugin_key):
        raise ValueError("plugin is not host-installed and enabled")
    cache_root = (
        home
        / ".codex"
        / "plugins"
        / "cache"
        / marketplace_name
        / plugin_id
    )
    try:
        cache_root.resolve().relative_to(home)
    except ValueError:
        raise ValueError("host-installed plugin cache escapes personal home") from None
    if cache_root.is_symlink():
        raise ValueError("host-installed plugin cache must not be a symlink")
    try:
        manifest = json.loads(
            (source_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("personal plugin manifest is invalid") from error
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not _safe_component(version):
        raise ValueError("personal plugin manifest version is invalid")
    cache = cache_root / version
    # Older local-plugin hosts used a literal `local` cache directory. Keep
    # that layout readable while preferring the manifest-versioned host cache.
    if not cache.exists() and (cache_root / "local").exists():
        cache = cache_root / "local"
    if cache.is_symlink():
        raise ValueError("host-installed plugin cache must not be a symlink")
    try:
        installed = cache.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("plugin is not host-installed and enabled") from error
    if not installed.is_dir():
        raise ValueError("host-installed plugin cache is not a directory")
    return installed


def _check_four_gates() -> bool:
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
    with TemporaryDirectory() as folder:
        routing_root = Path(folder)
        media = routing_root / "media" / "voiceover-v1.wav"
        media.parent.mkdir(parents=True)
        media.write_bytes(_voice_fixture_wav(duration_ms=15_000))
        for index, (capability, gate, target_type, extra) in enumerate(cases, 1):
            target_id = (
                f"storyboard-gate-{index}"
                if target_type == "storyboard"
                else f"gate-{index}"
            )
            task = _candidate(
                f"gate-task-{index}", capability, [target_id], gate, target_id, **extra
            )
            gate_voice = (
                _voice_bundle()
                if capability
                in {
                    "storyboard.plan",
                    "scene.produce",
                    "motion.preview",
                    "motion.produce",
                    "timeline.assemble",
                    "captions.produce",
                    "representative-slice.produce",
                }
                else []
            )
            routing_scope = (
                [_artifact("smoke-routing-scene-contract-v1", "scene-contract")]
                if "smoke-routing-scene-contract-v1" in task["inputs"]
                else []
            )
            artifacts = [
                _artifact(target_id, target_type),
                *routing_scope,
                *gate_voice,
            ]
            state = {"candidate_tasks": [task], "locked_task_ids": []}
            if calculate_ready_tasks(state, artifacts, [], root=routing_root):
                return False
            approval = {"target_id": target_id, "scope": gate, "decision": "approved"}
            if calculate_ready_tasks(
                state,
                [
                    _artifact(target_id, "unrelated-review-artifact"),
                    *routing_scope,
                    *gate_voice,
                ],
                [approval],
                root=routing_root,
            ):
                return False
            if calculate_ready_tasks(
                state, artifacts, [approval], root=routing_root
            ) != [capability]:
                return False
            descendant_id = (
                f"storyboard-input-{index}"
                if target_type == "storyboard"
                else f"gate-input-{index}"
            )
            unrelated_task = _candidate(
                f"unrelated-gate-task-{index}",
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
            if calculate_ready_tasks(
                unrelated_state,
                [
                    artifacts[0],
                    _artifact(
                        descendant_id,
                        "storyboard" if target_type == "storyboard" else "task-input",
                    ),
                    *routing_scope,
                    *gate_voice,
                ],
                [approval],
                root=routing_root,
            ):
                return False
            related_artifacts = [
                artifacts[0],
                _artifact(
                    descendant_id,
                    "storyboard" if target_type == "storyboard" else "task-input",
                    parents=[target_id],
                ),
                *routing_scope,
                *gate_voice,
            ]
            if calculate_ready_tasks(
                unrelated_state,
                related_artifacts,
                [approval],
                root=routing_root,
            ) != [capability]:
                return False
    return True


def _run_resume_scenario(
    *,
    voice_fixture: Optional[bytes] = None,
    voiceover_duration_ms: int = 15_000,
    voice_timing_duration_ms: int = 15_000,
) -> dict[str, Any]:
    """Build one persisted recovery scenario with controllable voice metadata."""
    with TemporaryDirectory() as folder:
        project = Path(folder) / "project"
        initialize_project(project, "kv-resume-smoke", "knowledge-video")
        voice_fixture = (
            _voice_fixture_wav(duration_ms=15_000)
            if voice_fixture is None
            else voice_fixture
        )
        voice_fixture_path = project / "media" / "voiceover-v1.wav"
        voice_fixture_path.write_bytes(voice_fixture)
        create_artifact(project, _artifact("style-v1", "style-pack"))
        voice_artifacts = _voice_bundle(
            voiceover_duration_ms=voiceover_duration_ms,
            voice_timing_duration_ms=voice_timing_duration_ms,
        )
        for item in voice_artifacts:
            create_artifact(project, item)
        create_artifact(
            project,
            _artifact(
                "semantic-beats-v1",
                "semantic-beats",
                parents=["narration-v1"],
                narration_id="narration-v1",
                beats=[
                    {
                        "beat_id": "B01",
                        "text_ref": "narration-v1:S01:L1",
                        "keyword": "timing",
                        "intent": "core-concept-emphasis",
                        "priority": "primary",
                        "preferred_carrier": "motion-graphics",
                        "approval_provenance": "user:smoke-keyword-review-v1",
                    }
                ],
            ),
        )
        create_artifact(
            project,
            _artifact(
                "timed-semantic-beats-v1",
                "timed-semantic-beats",
                parents=["semantic-beats-v1", "voice-timing-v1"],
                semantic_beats_id="semantic-beats-v1",
                voice_timing_id="voice-timing-v1",
                timing_kind="real",
                beats=[
                    {
                        "beat_id": "B01",
                        "speech_start_ms": 0,
                        "speech_end_ms": 5000,
                        "keyword_start_ms": 1000,
                        "keyword_end_ms": 2000,
                        "emphasis_ms": 1500,
                        "visual_window_ms": [800, 3000],
                        "approved_anchor_commitment": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                    }
                ],
            ),
        )
        approve_artifact(
            project,
            "style-v1",
            "visual-direction",
            "voice smoke direction approved",
        )
        storyboard_task = _candidate(
            "smoke-storyboard",
            "storyboard.plan",
            ["style-v1", "voice-timing-v1"],
            "visual-direction",
            "style-v1",
        )
        scene_task = _candidate(
            "smoke-scene",
            "scene.produce",
            ["storyboard-v1", "voice-timing-v1"],
            "storyboard-and-cost",
            "storyboard-v1",
            production_scope="representative-slice",
            scene_id="S01",
        )
        direction_approval = {
            "target_id": "style-v1",
            "scope": "visual-direction",
            "decision": "approved",
        }
        append_event(project, {"event": "project.phase_changed", "phase": "content_ready"})
        append_event(project, {"event": "project.phase_changed", "phase": "direction_ready"})
        direction_ready_actions = calculate_ready_tasks(
            {"phase": "direction_ready", "candidate_tasks": [storyboard_task, scene_task]},
            [_artifact("style-v1", "style-pack"), *voice_artifacts],
            [direction_approval],
            root=project,
        )
        preflight_voice = validate_project_authoritative_voice_bundle(
            project, voice_artifacts
        )
        if not preflight_voice["ok"]:
            return {
                "voice_timing_revision": {
                    "voice_validation_issue_codes": sorted(
                        {issue["code"] for issue in preflight_voice["issues"]}
                    )
                }
            }
        append_event(project, {"event": "project.phase_changed", "phase": "voice_ready"})
        voice_ready_phase = "voice_ready"
        voice_ready_actions = calculate_ready_tasks(
            {"phase": voice_ready_phase, "candidate_tasks": [storyboard_task, scene_task]},
            [_artifact("style-v1", "style-pack"), *voice_artifacts],
            [direction_approval],
            root=project,
        )
        for item in (
            _artifact("storyboard-v1", "storyboard", parents=["voice-timing-v1"]),
            _artifact(
                "contract-S01-v1", "scene-contract", parents=["storyboard-v1"], scene_id="S01"
            ),
            _artifact(
                "contract-S02-v1", "scene-contract", parents=["storyboard-v1"], scene_id="S02"
            ),
            _artifact(
                "scene-S01-v1", "media", parents=["contract-S01-v1"], scene_id="S01"
            ),
            _artifact(
                "scene-S02-v1", "media", parents=["contract-S02-v1"], scene_id="S02"
            ),
            _artifact(
                "contract-S02-v2",
                "scene-contract",
                version=2,
                parents=["storyboard-v1"],
                scene_id="S02",
            ),
        ):
            create_artifact(project, item)
        approve_artifact(
            project,
            "storyboard-v1",
            "storyboard-and-cost",
            "representative production approved",
        )
        if validate_authoritative_voice_bundle(voice_artifacts)["ok"]:
            create_task(
                project,
                _candidate(
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
        append_event(project, {"event": "project.phase_changed", "phase": "storyboard_ready"})
        invalidate_artifact_descendants(
            project,
            "contract-S02-v1",
            json.loads(
                (Path(__file__).parents[1] / "references/policies/invalidation.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        first = resume_project(project)
        second = resume_project(project)
        if first != second:
            raise RuntimeError("resume is not deterministic")
        voice_timing_v2 = _artifact(
            "voice-timing-v2",
            "voice-timing",
            version=2,
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=voice_timing_duration_ms,
            segments=_timing_segments(voice_timing_duration_ms),
            keyword_anchors=[],
        )
        create_artifact(project, voice_timing_v2)
        declared_descendants = sorted(
            [
                "contract-S01-v1",
                "contract-S02-v1",
                "contract-S02-v2",
                "scene-S01-v1",
                "scene-S02-v1",
                "timed-semantic-beats-v1",
                "storyboard-v1",
            ]
        )
        invalidated = invalidate_artifact_descendants(
            project,
            "voice-timing-v1",
            json.loads(
                (Path(__file__).parents[1] / "references/policies/invalidation.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        post_revision = resume_project(project)
        post_artifacts = {
            item["artifact_id"]: item for item in post_revision["artifacts"]
        }
        post_bundle = validate_authoritative_voice_bundle(
            [*voice_artifacts, voice_timing_v2]
        )
        structural = validate_project(project)
        voice_validation_issue_codes = sorted(
            {
                issue["code"]
                for issue in structural["errors"]
                if isinstance(issue, dict)
                and isinstance(issue.get("code"), str)
                and (
                    issue["code"].startswith("voice")
                    or issue["code"] == "real-voice-timing-required"
                )
            }
        )
        return {
            **post_revision,
            "pre_timing_revision": {
                "artifacts": first["artifacts"],
                "voice_artifacts": voice_artifacts,
                "ready_tasks": first["ready_tasks"],
            },
            "direction_ready_actions": direction_ready_actions,
            "voice_ready_phase": voice_ready_phase,
            "voice_ready_actions": voice_ready_actions,
            "voice_timing_revision": {
                "invalidated_artifact_ids": invalidated,
                "declared_descendant_ids": declared_descendants,
                "preserved_artifact_ids": sorted(
                    artifact_id
                    for artifact_id in (
                        "semantic-beats-v1",
                        "style-v1",
                        "voice-timing-v2",
                    )
                    if artifact_id not in invalidated
                ),
                "stale_descendant_ids": sorted(
                    artifact_id
                    for artifact_id in declared_descendants
                    if post_artifacts[artifact_id]["status"] == "stale"
                ),
                "current_voice_timing_id": post_bundle["voice_timing_id"],
                "style_status": post_artifacts["style-v1"]["status"],
                "voice_validation_issue_codes": voice_validation_issue_codes,
            },
            "media_files": sorted(path.name for path in (project / "media").iterdir()),
            "seeded_media_files": [voice_fixture_path.name],
            "voice_fixture_unchanged": (
                voice_fixture_path.is_file()
                and voice_fixture_path.read_bytes() == voice_fixture
            ),
        }


def _voice_fixture_wav(*, duration_ms: int, sample_rate: int = 8_000) -> bytes:
    """Return deterministic low-amplitude PCM pulses for smoke fixtures."""
    sample_count = duration_ms * sample_rate // 1_000
    pulse_frames = sample_rate // 10
    half_period = max(1, sample_rate // 500)
    audio = b"".join(
        struct.pack(
            "<h",
            (
                384 if (frame // half_period) % 2 == 0 else -384
            )
            if frame % sample_rate < pulse_frames
            else 0,
        )
        for frame in range(sample_count)
    )
    block_align = 2
    byte_rate = sample_rate * block_align
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(audio))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, block_align, 16)
        + b"data"
        + struct.pack("<I", len(audio))
        + audio
    )


def _migration_prerequisite(root: Path, legacy_root: Optional[Path]) -> dict[str, Any]:
    report = root / MIGRATION_REPORT
    baseline = root / BASELINE
    if not report.is_file() or not baseline.is_file():
        return {"ok": False, "detail": "migration report or baseline is missing"}
    if legacy_root is not None:
        try:
            audit = audit_legacy(legacy_root, root)
        except ValueError as error:
            return {"ok": False, "detail": str(error)}
        if not audit["ok"]:
            return {"ok": False, "detail": audit}
        return {"ok": True, "detail": "live legacy audit passed"}
    default_legacy = Path.home() / ".codex" / "skills" / LEGACY_SKILL
    if default_legacy.is_dir() and not default_legacy.is_symlink():
        try:
            audit = audit_legacy(default_legacy, root)
        except ValueError as error:
            return {"ok": False, "detail": str(error)}
        return {"ok": bool(audit["ok"]), "detail": audit}
    text = report.read_text(encoding="utf-8")
    required = (
        "Missing expected legacy files: 0",
        "Content hash mismatches: 0",
        "Undisposed executable scripts: 0",
    )
    if all(item in text for item in required):
        return {"ok": True, "detail": "committed migration audit passed"}
    return {"ok": False, "detail": "migration report does not record a complete audit"}


def _discover_personal_plugin(home: Path, plugin_id: str) -> Path:
    catalog = _read_personal_marketplace(home)
    plugins = catalog.get("plugins") if isinstance(catalog, dict) else None
    if not isinstance(plugins, list):
        raise ValueError("personal marketplace has no plugin list")
    matches = [item for item in plugins if isinstance(item, dict) and item.get("name") == plugin_id]
    if len(matches) != 1:
        raise ValueError(f"personal marketplace must contain exactly one {plugin_id} entry")
    source = matches[0].get("source")
    value = source.get("path") if isinstance(source, dict) else source
    relative = _safe_marketplace_path(value)
    plugin_root = home.joinpath(*relative.parts)
    try:
        plugin_root = plugin_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("personal plugin source does not exist") from error
    if not plugin_root.is_dir():
        raise ValueError("personal plugin source is not a directory")
    return plugin_root


def _read_personal_marketplace(home: Path) -> dict[str, Any]:
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    if marketplace.is_symlink() or not marketplace.is_file():
        raise ValueError("personal marketplace is missing or unsafe")
    try:
        catalog = json.loads(marketplace.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("personal marketplace is invalid") from error
    if not isinstance(catalog, dict):
        raise ValueError("personal marketplace is invalid")
    return catalog


def _plugin_is_enabled(config: Path, plugin_key: str) -> bool:
    return plugin_key in _enabled_plugin_keys(config)


def _enabled_plugin_keys(config: Path) -> set[str]:
    if not config.exists():
        return set()
    if config.is_symlink() or not config.is_file():
        raise ValueError("Codex plugin configuration is unreadable")
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError("Codex plugin configuration is unreadable") from error
    enabled: set[str] = set()
    current: Optional[str] = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            match = _PLUGIN_TABLE.fullmatch(line)
            current = None if match is None else next(
                value for value in match.groups() if value is not None
            )
            continue
        if current is None:
            continue
        match = _ENABLED_VALUE.fullmatch(line)
        if match is None:
            continue
        if match.group(1).casefold() == "true":
            enabled.add(current)
        else:
            enabled.discard(current)
    return enabled


def _safe_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
    )


def _safe_marketplace_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.startswith("./") or "\\" in value:
        raise ValueError("local plugin source.path must be a ./-prefixed POSIX path")
    path = PurePosixPath(value[2:])
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("local plugin source.path must stay within personal home")
    return path


def _plugin_skill_names(root: Path) -> set[str]:
    names = set()
    for path in (root / "skills").glob("*/SKILL.md"):
        names.add(_frontmatter_name(path) or path.parent.name)
    return names


def _all_personal_skill_names(home: Path) -> set[str]:
    names = set()
    roots = (home / ".codex" / "skills", home / ".agents" / "skills")
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*/SKILL.md"):
            names.add(_frontmatter_name(path) or path.parent.name)
            names.add(path.parent.name)
    config = home / ".codex" / "config.toml"
    cache = home / ".codex" / "plugins" / "cache"
    for plugin_key in sorted(_enabled_plugin_keys(config)):
        plugin_name, separator, marketplace_name = plugin_key.rpartition("@")
        if (
            not separator
            or not _safe_component(plugin_name)
            or not _safe_component(marketplace_name)
        ):
            continue
        versions = cache / marketplace_name / plugin_name
        if versions.is_symlink() or not versions.is_dir():
            continue
        for path in versions.glob("*/skills/*/SKILL.md"):
            if path.is_symlink() or any(
                parent.is_symlink() for parent in list(path.parents)[:3]
            ):
                continue
            for skill_name in (_frontmatter_name(path), path.parent.name):
                identity = _skill_identity(skill_name)
                if identity is not None:
                    names.add(f"{plugin_name}:{identity[1]}")
    return names


def _frontmatter_name(path: Path) -> Optional[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip().strip('"\'')
            return value or None
    return None


def _matches_installed_skill(
    required: Any,
    discovered: set[str],
    adapter_namespace: Any,
) -> bool:
    required_identity = _skill_identity(required)
    if required_identity is None:
        return False
    required_namespace, skill_name = required_identity
    expected_namespace = required_namespace
    if expected_namespace is None and _safe_component(adapter_namespace):
        expected_namespace = adapter_namespace
    allowed = {skill_name}
    if expected_namespace is not None:
        allowed.add(f"{expected_namespace}:{skill_name}")
    return bool(allowed & discovered)


def _skill_identity(value: Any) -> Optional[tuple[Optional[str], str]]:
    if not isinstance(value, str) or not value:
        return None
    parts = value.split(":")
    if len(parts) == 1 and _safe_component(parts[0]):
        return None, parts[0]
    if len(parts) == 2 and all(_safe_component(part) for part in parts):
        return parts[0], parts[1]
    return None


def _skill_is_discoverable(home: Path, plugin_root: Path, name: str) -> bool:
    if name in _plugin_skill_names(plugin_root) or name in _all_personal_skill_names(home):
        return True
    return any(
        path.exists()
        for path in (home / ".codex" / "skills" / name, home / ".agents" / "skills" / name)
    )


def _artifact(
    artifact_id: str,
    artifact_type: str,
    *,
    version: int = 1,
    parents: Optional[list[str]] = None,
    **metadata: Any,
) -> dict[str, Any]:
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
        "status": "approved",
        "parents": list(parents or []),
        "path": default_path,
        **metadata,
    }


def _candidate(
    task_id: str,
    capability: str,
    inputs: list[str],
    gate: str,
    target_id: str,
    **constraints: Any,
) -> dict[str, Any]:
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
                "smoke-routing-scene-contract-v1",
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


def _timing_segments(duration_ms: int) -> list[dict[str, Any]]:
    """Return the fixed smoke transcript with a final segment ending at duration."""
    return [
        {"start_ms": 0, "end_ms": 5000, "text": "first"},
        {"start_ms": 5000, "end_ms": 10000, "text": "second"},
        {"start_ms": 10000, "end_ms": duration_ms, "text": "third"},
    ]


def _voice_bundle(
    *, voiceover_duration_ms: int = 15_000, voice_timing_duration_ms: int = 15_000
) -> list[dict[str, Any]]:
    return [
        _artifact("narration-v1", "narration"),
        _artifact(
            "voice-source-v1",
            "voice-source-decision",
            parents=["narration-v1"],
            narration_id="narration-v1",
            mode="tts",
            decision="approved",
            decision_provenance="user:smoke-source-v1",
        ),
        _artifact(
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
            consent_provenance="user:smoke-consent-v1",
            profile_provenance="user:smoke-profile-v1",
        ),
        _artifact(
            "voiceover-v1",
            "voiceover",
            parents=["narration-v1", "voice-source-v1", "voice-profile-v1"],
            narration_id="narration-v1",
            source_decision_id="voice-source-v1",
            mode="tts",
            profile_id="voice-profile-v1",
            media_path="media/voiceover-v1.wav",
            media_format="wav",
            duration_ms=voiceover_duration_ms,
            provenance="smoke-fixture",
        ),
        _artifact(
            "voice-timing-v1",
            "voice-timing",
            parents=["voiceover-v1"],
            voiceover_id="voiceover-v1",
            timing_kind="real",
            duration_ms=voice_timing_duration_ms,
            segments=_timing_segments(voice_timing_duration_ms),
            keyword_anchors=[],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--require-skill")
    parser.add_argument("--forbid-skill")
    parser.add_argument("--check-external-skills", action="store_true")
    parser.add_argument("--require-resume-smoke", action="store_true")
    parser.add_argument("--require-visual-media-smoke", action="store_true")
    parser.add_argument("--require-timing-smoke", action="store_true")
    parser.add_argument(
        "--visual-media-smoke-root", type=Path, help=argparse.SUPPRESS
    )
    parser.add_argument("--timing-smoke-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.visual_media_smoke_root is not None:
        result = _run_visual_media_smoke_in_process(args.visual_media_smoke_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if args.timing_smoke_root is not None:
        result = _run_timing_smoke_in_process(args.timing_smoke_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    result = verify_installation(
        repo=args.repo,
        home=args.home,
        require_skill=args.require_skill,
        forbid_skill=args.forbid_skill,
        check_external_skills=args.check_external_skills,
        require_resume_smoke=args.require_resume_smoke,
        require_visual_media_smoke=args.require_visual_media_smoke,
        require_timing_smoke=args.require_timing_smoke,
        legacy_root=args.legacy_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

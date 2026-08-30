"""Deterministic, objective checks for a video-toolkit runtime project."""

import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Optional, Union

from .artifacts import validate_artifact_record
from .contracts import validate_scene_contract
from .project_state import (
    LEGACY_PHASES,
    LEGACY_PROJECT_SCHEMA_VERSION,
    PHASES,
    V3_PHASES,
    V3_PROJECT_SCHEMA_VERSION,
    PROJECT_SCHEMA_VERSIONS,
    replay_events,
)
from .invalidation import invalidated_artifact_ids
from .packs import validate_layout_pack, validate_style_pack
from .runtime_paths import project_path, project_root
from .scene_timing import validate_scene_timing_contracts
from .tasks import (
    _is_current_result,
    _validate_conditional_visual_media_result,
    _validate_envelope_shape,
    _validate_persisted_envelope,
    _validate_result,
    _validate_result_artifacts,
)
from .visual_media_context import (
    ACTIVE_VISUAL_MEDIA_OPERATIONS,
    classify_visual_media_task,
    project_legacy_image_context,
    validate_declared_visual_media_inputs,
    validate_result_envelope,
    validate_visual_media_context,
)
from .voice import validate_project_authoritative_voice_bundle


ARTIFACT_REQUIRED_KEYS = ("artifact_id", "type", "version", "status", "parents", "path")
ARTIFACT_STATUSES = {"draft", "approved", "stale", "superseded", "invalid"}
APPROVAL_DECISIONS = {"approved", "delegated", "skipped"}
NON_SEMANTIC_TRACK_KINDS = {
    "voice",
    "voiceover",
    "caption",
    "captions",
    "music",
    "sfx",
    "transition",
    "transitions",
}
PROJECT_COUPLED_PROMOTED_CHARACTER_PATTERNS = (
    r"(?:^|_)(?:S\d{3,}|镜头\d+)(?:_|$)",
    r"(?:^|_)(?:项目|课程|视频)(?:_|$)",
)
VOICE_ARTIFACT_TYPES = frozenset(
    {"voice-source-decision", "voice-profile", "voiceover", "voice-timing"}
)


def validate_project(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Return stable structural errors and warnings for *root*.

    The result deliberately describes persisted facts only.  It never derives an
    aesthetic opinion or changes project state, so callers can safely run it
    before a user-review gate or after an interrupted production task.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        root = project_root(root)
    except ValueError:
        return {
            "errors": [_issue("unsafe-runtime-root")],
            "warnings": [],
        }
    project_snapshot = _read_project(root, errors)
    replayed_project, schema_origin = _replayed_project_authority(root, errors)
    if project_snapshot and replayed_project and project_snapshot != replayed_project:
        errors.append(_issue("project-state-mismatch", path="project.json"))
    project = replayed_project or project_snapshot
    artifacts = _read_artifacts(root, errors)
    try:
        invalidated = invalidated_artifact_ids(root)
    except ValueError:
        errors.append(_issue("invalid-event-log"))
        invalidated = set()
    artifacts = {
        artifact_id: ({**artifact, "status": "stale"} if artifact_id in invalidated else artifact)
        for artifact_id, artifact in artifacts.items()
    }
    unresolved_legacy = _is_unresolved_legacy_project(
        project, schema_origin, artifacts
    )
    approvals = _read_approvals(root, errors)
    _check_artifact_graph(root, artifacts, errors)
    _check_timed_semantic_graph(artifacts, errors)
    _check_voice_lineage(root, project, schema_origin, artifacts, errors)
    _check_v3_phase_gates(root, project, artifacts, errors)
    _check_packs(root, artifacts, errors)
    _check_promoted_assets(root, artifacts, errors)
    tasks = _check_tasks(root, artifacts, errors)
    _check_task_results(root, tasks, artifacts, errors)
    active_timeline = _resolve_active_timeline(root, project, artifacts, errors)
    if active_timeline is not None:
        timeline_id, timeline = active_timeline
        _check_timeline(
            root,
            timeline_id,
            timeline,
            artifacts,
            errors,
            warnings,
            allow_legacy_scene_contracts=(
                unresolved_legacy
            ),
        )
    _check_required_approvals(project, artifacts, approvals, errors)
    return {"errors": _sorted_issues(errors), "warnings": _sorted_issues(warnings)}


def _check_voice_lineage(
    root: Path,
    project: dict[str, Any],
    schema_origin: Optional[int],
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Check the current voice DAG and only the audio metadata needed to use it."""
    if _is_unresolved_legacy_project(project, schema_origin, artifacts):
        return
    has_voice_artifacts = any(
        artifact.get("type") in VOICE_ARTIFACT_TYPES
        for artifact in artifacts.values()
    )
    upgraded_legacy = (
        schema_origin == LEGACY_PROJECT_SCHEMA_VERSION
        and project.get("schema_version") != LEGACY_PROJECT_SCHEMA_VERSION
    )
    phase_requires_voice = (
        project.get("phase") in PHASES[PHASES.index("voice_ready") :]
    )
    if not (has_voice_artifacts or upgraded_legacy or phase_requires_voice):
        return
    bundle = validate_project_authoritative_voice_bundle(root, artifacts.values())
    errors.extend(bundle["issues"])


def _is_unresolved_legacy_project(
    project: dict[str, Any],
    schema_origin: Optional[int],
    artifacts: dict[str, dict[str, Any]],
) -> bool:
    """Return whether a v1 project still has no voice-era persisted state."""
    return (
        schema_origin == LEGACY_PROJECT_SCHEMA_VERSION
        and project.get("schema_version") == LEGACY_PROJECT_SCHEMA_VERSION
        and not any(
            artifact.get("type") in VOICE_ARTIFACT_TYPES
            for artifact in artifacts.values()
        )
    )


def _replayed_project_authority(
    root: Path, errors: list[dict[str, Any]]
) -> tuple[dict[str, Any], Optional[int]]:
    try:
        replayed = replay_events(root)
        event_log = project_path(root, "events/events.jsonl")
        first_line = event_log.read_text(encoding="utf-8").splitlines()[0]
        initialized = json.loads(first_line)
    except (IndexError, OSError, TypeError, ValueError, json.JSONDecodeError):
        errors.append(_issue("invalid-event-log"))
        return {}, None
    origin = initialized.get("schema_version")
    if initialized.get("event") != "project.initialized" or origin not in PROJECT_SCHEMA_VERSIONS:
        errors.append(_issue("invalid-event-log"))
        return {}, None
    return replayed, origin


def read_effective_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    """Return valid artifact metadata with event invalidation overlaid as stale."""
    root = project_root(root)
    artifacts = _read_artifacts(root, [])
    invalidated = invalidated_artifact_ids(root)
    return {
        artifact_id: (
            {**artifact, "status": "stale"}
            if artifact_id in invalidated
            else artifact
        )
        for artifact_id, artifact in artifacts.items()
    }


def _read_project(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        snapshot_path = project_path(root, "project.json")
    except ValueError:
        errors.append(_issue("unsafe-runtime-storage", storage="project.json"))
        return {}
    project = _read_json_object(snapshot_path)
    if project is None:
        errors.append(_issue("missing-project-state", path="project.json"))
        return {}
    required = {"schema_version", "project_id", "workflow", "phase"}
    allowed = required | {"active_timeline_id"}
    if (
        not required.issubset(project)
        or not set(project).issubset(allowed)
        or project.get("schema_version") not in PROJECT_SCHEMA_VERSIONS
    ):
        errors.append(_issue("invalid-project-state", path="project.json"))
        return {}
    if not all(isinstance(project.get(key), str) and project[key] for key in ("project_id", "workflow", "phase")):
        errors.append(_issue("invalid-project-state", path="project.json"))
        return {}
    valid_phases = V3_PHASES if project.get("schema_version") == V3_PROJECT_SCHEMA_VERSION else PHASES
    if project["phase"] not in valid_phases or (
        project["schema_version"] == LEGACY_PROJECT_SCHEMA_VERSION
        and project["phase"] not in LEGACY_PHASES
    ):
        errors.append(_issue("invalid-project-state", path="project.json"))
        return {}
    if "active_timeline_id" in project and not _safe_component(project["active_timeline_id"]):
        errors.append(_issue("invalid-project-state", path="project.json"))
        return {}
    return project


def _check_v3_phase_gates(
    root: Path,
    project: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Validate current timing authority for v3 readiness phases."""
    if project.get("schema_version") != V3_PROJECT_SCHEMA_VERSION:
        return
    phase = project.get("phase")
    if phase not in V3_PHASES or V3_PHASES.index(phase) < V3_PHASES.index("timing_bound"):
        return

    def current(artifact_type: str, **lineage: Any) -> Optional[dict[str, Any]]:
        candidates = [
            item
            for item in artifacts.values()
            if item.get("type") == artifact_type
            and item.get("status") == "approved"
            and all(item.get(key) == value for key, value in lineage.items())
        ]
        return max(
            candidates,
            key=lambda item: (item.get("version", 0), item.get("artifact_id", "")),
            default=None,
        )

    voice_bundle = validate_project_authoritative_voice_bundle(root, artifacts.values())
    voice_timing_id = voice_bundle.get("voice_timing_id")
    voice_timing = artifacts.get(voice_timing_id) if isinstance(voice_timing_id, str) else None
    if (
        not voice_bundle.get("ok")
        or voice_timing is None
        or voice_timing.get("type") != "voice-timing"
        or voice_timing.get("status") != "approved"
        or voice_timing.get("timing_kind") != "real"
    ):
        errors.append(_issue("voice-timing-required"))
        return
    timed = current(
        "timed-semantic-beats", voice_timing_id=voice_timing.get("artifact_id")
    )
    if timed is None or voice_timing.get("artifact_id") not in timed.get("parents", []):
        errors.append(_issue("timed-semantic-beats-required"))
        return
    if V3_PHASES.index(phase) < V3_PHASES.index("storyboard_timed"):
        return
    scenes = current(
        "scene-timing-contracts", timed_semantic_beats_id=timed.get("artifact_id")
    )
    if scenes is None or timed.get("artifact_id") not in scenes.get("parents", []):
        errors.append(_issue("scene-timing-contracts-required"))
        return
    if phase != "production_ready":
        return
    validation_candidates = [
        item
        for item in artifacts.values()
        if item.get("type") == "timing-validation"
        and item.get("status") == "approved"
        and scenes.get("artifact_id") in item.get("parents", [])
    ]
    validation = max(
        validation_candidates,
        key=lambda item: (item.get("version", 0), item.get("artifact_id", "")),
        default=None,
    )
    payload = None
    if validation is not None:
        source = _safe_project_path(root, validation.get("path"))
        payload = _read_json_object(source) if source is not None else None
    if not isinstance(payload, dict) or payload.get("status") != "passed":
        errors.append(_issue("timing-validation-required"))


def _read_artifacts(root: Path, errors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    artifacts_root = root / "artifacts"
    if artifacts_root.is_symlink():
        errors.append(_issue("unsafe-runtime-storage", storage="artifacts"))
        return artifacts
    if not artifacts_root.is_dir():
        return artifacts
    paths = []
    for type_directory in sorted(artifacts_root.iterdir()):
        if type_directory.is_symlink():
            errors.append(_issue("unsafe-runtime-storage", storage=_relative(root, type_directory)))
            continue
        if type_directory.is_dir():
            paths.extend(sorted(type_directory.glob("*.json")))
    for path in paths:
        if path.is_symlink():
            errors.append(_issue("unsafe-runtime-storage", storage=_relative(root, path)))
            continue
        raw = _read_json_object(path)
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("artifact_id"), str)
            and _safe_project_path(root, raw.get("path")) is None
        ):
            errors.append(
                _issue("unsafe-artifact-path", artifact_id=raw["artifact_id"])
            )
        if raw is None or not _valid_artifact(raw) or path.name != f"{raw.get('artifact_id')}.json":
            if isinstance(raw, dict) and raw.get("type") == "timed-semantic-beats":
                if isinstance(raw.get("beats"), list) and any(
                    not _valid_timed_beat(beat) for beat in raw["beats"]
                ):
                    errors.append(
                        _issue(
                            "invalid-timed-semantic-timing",
                            artifact_id=raw.get("artifact_id", "unknown"),
                        )
                    )
            elif isinstance(raw, dict) and raw.get("type") == "scene-timing-contracts":
                if isinstance(raw.get("scenes"), list) and any(
                    not _valid_timing_window(scene.get("scene_window_ms"))
                    or not _valid_timing_window(scene.get("visual_window_ms"))
                    for scene in raw["scenes"]
                    if isinstance(scene, dict)
                ):
                    errors.append(
                        _issue(
                            "invalid-scene-timing-window",
                            artifact_id=raw.get("artifact_id", "unknown"),
                        )
                    )
            errors.append(_issue("invalid-artifact-metadata", path=_relative(root, path)))
            continue
        artifact_id = raw["artifact_id"]
        if artifact_id in artifacts:
            errors.append(_issue("duplicate-artifact-id", artifact_id=artifact_id))
            continue
        artifacts[artifact_id] = raw
    return artifacts


def _valid_artifact(artifact: dict[str, Any]) -> bool:
    try:
        validate_artifact_record(artifact)
    except (TypeError, ValueError):
        return False
    return True


def _read_approvals(root: Path, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approvals: list[dict[str, Any]] = []
    approval_root = root / "approvals"
    if approval_root.is_symlink():
        errors.append(_issue("unsafe-runtime-storage", storage="approvals"))
        return approvals
    if not approval_root.is_dir():
        return approvals
    for path in sorted(approval_root.glob("*.json")):
        if path.is_symlink():
            errors.append(
                _issue("unsafe-runtime-storage", storage=_relative(root, path))
            )
            continue
        approval = _read_json_object(path)
        if approval is None or not _valid_approval(approval) or path.name != f"{approval.get('approval_id')}.json":
            errors.append(_issue("invalid-approval-record", path=_relative(root, path)))
            continue
        normalized = dict(approval)
        normalized.setdefault("decision", "approved")
        approvals.append(normalized)
    return approvals


def _valid_approval(approval: dict[str, Any]) -> bool:
    allowed = {"approval_id", "target_id", "scope", "decision", "notes"}
    required = allowed - {"decision"}
    if not required.issubset(approval) or not set(approval).issubset(allowed):
        return False
    if not all(isinstance(approval[key], str) and approval[key] for key in ("approval_id", "target_id", "scope")):
        return False
    if not _safe_component(approval["approval_id"]) or not isinstance(approval["notes"], str):
        return False
    return "decision" not in approval or approval["decision"] in APPROVAL_DECISIONS


def _check_artifact_graph(root: Path, artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    for artifact in artifacts.values():
        artifact_id = artifact["artifact_id"]
        for parent_id in artifact["parents"]:
            if parent_id not in artifacts:
                errors.append(_issue("missing-parent-artifact", artifact_id=artifact_id, parent_id=parent_id))
        source = _safe_project_path(root, artifact["path"])
        if source is None:
            errors.append(_issue("unsafe-artifact-path", artifact_id=artifact_id))
        elif not source.is_file():
            errors.append(_issue("missing-artifact-file", artifact_id=artifact_id, path=artifact["path"]))
    _check_artifact_parent_cycles(artifacts, errors)


def _check_artifact_parent_cycles(artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    visited: set[str] = set()
    visiting: list[str] = []
    cycle_members: set[str] = set()

    def visit(artifact_id: str) -> None:
        if artifact_id in visited:
            return
        if artifact_id in visiting:
            cycle_members.update(visiting[visiting.index(artifact_id):])
            return
        visiting.append(artifact_id)
        for parent_id in artifacts[artifact_id]["parents"]:
            if parent_id in artifacts:
                visit(parent_id)
        visiting.pop()
        visited.add(artifact_id)

    for artifact_id in sorted(artifacts):
        visit(artifact_id)
    for artifact_id in sorted(cycle_members):
        errors.append(_issue("artifact-parent-cycle", artifact_id=artifact_id))


def _check_timed_semantic_graph(
    artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]
) -> None:
    """Validate the metadata-only semantic-beat timing lineage."""
    for artifact_id in sorted(artifacts):
        artifact = artifacts[artifact_id]
        if artifact.get("type") == "semantic-beats" and "beats" in artifact:
            _check_semantic_beats_artifact(artifact, artifacts, errors)
            if _has_duplicate_beat_ids(artifact.get("beats")):
                errors.append(_issue("semantic-beat-duplicate-id", artifact_id=artifact_id))
        elif artifact.get("type") == "timed-semantic-beats":
            _check_timed_semantic_artifact(artifact, artifacts, errors)
        elif artifact.get("type") == "scene-timing-contracts":
            _check_scene_timing_artifact(artifact, artifacts, errors)


def _timing_beat_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item["beat_id"]
        for item in value
        if isinstance(item, dict) and isinstance(item.get("beat_id"), str)
    ]


def _has_duplicate_beat_ids(value: Any) -> bool:
    beat_ids = _timing_beat_ids(value)
    return len(beat_ids) != len(set(beat_ids))


def _is_approved_artifact(
    artifact: Any, artifact_type: str
) -> bool:
    return (
        isinstance(artifact, dict)
        and artifact.get("type") == artifact_type
        and artifact.get("status") == "approved"
    )


def _check_semantic_beats_artifact(
    artifact: dict[str, Any], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]
) -> None:
    narration_id = artifact.get("narration_id")
    narration = artifacts.get(narration_id) if isinstance(narration_id, str) else None
    if (
        not _is_approved_artifact(narration, "narration")
        or narration_id not in artifact["parents"]
    ):
        errors.append(
            _issue("semantic-beats-lineage-mismatch", artifact_id=artifact["artifact_id"])
        )


def _valid_timing_window(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        and 0 <= value[0] < value[1] <= 36_000_000
    )


def _valid_timed_beat(beat: Any) -> bool:
    if not isinstance(beat, dict):
        return False
    fields = (
        "speech_start_ms",
        "speech_end_ms",
        "keyword_start_ms",
        "keyword_end_ms",
        "emphasis_ms",
    )
    if not all(
        isinstance(beat.get(field), int) and not isinstance(beat[field], bool)
        and 0 <= beat[field] <= 36_000_000
        for field in fields
    ) or not _valid_timing_window(beat.get("visual_window_ms")) or not (
        isinstance(beat.get("approved_anchor_commitment"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", beat["approved_anchor_commitment"])
    ):
        return False
    return (
        beat["speech_start_ms"] <= beat["keyword_start_ms"]
        <= beat["emphasis_ms"] <= beat["keyword_end_ms"]
        <= beat["speech_end_ms"]
    )


def _check_timed_semantic_artifact(
    artifact: dict[str, Any], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]
) -> None:
    artifact_id = artifact["artifact_id"]
    semantic_id = artifact.get("semantic_beats_id")
    voice_timing_id = artifact.get("voice_timing_id")
    semantic = artifacts.get(semantic_id) if isinstance(semantic_id, str) else None
    voice_timing = (
        artifacts.get(voice_timing_id) if isinstance(voice_timing_id, str) else None
    )
    if (
        not _is_approved_artifact(semantic, "semantic-beats")
        or not _is_approved_artifact(voice_timing, "voice-timing")
        or voice_timing.get("timing_kind") != "real"
        or semantic_id not in artifact["parents"]
        or voice_timing_id not in artifact["parents"]
    ):
        errors.append(_issue("timed-semantic-lineage-mismatch", artifact_id=artifact_id))
    timed_ids = _timing_beat_ids(artifact.get("beats"))
    if len(timed_ids) != len(set(timed_ids)):
        errors.append(_issue("timed-semantic-beat-duplicate-id", artifact_id=artifact_id))
    if _is_approved_artifact(semantic, "semantic-beats"):
        if set(timed_ids) != set(_timing_beat_ids(semantic.get("beats"))):
            errors.append(
                _issue("timed-semantic-beat-ids-mismatch", artifact_id=artifact_id)
            )
    if not isinstance(artifact.get("beats"), list) or any(
        not _valid_timed_beat(beat) for beat in artifact["beats"]
    ):
        errors.append(_issue("invalid-timed-semantic-timing", artifact_id=artifact_id))


def _check_scene_timing_artifact(
    artifact: dict[str, Any], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]
) -> None:
    artifact_id = artifact["artifact_id"]
    timed_id = artifact.get("timed_semantic_beats_id")
    timed = artifacts.get(timed_id) if isinstance(timed_id, str) else None
    if (
        not _is_approved_artifact(timed, "timed-semantic-beats")
        or timed_id not in artifact["parents"]
    ):
        errors.append(_issue("scene-timing-lineage-mismatch", artifact_id=artifact_id))
    if not _is_approved_artifact(timed, "timed-semantic-beats") or not isinstance(timed_id, str):
        return
    try:
        validate_scene_timing_contracts(
            {
                "timed_semantic_beats_id": timed_id,
                "scenes": artifact.get("scenes"),
            },
            timed,
        )
    except ValueError as error:
        message = str(error)
        if "beat ID" in message or "exactly once" in message:
            errors.append(_issue("scene-timing-beat-ids-mismatch", artifact_id=artifact_id))
        else:
            errors.append(_issue("invalid-scene-timing-window", artifact_id=artifact_id))


def _check_packs(
    root: Path,
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Validate approved pack payloads, normalized regions, previews, and fonts."""
    for artifact_id in sorted(artifacts):
        artifact = artifacts[artifact_id]
        if artifact["type"] not in {"style-pack", "layout-pack"}:
            continue
        source = _safe_project_path(root, artifact["path"])
        payload = _read_json_object(source) if source is not None else None
        if payload is None:
            continue
        try:
            if artifact["type"] == "style-pack":
                payload = validate_style_pack(payload)
            else:
                payload = validate_layout_pack(payload)
        except ValueError:
            errors.append(
                _issue(
                    "invalid-style-pack"
                    if artifact["type"] == "style-pack"
                    else "invalid-layout-pack",
                    artifact_id=artifact_id,
                )
            )
            continue
        previews = payload["previews"] if artifact["type"] == "style-pack" else [payload["preview"]]
        for preview in previews:
            preview_path = _safe_project_path(root, preview)
            if preview_path is None or not preview_path.is_file():
                errors.append(
                    _issue(
                        "missing-pack-preview",
                        artifact_id=artifact_id,
                        path=preview,
                    )
                )
        if artifact["type"] != "style-pack":
            continue
        for font in payload["required_fonts"]:
            if font["source"] != "bundled":
                continue
            font_path = _safe_project_path(root, font["path"])
            if font_path is None or not font_path.is_file():
                errors.append(
                    _issue(
                        "missing-required-font",
                        artifact_id=artifact_id,
                        family=font["family"],
                        path=font["path"],
                    )
                )


def _check_promoted_assets(
    root: Path,
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Validate the deterministic boundary for deliberate cross-project reuse."""
    for artifact_id in sorted(artifacts):
        artifact = artifacts[artifact_id]
        if artifact["type"] != "promoted-asset":
            continue
        promotion = artifact.get("promotion")
        if not isinstance(promotion, dict):
            errors.append(_issue("invalid-promoted-asset-metadata", artifact_id=artifact_id))
            continue
        if promotion.get("ownership") != "cross-project-registry":
            errors.append(_issue("invalid-promoted-asset-ownership", artifact_id=artifact_id))
        if promotion.get("scope") != "project-independent":
            errors.append(_issue("invalid-promoted-asset-scope", artifact_id=artifact_id))
        if not _nonempty_text(promotion.get("source_or_license")):
            errors.append(_issue("missing-promoted-asset-source", artifact_id=artifact_id))
        provenance = promotion.get("provenance")
        if not (
            isinstance(provenance, dict)
            and set(provenance) == {"project_id", "artifact_id"}
            and _safe_component(provenance.get("project_id"))
            and _safe_component(provenance.get("artifact_id"))
        ):
            errors.append(_issue("missing-promoted-asset-provenance", artifact_id=artifact_id))
        for field, code in (
            ("validation_evidence", "missing-promoted-asset-validation-evidence"),
            ("applicability", "missing-promoted-asset-applicability"),
        ):
            values = promotion.get(field)
            if not (
                isinstance(values, list)
                and values
                and all(_nonempty_text(value) for value in values)
                and len(values) == len(set(values))
            ):
                errors.append(_issue(code, artifact_id=artifact_id))
        if promotion.get("asset_kind") == "character-action":
            _check_promoted_character_action(root, artifact, promotion, errors)
        elif not _nonempty_text(promotion.get("asset_kind")):
            errors.append(_issue("invalid-promoted-asset-kind", artifact_id=artifact_id))


def _check_promoted_character_action(
    root: Path,
    artifact: dict[str, Any],
    promotion: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    artifact_id = artifact["artifact_id"]
    name = Path(artifact["path"]).name
    if any(
        re.search(pattern, name, re.IGNORECASE)
        for pattern in PROJECT_COUPLED_PROMOTED_CHARACTER_PATTERNS
    ):
        errors.append(
            _issue(
                "project-coupled-promoted-character-name",
                artifact_id=artifact_id,
                name=name,
            )
        )
    if re.search(r"_v\d{2}\.png$", name, re.IGNORECASE) is None:
        errors.append(
            _issue(
                "invalid-promoted-character-version-suffix",
                artifact_id=artifact_id,
                name=name,
            )
        )
    subject = promotion.get("subject")
    action = promotion.get("action")
    subject_text = subject.strip() if isinstance(subject, str) else ""
    action_text = action.strip() if isinstance(action, str) else ""
    if (
        not subject_text
        or not action_text
        or subject_text not in name
        or action_text not in name
    ):
        errors.append(
            _issue(
                "promoted-character-name-metadata-mismatch",
                artifact_id=artifact_id,
                name=name,
            )
        )
    neutral = (
        all(_nonempty_text(promotion.get(field)) for field in ("subject", "action", "orientation"))
        and promotion.get("scene") == ""
        and promotion.get("alpha") == "yes"
    )
    if not neutral:
        errors.append(_issue("non-neutral-promoted-character-action", artifact_id=artifact_id))
    evidence = promotion.get("validation_evidence")
    if not isinstance(evidence, list) or "identity-continuity-reviewed" not in evidence:
        errors.append(_issue("missing-character-identity-evidence", artifact_id=artifact_id))
    if Path(artifact["path"]).suffix.casefold() != ".png":
        errors.append(_issue("promoted-character-action-must-be-png", artifact_id=artifact_id))
        return
    if (
        not isinstance(evidence, list)
        or "isolated-image-inspect:alpha-transparency-present" not in evidence
    ):
        errors.append(
            _issue(
                "promoted-character-action-alpha-inspection-required",
                artifact_id=artifact_id,
            )
        )


def _check_tasks(
    root: Path,
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], str]]:
    validated: dict[str, tuple[dict[str, Any], str]] = {}
    task_root = root / "tasks"
    if task_root.is_symlink() or (task_root.exists() and not task_root.is_dir()):
        errors.append(_issue("unsafe-runtime-storage", storage="tasks"))
        return validated
    if not task_root.is_dir():
        return validated
    for path in sorted(task_root.glob("*.json")):
        if path.is_symlink():
            errors.append(
                _issue("unsafe-runtime-storage", storage=_relative(root, path))
            )
            continue
        envelope = _read_json_object(path)
        if envelope is None or path.name != f"{envelope.get('task_id')}.json":
            errors.append(_issue("invalid-task-envelope", path=_relative(root, path)))
            continue
        if _is_unprovable_legacy_visual_task(envelope, artifacts):
            errors.append(
                _issue(
                    "legacy-visual-task-blocked", path=_relative(root, path)
                )
            )
            continue
        constraints = envelope.get("constraints")
        if isinstance(constraints, dict):
            operation = constraints.get("visual_media_operation")
            has_deprecated_authority = bool(
                {"image_operation", "image_context", "visual_operation"}
                & constraints.keys()
            )
            if operation in ACTIVE_VISUAL_MEDIA_OPERATIONS and not has_deprecated_authority:
                try:
                    validate_visual_media_context(
                        constraints.get("visual_media_context")
                    )
                except ValueError:
                    errors.append(
                        _issue(
                            "visual-media-context-invalid",
                            path=_relative(root, path),
                        )
                    )
                    continue
                if constraints.get("execution_context") != "isolated-child-agent":
                    errors.append(
                        _issue(
                            "visual-media-isolation-required",
                            path=_relative(root, path),
                        )
                    )
                    continue
        if not _valid_task_envelope(envelope):
            errors.append(_issue("invalid-task-envelope", path=_relative(root, path)))
            continue
        for artifact_id in envelope["inputs"]:
            if artifact_id not in artifacts:
                errors.append(_issue("missing-task-input", artifact_id=artifact_id, task_id=envelope["task_id"]))
        if not all(artifact_id in artifacts for artifact_id in envelope["inputs"]):
            continue
        classification = _check_persisted_visual_media_authority(
            envelope, artifacts, path=_relative(root, path), errors=errors
        )
        if classification is not None:
            validated[envelope["task_id"]] = (envelope, classification)
    return validated


def _is_unprovable_legacy_visual_task(
    envelope: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> bool:
    """Identify shaped legacy visual authority that cannot prove one scope."""
    try:
        _validate_envelope_shape(envelope)
        classification = classify_visual_media_task(envelope, artifacts)
    except ValueError:
        return False
    constraints = envelope["constraints"]
    if classification != "visual" or not (
        {"image_operation", "image_context"} & constraints.keys()
    ):
        return False
    if "image_context" not in constraints:
        return constraints.get("image_operation") in {"generate", "image-inspect"}
    try:
        return project_legacy_image_context(envelope) is None
    except ValueError:
        return False


def _check_persisted_visual_media_authority(
    envelope: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    *,
    path: str,
    errors: list[dict[str, Any]],
) -> Optional[str]:
    """Revalidate immutable task authority without migrating or broadening it."""
    constraints = envelope["constraints"]
    has_current = bool(
        {"visual_media_operation", "visual_media_context"} & constraints.keys()
    )
    has_legacy = bool({"image_operation", "image_context"} & constraints.keys())
    try:
        classification = classify_visual_media_task(envelope, artifacts)
    except ValueError:
        errors.append(_issue("visual-media-context-invalid", path=path))
        return None

    if not has_current and not has_legacy:
        code = (
            "legacy-visual-task-blocked"
            if classification == "visual"
            else "visual-media-context-invalid"
        )
        errors.append(_issue(code, path=path))
        return None

    if has_legacy:
        try:
            legacy_context = project_legacy_image_context(envelope)
        except ValueError:
            errors.append(_issue("visual-media-context-invalid", path=path))
            return None
        if classification == "visual" and legacy_context is None:
            errors.append(_issue("legacy-visual-task-blocked", path=path))
            return None
    else:
        operation = constraints.get("visual_media_operation")
        if operation != "none":
            try:
                validate_visual_media_context(
                    constraints.get("visual_media_context")
                )
            except ValueError:
                errors.append(_issue("visual-media-context-invalid", path=path))
                return None

    try:
        validate_declared_visual_media_inputs(envelope, artifacts)
    except PermissionError:
        errors.append(_issue("visual-media-input-forbidden", path=path))
        return None
    except ValueError:
        errors.append(_issue("visual-media-context-invalid", path=path))
        return None

    if (
        not has_legacy
        and classification == "visual"
        and constraints.get("execution_context") != "isolated-child-agent"
    ):
        errors.append(_issue("visual-media-isolation-required", path=path))
        return None
    return classification


def _check_task_results(
    root: Path,
    tasks: dict[str, tuple[dict[str, Any], str]],
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    task_root = root / "tasks"
    if task_root.is_symlink() or not task_root.is_dir():
        return
    records: list[tuple[str, Path, Optional[dict[str, Any]]]] = []
    for directory in ("results", "status", "stale-results"):
        result_root = task_root / directory
        if result_root.is_symlink():
            errors.append(
                _issue(
                    "unsafe-runtime-storage",
                    storage=_relative(root, result_root),
                )
            )
            continue
        if not result_root.is_dir():
            continue
        for path in sorted(result_root.glob("*.json")):
            relative = _relative(root, path)
            if path.is_symlink():
                errors.append(_issue("unsafe-runtime-storage", storage=relative))
                continue
            records.append((directory, path, _read_json_object(path)))

    by_persisted_id: dict[str, list[Path]] = {}
    by_task_id: dict[str, list[Path]] = {}
    for _, path, result in records:
        by_persisted_id.setdefault(path.stem, []).append(path)
        task_id = result.get("task_id") if isinstance(result, dict) else None
        if isinstance(task_id, str):
            by_task_id.setdefault(task_id, []).append(path)
    duplicate_paths = {
        path
        for grouped in (by_persisted_id, by_task_id)
        for paths in grouped.values()
        if len(paths) > 1
        for path in paths
    }

    for directory, path, result in records:
        relative = _relative(root, path)
        try:
            validate_result_envelope(result)
            _validate_result(result)
            task_id = result["task_id"]
            if (
                path.name != f"{task_id}.json"
                or task_id not in tasks
                or path in duplicate_paths
            ):
                raise ValueError("task result does not match one unique valid task")
            envelope, declared_classification = tasks[task_id]
            if result["inputs"] != envelope["inputs"]:
                raise ValueError("task result inputs do not match its task")
            if directory == "results" and result["status"] != "succeeded":
                raise ValueError("terminal task results must have succeeded")
            if directory == "status" and result["status"] == "succeeded":
                raise ValueError("resumable task status must not have succeeded")
            is_current = _is_current_result(root, envelope, result)
            if directory == "stale-results":
                if is_current:
                    raise ValueError("stale task result requires non-current inputs")
            elif not is_current:
                raise ValueError("current task result requires current inputs")
            produced = _validate_result_artifacts(envelope, result, artifacts)
            _validate_conditional_visual_media_result(
                envelope,
                result,
                produced,
                artifacts,
                declared_classification,
            )
        except (KeyError, PermissionError, TypeError, ValueError):
            errors.append(_issue("visual-media-result-invalid", path=relative))


def _valid_task_envelope(envelope: dict[str, Any]) -> bool:
    try:
        _validate_persisted_envelope(envelope)
    except ValueError:
        return False
    return True


def resolve_active_timeline(root: Path) -> Optional[tuple[str, dict[str, Any]]]:
    """Resolve the one approved, fresh timeline referenced by persisted state."""
    root = project_root(root)
    ignored: list[dict[str, Any]] = []
    project = _read_project(root, ignored)
    artifacts = _read_artifacts(root, ignored)
    try:
        invalidated = invalidated_artifact_ids(root)
    except ValueError:
        return None
    artifacts = {
        artifact_id: ({**artifact, "status": "stale"} if artifact_id in invalidated else artifact)
        for artifact_id, artifact in artifacts.items()
    }
    selected = _resolve_active_timeline(root, project, artifacts, ignored)
    if selected is None:
        return None
    timeline_id, timeline = selected
    if not _timeline_references_are_current(
        artifacts[timeline_id], timeline, artifacts
    ):
        return None
    return selected


def _timeline_references_are_current(
    timeline_artifact: dict[str, Any],
    timeline: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> bool:
    referenced_ids = set(timeline_artifact["parents"])
    for _, _, _, clips in _timeline_tracks(timeline):
        for clip in clips:
            for field in ("artifact_id", "contract_id"):
                artifact_id = clip.get(field)
                if artifact_id is not None:
                    if not isinstance(artifact_id, str) or not artifact_id:
                        return False
                    referenced_ids.add(artifact_id)
    return all(
        artifact_id in artifacts
        and artifacts[artifact_id]["status"] == "approved"
        and not _has_newer_approved_lineage(artifacts[artifact_id], artifacts)
        for artifact_id in referenced_ids
    )


def _resolve_active_timeline(root: Path, project: dict[str, Any], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> Optional[tuple[str, dict[str, Any]]]:
    preferred_id = project.get("active_timeline_id")
    candidates = []
    for artifact in artifacts.values():
        if artifact["type"] != "timeline" or artifact["status"] != "approved":
            continue
        if _has_newer_approved_lineage(artifact, artifacts):
            continue
        source = _safe_project_path(root, artifact["path"])
        timeline = _read_json_object(source) if source is not None else None
        if timeline is None:
            errors.append(_issue("invalid-timeline", artifact_id=artifact["artifact_id"]))
            continue
        candidates.append((artifact["artifact_id"], timeline))
    if isinstance(preferred_id, str) and preferred_id:
        selected = [candidate for candidate in candidates if candidate[0] == preferred_id]
        if len(selected) == 1:
            return selected[0]
        errors.append(_issue("invalid-active-timeline-reference", artifact_id=preferred_id))
        return None
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        errors.append(_issue("missing-active-timeline"))
    else:
        errors.append(_issue("ambiguous-active-timeline", artifact_ids=sorted(candidate[0] for candidate in candidates)))
    return None


def _check_timeline(
    root: Path,
    timeline_id: str,
    timeline: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    allow_legacy_scene_contracts: bool,
) -> None:
    duration = timeline.get("duration_ms")
    if not _duration(duration) or duration <= 0:
        errors.append(_issue("invalid-timeline-duration", timeline_id=timeline_id))
        return
    saved_project = timeline.get("saved_project")
    saved_path = _safe_project_path(root, saved_project) if isinstance(saved_project, str) else None
    if saved_path is None or not saved_path.is_file():
        errors.append(_issue("missing-saved-project-reference", timeline_id=timeline_id))
    tracks = _timeline_tracks(timeline)
    if not tracks:
        errors.append(_issue("missing-timeline-tracks", timeline_id=timeline_id))
    primary_count = sum(1 for _, _, primary, _ in tracks if primary)
    if primary_count != 1:
        errors.append(_issue("invalid-primary-track-count", count=primary_count, timeline_id=timeline_id))
    for track_id, _, primary, clips in tracks:
        _check_track(timeline_id, track_id, primary or primary_count != 1, clips, duration, artifacts, errors, warnings)
    _check_captions(timeline_id, timeline.get("captions", []), duration, errors)
    contracted_clips = _check_contracts(
        root,
        timeline_id,
        timeline,
        artifacts,
        errors,
        allow_legacy_scene_contracts=allow_legacy_scene_contracts,
    )
    _check_demo_lifecycle(timeline_id, timeline, contracted_clips, errors)


def _timeline_tracks(timeline: dict[str, Any]) -> list[tuple[str, str, bool, list[dict[str, Any]]]]:
    if isinstance(timeline.get("clips"), list):
        return [("primary", "visual", True, _object_list(timeline["clips"]))]
    tracks = timeline.get("tracks")
    if not isinstance(tracks, list):
        return []
    output = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            continue
        clips = track.get("clips")
        if not isinstance(clips, list):
            continue
        kind = track.get("kind", "visual")
        output.append((str(track.get("id", index)), kind if isinstance(kind, str) else "visual", bool(track.get("primary", False)), _object_list(clips)))
    return output


def _check_track(timeline_id: str, track_id: str, primary: bool, clips: list[dict[str, Any]], duration: Union[int, float], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    valid_clips = []
    for clip in clips:
        start, end = clip.get("start_ms"), clip.get("end_ms")
        if not _duration(start) or not _duration(end) or start < 0 or end <= start or end > duration:
            errors.append(_issue("invalid-timeline-clip", timeline_id=timeline_id, track_id=track_id))
            continue
        valid_clips.append(clip)
    ordered = sorted(valid_clips, key=lambda clip: (clip["start_ms"], clip["end_ms"]))
    previous_end = 0
    for clip in ordered:
        start, end = clip.get("start_ms"), clip.get("end_ms")
        artifact_id = clip.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            artifact = artifacts.get(artifact_id)
            if artifact is None:
                errors.append(_issue("missing-active-artifact", artifact_id=artifact_id, timeline_id=timeline_id))
            elif artifact["status"] == "stale":
                errors.append(_issue("stale-active-artifact", artifact_id=artifact_id, timeline_id=timeline_id))
            elif artifact["status"] != "approved":
                errors.append(_issue("inactive-active-artifact", artifact_id=artifact_id, timeline_id=timeline_id))
            elif _has_newer_approved_lineage(artifact, artifacts):
                errors.append(_issue("superseded-active-artifact", artifact_id=artifact_id, timeline_id=timeline_id))
        if primary and start > previous_end:
            errors.append(_issue("timeline-gap", end_ms=start, start_ms=previous_end, timeline_id=timeline_id, track_id=track_id))
        if start < previous_end:
            errors.append(_issue("timeline-overlap", end_ms=previous_end, start_ms=start, timeline_id=timeline_id, track_id=track_id))
        previous_end = max(previous_end, end)
    if primary and ordered and previous_end < duration:
        errors.append(_issue("timeline-gap", end_ms=duration, start_ms=previous_end, timeline_id=timeline_id, track_id=track_id))
    if not ordered:
        warnings.append(_issue("empty-timeline-track", timeline_id=timeline_id, track_id=track_id))


def _check_captions(timeline_id: str, captions: Any, duration: Union[int, float], errors: list[dict[str, Any]]) -> None:
    if not isinstance(captions, list):
        errors.append(_issue("invalid-captions", timeline_id=timeline_id))
        return
    for caption in captions:
        if not isinstance(caption, dict):
            errors.append(_issue("invalid-caption", timeline_id=timeline_id))
            continue
        if not caption.get("safe_region") and not isinstance(caption.get("safe_region_record"), dict):
            errors.append(_issue("missing-caption-safe-region", timeline_id=timeline_id))
        start, end = caption.get("start_ms"), caption.get("end_ms")
        if not _duration(start) or not _duration(end) or start < 0 or end <= start or end > duration:
            errors.append(_issue("invalid-caption-timing", timeline_id=timeline_id))


def _requires_scene_contract(track_kind: str, clip: dict[str, Any]) -> bool:
    """Require scene contracts for visual/semantic content, not support tracks."""
    kind = clip.get("kind", track_kind)
    if not isinstance(kind, str):
        return True
    normalized = kind.strip().lower().replace("_", "-")
    return normalized not in NON_SEMANTIC_TRACK_KINDS


def _check_contracts(
    root: Path,
    timeline_id: str,
    timeline: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    *,
    allow_legacy_scene_contracts: bool,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    referenced: dict[str, list[dict[str, Any]]] = {}
    contracted_clips: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for _, track_kind, _, clips in _timeline_tracks(timeline):
        for clip in clips:
            if not _requires_scene_contract(track_kind, clip):
                continue
            contract_id = clip.get("contract_id")
            if not isinstance(contract_id, str) or not contract_id:
                errors.append(_issue("missing-contract-reference", scene_id=clip.get("scene_id", "unknown"), timeline_id=timeline_id))
                continue
            referenced.setdefault(contract_id, []).append(clip)
    for contract_id in sorted(referenced):
        contract = artifacts.get(contract_id)
        if contract is None or contract["type"] != "scene-contract" or contract["status"] != "approved":
            errors.append(_issue("missing-approved-contract", contract_id=contract_id, timeline_id=timeline_id))
            continue
        source = _safe_project_path(root, contract["path"])
        payload = _read_json_object(source) if source is not None else None
        if payload is None:
            errors.append(_issue("invalid-contract-coverage", contract_id=contract_id, timeline_id=timeline_id))
            continue
        try:
            timing = artifacts.get(payload.get("voice_timing_id"))
            payload = validate_scene_contract(
                payload,
                None if allow_legacy_scene_contracts else timing,
                allow_legacy_unresolved_timing=allow_legacy_scene_contracts,
                artifacts=None if allow_legacy_scene_contracts else artifacts.values(),
            )
        except ValueError:
            errors.append(
                _issue(
                    "invalid-scene-contract",
                    contract_id=contract_id,
                    timeline_id=timeline_id,
                )
            )
            continue
        for clip in referenced[contract_id]:
            contracted_clips.append((clip, payload))
            scene_id = clip.get("scene_id")
            if isinstance(scene_id, str) and scene_id and payload.get("scene_id") != scene_id:
                errors.append(_issue("contract-scene-mismatch", contract_id=contract_id, scene_id=scene_id, timeline_id=timeline_id))
            start, end = clip.get("start_ms"), clip.get("end_ms")
            if (
                _duration(start)
                and _duration(end)
                and (start < payload["start_ms"] or end > payload["end_ms"])
            ):
                errors.append(
                    _issue(
                        "contract-timing-mismatch",
                        contract_id=contract_id,
                        scene_id=scene_id or "unknown",
                        timeline_id=timeline_id,
                    )
                )
    return contracted_clips


def _check_demo_lifecycle(
    timeline_id: str,
    timeline: dict[str, Any],
    contracted_clips: list[tuple[dict[str, Any], dict[str, Any]]],
    errors: list[dict[str, Any]],
) -> None:
    demos = timeline.get("demos", [])
    records = {
        demo.get("demo_id"): demo
        for demo in _object_list(demos)
        if isinstance(demo.get("demo_id"), str) and demo["demo_id"]
    }
    for clip, contract in contracted_clips:
        if contract["primary_carrier"] != "demo":
            continue
        demo_id = clip.get("demo_id")
        record = records.get(demo_id) if isinstance(demo_id, str) else None
        if record is None or record.get("status") not in {"captured", "recorded", "approved"}:
            errors.append(_issue("demo-lifecycle-incomplete", timeline_id=timeline_id, demo_id=demo_id or "unknown"))


def _check_required_approvals(project: dict[str, Any], artifacts: dict[str, dict[str, Any]], approvals: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    targets = {approval["target_id"] for approval in approvals}
    for artifact in artifacts.values():
        if artifact.get("requires_approval") and artifact["artifact_id"] not in targets:
            errors.append(_issue("missing-required-approval", artifact_id=artifact["artifact_id"]))
    if project.get("phase") not in {"review_ready", "handoff_ready"}:
        return
    for artifact in artifacts.values():
        if artifact["type"] == "timeline" and artifact["status"] == "approved" and artifact["artifact_id"] not in targets:
            errors.append(_issue("missing-timeline-approval", artifact_id=artifact["artifact_id"]))


def _has_newer_approved_lineage(artifact: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> bool:
    return any(
        candidate["type"] == artifact["type"]
        and candidate["status"] == "approved"
        and candidate["version"] > artifact["version"]
        and _is_descendant(candidate, artifact["artifact_id"], artifacts)
        for candidate in artifacts.values()
    )


def _is_descendant(candidate: dict[str, Any], ancestor_id: str, artifacts: dict[str, dict[str, Any]]) -> bool:
    pending = list(candidate["parents"])
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == ancestor_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        if current in artifacts:
            pending.extend(artifacts[current]["parents"])
    return False


def _read_json_object(path: Optional[Path]) -> Optional[dict[str, Any]]:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_project_path(root: Path, relative: Any) -> Optional[Path]:
    if not isinstance(relative, str) or not relative:
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or "\\" in relative or any(part in {".", ".."} for part in candidate.parts):
        return None
    try:
        destination = project_path(root, candidate)
    except ValueError:
        return None
    return destination


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _safe_component(value: Any) -> bool:
    return isinstance(value, str) and value not in {"", ".", ".."} and "/" not in value and "\\" not in value


def _nonempty_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def _duration(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _issue(code: str, **references: Any) -> dict[str, Any]:
    return {"code": code, **{key: references[key] for key in sorted(references)}}


def _sorted_issues(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

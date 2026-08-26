"""Deterministic, objective checks for a video-toolkit runtime project."""

import json
import math
from pathlib import Path
from typing import Any, Iterable, Optional, Union


ARTIFACT_REQUIRED_KEYS = ("artifact_id", "type", "version", "status", "parents", "path")
ARTIFACT_STATUSES = {"draft", "approved", "stale", "superseded", "invalid"}
APPROVAL_DECISIONS = {"approved", "delegated", "skipped"}
TASK_REQUIRED_KEYS = {
    "task_id",
    "capability",
    "inputs",
    "adapter_preferences",
    "output_contract",
    "constraints",
}
PRIMARY_CARRIERS = {"A-roll", "B-roll", "Scene", "Demo", "Motion Graphics", "Evidence"}


def validate_project(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Return stable structural errors and warnings for *root*.

    The result deliberately describes persisted facts only.  It never derives an
    aesthetic opinion or changes project state, so callers can safely run it
    before a user-review gate or after an interrupted production task.
    """
    root = Path(root).resolve()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    project = _read_project(root, errors)
    artifacts = _read_artifacts(root, errors)
    approvals = _read_approvals(root, errors)
    _check_artifact_graph(root, artifacts, errors)
    _check_tasks(root, artifacts, errors)
    timelines = _read_timelines(root, artifacts, errors)
    for timeline_id, timeline in timelines:
        _check_timeline(root, timeline_id, timeline, artifacts, errors, warnings)
    _check_required_approvals(project, artifacts, approvals, errors)
    return {"errors": _sorted_issues(errors), "warnings": _sorted_issues(warnings)}


def _read_project(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    project_path = root / "project.json"
    project = _read_json_object(project_path)
    if project is None:
        errors.append(_issue("missing-project-state", path="project.json"))
        return {}
    required = {"schema_version", "project_id", "workflow", "phase"}
    if set(project) != required or project.get("schema_version") != 1:
        errors.append(_issue("invalid-project-state", path="project.json"))
        return {}
    if not all(isinstance(project.get(key), str) and project[key] for key in ("project_id", "workflow", "phase")):
        errors.append(_issue("invalid-project-state", path="project.json"))
        return {}
    return project


def _read_artifacts(root: Path, errors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    artifacts_root = root / "artifacts"
    if not artifacts_root.is_dir():
        return artifacts
    for path in sorted(artifacts_root.glob("*/*.json")):
        raw = _read_json_object(path)
        if raw is None or not _valid_artifact(raw) or path.name != f"{raw.get('artifact_id')}.json":
            errors.append(_issue("invalid-artifact-metadata", path=_relative(root, path)))
            continue
        artifact_id = raw["artifact_id"]
        if artifact_id in artifacts:
            errors.append(_issue("duplicate-artifact-id", artifact_id=artifact_id))
            continue
        artifacts[artifact_id] = raw
    return artifacts


def _valid_artifact(artifact: dict[str, Any]) -> bool:
    if not all(key in artifact for key in ARTIFACT_REQUIRED_KEYS):
        return False
    if not all(isinstance(artifact[key], str) and artifact[key] for key in ("artifact_id", "type", "path")):
        return False
    if not _safe_component(artifact["artifact_id"]) or not _safe_component(artifact["type"]):
        return False
    if isinstance(artifact["version"], bool) or not isinstance(artifact["version"], int) or artifact["version"] < 1:
        return False
    return (
        artifact["status"] in ARTIFACT_STATUSES
        and isinstance(artifact["parents"], list)
        and len(artifact["parents"]) == len(set(artifact["parents"]))
        and all(isinstance(parent, str) and parent for parent in artifact["parents"])
    )


def _read_approvals(root: Path, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approvals: list[dict[str, Any]] = []
    approval_root = root / "approvals"
    if not approval_root.is_dir():
        return approvals
    for path in sorted(approval_root.glob("*.json")):
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


def _check_tasks(root: Path, artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    task_root = root / "tasks"
    if not task_root.is_dir():
        return
    for path in sorted(task_root.glob("*.json")):
        envelope = _read_json_object(path)
        if envelope is None or not _valid_task_envelope(envelope) or path.name != f"{envelope.get('task_id')}.json":
            errors.append(_issue("invalid-task-envelope", path=_relative(root, path)))
            continue
        for artifact_id in envelope["inputs"]:
            if artifact_id not in artifacts:
                errors.append(_issue("missing-task-input", artifact_id=artifact_id, task_id=envelope["task_id"]))


def _valid_task_envelope(envelope: dict[str, Any]) -> bool:
    if set(envelope) != TASK_REQUIRED_KEYS:
        return False
    if not _safe_component(envelope.get("task_id")):
        return False
    if not all(isinstance(envelope.get(key), str) and envelope[key] for key in ("capability", "output_contract")):
        return False
    for field, nonempty in (("inputs", False), ("adapter_preferences", True)):
        value = envelope.get(field)
        if not isinstance(value, list) or (nonempty and not value) or len(value) != len(set(value)):
            return False
        if not all(_safe_component(item) for item in value):
            return False
    return isinstance(envelope.get("constraints"), dict)


def _read_timelines(root: Path, artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    seen_paths: set[Path] = set()
    for artifact in artifacts.values():
        if artifact["type"] != "timeline" or artifact["status"] != "approved":
            continue
        source = _safe_project_path(root, artifact["path"])
        if source is None or source in seen_paths:
            continue
        seen_paths.add(source)
        timeline = _read_json_object(source)
        if timeline is None:
            errors.append(_issue("invalid-timeline", artifact_id=artifact["artifact_id"]))
        else:
            records.append((artifact["artifact_id"], timeline))
    if records:
        return records
    timeline_root = root / "timeline"
    if timeline_root.is_dir():
        for source in sorted(timeline_root.glob("*.json")):
            timeline = _read_json_object(source)
            if timeline is not None:
                records.append((source.stem, timeline))
    return records


def _check_timeline(root: Path, timeline_id: str, timeline: dict[str, Any], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
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
    for track_id, primary, clips in tracks:
        _check_track(timeline_id, track_id, primary, clips, duration, artifacts, errors, warnings)
    _check_captions(timeline_id, timeline.get("captions", []), duration, errors)
    _check_contracts(root, timeline_id, timeline, artifacts, errors)
    _check_demo_lifecycle(timeline_id, timeline, errors)


def _timeline_tracks(timeline: dict[str, Any]) -> list[tuple[str, bool, list[dict[str, Any]]]]:
    if isinstance(timeline.get("clips"), list):
        return [("primary", True, _object_list(timeline["clips"]))]
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
        output.append((str(track.get("id", index)), bool(track.get("primary", False)), _object_list(clips)))
    return output


def _check_track(timeline_id: str, track_id: str, primary: bool, clips: list[dict[str, Any]], duration: Union[int, float], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    ordered = sorted(clips, key=lambda clip: (clip.get("start_ms", -1), clip.get("end_ms", -1)))
    previous_end = 0
    for clip in ordered:
        start, end = clip.get("start_ms"), clip.get("end_ms")
        if not _duration(start) or not _duration(end) or start < 0 or end <= start or end > duration:
            errors.append(_issue("invalid-timeline-clip", timeline_id=timeline_id, track_id=track_id))
            continue
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


def _check_contracts(root: Path, timeline_id: str, timeline: dict[str, Any], artifacts: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    referenced = {
        clip["contract_id"]
        for _, _, clips in _timeline_tracks(timeline)
        for clip in clips
        if isinstance(clip.get("contract_id"), str) and clip["contract_id"]
    }
    for contract_id in sorted(referenced):
        contract = artifacts.get(contract_id)
        if contract is None or contract["type"] != "scene-contract" or contract["status"] != "approved":
            errors.append(_issue("missing-approved-contract", contract_id=contract_id, timeline_id=timeline_id))
            continue
        source = _safe_project_path(root, contract["path"])
        payload = _read_json_object(source) if source is not None else None
        if payload is None:
            continue
        for beat in _object_list(payload.get("semantic_beats", [])):
            carrier = beat.get("primary_carrier")
            secondary = beat.get("secondary_layer", beat.get("secondary_layers", []))
            layers = secondary if isinstance(secondary, list) else [secondary] if secondary else []
            if carrier not in PRIMARY_CARRIERS:
                errors.append(_issue("invalid-primary-carrier", contract_id=contract_id))
            if len(layers) > 1:
                errors.append(_issue("too-many-secondary-layers", contract_id=contract_id))


def _check_demo_lifecycle(timeline_id: str, timeline: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    demos = timeline.get("demos", [])
    records = {
        demo.get("demo_id"): demo
        for demo in _object_list(demos)
        if isinstance(demo.get("demo_id"), str) and demo["demo_id"]
    }
    for _, _, clips in _timeline_tracks(timeline):
        for clip in clips:
            if clip.get("primary_carrier") != "Demo":
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
    destination = root / candidate
    try:
        destination.resolve().relative_to(root)
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


def _duration(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _issue(code: str, **references: Any) -> dict[str, Any]:
    return {"code": code, **{key: references[key] for key in sorted(references)}}


def _sorted_issues(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

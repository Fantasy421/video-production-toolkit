"""Compact, deterministic coordinator state for one video-production action."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Optional, Union

from scripts.toolkit.artifacts import (
    _artifact_paths_by_id,
    _read_valid_artifact,
    read_approval,
)
from scripts.toolkit.invalidation import (
    invalidate_descendants,
    invalidated_artifact_ids,
)
from scripts.toolkit.project_state import (
    PHASES,
    append_event,
    project_recovery_view,
    replay_events,
)
from scripts.toolkit.runtime_paths import project_path, project_root
from scripts.toolkit.tasks import (
    _read_envelope,
    _validate_envelope,
    active_claim_task_ids,
    voice_timing_input_is_current,
)
from scripts.toolkit.voice import validate_voice_bundle


GATES = (
    "content",
    "visual-direction",
    "storyboard-and-cost",
    "representative-slice-and-final-draft",
)

_BASE_GATES = {
    "narration.plan": "content",
    "visual.preview": "content",
    "voice.prepare": "visual-direction",
    "storyboard.plan": "visual-direction",
    "scene.produce": "storyboard-and-cost",
    "motion.preview": "storyboard-and-cost",
    "motion.produce": "storyboard-and-cost",
    "timeline.assemble": "storyboard-and-cost",
    "structure.validate": "storyboard-and-cost",
    "review.package": "storyboard-and-cost",
}
_UNGATED_CAPABILITIES = {"project.manage"}
_EXPANSION_SCOPES = {"full-production", "final-draft", "handoff", "export"}
_VALID_DECISIONS = {"approved", "delegated", "skipped"}
_GATE_TARGET_TYPES = {
    "content": "decision-pack",
    "visual-direction": "style-pack",
    "storyboard-and-cost": "storyboard",
}
_FINAL_GATE_TARGET_TYPES = {
    "full-production": "representative-slice",
    "final-draft": "final-draft",
    "handoff": "final-draft",
    "export": "final-draft",
}
_CAPABILITY_PHASES = {
    "narration.plan": {"initialized"},
    "visual.preview": {"content_ready"},
    "voice.prepare": {"direction_ready"},
    "storyboard.plan": {"voice_ready"},
    "scene.produce": {"storyboard_ready", "production_ready"},
    "motion.preview": {"storyboard_ready"},
    "motion.produce": {"storyboard_ready", "production_ready"},
    "timeline.assemble": {"storyboard_ready", "production_ready"},
    "structure.validate": {"assembled"},
    "review.package": {"review_ready"},
    "project.manage": set(PHASES),
}


def calculate_ready_tasks(
    state: Mapping[str, Any],
    artifacts: Union[Iterable[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]],
    approvals: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Return zero or one policy-authorized action from compact project data.

    The function only calculates routing metadata. It never imports or invokes a
    media provider. Parent versions, decision gates, terminal task state, and
    live task locks are checked before deterministic task-ID ordering selects a
    single action slice.
    """
    if not isinstance(state, Mapping):
        raise ValueError("state must be a mapping")
    phase = state.get("phase")
    if phase is not None and phase not in PHASES:
        raise ValueError("project phase is not recognized")
    candidates = state.get("candidate_tasks", [])
    if not isinstance(candidates, list):
        raise ValueError("candidate_tasks must be a list")
    locked = _string_set(state.get("locked_task_ids", []), "locked_task_ids")
    completed = _string_set(state.get("completed_task_ids", []), "completed_task_ids")
    by_id = _normalize_artifacts(artifacts)
    normalized_approvals = _normalize_approvals(approvals)

    ready: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate task must be an object")
        _validate_envelope(candidate)
        task_id = candidate["task_id"]
        if task_id in seen_task_ids:
            raise ValueError(f"candidate task ID is duplicated: {task_id}")
        seen_task_ids.add(task_id)
        if task_id in locked or task_id in completed:
            continue
        if phase is not None and not _capability_is_legal_in_phase(candidate, phase):
            continue
        if not _parents_are_current(candidate["inputs"], by_id):
            continue
        if not voice_timing_input_is_current(candidate, by_id):
            continue
        gate = _required_gate(candidate)
        if gate is not None and not _has_gate_approval(
            candidate, gate, by_id, normalized_approvals
        ):
            continue
        ready.append(candidate)

    if not ready:
        return []
    selected = min(ready, key=lambda item: item["task_id"])
    return [_action_name(selected)]


def _capability_is_legal_in_phase(candidate: Mapping[str, Any], phase: str) -> bool:
    capability = candidate["capability"]
    allowed = _CAPABILITY_PHASES.get(capability)
    if allowed is None:
        raise ValueError(f"unknown coordinator capability: {capability}")
    scope = candidate["constraints"].get("production_scope")
    if capability in {"scene.produce", "motion.produce", "timeline.assemble"}:
        if scope in _EXPANSION_SCOPES:
            return phase == "production_ready"
        return phase == "storyboard_ready"
    return phase in allowed


def invalidate_artifact_descendants(
    root: Path,
    changed_id: str,
    rules: Mapping[str, list[str]],
) -> list[str]:
    """Persist local DAG invalidation as an event without rewriting artifacts."""
    root = project_root(root)
    artifacts = _load_artifacts(root)
    stale = sorted(invalidate_descendants(artifacts, changed_id, rules))
    append_event(
        root,
        {
            "event": "artifacts.invalidated",
            "changed_id": changed_id,
            "artifact_ids": stale,
        },
    )
    return stale


def resume_project(root: Path) -> dict[str, Any]:
    """Rebuild compact coordinator input and one ready action from disk."""
    root = project_root(root)
    state = replay_events(root)
    if not state:
        raise ValueError("project event log does not contain initialization")
    artifacts = _load_artifacts(root)
    invalidated = invalidated_artifact_ids(root)
    effective_artifacts = [
        {**item, "status": "stale"} if item["artifact_id"] in invalidated else item
        for item in artifacts
    ]
    state = project_recovery_view(
        root,
        effective_artifacts,
        has_current_voice_lineage=_has_current_voice_bundle,
    )
    candidate_tasks = _load_candidate_tasks(root)
    locked = active_claim_task_ids(root)
    completed = sorted(
        set(_task_ids(root, Path("tasks") / "results", ".json"))
        | set(_task_ids(root, Path("tasks") / "stale-results", ".json"))
    )
    approvals = _load_approvals(root)
    coordinator_state = {
        **state,
        "candidate_tasks": candidate_tasks,
        "locked_task_ids": locked,
        "completed_task_ids": completed,
    }
    ready = calculate_ready_tasks(coordinator_state, effective_artifacts, approvals)
    return {
        **state,
        "artifacts": effective_artifacts,
        "approvals": approvals,
        "candidate_tasks": candidate_tasks,
        "locked_task_ids": locked,
        "completed_task_ids": completed,
        "ready_tasks": ready,
    }


def _has_current_voice_bundle(artifacts: Iterable[Mapping[str, Any]]) -> bool:
    """Use the authoritative validator behind project-state's dependency seam."""
    records = list(artifacts)
    narration_ids = sorted(
        {
            item.get("narration_id")
            for item in records
            if isinstance(item, Mapping)
            and item.get("type") == "voice-source-decision"
            and isinstance(item.get("narration_id"), str)
            and item.get("narration_id")
        }
    )
    for narration_id in narration_ids:
        try:
            if validate_voice_bundle(records, narration_id)["ok"]:
                return True
        except ValueError:
            continue
    return False


def _required_gate(candidate: Mapping[str, Any]) -> Optional[str]:
    capability = candidate["capability"]
    constraints = candidate["constraints"]
    if capability in _UNGATED_CAPABILITIES:
        expected = None
    elif capability not in _BASE_GATES:
        raise ValueError(f"unknown coordinator capability: {capability}")
    else:
        expected = _BASE_GATES[capability]
    if constraints.get("production_scope") in _EXPANSION_SCOPES:
        expected = "representative-slice-and-final-draft"
    declared = constraints.get("required_gate")
    if declared != expected:
        raise ValueError(
            f"task {candidate['task_id']} declares gate {declared!r}; expected {expected!r}"
        )
    return expected


def _has_gate_approval(
    candidate: Mapping[str, Any],
    gate: str,
    artifacts: Mapping[str, Mapping[str, Any]],
    approvals: list[dict[str, str]],
) -> bool:
    target_id = candidate["constraints"].get("gate_target_id")
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("a gated task requires a gate_target_id")
    target = artifacts.get(target_id)
    if target is None or target["status"] in {"stale", "superseded", "invalid"}:
        return False
    if not _target_is_in_input_lineage(target_id, candidate["inputs"], artifacts):
        return False
    if gate == "representative-slice-and-final-draft":
        expected_type = _FINAL_GATE_TARGET_TYPES.get(
            candidate["constraints"].get("production_scope")
        )
    else:
        expected_type = _GATE_TARGET_TYPES.get(gate)
    if expected_type is None or target.get("type") != expected_type:
        return False
    return any(
        approval["target_id"] == target_id
        and approval["scope"] == gate
        and approval["decision"] in _VALID_DECISIONS
        for approval in approvals
    )


def _target_is_in_input_lineage(
    target_id: str,
    inputs: list[str],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> bool:
    pending = list(inputs)
    seen = set()
    while pending:
        artifact_id = pending.pop()
        if artifact_id == target_id:
            return True
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        artifact = artifacts.get(artifact_id)
        if artifact is not None:
            pending.extend(artifact.get("parents", []))
    return False


def _parents_are_current(
    inputs: list[str], artifacts: Mapping[str, Mapping[str, Any]]
) -> bool:
    return all(
        artifact_id in artifacts and artifacts[artifact_id]["status"] == "approved"
        for artifact_id in inputs
    )


def _action_name(candidate: Mapping[str, Any]) -> str:
    capability = candidate["capability"]
    scene_id = candidate["constraints"].get("scene_id")
    if scene_id is None:
        return capability
    if not isinstance(scene_id, str) or not scene_id or "/" in scene_id or "\\" in scene_id:
        raise ValueError("scene_id must be a safe non-empty string")
    return f"{capability}:{scene_id}"


def _normalize_artifacts(
    artifacts: Union[Iterable[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]]
) -> dict[str, dict[str, Any]]:
    values = artifacts.values() if isinstance(artifacts, Mapping) else artifacts
    if isinstance(values, (str, bytes)):
        raise ValueError("artifacts must be a collection")
    by_id: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, Mapping):
            raise ValueError("artifact must be an object")
        artifact_id = item.get("artifact_id")
        status = item.get("status")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("artifact_id must be a non-empty string")
        if status not in {"draft", "approved", "stale", "superseded", "invalid"}:
            raise ValueError("artifact status is not recognized")
        if artifact_id in by_id:
            raise ValueError(f"artifact ID is duplicated: {artifact_id}")
        by_id[artifact_id] = dict(item)
    return by_id


def _normalize_approvals(approvals: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    if isinstance(approvals, (str, bytes)):
        raise ValueError("approvals must be a collection")
    normalized = []
    for item in approvals:
        if not isinstance(item, Mapping):
            raise ValueError("approval must be an object")
        target_id = item.get("target_id")
        scope = item.get("scope")
        decision = item.get("decision", "approved")
        if not all(isinstance(value, str) and value for value in (target_id, scope)):
            raise ValueError("approval target_id and scope must be non-empty strings")
        if decision not in _VALID_DECISIONS:
            raise ValueError("approval decision is not recognized")
        normalized.append(
            {"target_id": target_id, "scope": scope, "decision": decision}
        )
    return normalized


def _load_artifacts(root: Path) -> list[dict[str, Any]]:
    artifacts = []
    artifacts_root = project_path(root, "artifacts")
    for artifact_id, path in sorted(_artifact_paths_by_id(artifacts_root).items()):
        item = _read_valid_artifact(path)
        if item is None or item["artifact_id"] != artifact_id:
            raise ValueError(f"invalid artifact metadata: {path}")
        artifacts.append(item)
    return artifacts


def _load_candidate_tasks(root: Path) -> list[dict[str, Any]]:
    tasks = []
    tasks_root = project_path(root, "tasks")
    if not tasks_root.is_dir():
        return tasks
    for path in sorted(tasks_root.glob("*.json")):
        tasks.append(_read_envelope(root, path.stem))
    return tasks


def _load_approvals(root: Path) -> list[dict[str, Any]]:
    approvals_root = project_path(root, "approvals")
    if not approvals_root.is_dir():
        return []
    return [read_approval(root, path.stem) for path in sorted(approvals_root.glob("*.json"))]


def _task_ids(root: Path, relative: Path, suffix: str) -> list[str]:
    directory = project_path(root, relative)
    if not directory.is_dir():
        return []
    task_ids = []
    for path in directory.glob(f"*{suffix}"):
        if path.is_symlink():
            raise ValueError(f"task result storage must not contain symlinks: {path.name}")
        if path.is_file():
            task_ids.append(path.name[: -len(suffix)])
    return sorted(task_ids)


def _string_set(value: Any, label: str) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must be a string list")
    return set(value)

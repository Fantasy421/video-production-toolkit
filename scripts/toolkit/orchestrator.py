"""Compact, deterministic coordinator state for one video-production action."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Optional, Union

from scripts.toolkit.artifacts import (
    _artifact_paths_by_id,
    _read_valid_artifact,
    coordinator_safe_artifact_projection,
    read_approval,
)
from scripts.toolkit.invalidation import (
    invalidate_descendants,
    invalidated_artifact_ids,
)
from scripts.toolkit.project_state import (
    PHASES,
    V3_PHASES,
    append_event,
    project_recovery_view,
    replay_events,
)
from scripts.toolkit.runtime_paths import project_path, project_root
from scripts.toolkit.tasks import (
    _read_envelope,
    active_claim_task_ids,
    authorize_declared_visual_media_task,
    validate_current_task_envelope,
    validate_persisted_task_envelope,
    timing_contract_inputs_are_current,
)
from scripts.toolkit.timing_validation import validate_timing_validation_result
from scripts.toolkit.visual_media_context import SAFE_ID_RE


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
    "captions.produce": "storyboard-and-cost",
    "representative-slice.produce": "storyboard-and-cost",
    "structure.validate": "storyboard-and-cost",
    "review.package": "storyboard-and-cost",
}
_UNGATED_CAPABILITIES = {"project.manage", "timing-repair"}
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
    "captions.produce": {"storyboard_ready", "production_ready"},
    "representative-slice.produce": {"storyboard_ready"},
    "structure.validate": {"assembled"},
    "review.package": {"review_ready"},
    "timing-repair": {"storyboard_timed", "production_ready"},
    "project.manage": set(PHASES),
}


def calculate_ready_tasks(
    state: Mapping[str, Any],
    artifacts: Union[Iterable[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]],
    approvals: Iterable[Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
) -> list[str]:
    """Return zero or one policy-authorized action from compact project data.

    The function only calculates routing metadata. It never imports or invokes a
    media provider. Parent versions, decision gates, terminal task state, and
    live task locks are checked before deterministic task-ID ordering selects a
    single action slice.
    """
    ready, _ = _calculate_ready_tasks(
        state,
        artifacts,
        approvals,
        root=root,
        validator=validate_current_task_envelope,
        recover=False,
    )
    return ready


def _calculate_ready_tasks(
    state: Mapping[str, Any],
    artifacts: Union[Iterable[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]],
    approvals: Iterable[Mapping[str, Any]],
    *,
    root: Optional[Path],
    validator: Any,
    recover: bool,
) -> tuple[list[str], list[dict[str, str]]]:
    if not isinstance(state, Mapping):
        raise ValueError("state must be a mapping")
    phase = state.get("phase")
    if phase is not None and phase not in {*PHASES, *V3_PHASES}:
        raise ValueError("project phase is not recognized")
    candidates = state.get("candidate_tasks", [])
    if not isinstance(candidates, list):
        raise ValueError("candidate_tasks must be a list")
    locked = _string_set(state.get("locked_task_ids", []), "locked_task_ids")
    completed = _string_set(state.get("completed_task_ids", []), "completed_task_ids")
    by_id = _normalize_artifacts(artifacts)
    normalized_approvals = _normalize_approvals(approvals)

    ready: list[dict[str, Any]] = []
    recovery_issues: list[dict[str, str]] = []
    seen_task_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            if recover:
                recovery_issues.append({"code": "visual-media-context-invalid"})
                continue
            raise ValueError("candidate task must be an object")
        try:
            validator(candidate)
        except (PermissionError, TypeError, ValueError) as error:
            if not recover:
                raise
            recovery_issues.append(_visual_recovery_issue(candidate, error))
            continue
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
        if not timing_contract_inputs_are_current(candidate, by_id, root=root):
            continue
        v3_project = (
            state.get("schema_version") == 3
            or phase in set(V3_PHASES) - {"production_ready"}
            or "timing_validation_id" in candidate["constraints"]
        )
        if not _timing_route_is_current(candidate, by_id, phase, v3_project):
            continue
        gate = _required_gate(candidate)
        if gate is not None and not _has_gate_approval(
            candidate, gate, by_id, normalized_approvals
        ):
            continue
        try:
            authorize_declared_visual_media_task(candidate, by_id)
        except (PermissionError, TypeError, ValueError) as error:
            if not recover:
                raise
            recovery_issues.append(_visual_recovery_issue(candidate, error))
            continue
        ready.append(candidate)

    if not ready:
        return [], recovery_issues
    repairs = [item for item in ready if item["capability"] == "timing-repair"]
    selected = min(repairs or ready, key=lambda item: item["task_id"])
    return [_action_name(selected)], recovery_issues


def _timing_route_is_current(
    candidate: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    phase: Optional[str],
    v3_project: bool,
) -> bool:
    """Gate v3 visual work on the worker's compact current validation result."""
    capability = candidate["capability"]
    current = _current_timing_validation(candidate, artifacts)
    if capability == "timing-repair":
        return current is not None and current["timing_validation"]["status"] == "blocked"
    if (
        not v3_project
        or phase not in V3_PHASES
        or V3_PHASES.index(phase) < V3_PHASES.index("storyboard_timed")
        or capability
        not in {
            "scene.produce",
            "motion.preview",
            "motion.produce",
            "timeline.assemble",
            "captions.produce",
            "representative-slice.produce",
        }
    ):
        return True
    return current is not None and current["timing_validation"]["status"] == "passed"


def _current_timing_validation(
    candidate: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Resolve the latest validated result on the current timing DAG."""
    constraints = candidate.get("constraints", {})
    validation_id = constraints.get("timing_validation_id")
    inputs = candidate.get("inputs")
    if (
        not isinstance(validation_id, str)
        or SAFE_ID_RE.fullmatch(validation_id) is None
        or not isinstance(inputs, list)
        or validation_id not in inputs
    ):
        return None

    def latest(records: list[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
        if not records:
            return None
        return max(
            (dict(record) for record in records),
            key=lambda record: (
                record.get("version")
                if isinstance(record.get("version"), int)
                and not isinstance(record.get("version"), bool)
                else -1,
                record.get("artifact_id")
                if isinstance(record.get("artifact_id"), str)
                else "",
            ),
        )

    def has_parent(record: Mapping[str, Any], parent_id: Any) -> bool:
        parents = record.get("parents")
        return isinstance(parents, list) and parent_id in parents

    voice = latest(
        [
            item
            for item in artifacts.values()
            if item.get("type") == "voice-timing"
            and item.get("status") == "approved"
            and item.get("timing_kind") == "real"
        ]
    )
    if voice is None:
        return None
    timed = latest(
        [
            item
            for item in artifacts.values()
            if item.get("type") == "timed-semantic-beats"
            and item.get("status") == "approved"
            and item.get("timing_kind") == "real"
            and item.get("voice_timing_id") == voice.get("artifact_id")
            and has_parent(item, voice.get("artifact_id"))
        ]
    )
    if timed is None:
        return None
    scene = latest(
        [
            item
            for item in artifacts.values()
            if item.get("type") == "scene-timing-contracts"
            and item.get("status") == "approved"
            and item.get("timed_semantic_beats_id") == timed.get("artifact_id")
            and has_parent(item, timed.get("artifact_id"))
        ]
    )
    if scene is None:
        return None

    expected_lineage = {
        "voice_timing_id": voice.get("artifact_id"),
        "timed_semantic_beats_id": timed.get("artifact_id"),
        "scene_timing_contracts_id": scene.get("artifact_id"),
    }
    if any(
        key in constraints and constraints.get(key) != value
        for key, value in expected_lineage.items()
    ):
        return None

    candidates: list[dict[str, Any]] = []
    for item in artifacts.values():
        if (
            item.get("type") != "timing-validation"
            or item.get("status") != "approved"
            or not has_parent(item, scene.get("artifact_id"))
        ):
            continue
        candidates.append(dict(item))
    current = latest(candidates)
    if current is None or current.get("artifact_id") != validation_id:
        return None
    try:
        current["timing_validation"] = validate_timing_validation_result(
            current["timing_validation"]
        )
    except (KeyError, TypeError, ValueError):
        return None
    return current


def _capability_is_legal_in_phase(candidate: Mapping[str, Any], phase: str) -> bool:
    capability = candidate["capability"]
    allowed = _CAPABILITY_PHASES.get(capability)
    if allowed is None:
        raise ValueError(f"unknown coordinator capability: {capability}")
    scope = candidate["constraints"].get("production_scope")
    if phase in V3_PHASES:
        v3_allowed = {
            "narration.plan": {"script_confirmed"},
            "visual.preview": {"semantic_beats_confirmed", "visual_direction_previewed"},
            "voice.prepare": {"semantic_beats_confirmed", "visual_direction_previewed"},
            "storyboard.plan": {"timing_bound"},
            "representative-slice.produce": {"storyboard_timed"},
            "motion.preview": {"storyboard_timed"},
            "scene.produce": {"storyboard_timed", "production_ready"},
            "motion.produce": {"storyboard_timed", "production_ready"},
            "timeline.assemble": {"storyboard_timed", "production_ready"},
            "captions.produce": {"storyboard_timed", "production_ready"},
            "structure.validate": set(),
            "review.package": set(),
            "timing-repair": {"storyboard_timed", "production_ready"},
            "project.manage": set(V3_PHASES),
        }
        allowed_v3 = v3_allowed.get(capability)
        if allowed_v3 is None:
            raise ValueError(f"unknown coordinator capability: {capability}")
        scope = candidate["constraints"].get("production_scope")
        if capability in {"scene.produce", "motion.produce", "timeline.assemble", "captions.produce"}:
            return phase == "production_ready" if scope in _EXPANSION_SCOPES else phase == "storyboard_timed"
        return phase in allowed_v3

    if capability in {
        "scene.produce",
        "motion.produce",
        "timeline.assemble",
        "captions.produce",
    }:
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
    state = project_recovery_view(root, effective_artifacts)
    candidate_tasks, load_issues = _load_candidate_tasks(root)
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
    ready, authority_issues = _calculate_ready_tasks(
        coordinator_state,
        effective_artifacts,
        approvals,
        root=root,
        validator=validate_persisted_task_envelope,
        recover=True,
    )
    from scripts.toolkit.validation import validate_project

    persisted = validate_project(root)
    blocking_codes = {
        "invalid-artifact-metadata",
        "legacy-visual-task-blocked",
        "visual-media-context-invalid",
        "visual-media-input-forbidden",
        "visual-media-isolation-required",
        "visual-media-result-invalid",
        "voice-timing-required",
        "timed-semantic-beats-required",
        "scene-timing-contracts-required",
        "timing-validation-required",
    }
    persisted_issues = [
        {
            key: value
            for key, value in issue.items()
            if key in {"code", "task_id", "artifact_id", "path"}
        }
        for issue in persisted["errors"]
        if issue.get("code") in blocking_codes
    ]
    state_recovery_issues = [
        {"code": code}
        for code in state.get("migration_requirement", {}).get("issues", [])
        if isinstance(code, str)
    ]
    recovery_issues = _deduplicate_recovery_issues(
        [*state_recovery_issues, *load_issues, *authority_issues, *persisted_issues]
    )
    if recovery_issues:
        recorded_phase = state.get("migration_requirement", {}).get(
            "recorded_phase", state["phase"]
        )
        recovery_floor = (
            "semantic_beats_confirmed"
            if state.get("schema_version") == 3
            else "direction_ready"
        )
        safe_phase = (
            recovery_floor
            if _phase_position(recorded_phase) > _phase_position(recovery_floor)
            else recorded_phase
        )
        state = {
            **state,
            "phase": safe_phase,
            "migration_requirement": {
                "code": "visual-media-recovery-blocked",
                "recorded_phase": recorded_phase,
                **({"issues": [item["code"] for item in recovery_issues if "code" in item]}
                   if state.get("schema_version") == 3 else {}),
            },
        }
        candidate_tasks = []
        ready = []
    return {
        **state,
        "artifacts": [
            coordinator_safe_artifact_projection(item)
            for item in effective_artifacts
        ],
        "approvals": [_coordinator_safe_approval_projection(item) for item in approvals],
        "candidate_tasks": [
            _coordinator_safe_task_projection(item) for item in candidate_tasks
        ],
        "locked_task_ids": locked,
        "completed_task_ids": completed,
        "ready_tasks": ready,
        **({"recovery_issues": recovery_issues} if recovery_issues else {}),
    }


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


_SAFE_COORDINATOR_CONSTRAINTS = frozenset(
    {
        "visual_media_operation",
        "required_gate",
        "gate_target_id",
        "production_scope",
        "scene_id",
        "voice_timing_id",
        "timed_semantic_beats_id",
        "scene_timing_contracts_id",
        "timing_validation_id",
        "affected_beat_ids",
        "issue_counts",
        "examples",
    }
)


def _coordinator_safe_task_projection(task: Mapping[str, Any]) -> dict[str, Any]:
    """Project persisted task authority without forwarding worker payloads."""
    constraints = task.get("constraints", {})
    legacy_keys = {"image_operation", "image_context"}
    if set(constraints) <= legacy_keys and constraints:
        # Preserve the historical read-only view for old callers; persisted
        # current authority always takes the compact projection below.
        legacy_projection = dict(task)
        output_contract = legacy_projection.get("output_contract")
        if not (
            isinstance(output_contract, str)
            and len(output_contract) <= 128
            and SAFE_ID_RE.fullmatch(output_contract) is not None
        ):
            legacy_projection.pop("output_contract", None)
        return legacy_projection
    projected_constraints = {
        key: constraints[key]
        for key in _SAFE_COORDINATOR_CONSTRAINTS
        if key in constraints
    }
    is_valid_timing_repair = False
    if task.get("capability") == "timing-repair":
        try:
            validate_current_task_envelope(dict(task))
        except (PermissionError, TypeError, ValueError):
            pass
        else:
            is_valid_timing_repair = True
    if not is_valid_timing_repair:
        for key in ("affected_beat_ids", "issue_counts", "examples"):
            projected_constraints.pop(key, None)
    output_contract = task.get("output_contract")
    return {
        "task_id": task["task_id"],
        "capability": task["capability"],
        "inputs": list(task["inputs"]),
        "constraints": projected_constraints,
        **(
            {"output_contract": output_contract}
            if isinstance(output_contract, str)
            and len(output_contract) <= 128
            and SAFE_ID_RE.fullmatch(output_contract) is not None
            else {}
        ),
    }


def _coordinator_safe_approval_projection(approval: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: approval[key]
        for key in ("approval_id", "target_id", "scope", "decision")
        if isinstance(approval.get(key), str)
    }


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


def _load_candidate_tasks(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    tasks = []
    issues: list[dict[str, str]] = []
    tasks_root = project_path(root, "tasks")
    if not tasks_root.is_dir():
        return tasks, issues
    for path in sorted(tasks_root.glob("*.json")):
        try:
            tasks.append(_read_envelope(root, path.stem))
        except (OSError, PermissionError, TypeError, ValueError):
            issues.append(
                {
                    "code": "visual-media-context-invalid",
                    "task_id": path.stem,
                }
            )
    return tasks, issues


def _visual_recovery_issue(
    candidate: Mapping[str, Any], error: BaseException
) -> dict[str, str]:
    message = str(error).casefold()
    if "isolated child" in message:
        code = "visual-media-isolation-required"
    elif isinstance(error, PermissionError):
        code = "visual-media-input-forbidden"
    elif "legacy" in message and "visual" in message:
        code = "legacy-visual-task-blocked"
    else:
        code = "visual-media-context-invalid"
    issue = {"code": code}
    task_id = candidate.get("task_id")
    if isinstance(task_id, str):
        issue["task_id"] = task_id
    return issue


def _deduplicate_recovery_issues(
    issues: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for issue in issues:
        compact = {
            key: value
            for key, value in issue.items()
            if key in {"code", "task_id", "artifact_id", "path"}
            and isinstance(value, str)
        }
        identity = tuple(sorted(compact.items()))
        if compact and identity not in seen:
            seen.add(identity)
            normalized.append(compact)
    return sorted(normalized, key=lambda item: tuple(sorted(item.items())))


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


def _phase_position(phase: str) -> int:
    """Return a comparable position across historical and v3 recovery views."""
    if phase in V3_PHASES:
        return V3_PHASES.index(phase)
    if phase in PHASES:
        return PHASES.index(phase)
    return -1

"""Durable, isolated task dispatch records and bounded retry decisions."""

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from scripts.toolkit.artifacts import _artifact_paths_by_id, _read_valid_artifact
from scripts.toolkit.adapters import select_adapter
from scripts.toolkit.invalidation import invalidated_artifact_ids
from scripts.toolkit.image_context import (
    compact_image_result,
    validate_image_result_envelope,
    validate_image_task_constraints,
)
from scripts.toolkit.project_state import _state_lock
from scripts.toolkit.runtime_paths import project_path, project_root, storage_directory
from scripts.toolkit.visual_media_context import (
    SAFE_ID_RE,
    VISUAL_MEDIA_OPERATIONS,
    classify_visual_media_artifact,
    classify_visual_media_task,
    compact_visual_media_result,
    project_legacy_image_context,
    validate_declared_visual_media_inputs,
    validate_result_envelope,
    validate_visual_media_context,
    validate_visual_media_result_envelope,
    validate_visual_media_operation_outputs,
)
from scripts.toolkit.voice import validate_project_authoritative_voice_bundle


CLAIM_LEASE_SECONDS = 300.0
RESULT_STATUSES = {
    "blocked",
    "waiting_external",
    "waiting_user",
    "succeeded",
    "failed",
    "cancelled",
}
RETRYABLE_ERRORS = {"contract_error", "adapter_error"}
USER_ACTION_ERRORS = {"input_error", "direction_error"}
ENVELOPE_KEYS = {
    "task_id",
    "capability",
    "inputs",
    "adapter_preferences",
    "output_contract",
    "constraints",
}
RESULT_KEYS = {
    "task_id",
    "status",
    "inputs",
    "artifacts",
    "checks",
    "warnings",
    "worker_id",
    "claim_token",
    "error",
    "user_decision_request",
    "image_handoff",
    "visual_media_handoff",
}
TASK_CAPABILITIES = frozenset(
    {
        "project.manage",
        "narration.plan",
        "visual.preview",
        "voice.prepare",
        "storyboard.plan",
        "scene.produce",
        "motion.preview",
        "motion.produce",
        "timeline.assemble",
        "structure.validate",
        "review.package",
        "captions.produce",
        "representative-slice.produce",
    }
)
VOICE_TIMING_CAPABILITIES = frozenset(
    {
        "storyboard.plan",
        "scene.produce",
        "motion.preview",
        "motion.produce",
        "timeline.assemble",
        "captions.produce",
        "representative-slice.produce",
    }
)


def create_task(root: Path, envelope: dict[str, Any]) -> Path:
    """Persist one immutable, schema-shaped task envelope."""
    _validate_current_envelope(envelope)
    root = project_root(root)
    storage_directory(root, "events", create=True)
    with _state_lock(root, exclusive=False):
        artifacts = _effective_artifacts_by_id(root)
        if not voice_timing_input_is_current(envelope, artifacts, root=root):
            raise ValueError("task envelope requires the current real voice_timing_id")
        if not _artifact_inputs_are_current(envelope, artifacts):
            raise ValueError("task envelope requires current approved inputs")
        _authorize_declared_visual_media_inputs(envelope, artifacts)
        storage_directory(root, "tasks", create=True)
        destination = _task_path(root, envelope["task_id"])
        _publish_immutable_json(destination, _serialize_json(envelope))
        return destination


def voice_timing_input_is_current(
    envelope: dict[str, Any], artifacts: Any, *, root: Optional[Path] = None
) -> bool:
    """Return whether a timing consumer declares the exact current real timing.

    Structural envelope defects remain programmer errors. Project-content
    defects (missing, stale, estimated, or mismatched voice lineage) make the
    task ineligible instead of weakening the immutable input contract.
    """
    _validate_envelope_shape(envelope)
    if envelope["capability"] not in VOICE_TIMING_CAPABILITIES:
        return True
    if root is None:
        return False
    records = _artifact_values(artifacts)
    timing_id = envelope["constraints"].get("voice_timing_id")
    if (
        not isinstance(timing_id, str)
        or not timing_id
        or timing_id in {".", ".."}
        or "/" in timing_id
        or "\\" in timing_id
        or timing_id not in envelope["inputs"]
    ):
        return False
    bundle = validate_project_authoritative_voice_bundle(root, records)
    return (
        bundle["ok"]
        and bundle["voice_timing_id"] == timing_id
    )


def _artifact_values(artifacts: Any) -> list[dict[str, Any]]:
    values = artifacts.values() if isinstance(artifacts, Mapping) else artifacts
    if isinstance(values, (str, bytes)):
        raise ValueError("artifacts must be a collection")
    try:
        records = list(values)
    except TypeError as error:
        raise ValueError("artifacts must be a collection") from error
    if not all(isinstance(item, Mapping) for item in records):
        raise ValueError("artifacts must contain objects")
    return [dict(item) for item in records]


def claim_task(root: Path, task_id: str, worker_id: str) -> dict[str, str]:
    """Exclusively assign a task and return its completion authority."""
    root = project_root(root)
    storage_directory(root, "tasks", create=True)
    _require_safe_id(task_id, "task_id")
    _require_nonempty_string(worker_id, "worker_id")
    if not _task_path(root, task_id).is_file():
        raise ValueError(f"task does not exist: {task_id}")
    if _result_path(root, task_id).exists() or _stale_result_path(root, task_id).exists():
        raise RuntimeError(f"task already reached a terminal result: {task_id}")

    lock = _claim_path(root, task_id)
    while True:
        token = uuid4().hex
        now = time.time()
        claim = {
            "task_id": task_id,
            "worker_id": worker_id,
            "claim_token": token,
            "pid": os.getpid(),
            "created_at": now,
            "lease_expires_at": now + CLAIM_LEASE_SECONDS,
        }
        try:
            _create_claim(lock, claim)
        except FileExistsError:
            if not _reclaim_claim(lock):
                raise RuntimeError(f"task already claimed: {task_id}") from None
            continue
        if _result_path(root, task_id).exists() or _stale_result_path(root, task_id).exists():
            _remove_claim_if_current(lock, token)
            raise RuntimeError(f"task already reached a terminal result: {task_id}")
        try:
            storage_directory(root, "events", create=True)
            with _state_lock(root, exclusive=False):
                envelope = _read_envelope(root, task_id)
                if not _task_inputs_are_current(
                    root, envelope, _effective_artifacts_by_id(root)
                ):
                    raise ValueError("task inputs are no longer current")
        except BaseException:
            _remove_claim_if_current(lock, token)
            raise
        return {"worker_id": worker_id, "claim_token": token}


def complete_task(root: Path, result: dict[str, Any]) -> str:
    """Atomically register a terminal success or resumable worker checkpoint."""
    root = project_root(root)
    storage_directory(root, "tasks")
    validate_result_envelope(result)
    _validate_result(result)
    task_id = result["task_id"]
    handle = _hold_claim(_claim_path(root, task_id))
    destination: Optional[Path] = None
    try:
        _require_current_claim(handle, result)
        envelope = _read_envelope(root, task_id)
        artifacts = _effective_artifacts_by_id(root)
        declared_classification = _authorize_declared_visual_media_inputs(
            envelope, artifacts
        )
        produced_artifacts = _validate_result_artifacts(envelope, result, artifacts)
        _validate_conditional_visual_media_result(
            envelope,
            result,
            produced_artifacts,
            artifacts,
            declared_classification,
        )
        if not _is_current_result(root, envelope, result):
            destination = _stale_result_path(root, task_id)
            status = "stale-result"
        elif result["status"] == "succeeded":
            destination = _result_path(root, task_id)
            status = "completed"
        else:
            destination = _status_path(root, task_id)
            status = "resumable"
        if destination.exists() and status != "resumable":
            if status == "stale-result":
                return status
            raise RuntimeError(f"task already completed: {task_id}")
        if status == "resumable":
            _replace_json(destination, _serialize_json(result))
        else:
            _publish_immutable_json(destination, _serialize_json(result))
            if status == "completed":
                _status_path(root, task_id).unlink(missing_ok=True)
        return status
    finally:
        if destination is not None and destination.exists():
            _release_claim(handle)
        os.close(handle[1])


def retry_decision(root: Path, task_id: str, result: dict[str, Any]) -> dict[str, str]:
    """Persist and return the next bounded retry action for one task failure.

    Adapter choices always come from the immutable task envelope. The ledger is
    updated under a task-local file lock so concurrent failure reports cannot
    reset attempt counts or re-enable a consumed fallback.
    """
    root = project_root(root)
    storage_directory(root, "tasks")
    _require_safe_id(task_id, "task_id")
    _validate_retry_result(result)
    envelope = _read_envelope(root, task_id)
    error = result["error"]
    if error in USER_ACTION_ERRORS:
        return {"action": "request-user-action", "reason": error}
    if error not in RETRYABLE_ERRORS:
        return {"action": "block", "reason": "non-retryable-error"}

    lock = _retry_lock_path(root, task_id)
    descriptor = _hold_retry_lock(lock)
    try:
        ledger = _read_retry_ledger(_retry_ledger_path(root, task_id), envelope)
        adapter = result.get("adapter", ledger["current_adapter"])
        if adapter not in envelope["adapter_preferences"]:
            raise ValueError("retry adapter must be declared by the task envelope")
        if adapter != ledger["current_adapter"]:
            raise ValueError("retry adapter does not match the active retry adapter")

        attempts = ledger["attempts"]
        if attempts.get(adapter, 0) >= 2:
            return {"action": "block", "reason": "retry-budget-exhausted"}
        attempts[adapter] = attempts.get(adapter, 0) + 1
        ledger["history"].append(
            {"adapter": adapter, "attempt": attempts[adapter], "error": error}
        )
        if attempts[adapter] < 2:
            decision = {"action": "retry", "adapter": adapter}
        elif ledger["fallback_used"]:
            decision = {"action": "block", "reason": "retry-budget-exhausted"}
        else:
            fallback = _compatible_retry_fallback(envelope, adapter)
            if fallback is None:
                decision = {"action": "block", "reason": "no-fallback-adapter"}
            else:
                ledger["fallback_used"] = True
                ledger["current_adapter"] = fallback
                decision = {"action": "switch-adapter", "adapter": fallback}
        _replace_json(_retry_ledger_path(root, task_id), _serialize_json(ledger))
        return decision
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def active_claim_task_ids(root: Path) -> list[str]:
    """Return live task claims after safely reclaiming dead-PID locks."""
    root = project_root(root)
    tasks_root = storage_directory(root, "tasks", create=True)
    locks_root = tasks_root / "locks"
    if locks_root.is_symlink():
        raise ValueError("task lock storage must not be a symlink")
    if not locks_root.is_dir():
        return []
    active = []
    for path in sorted(locks_root.glob("*.lock")):
        if path.is_symlink():
            raise ValueError(f"task lock storage must not contain symlinks: {path.name}")
        task_id = path.name[: -len(".lock")]
        _require_safe_id(task_id, "task_id")
        while path.exists():
            if not _reclaim_claim(path):
                active.append(task_id)
                break
    return active


def _is_current_result(root: Path, envelope: dict[str, Any], result: dict[str, Any]) -> bool:
    if result["inputs"] != envelope["inputs"]:
        return False
    return _task_inputs_are_current(root, envelope, _effective_artifacts_by_id(root))


def _task_inputs_are_current(
    root: Path,
    envelope: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> bool:
    if not voice_timing_input_is_current(envelope, artifacts, root=root):
        return False
    if not _artifact_inputs_are_current(envelope, artifacts):
        return False
    _authorize_declared_visual_media_inputs(envelope, artifacts)
    return True


def _authorize_declared_visual_media_inputs(
    envelope: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> str:
    validate_declared_visual_media_inputs(envelope, artifacts)
    classification = classify_visual_media_task(envelope, artifacts)
    constraints = envelope["constraints"]
    is_legacy = (
        "image_operation" in constraints or "image_context" in constraints
    )
    if (
        classification == "visual"
        and not is_legacy
        and constraints.get("execution_context") != "isolated-child-agent"
    ):
        raise ValueError("visual media task requires an isolated child agent")
    return classification


def authorize_declared_visual_media_task(
    envelope: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> str:
    """Public shared scope/isolation authorization for readiness and lifecycle."""
    return _authorize_declared_visual_media_inputs(envelope, artifacts)


def _artifact_inputs_are_current(
    envelope: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> bool:
    for artifact_id in envelope["inputs"]:
        artifact = artifacts.get(artifact_id)
        if artifact is None or artifact["status"] != "approved":
            return False
        if _has_newer_approved_lineage(artifact, artifacts):
            return False
    return True


def _effective_artifacts_by_id(root: Path) -> dict[str, dict[str, Any]]:
    artifacts = _artifacts_by_id(root / "artifacts")
    invalidated = invalidated_artifact_ids(root)
    return {
        artifact_id: (
            {**artifact, "status": "stale"}
            if artifact_id in invalidated
            else artifact
        )
        for artifact_id, artifact in artifacts.items()
    }


def _validate_result_artifacts(
    envelope: dict[str, Any],
    result: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Require every claimed output to be a persisted artifact of the declared contract."""
    if result["status"] == "succeeded" and not result["artifacts"]:
        raise ValueError("a succeeded task must return at least one artifact")
    returned: list[dict[str, Any]] = []
    for artifact_id in result["artifacts"]:
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise ValueError(f"task result artifact does not exist: {artifact_id}")
        if artifact.get("output_contract") != envelope["output_contract"]:
            raise ValueError(
                f"task result artifact {artifact_id} does not satisfy "
                f"{envelope['output_contract']}"
            )
        if result["status"] == "succeeded":
            if artifact["status"] != "approved" or _has_newer_approved_lineage(
                artifact, artifacts
            ):
                raise ValueError(
                    f"task result artifact {artifact_id} must be current approved output"
                )
        elif artifact["status"] not in {"draft", "approved"}:
            raise ValueError(
                f"resumable task result artifact {artifact_id} must be draft or approved"
            )
        classify_visual_media_artifact(artifact)
        returned.append(artifact)
    return returned


def _compatible_retry_fallback(
    envelope: dict[str, Any], current_adapter: str
) -> Optional[str]:
    """Reuse initial routing predicates to choose the selected manifest fallback."""
    manifests_root = Path(__file__).parents[2] / "registries" / "adapters"
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(manifests_root.glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid packaged adapter manifest: {path}") from error
        if not isinstance(manifest, dict) or manifest.get("id") != path.stem:
            raise ValueError(f"invalid packaged adapter manifest: {path}")
        manifests[path.stem] = manifest
    current = manifests.get(current_adapter)
    if current is None:
        raise ValueError("retry adapter is not a packaged adapter")

    constraints = envelope["constraints"]
    routing_keys = {
        "accepted_contract",
        "contract",
        "editable",
        "format",
        "installed_skills",
        "output",
        "overlay",
        "required_output",
    }
    requirements = {
        key: constraints[key]
        for key in routing_keys
        if key in constraints
    }
    requirements["adapter_preferences"] = list(envelope["adapter_preferences"])
    requirements["preferred_adapter"] = current_adapter
    if "installed_skills" not in requirements:
        requirements["installed_skills"] = [
            manifests[adapter_id]["installed_skill"]
            for adapter_id in envelope["adapter_preferences"]
            if adapter_id in manifests
        ]
    if not ({"output", "required_output"} & requirements.keys()):
        output_contract = envelope["output_contract"]
        if any(output_contract in manifest.get("outputs", []) for manifest in manifests.values()):
            requirements["output"] = output_contract

    selected = select_adapter(envelope["capability"], requirements, manifests)
    fallback = selected["fallback"]
    return None if fallback is None else fallback["id"]


def _has_newer_approved_lineage(
    artifact: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> bool:
    return any(
        candidate["type"] == artifact["type"]
        and candidate["status"] == "approved"
        and candidate["version"] > artifact["version"]
        and _is_descendant(candidate, artifact["artifact_id"], artifacts)
        for candidate in artifacts.values()
    )


def _is_descendant(
    candidate: dict[str, Any], ancestor_id: str, artifacts: dict[str, dict[str, Any]]
) -> bool:
    pending = list(candidate["parents"])
    seen = set()
    while pending:
        artifact_id = pending.pop()
        if artifact_id == ancestor_id:
            return True
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        parent = artifacts.get(artifact_id)
        if parent is not None:
            pending.extend(parent["parents"])
    return False


def _artifacts_by_id(artifacts_root: Path) -> dict[str, dict[str, Any]]:
    paths = _artifact_paths_by_id(artifacts_root)
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact_id, path in paths.items():
        artifact = _read_valid_artifact(path)
        if artifact is None:
            raise ValueError(f"invalid artifact metadata: {path}")
        artifacts[artifact_id] = artifact
    return artifacts


def _read_envelope(root: Path, task_id: str) -> dict[str, Any]:
    path = _task_path(root, task_id)
    if not path.is_file():
        raise ValueError(f"task does not exist: {task_id}")
    envelope = _read_json_object(path, "task envelope")
    _validate_persisted_envelope(envelope)
    if envelope["task_id"] != task_id:
        raise ValueError("persisted task_id does not match its requested task path")
    return envelope


def _claim_path(root: Path, task_id: str) -> Path:
    return project_path(root, Path("tasks") / "locks" / f"{task_id}.lock")


def _result_path(root: Path, task_id: str) -> Path:
    return project_path(root, Path("tasks") / "results" / f"{task_id}.json")


def _stale_result_path(root: Path, task_id: str) -> Path:
    return project_path(root, Path("tasks") / "stale-results" / f"{task_id}.json")


def _status_path(root: Path, task_id: str) -> Path:
    return project_path(root, Path("tasks") / "status" / f"{task_id}.json")


def _retry_ledger_path(root: Path, task_id: str) -> Path:
    return project_path(root, Path("tasks") / "retries" / f"{task_id}.json")


def _retry_lock_path(root: Path, task_id: str) -> Path:
    return project_path(root, Path("tasks") / "retry-locks" / f"{task_id}.lock")


def _task_path(root: Path, task_id: str) -> Path:
    _require_safe_id(task_id, "task_id")
    return project_path(root, Path("tasks") / f"{task_id}.json")


def _create_claim(path: Path, claim: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, _serialize_json(claim).encode("utf-8"))
        os.fsync(descriptor)
    except BaseException:
        if _is_current_path(path, descriptor):
            path.unlink(missing_ok=True)
        raise
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _hold_claim(path: Path) -> tuple[Path, int]:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        raise RuntimeError("task has no active claim") from None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except BaseException:
        os.close(descriptor)
        raise
    return path, descriptor


def _reclaim_claim(path: Path) -> bool:
    try:
        handle = _hold_claim_nonblocking(path)
    except FileNotFoundError:
        return True
    except BlockingIOError:
        return False
    try:
        if not _is_current_path(path, handle[1]):
            return True
        claim = _read_claim(handle[1])
        if claim is None or _pid_is_alive(claim["pid"]):
            return False
        path.unlink(missing_ok=True)
        return True
    finally:
        fcntl.flock(handle[1], fcntl.LOCK_UN)
        os.close(handle[1])


def _hold_claim_nonblocking(path: Path) -> tuple[Path, int]:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(descriptor)
        raise
    return path, descriptor


def _require_current_claim(handle: tuple[Path, int], result: dict[str, Any]) -> None:
    path, descriptor = handle
    if not _is_current_path(path, descriptor):
        raise RuntimeError("task claim was replaced")
    claim = _read_claim(descriptor)
    if claim is None:
        raise RuntimeError("task claim is invalid")
    if claim["task_id"] != result["task_id"]:
        raise RuntimeError("task claim belongs to another task")
    if (
        claim["worker_id"] != result["worker_id"]
        or claim["claim_token"] != result["claim_token"]
    ):
        raise RuntimeError("task result does not own the active claim")


def _release_claim(handle: tuple[Path, int]) -> None:
    path, descriptor = handle
    if _is_current_path(path, descriptor):
        path.unlink(missing_ok=True)


def _remove_claim_if_current(path: Path, token: str) -> None:
    try:
        handle = _hold_claim(path)
    except RuntimeError:
        return
    try:
        claim = _read_claim(handle[1])
        if claim is not None and claim["claim_token"] == token:
            _release_claim(handle)
    finally:
        os.close(handle[1])


def _read_claim(descriptor: int) -> Optional[dict[str, Any]]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        value = json.loads(os.read(descriptor, 65_537).decode("utf-8"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    required = {
        "task_id",
        "worker_id",
        "claim_token",
        "pid",
        "created_at",
        "lease_expires_at",
    }
    if set(value) != required:
        return None
    if not all(isinstance(value[key], str) and value[key] for key in required - {"pid", "created_at", "lease_expires_at"}):
        return None
    if isinstance(value["pid"], bool) or not isinstance(value["pid"], int) or value["pid"] < 1:
        return None
    for key in ("created_at", "lease_expires_at"):
        if isinstance(value[key], bool) or not isinstance(value[key], (int, float)):
            return None
    return value


def _hold_retry_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_retry_ledger(path: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {
            "task_id": envelope["task_id"],
            "current_adapter": envelope["adapter_preferences"][0],
            "fallback_used": False,
            "attempts": {},
            "history": [],
        }
    ledger = _read_json_object(path, "retry ledger")
    required = {"task_id", "current_adapter", "fallback_used", "attempts", "history"}
    if set(ledger) != required or ledger["task_id"] != envelope["task_id"]:
        raise ValueError("retry ledger is invalid")
    if ledger["current_adapter"] not in envelope["adapter_preferences"]:
        raise ValueError("retry ledger selects an undeclared adapter")
    if not isinstance(ledger["fallback_used"], bool):
        raise ValueError("retry ledger fallback_used must be boolean")
    if not isinstance(ledger["attempts"], dict) or not all(
        adapter in envelope["adapter_preferences"]
        and isinstance(attempt, int)
        and not isinstance(attempt, bool)
        and attempt >= 0
        for adapter, attempt in ledger["attempts"].items()
    ):
        raise ValueError("retry ledger attempts are invalid")
    if not isinstance(ledger["history"], list):
        raise ValueError("retry ledger history is invalid")
    return ledger


def _validate_envelope_shape(envelope: dict[str, Any]) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("task envelope must be an object")
    _reject_unknown_keys(envelope, ENVELOPE_KEYS, "task envelope")
    _require_keys(envelope, ENVELOPE_KEYS, "task envelope")
    _require_safe_id(envelope["task_id"], "task_id")
    for key in ("capability", "output_contract"):
        _require_nonempty_string(envelope[key], key)
    if envelope["capability"] not in TASK_CAPABILITIES:
        raise ValueError("task envelope capability is not recognized")
    _validate_id_list(envelope["inputs"], "inputs")
    _validate_adapters(envelope["adapter_preferences"])
    if not isinstance(envelope["constraints"], dict):
        raise ValueError("constraints must be an object")


def _validate_current_envelope(envelope: dict[str, Any]) -> None:
    """Validate a newly minted envelope without granting deprecated authority."""
    _validate_envelope_shape(envelope)
    constraints = envelope["constraints"]
    if "visual_operation" in constraints:
        raise ValueError("legacy visual authority is read-only")
    if {"image_operation", "image_context"} & constraints.keys():
        raise ValueError("legacy image authority is read-only")
    validate_image_task_constraints(constraints)
    _validate_current_visual_operation_subset(envelope)


def validate_current_task_envelope(envelope: dict[str, Any]) -> None:
    """Validate one current in-memory candidate without legacy compatibility."""
    _validate_current_envelope(envelope)


def validate_persisted_task_envelope(envelope: dict[str, Any]) -> None:
    """Validate immutable current or explicitly supported legacy task authority."""
    _validate_persisted_envelope(envelope)


def _validate_persisted_envelope(envelope: dict[str, Any]) -> None:
    """Validate current records or project already-persisted legacy image records."""
    _validate_envelope_shape(envelope)
    constraints = envelope["constraints"]
    has_current = bool(
        {"visual_media_operation", "visual_media_context"} & constraints.keys()
    )
    has_legacy = bool({"image_operation", "image_context"} & constraints.keys())
    if has_current and (has_legacy or "visual_operation" in constraints):
        raise ValueError("task must not mix visual media and legacy image authority")
    if has_current:
        _validate_current_visual_operation_subset(envelope)
    validate_image_task_constraints(
        constraints,
        capability=(
            envelope["capability"]
            if has_legacy
            or (envelope["capability"] == "structure.validate" and not has_current)
            else None
        ),
    )


def _validate_current_visual_operation_subset(envelope: dict[str, Any]) -> None:
    constraints = envelope["constraints"]
    operation = constraints.get("visual_media_operation")
    if operation not in VISUAL_MEDIA_OPERATIONS:
        raise ValueError("task requires a recognized visual_media_operation")
    if operation == "none":
        if "visual_media_context" in constraints:
            raise ValueError("visual_media_operation none must not include context")
        if (
            "execution_context" in constraints
            and constraints["execution_context"] != "isolated-child-agent"
        ):
            raise ValueError("execution_context is not recognized")
    else:
        if "visual_media_context" not in constraints:
            raise ValueError("visual media operation requires visual_media_context")
        validate_visual_media_context(constraints["visual_media_context"])
        if constraints.get("execution_context") != "isolated-child-agent":
            raise ValueError("visual media task requires an isolated child agent")
    if (
        envelope["capability"] == "structure.validate"
        and operation
        not in {"none", "image-inspect"}
    ):
        raise ValueError(
            "structure.validate visual_media_operation must be none or image-inspect"
        )


def _validate_result(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ValueError("task result must be an object")
    _reject_unknown_keys(result, RESULT_KEYS, "task result")
    _require_keys(
        result,
        ("task_id", "status", "inputs", "artifacts", "checks", "warnings", "worker_id", "claim_token"),
        "task result",
    )
    _require_safe_id(result["task_id"], "task_id")
    if result["status"] not in RESULT_STATUSES:
        raise ValueError("task result status is not recognized")
    for key in ("inputs", "artifacts", "checks", "warnings"):
        _validate_string_list(result[key], key)
    for key in ("worker_id", "claim_token"):
        _require_nonempty_string(result[key], key)
    for key in ("error", "user_decision_request"):
        if key in result:
            _require_nonempty_string(result[key], key)


def _validate_conditional_visual_media_result(
    envelope: dict[str, Any],
    result: dict[str, Any],
    produced_artifacts: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    declared_classification: str,
) -> None:
    constraints = envelope["constraints"]
    has_legacy = "image_operation" in constraints or "image_context" in constraints
    has_image_handoff = "image_handoff" in result
    has_visual_handoff = "visual_media_handoff" in result
    image_handoff = result.get("image_handoff")
    visual_handoff = result.get("visual_media_handoff")
    if has_image_handoff and has_visual_handoff:
        raise ValueError("task result must not mix image_handoff and visual_media_handoff")

    completed_classification = classify_visual_media_task(
        envelope, artifacts, produced_artifacts
    )
    if declared_classification == "non-visual" and completed_classification == "visual":
        raise ValueError("non-visual task cannot return visual media artifacts")

    registered_paths = [artifact["path"] for artifact in produced_artifacts]
    produced_kinds = [
        classify_visual_media_artifact(artifact) for artifact in produced_artifacts
    ]
    if has_legacy:
        image_context = project_legacy_image_context(envelope)
        if image_context is None:
            if any(kind != "non-visual" for kind in produced_kinds):
                raise ValueError(
                    "legacy non-image task cannot return visual media artifacts"
                )
            if has_image_handoff or has_visual_handoff:
                raise ValueError("non-image legacy task result cannot contain a handoff")
            return
        if (
            result["status"] == "succeeded"
            and constraints.get("image_operation") == "generate"
            and "image" not in produced_kinds
        ):
            raise ValueError("generate must return at least one image artifact")
        if any(kind not in {"image", "non-visual"} for kind in produced_kinds):
            raise ValueError("legacy image task cannot return non-image visual media")
        if has_visual_handoff:
            raise ValueError("legacy image task result must use image_handoff")
        if not has_image_handoff:
            raise ValueError("legacy image task result requires image_handoff")
        legacy_context = validate_image_task_constraints(
            constraints, capability=envelope["capability"]
        )
        if legacy_context is None:
            raise ValueError("legacy visual task has no provable image context")
        validate_image_result_envelope(legacy_context, result)
        compact = compact_image_result(legacy_context, image_handoff)
        if compact.get("artifact_ids", []) != result["artifacts"]:
            raise ValueError("image_handoff artifact_ids must match result artifacts")
        if "status" in compact and compact["status"] != result["status"]:
            raise ValueError("image_handoff status must match task result status")
        if compact.get("paths", []) != registered_paths:
            raise ValueError("image_handoff contains an undeclared artifact path")
        return

    if declared_classification == "non-visual":
        if has_image_handoff or has_visual_handoff:
            raise ValueError("non-visual task result cannot contain a visual media handoff")
        return
    if has_image_handoff:
        raise ValueError("new visual media task result must use visual_media_handoff")
    context = validate_visual_media_context(constraints.get("visual_media_context"))
    validate_visual_media_result_envelope(context, result)
    compact = compact_visual_media_result(context, visual_handoff)
    validate_visual_media_operation_outputs(
        constraints.get("visual_media_operation"),
        produced_artifacts,
        compact,
        status=result["status"],
    )
    if compact["artifact_ids"] != result["artifacts"]:
        raise ValueError("visual_media_handoff artifact_ids must match result artifacts")
    if compact["paths"] != registered_paths:
        raise ValueError("visual_media_handoff contains an undeclared artifact path")


def _validate_retry_result(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ValueError("retry result must be an object")
    _reject_unknown_keys(result, {"error", "adapter"}, "retry result")
    _require_keys(result, ("error",), "retry result")
    _require_nonempty_string(result["error"], "error")
    if "adapter" in result:
        _require_nonempty_string(result["adapter"], "adapter")


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown keys: {', '.join(sorted(unknown))}")


def _require_keys(value: dict[str, Any], required: Any, label: str) -> None:
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"{label} is missing required keys: {', '.join(sorted(missing))}")


def _validate_id_list(value: Any, label: str) -> None:
    _validate_string_list(value, label)
    for item in value:
        _require_safe_id(item, label)


def _validate_string_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")


def _validate_adapters(adapters: Any) -> None:
    _validate_string_list(adapters, "adapter_preferences")
    if not adapters:
        raise ValueError("adapter_preferences must not be empty")


def _require_nonempty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")


def _require_safe_id(value: Any, label: str) -> None:
    _require_nonempty_string(value, label)
    if len(value) > 128 or SAFE_ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe single path component")


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _is_current_path(path: Path, descriptor: int) -> bool:
    try:
        return os.stat(path).st_ino == os.fstat(descriptor).st_ino
    except FileNotFoundError:
        return False


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _serialize_json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":")) + "\n"


def _publish_immutable_json(destination: Path, payload: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as stream:
            stream.write(payload)
            temporary_path = Path(stream.name)
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _replace_json(destination: Path, payload: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, delete=False
    ) as stream:
        stream.write(payload)
        temporary_path = Path(stream.name)
    temporary_path.replace(destination)

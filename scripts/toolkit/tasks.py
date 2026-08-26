"""Durable, isolated task dispatch records and bounded retry decisions."""

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from scripts.toolkit.artifacts import _artifact_paths_by_id, _read_valid_artifact
from scripts.toolkit.invalidation import invalidated_artifact_ids


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
}


def create_task(root: Path, envelope: dict[str, Any]) -> Path:
    """Persist one immutable, schema-shaped task envelope."""
    _validate_envelope(envelope)
    destination = _task_path(Path(root), envelope["task_id"])
    _publish_immutable_json(destination, _serialize_json(envelope))
    return destination


def claim_task(root: Path, task_id: str, worker_id: str) -> dict[str, str]:
    """Exclusively assign a task and return its completion authority."""
    root = Path(root)
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
        return {"worker_id": worker_id, "claim_token": token}


def complete_task(root: Path, result: dict[str, Any]) -> str:
    """Atomically validate and register an owner-authorized worker result."""
    root = Path(root)
    _validate_result(result)
    task_id = result["task_id"]
    handle = _hold_claim(_claim_path(root, task_id))
    destination: Optional[Path] = None
    try:
        _require_current_claim(handle, result)
        envelope = _read_envelope(root, task_id)
        if _is_current_result(root, envelope, result):
            destination = _result_path(root, task_id)
            status = "completed"
        else:
            destination = _stale_result_path(root, task_id)
            status = "stale-result"
        if destination.exists():
            if status == "stale-result":
                return status
            raise RuntimeError(f"task already completed: {task_id}")
        _publish_immutable_json(destination, _serialize_json(result))
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
    root = Path(root)
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
            fallback = next(
                (
                    candidate
                    for candidate in envelope["adapter_preferences"]
                    if candidate != adapter
                ),
                None,
            )
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
    locks_root = Path(root) / "tasks" / "locks"
    if not locks_root.is_dir():
        return []
    active = []
    for path in sorted(locks_root.glob("*.lock")):
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
    invalidated = invalidated_artifact_ids(root)
    artifacts = _artifacts_by_id(root / "artifacts")
    for artifact_id in envelope["inputs"]:
        artifact = artifacts.get(artifact_id)
        if (
            artifact is None
            or artifact["status"] != "approved"
            or artifact_id in invalidated
        ):
            return False
        if _has_newer_approved_lineage(artifact, artifacts):
            return False
    return True


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
    _validate_envelope(envelope)
    return envelope


def _claim_path(root: Path, task_id: str) -> Path:
    return root / "tasks" / "locks" / f"{task_id}.lock"


def _result_path(root: Path, task_id: str) -> Path:
    return root / "tasks" / "results" / f"{task_id}.json"


def _stale_result_path(root: Path, task_id: str) -> Path:
    return root / "tasks" / "stale-results" / f"{task_id}.json"


def _retry_ledger_path(root: Path, task_id: str) -> Path:
    return root / "tasks" / "retries" / f"{task_id}.json"


def _retry_lock_path(root: Path, task_id: str) -> Path:
    return root / "tasks" / "retry-locks" / f"{task_id}.lock"


def _task_path(root: Path, task_id: str) -> Path:
    _require_safe_id(task_id, "task_id")
    return root / "tasks" / f"{task_id}.json"


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


def _validate_envelope(envelope: dict[str, Any]) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("task envelope must be an object")
    _reject_unknown_keys(envelope, ENVELOPE_KEYS, "task envelope")
    _require_keys(envelope, ENVELOPE_KEYS, "task envelope")
    _require_safe_id(envelope["task_id"], "task_id")
    for key in ("capability", "output_contract"):
        _require_nonempty_string(envelope[key], key)
    _validate_id_list(envelope["inputs"], "inputs")
    _validate_adapters(envelope["adapter_preferences"])
    if not isinstance(envelope["constraints"], dict):
        raise ValueError("constraints must be an object")


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
    if value in {".", ".."} or "/" in value or "\\" in value:
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

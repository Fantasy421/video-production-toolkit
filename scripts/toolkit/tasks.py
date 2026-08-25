"""Durable, isolated task dispatch records and bounded retry decisions."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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


def create_task(root: Path, envelope: dict[str, Any]) -> Path:
    """Persist an immutable task envelope at its stable task-ID path."""
    _validate_envelope(envelope)
    destination = _task_path(Path(root), envelope["task_id"])
    _publish_json(destination, _serialize_json(envelope))
    return destination


def claim_task(root: Path, task_id: str, worker_id: str) -> None:
    """Exclusively assign one persisted task to one worker until completion."""
    root = Path(root)
    _require_safe_id(task_id, "task_id")
    _require_nonempty_string(worker_id, "worker_id")
    if not _task_path(root, task_id).is_file():
        raise ValueError(f"task does not exist: {task_id}")

    lock = root / "tasks" / "locks" / f"{task_id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock.open("x", encoding="utf-8") as stream:
            json.dump({"task_id": task_id, "worker_id": worker_id}, stream, separators=(",", ":"))
            stream.write("\n")
    except FileExistsError:
        raise RuntimeError(f"task already claimed: {task_id}") from None


def complete_task(root: Path, result: dict[str, Any]) -> str:
    """Register a current result, or retain an obsolete result for diagnosis."""
    root = Path(root)
    _validate_result(result)
    task_id = result["task_id"]
    envelope_path = _task_path(root, task_id)
    if not envelope_path.is_file():
        raise ValueError(f"task does not exist: {task_id}")
    envelope = _read_json_object(envelope_path, "task envelope")
    _validate_envelope(envelope)

    destination = root / "tasks" / "results" / f"{task_id}.json"
    if _is_current_result(root, envelope, result):
        _publish_json(destination, _serialize_json(result))
        _release_claim(root, task_id)
        return "completed"

    stale_destination = root / "tasks" / "stale-results" / f"{task_id}.json"
    _publish_json(stale_destination, _serialize_json(result))
    _release_claim(root, task_id)
    return "stale-result"


def retry_decision(
    task: dict[str, Any], result: dict[str, Any], adapters: list[str]
) -> dict[str, str]:
    """Return the only permitted next action for a classified task failure."""
    if not isinstance(task, dict) or not isinstance(result, dict):
        raise ValueError("task and result must be objects")
    _validate_adapters(adapters)
    error = result.get("error")
    if error in USER_ACTION_ERRORS:
        return {"action": "request-user-action", "reason": error}
    if error not in RETRYABLE_ERRORS:
        return {"action": "block", "reason": "non-retryable-error"}

    attempt = task.get("attempt", 0)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise ValueError("task attempt must be a non-negative integer")
    adapter = task.get("adapter", adapters[0])
    if adapter is not None and adapter not in adapters:
        raise ValueError("task adapter must be declared")

    if attempt < 2:
        return {"action": "retry", "adapter": adapter}
    if task.get("fallback_used") is True:
        return {"action": "block", "reason": "retry-budget-exhausted"}

    fallback = next((candidate for candidate in adapters if candidate != adapter), None)
    if fallback is None:
        return {"action": "block", "reason": "no-fallback-adapter"}
    return {"action": "switch-adapter", "adapter": fallback}


def _is_current_result(root: Path, envelope: dict[str, Any], result: dict[str, Any]) -> bool:
    if result["inputs"] != envelope["inputs"]:
        return False
    artifacts = _artifacts_by_id(root / "artifacts")
    return all(
        artifact_id in artifacts and artifacts[artifact_id].get("status") not in {"stale", "superseded", "invalid"}
        for artifact_id in envelope["inputs"]
    )


def _artifacts_by_id(artifacts_root: Path) -> dict[str, dict[str, Any]]:
    if not artifacts_root.is_dir():
        return {}
    artifacts: dict[str, dict[str, Any]] = {}
    for path in artifacts_root.glob("*/*.json"):
        try:
            artifact = _read_json_object(path, "artifact")
        except ValueError:
            continue
        artifact_id = artifact.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            artifacts[artifact_id] = artifact
    return artifacts


def _release_claim(root: Path, task_id: str) -> None:
    (root / "tasks" / "locks" / f"{task_id}.lock").unlink(missing_ok=True)


def _task_path(root: Path, task_id: str) -> Path:
    _require_safe_id(task_id, "task_id")
    return root / "tasks" / f"{task_id}.json"


def _validate_envelope(envelope: dict[str, Any]) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("task envelope must be an object")
    _require_keys(envelope, ("task_id", "capability", "inputs", "adapter_preferences", "output_contract", "constraints"), "task envelope")
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
    _require_keys(result, ("task_id", "status", "inputs", "artifacts", "checks", "warnings"), "task result")
    _require_safe_id(result["task_id"], "task_id")
    if result["status"] not in RESULT_STATUSES:
        raise ValueError("task result status is not recognized")
    for key in ("inputs", "artifacts", "checks", "warnings"):
        _validate_string_list(result[key], key)
    if "error" in result:
        _require_nonempty_string(result["error"], "error")
    if "user_decision_request" in result:
        _require_nonempty_string(result["user_decision_request"], "user_decision_request")


def _require_keys(value: dict[str, Any], required: tuple[str, ...], label: str) -> None:
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"{label} is missing required keys: {', '.join(missing)}")


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


def _serialize_json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":")) + "\n"


def _publish_json(destination: Path, payload: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
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

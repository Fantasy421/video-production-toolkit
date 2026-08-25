"""Durable immutable artifacts and user approvals for toolkit projects."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


ARTIFACT_REQUIRED_KEYS = (
    "artifact_id",
    "type",
    "version",
    "status",
    "parents",
    "path",
)
ARTIFACT_STATUSES = {"draft", "approved", "stale", "superseded", "invalid"}


def create_artifact(root: Path, artifact: dict[str, Any]) -> Path:
    """Persist one immutable artifact metadata record and return its path."""
    root = Path(root)
    _validate_artifact(artifact)
    payload = _serialize_json(artifact)
    artifacts_root = root / "artifacts"
    existing = _artifact_paths_by_id(artifacts_root)
    artifact_id = artifact["artifact_id"]
    if artifact_id in existing:
        raise FileExistsError(f"artifact already exists: {artifact_id}")

    missing_parents = [parent for parent in artifact["parents"] if parent not in existing]
    if missing_parents:
        raise ValueError(f"artifact parents do not exist: {', '.join(missing_parents)}")

    destination = artifacts_root / artifact["type"] / f"{artifact_id}.json"
    _require_within(artifacts_root, destination)
    lock = _acquire_artifact_lock(artifacts_root, artifact_id)
    try:
        _publish_json(destination, payload)
    finally:
        lock.unlink(missing_ok=True)
    return destination


def approve_artifact(root: Path, target_id: str, scope: str, notes: str) -> str:
    """Create a durable approval record for an existing artifact."""
    root = Path(root)
    if target_id not in _artifact_paths_by_id(root / "artifacts"):
        raise ValueError(f"approval target does not exist: {target_id}")
    if not isinstance(scope, str) or not scope:
        raise ValueError("approval scope must be a non-empty string")
    if not isinstance(notes, str):
        raise ValueError("approval notes must be a string")

    approval_id = f"approval-{uuid4().hex}"
    approval_path = root / "approvals" / f"{approval_id}.json"
    approval = {
        "approval_id": approval_id,
        "target_id": target_id,
        "scope": scope,
        "notes": notes,
    }
    payload = _serialize_json(approval)
    _require_within(root / "approvals", approval_path)
    _publish_json(approval_path, payload)
    return approval_id


def _artifact_paths_by_id(artifacts_root: Path) -> dict[str, Path]:
    if not artifacts_root.is_dir():
        return {}
    paths: dict[str, Path] = {}
    for path in artifacts_root.glob("*/*.json"):
        artifact = _read_valid_artifact(path)
        if artifact is None:
            continue
        artifact_id = artifact["artifact_id"]
        if artifact_id in paths:
            raise ValueError(f"duplicate artifact id in project: {artifact_id}")
        paths[artifact_id] = path
    return paths


def _read_valid_artifact(path: Path) -> Optional[dict[str, Any]]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        _validate_artifact(artifact)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if path.name != f"{artifact['artifact_id']}.json":
        return None
    return artifact


def _acquire_artifact_lock(artifacts_root: Path, artifact_id: str) -> Path:
    lock = artifacts_root / ".locks" / f"{artifact_id}.json"
    payload = _serialize_json({"pid": os.getpid(), "timestamp": time.time()})
    while True:
        try:
            _publish_json(lock, payload)
            return lock
        except FileExistsError:
            if artifact_id in _artifact_paths_by_id(artifacts_root):
                raise FileExistsError(f"artifact already exists: {artifact_id}") from None
            owner = _read_lock(lock)
            if owner is None or _pid_is_alive(owner["pid"]):
                raise FileExistsError(f"artifact is locked: {artifact_id}") from None
            lock.unlink(missing_ok=True)


def _read_lock(lock: Path) -> Optional[dict[str, Any]]:
    try:
        owner = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(owner, dict):
        return None
    pid = owner.get("pid")
    timestamp = owner.get("timestamp")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return None
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    return owner


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


def _publish_json(destination: Path, payload: str) -> None:
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


def _require_within(root: Path, destination: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    try:
        destination.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("artifact destination must remain inside its storage directory") from None


def _validate_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")
    missing = [key for key in ARTIFACT_REQUIRED_KEYS if key not in artifact]
    if missing:
        raise ValueError(f"artifact is missing required keys: {', '.join(missing)}")
    for key in ("artifact_id", "type", "path"):
        value = artifact[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"artifact {key} must be a non-empty string")
    if not _is_safe_component(artifact["artifact_id"]) or not _is_safe_component(artifact["type"]):
        raise ValueError("artifact_id and type must be safe single path components")
    if isinstance(artifact["version"], bool) or not isinstance(artifact["version"], int) or artifact["version"] < 1:
        raise ValueError("artifact version must be a positive integer")
    if artifact["status"] not in ARTIFACT_STATUSES:
        raise ValueError("artifact status is not recognized")
    if not isinstance(artifact["parents"], list) or not all(
        isinstance(parent, str) and parent for parent in artifact["parents"]
    ):
        raise ValueError("artifact parents must be a list of non-empty IDs")
    if len(set(artifact["parents"])) != len(artifact["parents"]):
        raise ValueError("artifact parents must not contain duplicates")


def _is_safe_component(value: str) -> bool:
    return value not in {".", ".."} and "/" not in value and "\\" not in value

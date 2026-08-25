"""Durable immutable artifacts and user approvals for toolkit projects."""

import json
from pathlib import Path
from typing import Any
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
    """Persist one immutable artifact metadata record and return its path.

    Every declared parent must already be durable in the project, so a stored
    record never contains a dangling DAG edge.
    """
    root = Path(root)
    _validate_artifact(artifact)
    artifacts_root = root / "artifacts"
    existing = _artifact_paths_by_id(artifacts_root)
    artifact_id = artifact["artifact_id"]
    if artifact_id in existing:
        raise FileExistsError(f"artifact already exists: {artifact_id}")

    missing_parents = [parent for parent in artifact["parents"] if parent not in existing]
    if missing_parents:
        raise ValueError(f"artifact parents do not exist: {', '.join(missing_parents)}")

    destination = artifacts_root / artifact["type"] / f"{artifact_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(artifact, stream, separators=(",", ":"))
        stream.write("\n")
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
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval = {
        "approval_id": approval_id,
        "target_id": target_id,
        "scope": scope,
        "notes": notes,
    }
    with approval_path.open("x", encoding="utf-8") as stream:
        json.dump(approval, stream, separators=(",", ":"))
        stream.write("\n")
    return approval_id


def _artifact_paths_by_id(artifacts_root: Path) -> dict[str, Path]:
    if not artifacts_root.is_dir():
        return {}
    paths: dict[str, Path] = {}
    for path in artifacts_root.glob("*/*.json"):
        artifact_id = path.stem
        if artifact_id in paths:
            raise ValueError(f"duplicate artifact id in project: {artifact_id}")
        paths[artifact_id] = path
    return paths


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
    if "/" in artifact["artifact_id"] or "/" in artifact["type"]:
        raise ValueError("artifact_id and type cannot contain path separators")
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

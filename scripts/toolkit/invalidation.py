"""Deterministic invalidation over immutable artifact dependency graphs."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Union

from .runtime_paths import project_path, project_root


def invalidate_descendants(
    artifacts: Union[Iterable[dict[str, Any]], Mapping[str, dict[str, Any]]],
    changed_id: str,
    rules: Mapping[str, list[str]],
) -> set[str]:
    """Return descendants made stale by *changed_id* under explicit type rules.

    Traversal follows recorded parent IDs only.  The rule lookup is made from
    the changed artifact's type, never from an artifact ID or its filename.
    """
    records = list(artifacts.values()) if isinstance(artifacts, Mapping) else list(artifacts)
    by_id = {artifact["artifact_id"]: artifact for artifact in records}
    if len(by_id) != len(records):
        raise ValueError("artifact IDs must be unique")
    if changed_id not in by_id:
        raise ValueError(f"changed artifact does not exist: {changed_id}")

    reverse_edges: dict[str, list[str]] = {artifact_id: [] for artifact_id in by_id}
    for artifact in records:
        for parent_id in artifact.get("parents", []):
            if parent_id in reverse_edges:
                reverse_edges[parent_id].append(artifact["artifact_id"])

    descendants: set[str] = set()
    pending = list(reverse_edges[changed_id])
    while pending:
        artifact_id = pending.pop()
        if artifact_id in descendants:
            continue
        descendants.add(artifact_id)
        pending.extend(reverse_edges[artifact_id])

    allowed_types = set(rules.get(by_id[changed_id]["type"], []))
    return {artifact_id for artifact_id in descendants if by_id[artifact_id]["type"] in allowed_types}


def invalidated_artifact_ids(root: Path) -> set[str]:
    """Project immutable metadata through append-only invalidation events."""
    root = project_root(root)
    events_root = root / "events"
    if events_root.is_symlink():
        raise ValueError("event storage must not be a symlink")
    if not events_root.exists():
        return set()
    event_log = project_path(root, "events/events.jsonl")
    if not event_log.is_file():
        return set()
    invalidated: set[str] = set()
    for number, line in enumerate(event_log.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid project event at line {number}") from error
        if event.get("event") != "artifacts.invalidated":
            continue
        artifact_ids = event.get("artifact_ids")
        if not isinstance(artifact_ids, list) or any(
            not isinstance(item, str) or not item for item in artifact_ids
        ):
            raise ValueError(f"invalid artifact invalidation event at line {number}")
        invalidated.update(artifact_ids)
    return invalidated

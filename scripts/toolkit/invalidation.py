"""Deterministic invalidation over immutable artifact dependency graphs."""

from collections.abc import Iterable, Mapping
from typing import Any, Union


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

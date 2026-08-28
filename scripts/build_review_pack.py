#!/usr/bin/env python3
"""Relay a verified visual-media handoff into a compact user review manifest."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


MAX_RELAY_ITEMS = 8
MEDIA_FIELDS = (
    "kind",
    "format",
    "mime_type",
    "width",
    "height",
    "duration_ms",
    "fps",
    "readiness",
    "checksum",
    "sha256",
)
ISSUE_FIELDS = ("code", "artifact_id", "message", "severity")


def build_review_pack(root: Path, handoff: Mapping[str, Any]) -> dict[str, Any]:
    """Return compact review metadata without accessing the preview path.

    ``handoff`` has already passed visual-media validation.  ``root`` is kept
    in the public interface for callers, but is intentionally not used: this
    relay must not resolve, open, probe, or otherwise dereference visual media.
    """
    del root
    if not isinstance(handoff, Mapping):
        raise ValueError("visual media handoff must be an object")

    preview_path = handoff.get("review_preview_path")
    if preview_path is not None and not isinstance(preview_path, str):
        raise ValueError("review handoff permits zero or one review preview path")

    return {
        "artifact_ids": _string_list(handoff.get("artifact_ids")),
        "paths": _string_list(handoff.get("paths")),
        "media": _compact_mapping(handoff.get("media"), MEDIA_FIELDS),
        "checks": _string_list(handoff.get("checks"), limit=MAX_RELAY_ITEMS),
        "issues": _issues(handoff.get("issues")),
        "summary": handoff.get("summary") if isinstance(handoff.get("summary"), str) else None,
        "review_preview_path": preview_path,
        "decision_status": "waiting_user",
        "subjective_acceptance_authority": "user",
        "allowed_user_decisions": ["approve", "reject", "request_revision"],
    }


def _string_list(value: Any, *, limit: int = MAX_RELAY_ITEMS) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)][:limit]


def _compact_mapping(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        field: value[field]
        for field in fields
        if field in value
        and (isinstance(value[field], (str, int, float, bool)) or value[field] is None)
    }


def _issues(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        _compact_mapping(issue, ISSUE_FIELDS)
        for issue in value[:MAX_RELAY_ITEMS]
        if isinstance(issue, Mapping)
    ]

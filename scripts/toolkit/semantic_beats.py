"""Metadata-only helpers for freezing approved, untimed semantic beat anchors.

Stage A records an approved editorial decision.  It deliberately has no voice
timing or millisecond fields; formal timing belongs to the later real-audio
stage.  The helpers return fresh dictionaries so callers cannot mutate input
objects through a shared reference.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .artifacts import TIMING_CARRIERS, validate_artifact_record


_SAFE_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"
)
_RECORD_FIELDS = frozenset({"narration_id", "beats"})
_CANDIDATE_FIELDS = frozenset(
    {
        "beat_id",
        "text_ref",
        "keyword",
        "intent",
        "priority",
        "preferred_carrier",
    }
)
_BEAT_FIELDS = _CANDIDATE_FIELDS | frozenset({"approval_provenance"})
_APPROVAL_FIELDS = frozenset({"decision", "provenance", "keywords"})
_PRIORITIES = frozenset({"primary", "secondary"})
_MAX_BEATS = 512


def validate_semantic_beats(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a fresh Stage A semantic-beat planning record.

    This intentionally validates the compact planning payload rather than
    authoring an Artifact.  The artifact writer supplies lifecycle fields and
    then enforces the authoritative closed ``semantic-beats`` schema.
    """
    if not isinstance(record, Mapping):
        raise ValueError("semantic beats record must be an object")
    normalized = dict(record)
    if set(normalized) != _RECORD_FIELDS:
        raise ValueError("semantic beats record has unknown or missing fields")
    _require_safe_id(normalized["narration_id"], "narration_id")
    beats = normalized["beats"]
    if not isinstance(beats, list) or not 1 <= len(beats) <= _MAX_BEATS:
        raise ValueError("semantic beats requires a bounded non-empty beat list")

    seen: set[str] = set()
    frozen: list[dict[str, Any]] = []
    for beat in beats:
        normalized_beat = _validate_beat(beat)
        beat_id = normalized_beat["beat_id"]
        if beat_id in seen:
            raise ValueError("semantic beats must have unique beat IDs")
        seen.add(beat_id)
        frozen.append(normalized_beat)
    return {"narration_id": normalized["narration_id"], "beats": frozen}


def freeze_semantic_beats(
    narration_id: str,
    candidates: Any,
    approval: Any,
) -> dict[str, Any]:
    """Freeze user-approved candidate anchors as an untimed Stage A record."""
    _require_safe_id(narration_id, "narration_id")
    normalized_approval = _validate_approval(approval)
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= _MAX_BEATS:
        raise ValueError("semantic beat candidates must be a bounded non-empty list")

    approved_keywords = set(normalized_approval["keywords"])
    beats: list[dict[str, Any]] = []
    for candidate in candidates:
        normalized_candidate = _validate_candidate(candidate)
        keyword = normalized_candidate["keyword"]
        if keyword not in approved_keywords:
            raise ValueError("approval does not include every semantic beat keyword")
        beats.append(
            {
                "beat_id": normalized_candidate["beat_id"],
                "text_ref": normalized_candidate["text_ref"],
                "keyword": keyword,
                "intent": normalized_candidate["intent"],
                "priority": normalized_candidate["priority"],
                "preferred_carrier": normalized_candidate["preferred_carrier"],
                "approval_provenance": normalized_approval["provenance"],
            }
        )
    return validate_semantic_beats({"narration_id": narration_id, "beats": beats})


def project_legacy_timed_beats(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a defensive view of a readable legacy timing-linked projection.

    New Stage A records never contain ``voice_timing_id``.  The legacy form is
    accepted only when the authoritative Artifact runtime accepts it as the
    read-only compatibility projection; it is not transformed or re-authored.
    """
    if not isinstance(record, Mapping):
        raise ValueError("legacy semantic beats record must be an object")
    if record.get("type") != "semantic-beats" or "voice_timing_id" not in record:
        return None
    normalized = dict(record)
    validate_artifact_record(normalized)
    return dict(normalized)


def _validate_beat(beat: Any) -> dict[str, Any]:
    if not isinstance(beat, Mapping) or set(beat) != _BEAT_FIELDS:
        raise ValueError("semantic beats must be closed records")
    normalized = dict(beat)
    _require_safe_id(normalized["beat_id"], "beat_id")
    _require_text(normalized["text_ref"], "text_ref", 256)
    _require_text(normalized["keyword"], "keyword", 256)
    _require_text(normalized["intent"], "intent", 128)
    _require_text(normalized["approval_provenance"], "approval_provenance", 500)
    if normalized["priority"] not in _PRIORITIES:
        raise ValueError("semantic beat priority is not recognized")
    if normalized["preferred_carrier"] not in TIMING_CARRIERS:
        raise ValueError("semantic beat carrier is not recognized")
    return normalized


def _validate_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_FIELDS:
        raise ValueError("semantic beat candidates must be closed editable records")
    normalized = dict(candidate)
    _require_safe_id(normalized["beat_id"], "beat_id")
    _require_text(normalized["text_ref"], "text_ref", 256)
    _require_text(normalized["keyword"], "keyword", 256)
    _require_text(normalized["intent"], "intent", 128)
    if normalized["priority"] not in _PRIORITIES:
        raise ValueError("semantic beat priority is not recognized")
    if normalized["preferred_carrier"] not in TIMING_CARRIERS:
        raise ValueError("semantic beat carrier is not recognized")
    return normalized


def _validate_approval(approval: Any) -> dict[str, Any]:
    if not isinstance(approval, Mapping):
        raise ValueError("approval must be an object")
    normalized = dict(approval)
    if set(normalized) != _APPROVAL_FIELDS:
        raise ValueError("approval has unknown or missing fields")
    if normalized["decision"] != "approved":
        raise ValueError("approval decision must be approved")
    provenance = normalized["provenance"]
    _require_text(provenance, "approval provenance", 500)
    if not provenance.startswith("user:"):
        raise ValueError("approval provenance must be user-scoped")
    keywords = normalized["keywords"]
    if not isinstance(keywords, list) or not 1 <= len(keywords) <= _MAX_BEATS:
        raise ValueError("approval keywords must be a bounded non-empty list")
    for keyword in keywords:
        _require_text(keyword, "approval keyword", 256)
    if len(keywords) != len(set(keywords)):
        raise ValueError("approval keywords must be unique")
    return {"decision": "approved", "provenance": provenance, "keywords": list(keywords)}


def _require_safe_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise ValueError(f"semantic beats {label} must be a safe ID")


def _require_text(value: Any, label: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"semantic beats {label} must be bounded non-empty text")

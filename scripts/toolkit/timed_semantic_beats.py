"""Bind frozen semantic decisions to compact, real voice-timing metadata.

This module intentionally receives only metadata.  It neither opens narration
media nor carries the timing transcript forward: sentence bounds and the
approved word anchors are reduced to one timing row per frozen beat.
"""

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from .artifacts import validate_artifact_record
from .semantic_beats import validate_semantic_beats


_RECORD_FIELDS = frozenset({"voice_timing_id", "timing_kind", "beats"})
_BEAT_FIELDS = frozenset(
    {
        "beat_id",
        "speech_start_ms",
        "speech_end_ms",
        "keyword_start_ms",
        "keyword_end_ms",
        "emphasis_ms",
        "visual_window_ms",
        "approved_anchor_commitment",
    }
)
_ANCHOR_FIELDS = frozenset({"beat_id", "keyword", "start_ms", "end_ms"})
_MAX_BEATS = 512
_MAX_MS = 36_000_000
_ENTRY_BEFORE_MS = 120
_EXIT_AFTER_MS = 200


def bind_semantic_beats(
    semantic_beats: Mapping[str, Any],
    voice_timing: Mapping[str, Any],
    keyword_anchors: Any,
) -> dict[str, Any]:
    """Return timing rows for exactly the frozen approved semantic beats.

    Segment timing provides the default sentence-level speech range.  Word
    anchors are accepted only when they name one frozen beat and repeat that
    beat's approved keyword exactly.  The compact return value deliberately
    omits segment text and all Stage-A creative fields.
    """
    semantic = validate_semantic_beats(semantic_beats)
    timing, segments = _current_real_timing(
        voice_timing, require_keyword_anchors=True
    )
    if keyword_anchors != timing["keyword_anchors"]:
        raise ValueError("keyword anchors must come from authoritative voice timing")
    anchors = _approved_anchors(keyword_anchors, semantic)
    beats: list[dict[str, Any]] = []
    for beat in semantic["beats"]:
        anchor = anchors[beat["beat_id"]]
        segment = _spoken_segment(anchor, segments)
        start = anchor["start_ms"]
        end = anchor["end_ms"]
        beats.append(
            {
                "beat_id": beat["beat_id"],
                "speech_start_ms": segment["start_ms"],
                "speech_end_ms": segment["end_ms"],
                "keyword_start_ms": start,
                "keyword_end_ms": end,
                "emphasis_ms": start + (end - start) // 2,
                "visual_window_ms": [start - _ENTRY_BEFORE_MS, end + _EXIT_AFTER_MS],
                "approved_anchor_commitment": _anchor_commitment(
                    semantic, beat["beat_id"], start, end
                ),
            }
        )
    record = {
        "voice_timing_id": timing["artifact_id"],
        "timing_kind": "real",
        "beats": beats,
    }
    return validate_timed_semantic_beats(record, semantic, timing)


def validate_timed_semantic_beats(
    record: Mapping[str, Any],
    semantic_beats: Mapping[str, Any],
    voice_timing: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and defensively copy a compact timed-semantic-beat record."""
    semantic = validate_semantic_beats(semantic_beats)
    timing, segments = _current_real_timing(
        voice_timing, require_keyword_anchors=True
    )
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
        raise ValueError("timed semantic beats must be a closed record")
    normalized = dict(record)
    if normalized["voice_timing_id"] != timing["artifact_id"]:
        raise ValueError("timed semantic beats voice timing lineage does not match")
    if normalized["timing_kind"] != "real":
        raise ValueError("timed semantic beats requires real timing")
    beats = normalized["beats"]
    if not isinstance(beats, list) or not 1 <= len(beats) <= _MAX_BEATS:
        raise ValueError("timed semantic beats requires a bounded non-empty beat list")
    by_id = {beat["beat_id"]: beat for beat in semantic["beats"]}
    if len(by_id) != len(beats):
        raise ValueError("timed semantic beats must preserve frozen beat IDs")
    frozen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in beats:
        if not isinstance(item, Mapping) or set(item) != _BEAT_FIELDS:
            raise ValueError("timed semantic beats must be closed records")
        beat = dict(item)
        beat_id = beat["beat_id"]
        if not isinstance(beat_id, str) or beat_id not in by_id or beat_id in seen:
            raise ValueError("timed semantic beats must preserve frozen beat IDs")
        seen.add(beat_id)
        _validate_beat(beat, semantic, segments, timing["duration_ms"])
        frozen.append(beat)
    return {
        "voice_timing_id": timing["artifact_id"],
        "timing_kind": "real",
        "beats": frozen,
    }


def _current_real_timing(
    voice_timing: Mapping[str, Any], *, require_keyword_anchors: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(voice_timing, Mapping):
        raise ValueError("voice timing must be an artifact record")
    timing = dict(voice_timing)
    try:
        validate_artifact_record(timing)
    except ValueError as error:
        raise ValueError("voice timing must be a structurally valid artifact") from error
    if (
        timing.get("type") != "voice-timing"
        or timing.get("timing_kind") != "real"
        or timing.get("status") != "approved"
    ):
        raise ValueError("voice timing must be real and current")
    if require_keyword_anchors and "keyword_anchors" not in timing:
        raise ValueError("voice timing requires authoritative keyword anchors")
    segments = timing["segments"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("voice timing requires spoken segments")
    normalized = [dict(segment) for segment in segments]
    previous_end = 0
    for segment in normalized:
        start = segment["start_ms"]
        end = segment["end_ms"]
        if start < previous_end or end > timing["duration_ms"]:
            raise ValueError("voice timing segments must be ordered and bounded")
        previous_end = end
    return timing, normalized


def _approved_anchors(keyword_anchors: Any, semantic: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(keyword_anchors, list) or len(keyword_anchors) != len(semantic["beats"]):
        raise ValueError("keyword anchor set must match approved beats")
    approved = {beat["beat_id"]: beat["keyword"] for beat in semantic["beats"]}
    anchors: dict[str, dict[str, Any]] = {}
    for item in keyword_anchors:
        if not isinstance(item, Mapping) or set(item) != _ANCHOR_FIELDS:
            raise ValueError("keyword anchors must be closed approved records")
        anchor = dict(item)
        beat_id = anchor["beat_id"]
        if beat_id not in approved or beat_id in anchors or anchor["keyword"] != approved[beat_id]:
            raise ValueError("keyword anchors must name only approved frozen keywords")
        for field in ("start_ms", "end_ms"):
            value = anchor[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_MS:
                raise ValueError("keyword anchor milliseconds must be bounded integers")
        if anchor["start_ms"] >= anchor["end_ms"]:
            raise ValueError("keyword anchor milliseconds must be ordered")
        anchors[beat_id] = anchor
    return anchors


def _spoken_segment(anchor: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        segment
        for segment in segments
        if segment["start_ms"] <= anchor["start_ms"] < anchor["end_ms"] <= segment["end_ms"]
    ]
    if len(matches) != 1:
        raise ValueError("keyword anchor must remain inside one spoken segment")
    return matches[0]


def _validate_beat(
    beat: dict[str, Any],
    semantic: dict[str, Any],
    segments: list[dict[str, Any]],
    duration_ms: int,
) -> None:
    for field in _BEAT_FIELDS - {"beat_id", "visual_window_ms", "approved_anchor_commitment"}:
        value = beat[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_MS:
            raise ValueError("timed semantic beat milliseconds must be bounded integers")
    window = beat["visual_window_ms"]
    if (
        not isinstance(window, list)
        or len(window) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in window)
        or not 0 <= window[0] < window[1] <= duration_ms
    ):
        raise ValueError("timed semantic beat visual window must be ordered and bounded")
    segment = _spoken_segment(
        {"start_ms": beat["keyword_start_ms"], "end_ms": beat["keyword_end_ms"]}, segments
    )
    if (
        beat["speech_start_ms"] != segment["start_ms"]
        or beat["speech_end_ms"] != segment["end_ms"]
        or not beat["keyword_start_ms"] <= beat["emphasis_ms"] <= beat["keyword_end_ms"]
    ):
        raise ValueError("timed semantic beat does not match its spoken timing")
    if not (
        _ENTRY_BEFORE_MS <= beat["keyword_start_ms"] - window[0] <= 250
        and 200 <= window[1] - beat["keyword_end_ms"] <= 500
    ):
        raise ValueError("timed semantic beat visual window is outside default bounds")
    if beat["approved_anchor_commitment"] != _anchor_commitment(
        semantic,
        beat["beat_id"],
        beat["keyword_start_ms"],
        beat["keyword_end_ms"],
    ):
        raise ValueError("timed semantic beat anchor commitment does not match")


def _anchor_commitment(
    semantic: dict[str, Any], beat_id: str, start_ms: int, end_ms: int
) -> str:
    """Commit a persisted word range to one frozen, user-approved keyword."""
    beat = next(beat for beat in semantic["beats"] if beat["beat_id"] == beat_id)
    payload = {
        "approval_provenance": beat["approval_provenance"],
        "beat_id": beat_id,
        "end_ms": end_ms,
        "keyword": beat["keyword"],
        "narration_id": semantic["narration_id"],
        "start_ms": start_ms,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

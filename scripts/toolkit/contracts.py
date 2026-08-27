"""Canonical runtime validation for persisted production contracts."""

import re
from collections.abc import Mapping
from typing import Any, Optional


SCENE_CARRIERS = frozenset(
    {"a-roll", "b-roll", "scene", "demo", "motion-graphics", "evidence"}
)
SCENE_CONTRACT_REQUIRED_FIELDS = frozenset(
    {
        "scene_id",
        "voice_timing_id",
        "start_ms",
        "end_ms",
        "primary_carrier",
        "purpose",
    }
)
SCENE_CONTRACT_OPTIONAL_FIELDS = frozenset(
    {
        "secondary_layer",
        "new_character_baseline",
        "scene_image_generation",
        "generated_video",
        "captions",
    }
)
_SAFE_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_:-]*(?:\.[A-Za-z0-9][A-Za-z0-9_:-]*)*"
)


def validate_scene_contract(
    value: Mapping[str, Any],
    voice_timing: Optional[Mapping[str, Any]] = None,
    *,
    allow_legacy_unresolved_timing: bool = False,
) -> dict[str, Any]:
    """Return a normalized copy when *value* matches scene-contract-v1 exactly."""
    if not isinstance(value, Mapping):
        raise ValueError("scene contract must be an object")
    fields = set(value)
    missing = SCENE_CONTRACT_REQUIRED_FIELDS - fields
    unknown = fields - SCENE_CONTRACT_REQUIRED_FIELDS - SCENE_CONTRACT_OPTIONAL_FIELDS
    if missing or unknown:
        raise ValueError("scene contract does not match scene-contract-v1")
    scene_id = value["scene_id"]
    if not isinstance(scene_id, str) or _SAFE_ID.fullmatch(scene_id) is None:
        raise ValueError("scene_id must be a safe artifact token")
    voice_timing_id = value["voice_timing_id"]
    if (
        not isinstance(voice_timing_id, str)
        or _SAFE_ID.fullmatch(voice_timing_id) is None
    ):
        raise ValueError("voice_timing_id must be a safe artifact token")
    start, end = value["start_ms"], value["end_ms"]
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise ValueError("scene contract requires positive millisecond timing")
    if value["primary_carrier"] not in SCENE_CARRIERS:
        raise ValueError("scene contract has an unknown primary carrier")
    for field in ("purpose", "secondary_layer"):
        if field in value and (
            not isinstance(value[field], str) or not value[field].strip()
        ):
            raise ValueError(f"scene contract {field} must be a non-empty string")
    for field in (
        "new_character_baseline",
        "scene_image_generation",
        "generated_video",
        "captions",
    ):
        if field in value and not isinstance(value[field], bool):
            raise ValueError(f"scene contract {field} must be a boolean")
    if voice_timing is None:
        if not allow_legacy_unresolved_timing:
            raise ValueError("current scene contract requires its real voice timing artifact")
    else:
        _validate_scene_interval_against_voice_timing(
            voice_timing, voice_timing_id, start, end
        )
    return dict(value)


def _validate_scene_interval_against_voice_timing(
    timing: Mapping[str, Any],
    voice_timing_id: str,
    start: int,
    end: int,
) -> None:
    if not isinstance(timing, Mapping):
        raise ValueError("scene contract requires a real voice timing artifact")
    if timing.get("artifact_id") != voice_timing_id:
        raise ValueError("scene contract must reference the exact voice timing artifact")
    if (
        timing.get("type") != "voice-timing"
        or timing.get("status") != "approved"
        or timing.get("timing_kind") != "real"
    ):
        raise ValueError("scene contract requires approved real voice timing")
    voiceover_id = timing.get("voiceover_id")
    if (
        not isinstance(voiceover_id, str)
        or _SAFE_ID.fullmatch(voiceover_id) is None
        or timing.get("parents") != [voiceover_id]
    ):
        raise ValueError("scene contract voice timing has invalid voiceover lineage")
    duration = timing.get("duration_ms")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int)
        or duration < 1
        or end > duration
    ):
        raise ValueError("scene contract interval exceeds real voice timing")
    segments = timing.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("scene contract requires a covered spoken timing segment")
    normalized_segments: list[tuple[int, int]] = []
    previous_end = 0
    for segment in segments:
        if not isinstance(segment, Mapping) or set(segment) != {
            "start_ms",
            "end_ms",
            "text",
        }:
            raise ValueError("scene contract requires valid real timing segments")
        segment_start = segment.get("start_ms")
        segment_end = segment.get("end_ms")
        text = segment.get("text")
        if (
            isinstance(segment_start, bool)
            or isinstance(segment_end, bool)
            or not isinstance(segment_start, int)
            or not isinstance(segment_end, int)
            or segment_start < previous_end
            or segment_start < 0
            or segment_end <= segment_start
            or segment_end > duration
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError("scene contract requires valid real timing segments")
        normalized_segments.append((segment_start, segment_end))
        previous_end = segment_end
    starts_in_speech = any(
        segment_start <= start < segment_end
        for segment_start, segment_end in normalized_segments
    )
    ends_in_speech = any(
        segment_start < end <= segment_end
        for segment_start, segment_end in normalized_segments
    )
    if not starts_in_speech or not ends_in_speech:
        raise ValueError("scene contract interval must end within a spoken timing segment")

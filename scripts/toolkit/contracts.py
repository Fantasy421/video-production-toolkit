"""Canonical runtime validation for persisted production contracts."""

import re
from collections.abc import Iterable, Mapping
from typing import Any, Optional

from .artifacts import validate_artifact_record
from .voice import validate_authoritative_voice_bundle


SCENE_CARRIERS = frozenset(
    {"a-roll", "b-roll", "scene", "demo", "motion-graphics", "evidence"}
)
SCENE_CONTRACT_REQUIRED_FIELDS = frozenset(
    {
        "scene_id",
        "voice_timing_id",
        "timed_semantic_beats_id",
        "scene_timing_contracts_id",
        "beat_ids",
        "start_ms",
        "end_ms",
        "primary_carrier",
        "purpose",
    }
)
LEGACY_SCENE_CONTRACT_REQUIRED_FIELDS = frozenset(
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
    r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*"
)


def validate_scene_contract(
    value: Mapping[str, Any],
    voice_timing: Optional[Mapping[str, Any]] = None,
    *,
    allow_legacy_unresolved_timing: bool = False,
    artifacts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Return a normalized current Scene Contract or opted-in legacy record."""
    if not isinstance(value, Mapping):
        raise ValueError("scene contract must be an object")
    fields = set(value)
    is_current = bool(
        fields
        & {"timed_semantic_beats_id", "scene_timing_contracts_id", "beat_ids"}
    )
    required = (
        SCENE_CONTRACT_REQUIRED_FIELDS
        if is_current
        else LEGACY_SCENE_CONTRACT_REQUIRED_FIELDS
    )
    missing = required - fields
    unknown = fields - required - SCENE_CONTRACT_OPTIONAL_FIELDS
    if missing or unknown:
        raise ValueError("scene contract does not match scene-contract-v1")
    if not is_current and not allow_legacy_unresolved_timing:
        raise ValueError(
            "current scene contract requires timed semantic beats and scene timing contracts"
        )
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
    if is_current:
        _validate_current_scene_lineage(value)
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
    if artifacts is None and (is_current or not allow_legacy_unresolved_timing):
        raise ValueError("current scene contract requires full artifact DAG context")
    if artifacts is not None:
        records = list(artifacts)
        bundle = validate_authoritative_voice_bundle(records)
        if not bundle["ok"] or bundle["voice_timing_id"] != voice_timing_id:
            raise ValueError("scene contract requires the authoritative voice timing")
        matches = [
            item for item in records if item.get("artifact_id") == voice_timing_id
        ]
        if len(matches) != 1:
            raise ValueError("scene contract requires one authoritative voice timing")
        voice_timing = matches[0]
        if is_current:
            _validate_scene_timing_artifact(value, records)
    if voice_timing is not None:
        _validate_scene_interval_against_voice_timing(
            voice_timing, voice_timing_id, start, end
        )
    return dict(value)


def _validate_current_scene_lineage(value: Mapping[str, Any]) -> None:
    for field in ("timed_semantic_beats_id", "scene_timing_contracts_id"):
        identifier = value[field]
        if not isinstance(identifier, str) or _SAFE_ID.fullmatch(identifier) is None:
            raise ValueError(f"scene contract {field} must be a safe artifact token")
    beat_ids = value["beat_ids"]
    if (
        not isinstance(beat_ids, list)
        or not 1 <= len(beat_ids) <= 512
        or any(
            not isinstance(beat_id, str) or _SAFE_ID.fullmatch(beat_id) is None
            for beat_id in beat_ids
        )
        or len(beat_ids) != len(set(beat_ids))
    ):
        raise ValueError("scene contract requires exact non-empty beat IDs")


def _validate_scene_timing_artifact(
    contract: Mapping[str, Any], records: list[Mapping[str, Any]]
) -> None:
    """Resolve and validate the complete current timing DAG for one scene."""
    from .scene_timing import validate_scene_timing_contracts

    timed_id = contract["timed_semantic_beats_id"]
    scene_timing_id = contract["scene_timing_contracts_id"]
    timed = [
        item
        for item in records
        if item.get("artifact_id") == timed_id
        and item.get("type") == "timed-semantic-beats"
        and item.get("status") == "approved"
        and item.get("timing_kind") == "real"
    ]
    scene_timing = [
        item
        for item in records
        if item.get("artifact_id") == scene_timing_id
        and item.get("type") == "scene-timing-contracts"
        and item.get("status") == "approved"
        and item.get("timed_semantic_beats_id") == timed_id
        and timed_id in item.get("parents", [])
    ]
    if len(timed) != 1 or len(scene_timing) != 1:
        raise ValueError("scene contract requires current timed semantic beats and scene timing contracts")
    timed_record = timed[0]
    semantic_id = timed_record.get("semantic_beats_id")
    voice_id = timed_record.get("voice_timing_id")
    semantic = [
        item
        for item in records
        if item.get("artifact_id") == semantic_id
        and item.get("type") == "semantic-beats"
        and item.get("status") == "approved"
    ]
    narration = [
        item
        for item in records
        if semantic
        and item.get("artifact_id") == semantic[0].get("narration_id")
        and item.get("type") == "narration"
        and item.get("status") == "approved"
    ]
    voice = [
        item
        for item in records
        if item.get("artifact_id") == voice_id
        and item.get("type") == "voice-timing"
        and item.get("status") == "approved"
        and item.get("timing_kind") == "real"
    ]
    if (
        voice_id != contract["voice_timing_id"]
        or not isinstance(semantic_id, str)
        or semantic_id not in timed_record.get("parents", [])
        or voice_id not in timed_record.get("parents", [])
        or len(semantic) != 1
        or len(voice) != 1
        or not isinstance(semantic[0].get("narration_id"), str)
        or semantic[0]["narration_id"] not in semantic[0].get("parents", [])
        or len(narration) != 1
    ):
        raise ValueError("scene contract requires exact timed semantic and voice lineage")
    try:
        validate_artifact_record(timed_record)
        validate_artifact_record(voice[0])
        validate_artifact_record(scene_timing[0])
    except ValueError as error:
        raise ValueError("scene contract requires valid timing artifact lineage") from error
    scene_record = {
        "timed_semantic_beats_id": scene_timing[0]["timed_semantic_beats_id"],
        "scenes": scene_timing[0]["scenes"],
    }
    try:
        validate_scene_timing_contracts(scene_record, timed_record)
    except ValueError as error:
        raise ValueError("scene contract requires a valid scene timing contract") from error
    matching_scenes = [
        scene
        for scene in scene_timing[0].get("scenes", [])
        if isinstance(scene, Mapping) and scene.get("scene_id") == contract["scene_id"]
    ]
    if len(matching_scenes) != 1:
        raise ValueError("scene contract beat IDs must exactly match its scene timing contract")
    timing_scene = matching_scenes[0]
    if (
        timing_scene.get("beat_ids") != contract["beat_ids"]
        or timing_scene.get("scene_window_ms") != [contract["start_ms"], contract["end_ms"]]
        or timing_scene.get("primary_carrier") != contract["primary_carrier"]
    ):
        raise ValueError("scene contract beat IDs must exactly match its scene timing contract")


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

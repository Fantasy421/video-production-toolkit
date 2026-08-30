"""Bind storyboard timing assignments to current approved timed semantic beats.

The module handles compact structural metadata only.  It deliberately does not
read media, transcript text, prompts, or any visual payload.
"""

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any

from .artifacts import validate_artifact_record
from .contracts import SCENE_CARRIERS


_RECORD_FIELDS = frozenset({"timed_semantic_beats_id", "scenes"})
_SCENE_FIELDS = frozenset(
    {
        "scene_id",
        "scene_window_ms",
        "beat_ids",
        "primary_carrier",
        "support_layer",
        "visual_window_ms",
    }
)
_MAX_SCENES = 512
_MAX_MS = 36_000_000
_SAFE_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*"
)


def build_scene_timing_contracts(
    timed_beats: Mapping[str, Any], assignments: Any
) -> dict[str, Any]:
    """Return one structural scene-timing record for the current timed beats.

    Every approved beat must be assigned exactly once.  An assignment remains
    bounded by the spoken time and approved visual window of every beat it
    carries; visual assignment stays a one-primary plus optional one-support
    decision.
    """
    timed = _current_timed_beats(timed_beats)
    record = {
        "timed_semantic_beats_id": timed["artifact_id"],
        "scenes": _copy_assignments(assignments),
    }
    return validate_scene_timing_contracts(record, timed)


def validate_scene_timing_contracts(
    record: Mapping[str, Any], timed_beats: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate and defensively copy a persisted structural timing record."""
    timed = _current_timed_beats(timed_beats)
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
        raise ValueError("scene timing contracts must be a closed record")
    if record["timed_semantic_beats_id"] != timed["artifact_id"]:
        raise ValueError("scene timing contracts lineage does not match timed beats")
    scenes = _copy_assignments(record["scenes"])
    if not 1 <= len(scenes) <= _MAX_SCENES:
        raise ValueError("scene timing contracts requires a bounded non-empty scene list")

    beats = timed["beats"]
    beat_positions = {beat["beat_id"]: index for index, beat in enumerate(beats)}
    beat_by_id = {beat["beat_id"]: beat for beat in beats}
    assigned_ids: list[str] = []
    scene_ids: set[str] = set()
    for scene in scenes:
        _validate_scene(scene, scene_ids, beat_positions, beat_by_id)
        assigned_ids.extend(scene["beat_ids"])
    if len(assigned_ids) != len(set(assigned_ids)) or set(assigned_ids) != set(beat_by_id):
        raise ValueError("scene timing contracts must assign every timed beat exactly once")
    return {
        "timed_semantic_beats_id": timed["artifact_id"],
        "scenes": scenes,
    }


def _current_timed_beats(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("timed semantic beats must be an artifact record")
    timed = dict(value)
    if timed.get("timing_kind") != "real":
        raise ValueError("scene timing contracts require current approved real timed beats")
    try:
        validate_artifact_record(timed)
    except ValueError as error:
        raise ValueError("timed semantic beats must be a structurally valid artifact") from error
    if (
        timed.get("type") != "timed-semantic-beats"
        or timed.get("status") != "approved"
    ):
        raise ValueError("scene timing contracts require current approved real timed beats")
    for beat in timed["beats"]:
        _validate_timed_beat(beat)
    return timed


def _validate_timed_beat(beat: Mapping[str, Any]) -> None:
    """Enforce intrinsic timing before deriving any scene-level boundaries."""
    speech_start = beat["speech_start_ms"]
    speech_end = beat["speech_end_ms"]
    keyword_start = beat["keyword_start_ms"]
    keyword_end = beat["keyword_end_ms"]
    emphasis = beat["emphasis_ms"]
    values = (speech_start, speech_end, keyword_start, keyword_end, emphasis)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("scene timing timed beat milliseconds must be bounded integers")
    if not (
        0 <= speech_start < speech_end <= _MAX_MS
        and speech_start <= keyword_start < keyword_end <= speech_end
        and keyword_start <= emphasis <= keyword_end
    ):
        raise ValueError("scene timing timed beat speech and keyword windows must be ordered and contained")
    beat_window = _window(beat["visual_window_ms"], "timed beat visual window")
    if not _contains(beat_window, [keyword_start, keyword_end]):
        raise ValueError("scene timing timed beat visual window must contain its keyword window")


def _copy_assignments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("scene timing assignments must be a list")
    copied: list[dict[str, Any]] = []
    for scene in value:
        if not isinstance(scene, Mapping) or set(scene) != _SCENE_FIELDS:
            raise ValueError("scene timing assignments must be closed records")
        # Detach nested lists from caller-owned assignment data.
        copied.append(deepcopy(dict(scene)))
    return copied


def _validate_scene(
    scene: dict[str, Any],
    scene_ids: set[str],
    beat_positions: dict[str, int],
    beat_by_id: dict[str, dict[str, Any]],
) -> None:
    scene_id = scene["scene_id"]
    if not _safe_id(scene_id) or scene_id in scene_ids:
        raise ValueError("scene timing contracts require unique safe scene IDs")
    scene_ids.add(scene_id)
    beat_ids = scene["beat_ids"]
    if (
        not isinstance(beat_ids, list)
        or not beat_ids
        or len(beat_ids) > _MAX_SCENES
        or any(not _safe_id(beat_id) or beat_id not in beat_positions for beat_id in beat_ids)
        or len(beat_ids) != len(set(beat_ids))
    ):
        raise ValueError("scene timing contracts require known unique beat IDs")
    positions = [beat_positions[beat_id] for beat_id in beat_ids]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        raise ValueError("scene timing contracts require ordered consecutive beat IDs")

    if (
        not isinstance(scene["primary_carrier"], str)
        or scene["primary_carrier"] not in SCENE_CARRIERS
    ):
        raise ValueError("scene timing contracts require exactly one registered primary carrier")
    support = scene["support_layer"]
    if support is not None and (
        not isinstance(support, str) or not support.strip() or len(support) > 128
    ):
        raise ValueError("scene timing contracts permit at most one support layer")

    scene_window = _window(scene["scene_window_ms"], "scene window")
    visual_window = _window(scene["visual_window_ms"], "visual window")
    if not _contains(scene_window, visual_window):
        raise ValueError("scene timing visual window must remain inside its scene window")
    assigned = [beat_by_id[beat_id] for beat_id in beat_ids]
    spoken_window = [
        min(beat["speech_start_ms"] for beat in assigned),
        max(beat["speech_end_ms"] for beat in assigned),
    ]
    if not _contains(spoken_window, scene_window):
        raise ValueError("scene timing scene window must remain inside spoken boundaries")
    for beat in assigned:
        beat_window = _window(beat["visual_window_ms"], "timed beat visual window")
        if not _contains(scene_window, beat_window):
            raise ValueError("scene timing beat visual window crosses its scene boundary")
        keyword_window = [beat["keyword_start_ms"], beat["keyword_end_ms"]]
        if not _contains(scene_window, keyword_window):
            raise ValueError("scene timing keyword window crosses its scene boundary")
        if not _contains(visual_window, beat_window):
            raise ValueError("scene timing visual window must contain every beat visual window")


def _window(value: Any, label: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or not 0 <= value[0] < value[1] <= _MAX_MS
    ):
        raise ValueError(f"scene timing {label} must be an ordered bounded window")
    return value


def _contains(outer: list[int], inner: list[int]) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def _safe_id(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 128:
        return False
    return _SAFE_ID.fullmatch(value) is not None

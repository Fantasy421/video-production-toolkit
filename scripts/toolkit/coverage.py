"""Pure semantic-coverage checks for immutable shot or scene artifacts."""

import re
from typing import Any, Optional


MEANINGFUL_KINDS = {
    "establish",
    "cause",
    "compare",
    "accumulate",
    "turn",
    "result",
    "evidence",
    "stable-evidence",
    "action",
    "object-change",
    "framing-change",
    "b-roll",
    "scene",
    "demo",
    "motion-graphics",
    "formula",
    "ui",
}
DECORATIVE_KINDS = {
    "breathing",
    "floating",
    "decorative-zoom",
    "caption-enter",
    "idle-loop",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def evaluate_coverage(shots: list[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic issue payloads without reading or writing artifacts.

    The caller owns artifact lookup and persistence.  Each shot may name its
    source ``artifact_id``; otherwise its ``shot_id`` is used as the issue
    owner.  Timing and readable-hold thresholds come from the shot contract.
    """
    if not isinstance(shots, list):
        raise ValueError("shots must be a list")

    issues: list[dict[str, Any]] = []
    uncovered_intervals: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        shot_issues, shot_intervals = _evaluate_shot(shot, index)
        issues.extend(shot_issues)
        uncovered_intervals.extend(shot_intervals)
    return {
        "schema_version": 1,
        "issues": issues,
        "uncovered_intervals": uncovered_intervals,
    }


def _evaluate_shot(
    shot: dict[str, Any], index: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(shot, dict):
        raise ValueError(f"shot {index} must be an object")
    shot_id = _safe_id(shot.get("shot_id"), f"shot {index} shot_id")
    artifact_id = _safe_id(shot.get("artifact_id", shot_id), f"shot {shot_id} artifact_id")
    duration_ms = _positive_integer(shot.get("duration_ms"), f"shot {shot_id} duration_ms")
    beats = _semantic_beats(shot.get("semantic_beats", []), shot_id, duration_ms)
    states = _visual_states(shot.get("visual_states", []), shot_id, duration_ms, set(beats))

    base = {"severity": "error", "artifact_id": artifact_id, "shot_id": shot_id}
    meaningful = [state for state in states if state["coverage_role"] == "meaningful"]
    issues: list[dict[str, Any]] = []
    if duration_ms >= 6_000 and len(beats) >= 2 and not meaningful:
        issues.append({"code": "six-second-static-multi-beat", **base})
    if states and all(state["coverage_role"] == "decorative" for state in states):
        issues.append({"code": "decorative-only", **base})

    covered_beats = {
        beat_id
        for state in meaningful
        for beat_id in state["beats"]
    }
    for beat_id in beats:
        if beat_id not in covered_beats:
            issues.append({"code": "uncovered-beat", **base, "beat_id": beat_id})

    issues.extend(_readable_hold_issues(shot, duration_ms, base))

    intervals = [(state["start_ms"], state["end_ms"]) for state in meaningful]
    gaps = _uncovered_intervals(duration_ms, intervals)
    interval_issues = [
        {
            "code": "uncovered-interval",
            **base,
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
        for start_ms, end_ms in gaps
    ]
    issues.extend(interval_issues)
    return issues, interval_issues


def _semantic_beats(
    raw_beats: Any, shot_id: str, duration_ms: int
) -> list[str]:
    if not isinstance(raw_beats, list):
        raise ValueError(f"shot {shot_id} semantic_beats must be a list")
    beats: list[str] = []
    for index, beat in enumerate(raw_beats):
        if isinstance(beat, str):
            beat_id = _label_id(beat, f"shot {shot_id} semantic beat {index}")
        elif isinstance(beat, dict):
            beat_id = _label_id(
                beat.get("beat_id"), f"shot {shot_id} semantic beat {index} beat_id"
            )
            if "start_ms" in beat or "end_ms" in beat:
                _interval(beat, duration_ms, f"shot {shot_id} semantic beat interval")
        else:
            raise ValueError(f"shot {shot_id} semantic beat {index} must be a string or object")
        if beat_id in beats:
            raise ValueError(f"shot {shot_id} semantic beat IDs must be unique")
        beats.append(beat_id)
    return beats


def _visual_states(
    raw_states: Any, shot_id: str, duration_ms: int, beat_ids: set[str]
) -> list[dict[str, Any]]:
    if not isinstance(raw_states, list):
        raise ValueError(f"shot {shot_id} visual_states must be a list")
    states: list[dict[str, Any]] = []
    for index, state in enumerate(raw_states):
        if not isinstance(state, dict):
            raise ValueError(f"shot {shot_id} visual state {index} must be an object")
        kind = state.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"shot {shot_id} visual state kind must be a non-empty string")
        start_ms, end_ms = _interval(
            state, duration_ms, f"shot {shot_id} visual state interval"
        )
        role = state.get("coverage_role")
        if role is None:
            if kind in MEANINGFUL_KINDS:
                role = "meaningful"
            elif kind in DECORATIVE_KINDS:
                role = "decorative"
            else:
                role = "neutral"
        if role not in {"meaningful", "decorative", "neutral"}:
            raise ValueError(f"shot {shot_id} visual state coverage_role is invalid")
        raw_state_beats = state.get("beats", [])
        if "beat" in state:
            if raw_state_beats:
                raise ValueError(f"shot {shot_id} visual state cannot declare beat and beats")
            raw_state_beats = [state["beat"]]
        if not isinstance(raw_state_beats, list):
            raise ValueError(f"shot {shot_id} visual state beats must be a list")
        state_beats = [
            _label_id(value, f"shot {shot_id} visual state beat")
            for value in raw_state_beats
        ]
        if len(state_beats) != len(set(state_beats)):
            raise ValueError(f"shot {shot_id} visual state beats must be unique")
        unknown = sorted(set(state_beats) - beat_ids)
        if unknown:
            raise ValueError(
                f"shot {shot_id} visual state references unknown beats: {', '.join(unknown)}"
            )
        states.append(
            {
                "kind": kind,
                "coverage_role": role,
                "beats": state_beats,
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
    return states


def _readable_hold_issues(
    shot: dict[str, Any], duration_ms: int, base: dict[str, Any]
) -> list[dict[str, Any]]:
    important_items = shot.get("important_items", [])
    readable_holds = shot.get("readable_holds", [])
    if not isinstance(important_items, list) or not isinstance(readable_holds, list):
        raise ValueError(f"shot {base['shot_id']} important_items and readable_holds must be lists")

    normalized_items: list[tuple[str, Optional[int]]] = []
    for index, item in enumerate(important_items):
        if isinstance(item, str):
            item_id = _label_id(item, f"shot {base['shot_id']} important item {index}")
            minimum = None
        elif isinstance(item, dict):
            item_id = _label_id(
                item.get("item_id"), f"shot {base['shot_id']} important item {index} item_id"
            )
            minimum = item.get("min_hold_ms")
            if minimum is not None:
                minimum = _positive_integer(
                    minimum, f"shot {base['shot_id']} important item min_hold_ms"
                )
        else:
            raise ValueError(f"shot {base['shot_id']} important item {index} is invalid")
        normalized_items.append((item_id, minimum))
    if len({item_id for item_id, _minimum in normalized_items}) != len(normalized_items):
        raise ValueError(f"shot {base['shot_id']} important item IDs must be unique")

    normalized_holds: list[tuple[Optional[str], Optional[int]]] = []
    for index, hold in enumerate(readable_holds):
        if isinstance(hold, str):
            normalized_holds.append(
                (_label_id(hold, f"shot {base['shot_id']} readable hold {index}"), None)
            )
            continue
        if not isinstance(hold, dict):
            raise ValueError(f"shot {base['shot_id']} readable hold {index} is invalid")
        raw_item_id = hold.get("item_id")
        item_id = (
            _label_id(raw_item_id, f"shot {base['shot_id']} readable hold item_id")
            if raw_item_id is not None
            else None
        )
        if "duration_ms" in hold:
            hold_duration = _positive_integer(
                hold["duration_ms"], f"shot {base['shot_id']} readable hold duration_ms"
            )
        else:
            start_ms, end_ms = _interval(
                hold, duration_ms, f"shot {base['shot_id']} readable hold interval"
            )
            hold_duration = end_ms - start_ms
        normalized_holds.append((item_id, hold_duration))

    issues: list[dict[str, Any]] = []
    for item_id, minimum in normalized_items:
        matching = [
            hold_duration
            for hold_item_id, hold_duration in normalized_holds
            if hold_item_id == item_id
            or (hold_item_id is None and len(normalized_items) == 1)
        ]
        if not matching:
            issues.append({"code": "missing-readable-hold", **base, "item_id": item_id})
            continue
        known_durations = [duration for duration in matching if duration is not None]
        if minimum is not None and (not known_durations or max(known_durations) < minimum):
            issues.append(
                {
                    "code": "short-readable-hold",
                    **base,
                    "item_id": item_id,
                    "required_ms": minimum,
                    "actual_ms": max(known_durations, default=0),
                }
            )
    return issues


def _uncovered_intervals(
    duration_ms: int, intervals: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    cursor = 0
    gaps: list[tuple[int, int]] = []
    for start_ms, end_ms in sorted(intervals):
        if start_ms > cursor:
            gaps.append((cursor, start_ms))
        cursor = max(cursor, end_ms)
    if cursor < duration_ms:
        gaps.append((cursor, duration_ms))
    return gaps


def _interval(value: dict[str, Any], duration_ms: int, label: str) -> tuple[int, int]:
    start_ms = _non_negative_integer(value.get("start_ms"), f"{label} start_ms")
    end_ms = _positive_integer(value.get("end_ms"), f"{label} end_ms")
    if start_ms >= end_ms or end_ms > duration_ms:
        raise ValueError(f"{label} must be ordered and contained by the shot")
    return start_ms, end_ms


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a safe non-empty ID")
    return value


def _label_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} must be a non-empty label")
    return value


def _non_negative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value

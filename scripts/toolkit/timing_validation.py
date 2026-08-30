"""Compact, deterministic validation for voice-timed visual beat rows.

The validator deliberately accepts a small structural projection of the timing
graph.  It does not accept (or need) narration, transcripts, paths, media,
motion source, or diagnostics.  Keep this module safe to run in the
coordinator: a result contains counts and no more than three Beat IDs per
issue code.
"""

from collections.abc import Iterable, Mapping
import re
from typing import Any, Callable

from .contracts import SCENE_CARRIERS


ISSUE_CODES = (
    "VOICE_TIMING_REQUIRED",
    "KEYWORD_ANCHOR_MISSING",
    "VISUAL_BEFORE_ALLOWED_WINDOW",
    "VISUAL_AFTER_ALLOWED_WINDOW",
    "BEAT_OUTSIDE_SCENE",
    "MULTIPLE_PRIMARY_CARRIERS",
    "SUPPORT_LAYER_OVERFLOW",
    "KEYWORD_EVENTS_TOO_CLOSE",
    "SCENE_TOO_SHORT",
    "STALE_VOICE_TIMING",
)

# The timing row is a closed projection.  Timing lineage fields are optional
# because the canonical scene row can be used when its parent DAG has already
# been checked; when supplied, they are checked too.
_ROW_FIELDS = frozenset(
    {
        "beat_id",
        "scene_id",
        "keyword_anchor_ms",
        "visual_window_ms",
        "scene_window_ms",
        "primary_carrier",
        "support_layer",
        "timing_kind",
        "voice_timing_status",
        "timing_status",
        "voice_timing_id",
        "current_voice_timing_id",
        "timed_semantic_beats_id",
        "current_timed_semantic_beats_id",
    }
)
_SAFE_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"
)
_MAX_MS = 36_000_000
_MAX_EXAMPLES = 3
_MIN_ENTRY_BEFORE_MS = 120
_MAX_ENTRY_BEFORE_MS = 250
_MIN_EXIT_AFTER_MS = 200
_MAX_EXIT_AFTER_MS = 500


def validate_timing_rows(
    rows: Iterable[Mapping[str, Any]], *, minimum_readable_duration_ms: int
) -> dict[str, Any]:
    """Validate compact rows and return a bounded issue summary.

    Rows are consumed in their given order.  This makes example Beat IDs
    deterministic and avoids sorting or carrying any verbose input forward.
    Unknown row fields are rejected so callers cannot smuggle payloads through
    the compact interface.
    """
    if isinstance(rows, (str, bytes, bytearray, Mapping)):
        raise ValueError("timing rows must be a compact row sequence")
    if (
        isinstance(minimum_readable_duration_ms, bool)
        or not isinstance(minimum_readable_duration_ms, int)
        or not 0 <= minimum_readable_duration_ms <= _MAX_MS
    ):
        raise ValueError("minimum readable duration must be a bounded integer")

    try:
        compact_rows = [_copy_row(row) for row in rows]
    except TypeError as error:
        raise ValueError("timing rows must be a compact row sequence") from error
    _validate_unique_beat_ids(compact_rows)

    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    checks_run = 0
    for row in compact_rows:
        # Every rule is evaluated for every row, even after one rule fails.
        # This fixed table keeps checks_run and issue aggregation predictable.
        for code, rule in _ROW_RULES:
            checks_run += 1
            if rule(row, minimum_readable_duration_ms):
                _record_issue(code, row["beat_id"], counts, examples)

    # Cross-row proximity is one check for each adjacent keyword event, rather
    # than a quadratic all-pairs scan.  The input is not reordered in the
    # result; only the local comparison order is deterministic.
    anchored = [
        row for row in compact_rows if _window(row.get("keyword_anchor_ms")) is not None
    ]
    anchored.sort(key=lambda row: (_window(row["keyword_anchor_ms"])[0], row["beat_id"]))
    for previous, current in zip(anchored, anchored[1:]):
        checks_run += 1
        previous_visual = _window(previous.get("visual_window_ms"))
        current_visual = _window(current.get("visual_window_ms"))
        if (
            previous_visual is not None
            and current_visual is not None
            and current_visual[0] < previous_visual[1]
        ):
            _record_issue(
                "KEYWORD_EVENTS_TOO_CLOSE", current["beat_id"], counts, examples
            )

    if not counts:
        return {"status": "passed", "checks_run": checks_run}
    return {
        "status": "blocked",
        "checks_run": checks_run,
        "issue_counts": counts,
        "examples": examples,
    }


def _copy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValueError("timing rows must be compact mapping records")
    unknown = set(row) - _ROW_FIELDS
    if unknown:
        raise ValueError("timing rows must be closed compact records")
    beat_id = row.get("beat_id")
    if not _safe_id(beat_id):
        raise ValueError("timing rows require safe Beat IDs")
    copied = dict(row)
    # Validate supplied metadata types now, while leaving absent timing fields
    # available for the VOICE_TIMING_REQUIRED rule.
    for field in (
        "timing_kind",
        "voice_timing_status",
        "timing_status",
        "voice_timing_id",
        "current_voice_timing_id",
        "timed_semantic_beats_id",
        "current_timed_semantic_beats_id",
    ):
        if field in copied and copied[field] is not None and not isinstance(copied[field], str):
            raise ValueError(f"timing row {field} must be metadata text")
    for field in ("scene_id",):
        if field in copied and copied[field] is not None and not _safe_id(copied[field]):
            raise ValueError(f"timing row {field} must be a safe ID")
    return copied


def _validate_unique_beat_ids(rows: list[dict[str, Any]]) -> None:
    beat_ids = [row["beat_id"] for row in rows]
    if len(beat_ids) != len(set(beat_ids)):
        raise ValueError("timing rows require unique Beat IDs")


def _record_issue(
    code: str, beat_id: str, counts: dict[str, int], examples: dict[str, list[str]]
) -> None:
    counts[code] = counts.get(code, 0) + 1
    ids = examples.setdefault(code, [])
    if len(ids) < _MAX_EXAMPLES and beat_id not in ids:
        ids.append(beat_id)


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 128 and _SAFE_ID.fullmatch(value) is not None


def _milliseconds(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= _MAX_MS
    )


def _window(value: Any) -> list[int] | None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(_milliseconds(item) for item in value)
        or value[0] >= value[1]
    ):
        return None
    return [value[0], value[1]]


def _anchor_missing(row: dict[str, Any], _: int) -> bool:
    return _window(row.get("keyword_anchor_ms")) is None


def _voice_required(row: dict[str, Any], _: int) -> bool:
    # The canonical compact row omits timing_kind when the already-validated
    # parent DAG supplies it.  An explicit non-real kind must fail closed.
    if "timing_kind" in row and row["timing_kind"] != "real":
        return True
    if row.get("voice_timing_status") in {"missing", "estimated", "unavailable"}:
        return True
    if "current_voice_timing_id" in row and not row.get("voice_timing_id"):
        return True
    return any(
        field in row and not row[field]
        for field in ("voice_timing_id", "timed_semantic_beats_id")
    )


def _visual_before(row: dict[str, Any], _: int) -> bool:
    anchor = _window(row.get("keyword_anchor_ms"))
    visual = _window(row.get("visual_window_ms"))
    if anchor is None or visual is None:
        return False
    return not (
        anchor[0] - _MAX_ENTRY_BEFORE_MS
        <= visual[0]
        <= anchor[0] - _MIN_ENTRY_BEFORE_MS
    )


def _visual_after(row: dict[str, Any], _: int) -> bool:
    anchor = _window(row.get("keyword_anchor_ms"))
    visual = _window(row.get("visual_window_ms"))
    if anchor is None or visual is None:
        return False
    return not (
        anchor[1] + _MIN_EXIT_AFTER_MS
        <= visual[1]
        <= anchor[1] + _MAX_EXIT_AFTER_MS
    )


def _outside_scene(row: dict[str, Any], _: int) -> bool:
    visual = _window(row.get("visual_window_ms"))
    scene = _window(row.get("scene_window_ms"))
    if visual is None or scene is None:
        return False
    return visual[0] < scene[0] or visual[1] > scene[1]


def _multiple_primary(row: dict[str, Any], _: int) -> bool:
    primary = row.get("primary_carrier")
    if isinstance(primary, (list, tuple, set, frozenset)):
        return len(primary) != 1
    return not isinstance(primary, str) or primary not in SCENE_CARRIERS


def _support_overflow(row: dict[str, Any], _: int) -> bool:
    support = row.get("support_layer")
    if isinstance(support, (list, tuple, set, frozenset)):
        return len(support) > 1
    return support is not None and not isinstance(support, str)


def _scene_too_short(row: dict[str, Any], minimum: int) -> bool:
    scene = _window(row.get("scene_window_ms"))
    return scene is not None and scene[1] - scene[0] < minimum


def _stale_voice_timing(row: dict[str, Any], _: int) -> bool:
    status = row.get("voice_timing_status", row.get("timing_status"))
    if status in {"stale", "superseded", "invalid"}:
        return True
    current = row.get("current_voice_timing_id")
    actual = row.get("voice_timing_id")
    return current is not None and actual is not None and current != actual


_ROW_RULES: tuple[tuple[str, Callable[[dict[str, Any], int], bool]], ...] = (
    ("VOICE_TIMING_REQUIRED", _voice_required),
    ("KEYWORD_ANCHOR_MISSING", _anchor_missing),
    ("VISUAL_BEFORE_ALLOWED_WINDOW", _visual_before),
    ("VISUAL_AFTER_ALLOWED_WINDOW", _visual_after),
    ("BEAT_OUTSIDE_SCENE", _outside_scene),
    ("MULTIPLE_PRIMARY_CARRIERS", _multiple_primary),
    ("SUPPORT_LAYER_OVERFLOW", _support_overflow),
    # The proximity rule is evaluated in the bounded adjacent-row pass.
    ("SCENE_TOO_SHORT", _scene_too_short),
    ("STALE_VOICE_TIMING", _stale_voice_timing),
)

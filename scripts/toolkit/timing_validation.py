"""Compact, deterministic validation for voice-timed visual beat rows.

The validator deliberately accepts a small structural projection of the timing
graph.  It does not accept (or need) narration, transcripts, paths, media,
motion source, or diagnostics.  Keep this module safe to run in the
coordinator: a result contains counts and no more than three Beat IDs per
issue code.
"""

from __future__ import annotations

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
_ISSUE_CODE_SET = frozenset(ISSUE_CODES)

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
_REQUIRED_ROW_FIELDS = frozenset(
    {
        "beat_id",
        "scene_id",
        "keyword_anchor_ms",
        "visual_window_ms",
        "scene_window_ms",
        "primary_carrier",
        "support_layer",
    }
)
_LINEAGE_FIELDS = frozenset(
    {
        "voice_timing_id",
        "current_voice_timing_id",
        "timed_semantic_beats_id",
        "current_timed_semantic_beats_id",
    }
)
_SUPPORT_LAYERS = frozenset(
    {
        "caption-emphasis",
        "callout",
        "number-animation",
        "label",
        "subtitle-emphasis",
        "connection",
        "progress-state",
        "annotation",
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


def validate_timing_validation_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the compact result persisted by the timing worker."""
    if not isinstance(result, Mapping):
        raise ValueError("timing validation result must be an object")
    allowed = {"status", "checks_run", "issue_counts", "examples"}
    if set(result) - allowed:
        raise ValueError("timing validation result has unknown fields")
    status = result.get("status")
    if status not in {"blocked", "passed"}:
        raise ValueError("timing validation status is not recognized")
    checks_run = result.get("checks_run")
    if isinstance(checks_run, bool) or not isinstance(checks_run, int) or not 0 <= checks_run <= 1_000_000:
        raise ValueError("timing validation checks_run is outside bounds")
    if status == "passed":
        if "issue_counts" in result or "examples" in result:
            raise ValueError("passed timing validation cannot contain issues")
        return {"status": status, "checks_run": checks_run}
    if not isinstance(result.get("issue_counts"), Mapping) or not isinstance(result.get("examples"), Mapping):
        raise ValueError("blocked timing validation requires issue counts and examples")
    issue_counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    if not result["issue_counts"]:
        raise ValueError("blocked timing validation requires an issue")
    for code, count in result["issue_counts"].items():
        if code not in _ISSUE_CODE_SET:
            raise ValueError("timing validation issue code is not recognized")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1_000_000:
            raise ValueError("timing validation issue count is outside bounds")
        issue_counts[code] = count
    for code, ids in result["examples"].items():
        if code not in _ISSUE_CODE_SET or code not in issue_counts:
            raise ValueError("timing validation example code is not recognized")
        if not isinstance(ids, list) or len(ids) > _MAX_EXAMPLES:
            raise ValueError("timing validation examples are outside bounds")
        if not all(_safe_id(item) for item in ids):
            raise ValueError("timing validation examples require safe Beat IDs")
        if len(ids) != len(set(ids)):
            raise ValueError("timing validation examples must be unique")
        examples[code] = list(ids)
    if set(examples) != set(issue_counts):
        raise ValueError("timing validation examples must match issue counts")
    return {
        "status": status,
        "checks_run": checks_run,
        "issue_counts": issue_counts,
        "examples": examples,
    }


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
    missing = _REQUIRED_ROW_FIELDS - set(row)
    if missing:
        raise ValueError("timing row requires a complete compact projection")
    beat_id = row.get("beat_id")
    if not _safe_id(beat_id):
        raise ValueError("timing rows require safe Beat IDs")
    copied = dict(row)
    # Validate supplied metadata types now, while leaving explicit empty
    # lineage values for STALE_VOICE_TIMING to report as a bounded blocker.
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
    if not _safe_id(copied["scene_id"]):
        raise ValueError("timing row scene_id must be a safe ID")
    for field in _LINEAGE_FIELDS:
        if field in copied and copied[field] not in (None, "") and not _safe_id(copied[field]):
            raise ValueError(f"timing row {field} must be a safe lineage ID")

    for field in ("keyword_anchor_ms", "visual_window_ms", "scene_window_ms"):
        if _window(copied[field]) is None:
            raise ValueError(f"timing row {field} must be an ordered bounded window")

    primary = copied["primary_carrier"]
    if isinstance(primary, (list, tuple, set, frozenset)):
        # A multi-value collection is retained as an explicit conflict so the
        # compact result can report MULTIPLE_PRIMARY_CARRIERS. A one-value
        # collection is malformed rather than silently canonicalized.
        if len(primary) <= 1:
            raise ValueError("timing row primary_carrier must be one registered scalar")
    elif not isinstance(primary, str) or primary not in SCENE_CARRIERS:
        raise ValueError("timing row primary_carrier must be one registered scalar")

    support = copied["support_layer"]
    if isinstance(support, (list, tuple, set, frozenset)):
        if len(support) <= 1:
            raise ValueError("timing row support_layer must be one scalar or null")
    elif support is not None and (
        not isinstance(support, str)
        or support not in _SUPPORT_LAYERS
        or not 0 < len(support) <= 128
        or not support.strip()
    ):
        raise ValueError("timing row support_layer must be a bounded nonempty scalar or null")
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
        not isinstance(value, list)
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
    return "voice_timing_id" in row and not row["voice_timing_id"]


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
    for claimed_field, current_field in (
        ("voice_timing_id", "current_voice_timing_id"),
        ("timed_semantic_beats_id", "current_timed_semantic_beats_id"),
    ):
        if claimed_field not in row and current_field not in row:
            continue
        claimed = row.get(claimed_field)
        current = row.get(current_field)
        if not claimed or not current or claimed != current:
            return True
    return False


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

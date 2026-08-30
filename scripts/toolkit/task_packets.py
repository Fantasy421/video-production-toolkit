"""Deterministic projection of durable task records into compact worker packets."""

import json
from collections.abc import Mapping
from typing import Any

from .tasks import validate_current_task_envelope
from .visual_media_context import (
    ACTIVE_VISUAL_MEDIA_OPERATIONS,
    SAFE_ID_RE,
    validate_visual_media_context,
)


PACKET_VERSION = 1
MAX_PACKET_BYTES = 8_192
MAX_RESULT_ITEMS = 8
MAX_RESULT_ITEM_CHARS = 64
RESULT_LIMITS = {
    "max_checks": MAX_RESULT_ITEMS,
    "max_warnings": MAX_RESULT_ITEMS,
    "max_item_chars": MAX_RESULT_ITEM_CHARS,
}
SUMMARY_FIELDS = {
    "project.manage": {"action", "target_phase"},
    "narration.plan": {"language", "platform", "target_duration_ms"},
    "visual.preview": {"beat_ids", "style_id", "layout_id"},
    "voice.prepare": {"narration_id", "source_mode", "profile_id"},
    "storyboard.plan": {"beat_ids", "style_id", "layout_id"},
    "scene.produce": {
        "chapter_id",
        "scene_ids",
        "scene_contract_ids",
        "production_scope",
    },
    "motion.preview": {"scene_ids", "motion_contract_ids", "production_scope"},
    "motion.produce": {"scene_ids", "motion_contract_ids", "production_scope"},
    "timeline.assemble": {"scene_ids", "timeline_id", "production_scope"},
    "structure.validate": {"validation_scope", "timeline_id", "scene_ids"},
    "review.package": {"review_scope", "artifact_ids"},
    "captions.produce": {"scene_ids", "language", "production_scope"},
    "representative-slice.produce": {"scene_ids", "ranges_ms"},
    "timing-repair": {"affected_beat_ids", "minimum_readable_duration_ms"},
}
PACKET_FIELDS = {
    "packet_version",
    "task_id",
    "capability",
    "artifact_ids",
    "time_window_ms",
    "contract_summary",
    "result_limits",
    "visual_media_authority",
}


def build_task_packet(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one durable envelope and return only worker-required metadata."""
    candidate = dict(envelope) if isinstance(envelope, Mapping) else envelope
    validate_current_task_envelope(candidate)
    constraints = candidate["constraints"]
    summary = constraints.get("contract_summary", {})
    _validate_contract_summary(candidate["capability"], summary)
    packet: dict[str, Any] = {
        "packet_version": PACKET_VERSION,
        "task_id": candidate["task_id"],
        "capability": candidate["capability"],
        "artifact_ids": list(candidate["inputs"]),
        "time_window_ms": _validate_time_window(
            constraints.get("time_window_ms")
        ),
        "contract_summary": _json_copy(summary),
        "result_limits": dict(RESULT_LIMITS),
    }
    operation = constraints.get("visual_media_operation")
    if operation != "none":
        context = validate_visual_media_context(constraints["visual_media_context"])
        packet["visual_media_authority"] = {
            "operation": operation,
            **context,
        }
    validate_task_packet(packet)
    return packet


def validate_task_packet(packet: Mapping[str, Any]) -> int:
    """Validate a closed packet and return its canonical UTF-8 byte size."""
    if not isinstance(packet, Mapping):
        raise ValueError("task packet must be an object")
    required = PACKET_FIELDS - {"visual_media_authority"}
    if not required <= set(packet) or set(packet) - PACKET_FIELDS:
        raise ValueError("task packet fields are invalid")
    if packet.get("packet_version") != PACKET_VERSION:
        raise ValueError("task packet version is invalid")
    capability = packet.get("capability")
    if capability not in SUMMARY_FIELDS:
        raise ValueError("task packet capability is invalid")
    task_id = packet.get("task_id")
    if not isinstance(task_id, str) or SAFE_ID_RE.fullmatch(task_id) is None:
        raise ValueError("task packet task_id is invalid")
    artifact_ids = packet.get("artifact_ids")
    if (
        not isinstance(artifact_ids, list)
        or not all(
            isinstance(item, str) and SAFE_ID_RE.fullmatch(item) is not None
            for item in artifact_ids
        )
        or len(set(artifact_ids)) != len(artifact_ids)
    ):
        raise ValueError("task packet artifact_ids are invalid")
    _validate_time_window(packet.get("time_window_ms"))
    _validate_contract_summary(capability, packet.get("contract_summary"))
    if capability == "scene.produce" and packet.get("contract_summary"):
        _validate_scene_summary(
            packet["contract_summary"],
            packet.get("time_window_ms"),
            artifact_ids,
        )
    if packet.get("result_limits") != RESULT_LIMITS:
        raise ValueError("task packet result limits are invalid")
    authority = packet.get("visual_media_authority")
    if authority is not None:
        if not isinstance(authority, Mapping) or "operation" not in authority:
            raise ValueError("task packet visual authority is invalid")
        operation = authority["operation"]
        context = {key: value for key, value in authority.items() if key != "operation"}
        context = validate_visual_media_context(context)
        if operation not in ACTIVE_VISUAL_MEDIA_OPERATIONS:
            raise ValueError("task packet visual operation is invalid")
        if context["context_budget_bytes"] > MAX_PACKET_BYTES:
            raise ValueError("task packet visual context budget exceeds 8192 bytes")
        if capability == "scene.produce" and context["scope_identity"]["kind"] == "scene-batch":
            expected = packet["contract_summary"].get("scene_contract_ids")
            if context["scope_identity"]["id"] != expected:
                raise ValueError("scene-batch visual scope must match the contract summary")
    size = len(_canonical_json(packet).encode("utf-8"))
    if size > MAX_PACKET_BYTES:
        raise ValueError("task packet exceeds 8192 bytes")
    return size


def validate_task_result_summary(result: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return closed bounded checks and warnings for model-to-runtime handoff."""
    if not isinstance(result, Mapping):
        raise ValueError("task result summary must be an object")
    normalized = {}
    for field in ("checks", "warnings"):
        value = result.get(field)
        if (
            not isinstance(value, list)
            or len(value) > MAX_RESULT_ITEMS
            or not all(
                isinstance(item, str)
                and 0 < len(item) <= MAX_RESULT_ITEM_CHARS
                for item in value
            )
            or len(set(value)) != len(value)
        ):
            raise ValueError(f"task result {field} must be compact and bounded")
        normalized[field] = list(value)
    return normalized


def _validate_contract_summary(capability: str, summary: Any) -> None:
    if not isinstance(summary, Mapping):
        raise ValueError("contract summary must be an object")
    unknown = set(summary) - SUMMARY_FIELDS.get(capability, set())
    if unknown:
        raise ValueError(
            "contract summary field is not allowed for capability: "
            + ", ".join(sorted(unknown))
        )
    _validate_compact_value(summary, depth=0)


def _validate_scene_summary(
    summary: Mapping[str, Any], time_window: Any, artifact_ids: list[str]
) -> None:
    required = {"chapter_id", "scene_ids", "scene_contract_ids"}
    if not required <= set(summary) or time_window is None:
        raise ValueError("scene production requires a bounded contract summary and window")
    chapter_id = summary["chapter_id"]
    scene_ids = summary["scene_ids"]
    contract_ids = summary["scene_contract_ids"]
    if not isinstance(chapter_id, str) or SAFE_ID_RE.fullmatch(chapter_id) is None:
        raise ValueError("scene contract summary chapter_id is invalid")
    for label, values in (("scene_ids", scene_ids), ("scene_contract_ids", contract_ids)):
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 6
            or len(values) != len(set(values))
            or not all(
                isinstance(item, str) and SAFE_ID_RE.fullmatch(item) is not None
                for item in values
            )
        ):
            raise ValueError(f"scene contract summary {label} is invalid")
    if len(scene_ids) != len(contract_ids) or not set(contract_ids) <= set(artifact_ids):
        raise ValueError("scene contract summary must match declared Artifact IDs")


def _validate_compact_value(value: Any, *, depth: int) -> None:
    if depth > 3:
        raise ValueError("contract summary nesting is too deep")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if not value or len(value) > 256:
            raise ValueError("contract summary strings must be bounded")
        return
    if isinstance(value, list):
        if len(value) > 32:
            raise ValueError("contract summary lists must be bounded")
        for item in value:
            _validate_compact_value(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > 16 or not all(isinstance(key, str) and key for key in value):
            raise ValueError("contract summary objects must be bounded")
        for item in value.values():
            _validate_compact_value(item, depth=depth + 1)
        return
    raise ValueError("contract summary values must be JSON metadata")


def _validate_time_window(value: Any) -> Any:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or not 0 <= value[0] < value[1] <= 36_000_000
    ):
        raise ValueError("time_window_ms must be one bounded increasing pair")
    return list(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value))

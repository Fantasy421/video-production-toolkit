"""Canonical runtime validation for persisted production contracts."""

import re
from collections.abc import Mapping
from typing import Any


SCENE_CARRIERS = frozenset(
    {"a-roll", "b-roll", "scene", "demo", "motion-graphics", "evidence"}
)
SCENE_CONTRACT_REQUIRED_FIELDS = frozenset(
    {"scene_id", "start_ms", "end_ms", "primary_carrier", "purpose"}
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


def validate_scene_contract(value: Mapping[str, Any]) -> dict[str, Any]:
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
    return dict(value)

"""Authoritative structural contracts for Style and Layout Packs."""

import math
from collections.abc import Mapping
from typing import Any


BASE_FIELDS = frozenset(
    {"id", "version", "job", "preview", "renderer", "implementation_ref", "license"}
)
STYLE_FIELDS = frozenset(
    {
        "tokens",
        "rules",
        "previews",
        "applicability",
        "exclusions",
        "required_fonts",
        "compatibility",
        "project_evidence",
    }
)
STYLE_OPTIONAL_FIELDS = frozenset({"mechanism", "participants", "canvas"})
LAYOUT_FIELDS = frozenset({"canvas", "regions", "density", "media_compatibility"})
LAYOUT_OPTIONAL_FIELDS = frozenset({"mechanism", "participants"})
REGION_NAMES = frozenset({"subject", "information", "subtitle", "platform_safe"})


def validate_style_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of one exact style-pack-v1 manifest."""
    _exact_fields(value, BASE_FIELDS | STYLE_FIELDS, STYLE_OPTIONAL_FIELDS, "style pack")
    _base(value, "style pack")
    if not isinstance(value["tokens"], Mapping) or not value["tokens"]:
        raise ValueError("style pack tokens must be a non-empty object")
    for field in ("rules", "previews", "applicability", "project_evidence"):
        _string_list(value[field], field)
    _string_list(value["exclusions"], "exclusions", allow_empty=True)
    if value["preview"] not in value["previews"]:
        raise ValueError("style pack preview must appear in previews")
    fonts = value["required_fonts"]
    if not isinstance(fonts, list) or not fonts:
        raise ValueError("style pack required_fonts must be non-empty")
    families = []
    for font in fonts:
        if not isinstance(font, Mapping):
            raise ValueError("style pack font must be an object")
        source = font.get("source")
        expected = {"family", "source", "path"} if source == "bundled" else {"family", "source"}
        if set(font) != expected or source not in {"system", "bundled"}:
            raise ValueError("style pack font source contract is invalid")
        _text(font["family"], "font family")
        if source == "bundled":
            _text(font["path"], "font path")
        families.append(font["family"])
    if len(families) != len(set(families)):
        raise ValueError("style pack font families must be unique")
    compatibility = value["compatibility"]
    if not isinstance(compatibility, Mapping) or set(compatibility) != {"canvases", "renderers"}:
        raise ValueError("style pack compatibility is invalid")
    _string_list(compatibility["canvases"], "compatibility canvases")
    _string_list(compatibility["renderers"], "compatibility renderers")
    if "canvas" in value:
        _string_list(value["canvas"], "canvas")
        if set(value["canvas"]) != set(compatibility["canvases"]):
            raise ValueError("style pack canvas must match compatibility canvases")
    _optional_common(value)
    return dict(value)


def validate_layout_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of one exact layout-pack-v1 manifest."""
    _exact_fields(value, BASE_FIELDS | LAYOUT_FIELDS, LAYOUT_OPTIONAL_FIELDS, "layout pack")
    _base(value, "layout pack")
    _string_list(value["canvas"], "canvas")
    _string_list(value["media_compatibility"], "media_compatibility")
    if value["density"] not in {"low", "medium", "high"}:
        raise ValueError("layout pack density is invalid")
    regions = value["regions"]
    if not isinstance(regions, Mapping) or set(regions) != REGION_NAMES:
        raise ValueError("layout pack regions are invalid")
    for name, region in regions.items():
        _validate_region(region, name)
    _optional_common(value)
    return dict(value)


def _exact_fields(
    value: Mapping[str, Any], required: frozenset[str], optional: frozenset[str], label: str
) -> None:
    if not isinstance(value, Mapping) or required - set(value) or set(value) - required - optional:
        raise ValueError(f"{label} fields are invalid")


def _base(value: Mapping[str, Any], label: str) -> None:
    for field in BASE_FIELDS:
        _text(value[field], f"{label} {field}")


def _optional_common(value: Mapping[str, Any]) -> None:
    if "mechanism" in value:
        _text(value["mechanism"], "mechanism")
    if "participants" in value:
        _string_list(value["participants"], "participants")


def _validate_region(value: Any, name: str) -> None:
    fields = {"x", "y", "width", "height"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"layout region {name} is invalid")
    coordinates = [value[field] for field in ("x", "y", "width", "height")]
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        for item in coordinates
    ):
        raise ValueError(f"layout region {name} must use finite numbers")
    x, y, width, height = coordinates
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise ValueError(f"layout region {name} leaves the normalized canvas")


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{label} must be a unique string list")


def _text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")

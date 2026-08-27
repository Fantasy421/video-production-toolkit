"""Versioned registry lookup and evidence-gated lesson promotion."""

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional, Tuple

from .packs import validate_layout_pack, validate_style_pack


COMPACT_FIELDS = (
    "id",
    "version",
    "score",
    "job",
    "preview",
    "renderer",
    "implementation_ref",
    "license",
)
MAX_CANDIDATES = 3
LESSON_STATUSES = ("observed", "candidate", "verified", "global", "deprecated")
REQUIRED_ENTRY_FIELDS = ("id", "version", "job", "preview", "renderer", "implementation_ref", "license")
OPTIONAL_ENTRY_FIELDS = {
    "mechanism",
    "participants",
    "duration",
    "canvas",
    "carriers",
    "capabilities",
    "accepts",
    "outputs",
    "editable",
    "installed_skill",
    "capability_skills",
    "capability_implementation_refs",
    "accepted_voice_media_formats",
    "duration_probe",
    "fallback",
    "license_mode",
    "tokens",
    "rules",
    "previews",
    "applicability",
    "exclusions",
    "required_fonts",
    "compatibility",
    "project_evidence",
    "regions",
    "density",
    "media_compatibility",
}


def search_registry(root: Path, kind: str, query: Mapping[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Return compact, deterministically ranked entries from one registry kind.

    Registry entries remain metadata-only: implementation bodies are never read or
    returned.  A requested canvas is a compatibility boundary; the remaining
    query terms rank compatible candidates without excluding useful fallbacks.
    """
    if not isinstance(kind, str) or not kind or Path(kind).name != kind:
        raise ValueError("kind must be a single registry directory name")
    if not isinstance(query, Mapping):
        raise ValueError("query must be a mapping")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    if limit == 0:
        return []

    candidates = []
    for entry in _load_entries(Path(root), kind):
        if not _supports_canvas(entry, query.get("canvas")):
            continue
        score = _score(entry, query)
        candidates.append(_compact_entry(entry, score))

    candidates.sort(key=lambda candidate: (-candidate["score"], candidate["id"]))
    return candidates[: min(limit, MAX_CANDIDATES)]


def promote_lesson(lesson: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Advance lesson maturity only when its evidence satisfies the policy.

    Global guidance is deliberately never inferred from observation counts: it
    requires an already verified lesson, evidence from two projects, and explicit
    user approval.
    """
    if not isinstance(lesson, Mapping):
        raise ValueError("lesson must be a mapping")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence must be a mapping")
    status = lesson.get("status", "observed")
    if status not in LESSON_STATUSES:
        raise ValueError(f"unknown lesson status: {status}")

    scenes = _evidence_count(evidence, "scenes")
    projects = _evidence_count(evidence, "projects")
    user_approved = evidence.get("user_approved", False)
    if not isinstance(user_approved, bool):
        raise ValueError("evidence user_approved must be a boolean")

    promoted = dict(lesson)
    if status in {"deprecated", "global"}:
        return promoted
    if status == "verified":
        if scenes >= 2 and projects >= 2 and user_approved:
            promoted["status"] = "global"
        return promoted
    if status == "candidate" and scenes >= 2 and projects >= 2:
        promoted["status"] = "verified"
    elif status == "observed" and scenes >= 2:
        promoted["status"] = "candidate"
    return promoted


def _load_entries(root: Path, kind: str) -> list[dict[str, Any]]:
    registry = root / "registries" / kind
    if not registry.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(registry.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid registry JSON: {path}") from error
        for entry in _entries_from_payload(payload, kind, path):
            _validate_entry(entry, path, kind)
            entries.append(entry)
    return entries


def _entries_from_payload(payload: Any, kind: str, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError(f"registry payload must be an object or list: {path}")
    if "id" in payload:
        return [dict(payload)]
    entries = payload.get(kind, payload.get("entries", []))
    if not isinstance(entries, list):
        raise ValueError(f"registry entries must be a list: {path}")
    return entries


def _validate_entry(entry: Any, path: Path, kind: str) -> None:
    if not isinstance(entry, Mapping):
        raise ValueError(f"registry entry must be an object: {path}")
    allowed = set(REQUIRED_ENTRY_FIELDS) | OPTIONAL_ENTRY_FIELDS
    unknown = sorted(set(entry) - allowed)
    if unknown:
        raise ValueError(f"registry entry has unknown fields ({', '.join(unknown)}): {path}")
    missing = [
        field
        for field in REQUIRED_ENTRY_FIELDS
        if not isinstance(entry.get(field), str) or not entry[field]
    ]
    if missing:
        raise ValueError(f"registry entry missing fields ({', '.join(missing)}): {path}")
    if "mechanism" in entry:
        _validate_string(entry["mechanism"], "mechanism", path)
    for field in ("participants", "canvas", "carriers", "capabilities", "accepts", "outputs"):
        if field in entry:
            _validate_string_list(entry[field], field, path)
    if "duration" in entry:
        _validate_duration(entry["duration"], path)
    if "editable" in entry and not isinstance(entry["editable"], bool):
        raise ValueError(f"registry editable must be a boolean: {path}")
    if "installed_skill" in entry:
        _validate_string(entry["installed_skill"], "installed_skill", path)
    if "capability_skills" in entry:
        _validate_capability_skills(entry, path)
    if "capability_implementation_refs" in entry:
        _validate_capability_implementation_refs(entry, path)
    if "accepted_voice_media_formats" in entry:
        _validate_string_list(
            entry["accepted_voice_media_formats"],
            "accepted_voice_media_formats",
            path,
        )
    if "duration_probe" in entry:
        probe = entry["duration_probe"]
        if (
            not isinstance(probe, Mapping)
            or not probe
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(value, str)
                or not value
                for name, value in probe.items()
            )
        ):
            raise ValueError(
                f"registry duration_probe must be a non-empty string map: {path}"
            )
    if "fallback" in entry and entry["fallback"] is not None:
        _validate_string(entry["fallback"], "fallback", path)
    if "license_mode" in entry and entry["license_mode"] != "external-reference":
        raise ValueError(f"registry license_mode must be external-reference: {path}")
    try:
        if kind == "styles":
            validate_style_pack(entry)
        elif kind == "layouts":
            validate_layout_pack(entry)
    except ValueError as error:
        raise ValueError(f"invalid {kind} registry entry: {path}: {error}") from error


def _validate_string(value: Any, field: str, path: Path) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"registry {field} must be a non-empty string: {path}")


def _validate_string_list(value: Any, field: str, path: Path) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"registry {field} must be a non-empty string array: {path}")
    if len(value) != len(set(value)):
        raise ValueError(f"registry {field} must not repeat values: {path}")


def _validate_capability_skills(entry: Mapping[str, Any], path: Path) -> None:
    """Allow a capability to name its installed Skill without widening routing."""
    value = entry["capability_skills"]
    capabilities = entry.get("capabilities")
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"registry capability_skills must be a non-empty object: {path}")
    if not isinstance(capabilities, list) or any(
        not isinstance(capability, str) or not capability for capability in capabilities
    ) or any(
        not isinstance(capability, str)
        or capability not in capabilities
        or not isinstance(skill, str)
        or not skill
        for capability, skill in value.items()
    ):
        raise ValueError(
            f"registry capability_skills must map declared capabilities to skills: {path}"
        )


def _validate_capability_implementation_refs(entry: Mapping[str, Any], path: Path) -> None:
    value = entry["capability_implementation_refs"]
    capabilities = entry.get("capabilities")
    if not isinstance(value, Mapping) or not value:
        raise ValueError(
            f"registry capability_implementation_refs must be a non-empty object: {path}"
        )
    if not isinstance(capabilities, list) or any(
        not isinstance(capability, str) or not capability for capability in capabilities
    ) or any(
        not isinstance(capability, str)
        or capability not in capabilities
        or not isinstance(reference, str)
        or not reference.startswith("external:")
        or not reference[len("external:") :]
        for capability, reference in value.items()
    ):
        raise ValueError(
            "registry capability_implementation_refs must map declared capabilities "
            f"to external references: {path}"
        )


def _validate_duration(value: Any, path: Path) -> None:
    if isinstance(value, bool):
        raise ValueError(f"registry duration must be a non-negative number or min/max object: {path}")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"registry duration must be a non-negative number: {path}")
        return
    if not isinstance(value, Mapping) or set(value) != {"min", "max"}:
        raise ValueError(f"registry duration must be a min/max object: {path}")
    minimum, maximum = value["min"], value["max"]
    if (
        isinstance(minimum, bool)
        or isinstance(maximum, bool)
        or not isinstance(minimum, (int, float))
        or not isinstance(maximum, (int, float))
        or not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum < 0
        or maximum < minimum
    ):
        raise ValueError(f"registry duration range is invalid: {path}")


def _compact_entry(entry: Mapping[str, Any], score: int) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "version": entry["version"],
        "score": score,
        "job": entry["job"],
        "preview": entry["preview"],
        "renderer": entry["renderer"],
        "implementation_ref": entry["implementation_ref"],
        "license": entry["license"],
    }


def _score(entry: Mapping[str, Any], query: Mapping[str, Any]) -> int:
    score = 0
    if _exact_match(entry.get("mechanism"), query.get("mechanism")):
        score += 40
    if _participants_compatible(entry.get("participants"), query.get("participants")):
        score += 20
    if _duration_matches(entry.get("duration"), query.get("duration")):
        score += 15
    if _exact_match(entry.get("renderer"), query.get("preferred_renderer")):
        score += 10

    recent_recipes, recent_carriers = _recent_ids(query.get("recent_ids"))
    if entry["id"] in recent_recipes:
        score -= 25
    if _values(entry.get("carriers")) & recent_carriers:
        score -= 12
    return score


def _supports_canvas(entry: Mapping[str, Any], requested: Any) -> bool:
    if requested in (None, "", [], ()):
        return True
    compatibility = entry.get("compatibility")
    supported = (
        compatibility.get("canvases")
        if isinstance(compatibility, Mapping) and "canvases" in compatibility
        else entry.get("canvas")
    )
    return bool(_values(supported) & _values(requested))


def _exact_match(value: Any, requested: Any) -> bool:
    return bool(_values(value) & _values(requested)) if requested not in (None, "", [], ()) else False


def _participants_compatible(value: Any, requested: Any) -> bool:
    requested_values = _values(requested)
    if not requested_values:
        return False
    return requested_values <= _values(value)


def _duration_matches(value: Any, requested: Any) -> bool:
    if requested is None or requested == "":
        return False
    lower, upper = _duration_range(value)
    query_lower, query_upper = _duration_range(requested)
    return lower is not None and query_lower is not None and lower <= query_upper and query_lower <= upper


def _duration_range(value: Any) -> Tuple[Optional[float], Optional[float]]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), float(value)
    if isinstance(value, Mapping):
        minimum = value.get("min", value.get("minimum"))
        maximum = value.get("max", value.get("maximum", minimum))
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        minimum, maximum = value
    else:
        return None, None
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in (minimum, maximum)):
        return None, None
    if minimum > maximum:
        return None, None
    return float(minimum), float(maximum)


def _recent_ids(value: Any) -> tuple[set[str], set[str]]:
    if isinstance(value, Mapping):
        return _values(value.get("recipes", value.get("recipe_ids"))), _values(
            value.get("carriers", value.get("carrier_ids"))
        )
    recent = _values(value)
    return recent, recent


def _values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return {str(key) for key, included in value.items() if included}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {item for item in value if isinstance(item, str)}
    return set()


def _evidence_count(evidence: Mapping[str, Any], key: str) -> int:
    value = evidence.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"evidence {key} must be a non-negative integer")
    return value

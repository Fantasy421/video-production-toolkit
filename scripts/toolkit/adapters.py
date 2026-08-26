"""Deterministic selection of one external capability provider and fallback."""

from collections.abc import Iterable, Mapping
import re
from typing import Any, Union


_MANIFEST_KEYS = {
    "id", "version", "job", "preview", "renderer", "implementation_ref", "license",
    "capabilities", "accepts", "outputs", "editable", "installed_skill", "fallback",
    "license_mode",
}
_REQUIREMENT_KEYS = {
    "adapter_preferences", "preferred_adapter", "installed_skills", "contract",
    "accepted_contract", "output", "required_output", "editable", "overlay", "format",
}
_LOCAL_NO_CREDIT = {"hyperframes", "remotion", "chatcut"}
_PRIMARY_ORDER = {
    "motion.preview": ("hyperframes", "remotion"),
    "motion.produce": ("remotion", "video-shotcraft", "chatcut"),
}
_OVERLAY_ORDER = ("chatcut", "remotion", "video-shotcraft")


def select_adapter(
    capability: str, requirements: Mapping[str, Any], manifests: Union[Iterable[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Return one compatible external adapter and at most one declared fallback.

    This is routing metadata only: it neither invokes providers nor reads their
    instructions.  Provider manifests cannot add gate or routing fields, so the
    coordinator remains the sole owner of approvals and task routing.
    """
    _safe_token(capability, "capability")
    if not isinstance(requirements, Mapping):
        raise ValueError("requirements must be a mapping")
    unknown = set(requirements) - _REQUIREMENT_KEYS
    if unknown:
        raise ValueError(f"unknown adapter requirements: {', '.join(sorted(unknown))}")
    entries = _normalize_manifests(manifests)
    preferences = _task_preferences(requirements)
    explicit_preferences = _explicit_preferences(requirements)
    ids = {entry["id"] for entry in entries}
    if any(preference not in ids for preference in preferences):
        raise ValueError("adapter preference is not a declared manifest")
    if any(preference not in preferences for preference in explicit_preferences):
        raise ValueError("explicit adapter preference is not declared by the task envelope")

    compatible = [entry for entry in entries if _matches(entry, capability, requirements)]
    compatible = [entry for entry in compatible if entry["id"] in preferences]
    fallback_candidates = compatible
    if explicit_preferences:
        preferred = [entry for entry in compatible if entry["id"] in explicit_preferences]
        if not preferred:
            raise ValueError("explicit adapter preference does not satisfy requirements")
        compatible = preferred
    if not compatible:
        raise ValueError("no adapter satisfies capability requirements")

    compatible.sort(key=lambda entry: _rank(entry, capability, requirements, explicit_preferences))
    primary = compatible[0]
    fallback = _find_fallback(primary, fallback_candidates, preferences, capability, requirements)
    return _compact(primary, fallback)


def _normalize_manifests(
    manifests: Union[Iterable[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    values = manifests.values() if isinstance(manifests, Mapping) else manifests
    if isinstance(values, (str, bytes)):
        raise ValueError("manifests must be a collection of manifest mappings")
    entries = []
    for manifest in values:
        if not isinstance(manifest, Mapping):
            raise ValueError("adapter manifest must be a mapping")
        _validate_manifest(manifest)
        entries.append(dict(manifest))
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("adapter manifest IDs must be unique")
    return entries


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    unknown = set(manifest) - _MANIFEST_KEYS
    if unknown:
        raise ValueError(f"adapter manifest has prohibited fields: {', '.join(sorted(unknown))}")
    required = ("id", "capabilities", "accepts", "outputs", "editable", "installed_skill", "implementation_ref", "fallback", "license_mode")
    missing = [field for field in required if field not in manifest]
    if missing:
        raise ValueError(f"adapter manifest missing fields: {', '.join(missing)}")
    _safe_token(manifest["id"], "adapter id")
    _string_list(manifest["capabilities"], "capabilities")
    _string_list(manifest["accepts"], "accepts")
    _string_list(manifest["outputs"], "outputs")
    _safe_token(manifest["installed_skill"], "installed_skill")
    reference = manifest["implementation_ref"]
    if not _is_safe_external_reference(reference):
        raise ValueError("adapter implementation_ref must be a safe external reference")
    if manifest["license_mode"] != "external-reference":
        raise ValueError("adapter must use external-reference license mode")
    if not isinstance(manifest["editable"], bool):
        raise ValueError("adapter editable must be a boolean")
    fallback = manifest["fallback"]
    if fallback is not None:
        _safe_token(fallback, "fallback")


def _matches(entry: Mapping[str, Any], capability: str, requirements: Mapping[str, Any]) -> bool:
    if capability not in entry["capabilities"]:
        return False
    skills = _installed_skills(requirements)
    if entry["installed_skill"] not in skills:
        return False
    contract = requirements.get("contract", requirements.get("accepted_contract"))
    if contract is not None and contract not in entry["accepts"]:
        return False
    output = requirements.get("output", requirements.get("required_output"))
    if output is None and requirements.get("format") == "html":
        output = "h5-preview"
    if output is not None and _output_name(output) not in entry["outputs"]:
        return False
    editable = requirements.get("editable")
    if editable is not None and (not isinstance(editable, bool) or entry["editable"] is not editable):
        return False
    return True


def _rank(entry: Mapping[str, Any], capability: str, requirements: Mapping[str, Any], preferences: list[str]) -> tuple[int, int, int, str]:
    adapter_id = entry["id"]
    preference_rank = preferences.index(adapter_id) if adapter_id in preferences else len(preferences)
    local_rank = 0 if adapter_id in _LOCAL_NO_CREDIT else 1
    order = _OVERLAY_ORDER if requirements.get("overlay") else _PRIMARY_ORDER.get(capability, ())
    declared_rank = order.index(adapter_id) if adapter_id in order else len(order)
    if requirements.get("overlay"):
        return preference_rank, declared_rank, local_rank, adapter_id
    return preference_rank, local_rank, declared_rank, adapter_id


def _find_fallback(
    primary: Mapping[str, Any],
    compatible: list[dict[str, Any]],
    task_preferences: list[str],
    capability: str,
    requirements: Mapping[str, Any],
) -> Union[dict[str, Any], None]:
    wanted = primary["fallback"]
    if wanted and wanted in task_preferences:
        for candidate in compatible:
            if candidate["id"] == wanted and _matches(candidate, capability, requirements):
                return candidate
    return None


def _compact(primary: Mapping[str, Any], fallback: Union[Mapping[str, Any], None]) -> dict[str, Any]:
    result = {
        "id": primary["id"],
        "version": primary.get("version"),
        "capabilities": list(primary["capabilities"]),
        "accepts": list(primary["accepts"]),
        "outputs": list(primary["outputs"]),
        "editable": primary["editable"],
        "installed_skill": primary["installed_skill"],
        "implementation_ref": primary["implementation_ref"],
    }
    result["fallback"] = None if fallback is None else {
        "id": fallback["id"],
        "implementation_ref": fallback["implementation_ref"],
        "installed_skill": fallback["installed_skill"],
    }
    return result


def _task_preferences(requirements: Mapping[str, Any]) -> list[str]:
    if "adapter_preferences" not in requirements:
        raise ValueError("adapter_preferences must be supplied by the immutable task envelope")
    values = requirements["adapter_preferences"]
    return _string_list(values, "adapter_preferences")


def _explicit_preferences(requirements: Mapping[str, Any]) -> list[str]:
    values = requirements.get("preferred_adapter", [])
    if isinstance(values, str):
        values = [values]
    return _string_list(values, "preferred_adapter") if values else []


def _installed_skills(requirements: Mapping[str, Any]) -> list[str]:
    if "installed_skills" not in requirements:
        raise ValueError("installed_skills must be supplied for deterministic adapter selection")
    return _string_list(requirements["installed_skills"], "installed_skills")


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must be a non-empty string list")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not repeat values")
    return list(value)


def _safe_token(value: Any, name: str) -> str:
    if not _is_safe_token(value):
        raise ValueError(f"{name} must be a safe token")
    return value


def _is_safe_external_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("external:"):
        return False
    return _is_safe_token(value[len("external:") :])


def _is_safe_token(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:-]*(?:\.[A-Za-z0-9][A-Za-z0-9_:-]*)*", value))


def _output_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("output must be a non-empty string")
    return {"html": "h5-preview"}.get(value, value)

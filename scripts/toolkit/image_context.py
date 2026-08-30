"""Deterministic metadata-only boundaries for isolated image tasks.

This module never reads media.  It validates immutable IDs, path strings, and
compact JSON-shaped handoffs before an isolated worker may access an artifact
or return metadata to its parent task.
"""

import base64
import binascii
import json
import math
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Optional


SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"
SAFE_ID_RE = re.compile(SAFE_ID_PATTERN)

CONTEXT_REQUIRED_FIELDS = frozenset(
    {
        "scope_identity",
        "allowed_image_artifact_ids",
        "allowed_character_pack_ids",
        "forbidden_scene_image_access",
        "max_review_previews",
        "context_budget",
    }
)
CONTEXT_OPTIONAL_FIELDS = frozenset({"continuity_exception"})
MAX_ALLOWED_IMAGE_ARTIFACT_IDS = 16
MAX_ALLOWED_CHARACTER_PACK_IDS = 8
MAX_CONTEXT_BUDGET_BYTES = 32_768

INDEPENDENT_CHARACTER_ASSET_TYPES = frozenset(
    {
        "character-model-sheet",
        "character-turnaround",
        "character-clothing-reference",
        "character-expression-reference",
        "character-pose-reference",
        "transparent-character-action",
        "character-identity-metadata",
    }
)
HISTORICAL_SCENE_IMAGE_TYPES = frozenset(
    {
        "scene",
        "scene-image",
        "storyboard",
        "storyboard-image",
        "b-roll",
        "b-roll-image",
        "motion-graphics",
        "motion-graphic-screenshot",
        "motion-graphics-screenshot",
        "motion-preview",
        "scene-preview",
    }
)
CURRENT_SCENE_IMAGE_TYPES = frozenset(
    {"scene-image", "scene-preview", "scene-render"}
)
IMAGE_FILE_SUFFIXES = frozenset(
    {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".heic",
        ".heif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".jxl",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    }
)
MEDIA_KINDS = frozenset({"audio", "data", "document", "image", "video"})
MEDIA_SUFFIX_RULES = {
    ".aac": ("audio", frozenset({"audio/aac"})),
    ".apng": ("image", frozenset({"image/apng"})),
    ".avif": ("image", frozenset({"image/avif"})),
    ".bmp": ("image", frozenset({"image/bmp"})),
    ".csv": ("data", frozenset({"text/csv"})),
    ".flac": ("audio", frozenset({"audio/flac"})),
    ".gif": ("image", frozenset({"image/gif"})),
    ".heic": ("image", frozenset({"image/heic"})),
    ".heif": ("image", frozenset({"image/heif"})),
    ".ico": (
        "image",
        frozenset({"image/vnd.microsoft.icon", "image/x-icon"}),
    ),
    ".jpeg": ("image", frozenset({"image/jpeg"})),
    ".jpg": ("image", frozenset({"image/jpeg"})),
    ".json": ("data", frozenset({"application/json"})),
    ".jxl": ("image", frozenset({"image/jxl"})),
    ".m4a": ("audio", frozenset({"audio/mp4", "audio/x-m4a"})),
    ".mkv": ("video", frozenset({"video/x-matroska"})),
    ".md": ("document", frozenset({"text/markdown"})),
    ".mov": ("video", frozenset({"video/quicktime"})),
    ".mp3": ("audio", frozenset({"audio/mpeg"})),
    ".mp4": ("video", frozenset({"video/mp4"})),
    ".pdf": ("document", frozenset({"application/pdf"})),
    ".png": ("image", frozenset({"image/png"})),
    ".svg": ("image", frozenset({"image/svg+xml"})),
    ".tif": ("image", frozenset({"image/tiff"})),
    ".tiff": ("image", frozenset({"image/tiff"})),
    ".tsv": ("data", frozenset({"text/tab-separated-values"})),
    ".txt": ("document", frozenset({"text/plain"})),
    ".wav": (
        "audio",
        frozenset({"audio/wav", "audio/wave", "audio/x-wav"}),
    ),
    ".webm": ("video", frozenset({"video/webm"})),
    ".webp": ("image", frozenset({"image/webp"})),
}
KNOWN_MIME_SUFFIXES = {
    mime_type: frozenset(
        suffix
        for suffix, (_, mime_types) in MEDIA_SUFFIX_RULES.items()
        if mime_type in mime_types
    )
    for _, mime_types in MEDIA_SUFFIX_RULES.values()
    for mime_type in mime_types
}
KNOWN_MIME_KINDS = {
    mime_type: media_kind
    for media_kind, mime_types in MEDIA_SUFFIX_RULES.values()
    for mime_type in mime_types
}
MIME_TYPE_RE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*"
)
URI_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
DATA_IMAGE_URL_RE = re.compile(r"data\s*:\s*image\s*/", re.IGNORECASE)
BASE64_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])"
    r"([A-Za-z0-9+/]+(?:[ \t\r\n]+[A-Za-z0-9+/]+)*={0,2})"
    r"(?![A-Za-z0-9+/=])"
)
PROMOTED_CHARACTER_ASSET_KINDS = frozenset(
    {
        "character-action",
        "character-clothing-reference",
        "character-expression-reference",
        "character-model-sheet",
        "character-pose-reference",
        "character-turnaround",
    }
)

COMPACT_RESULT_FIELDS = frozenset(
    {
        "artifact_ids",
        "paths",
        "summary",
        "metadata",
        "issues",
        "status",
        "user_decision_request",
        "review_previews",
    }
)
IMAGE_RESULT_STATUSES = frozenset(
    {"blocked", "waiting_external", "waiting_user", "succeeded", "failed", "cancelled"}
)
ISSUE_FIELDS = frozenset({"code", "artifact_id", "message", "severity"})
PAYLOAD_FIELD_MARKERS = frozenset(
    {
        "base64",
        "binary",
        "blob",
        "bytes",
        "data",
        "data_url",
        "image",
        "image_bytes",
        "image_data",
        "image_payload",
        "image_uri",
        "image_url",
        "images",
        "payload",
        "pixels",
        "preview_data",
        "preview_url",
        "thumbnail",
        "uri",
        "url",
    }
)
PROMPT_HISTORY_FIELD_MARKERS = frozenset(
    {
        "generation_history",
        "iteration_history",
        "prompt_history",
        "prompt_iteration_transcript",
        "prompt_iterations",
        "prompts",
    }
)


def authorize_image_access(
    context: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    historical: bool,
) -> None:
    """Raise unless *artifact* is exactly authorized by a closed image context."""
    normalized = validate_image_context(context)
    if not isinstance(historical, bool):
        raise ValueError("historical must be boolean")
    if not isinstance(artifact, Mapping):
        raise ValueError("image artifact must be an object")
    artifact_id = artifact.get("artifact_id")
    artifact_type = artifact.get("type")
    if not _safe_id(artifact_id) or not _safe_id(artifact_type):
        raise ValueError("image artifact requires safe artifact_id and type")

    declared_ids = set(normalized["allowed_image_artifact_ids"])
    continuity = normalized.get("continuity_exception")
    continuity_id = continuity["artifact_id"] if continuity is not None else None

    if historical:
        if _is_historical_scene_class(artifact):
            raise PermissionError("historical scene image access is forbidden")
        if not normalized["forbidden_scene_image_access"]:
            raise PermissionError("historical scene ban must remain enabled")
        if artifact_id not in declared_ids:
            raise PermissionError("undeclared image access is forbidden")
        if (
            not _is_independent_character_asset(artifact)
            or artifact.get("status") != "approved"
        ):
            raise PermissionError(
                "historical access requires an approved character asset"
            )
        return

    if artifact_type in CURRENT_SCENE_IMAGE_TYPES:
        if artifact_id in declared_ids:
            raise PermissionError(
                "current scene image requires an exact continuity exception"
            )
        if artifact_id != continuity_id:
            raise PermissionError(
                "current scene image requires an exact continuity exception"
            )
        return
    if artifact_id == continuity_id:
        raise PermissionError("continuity exception must name one current scene image")
    if artifact_id not in declared_ids:
        raise PermissionError("undeclared image access is forbidden")


def compact_image_result(
    context: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a closed compact handoff without media payloads or hidden paths."""
    normalized_context = validate_image_context(context)
    if not isinstance(result, Mapping):
        raise ValueError("image result must be an object")
    _reject_leaking_content(result)
    unknown = set(result) - COMPACT_RESULT_FIELDS
    if unknown:
        raise ValueError(
            "image result has unknown fields: " + ", ".join(sorted(unknown))
        )

    compact = dict(result)
    artifact_ids = _optional_id_list(compact, "artifact_ids")
    paths = _optional_path_list(compact, "paths")
    previews = _optional_path_list(compact, "review_previews")
    if len(paths) > len(artifact_ids):
        raise ValueError("image result contains an undeclared path")
    if len(previews) > normalized_context["max_review_previews"]:
        raise ValueError("image result exceeds the review preview budget")
    if any(
        not _path_is_bound_to_artifact(path, artifact_id)
        for path, artifact_id in zip(paths, artifact_ids)
    ):
        raise ValueError("image result contains an undeclared path")
    if any(
        not any(_path_is_bound_to_artifact(path, artifact_id) for artifact_id in artifact_ids)
        for path in previews
    ):
        raise ValueError("image result contains an undeclared path")

    summary = compact.get("summary")
    if summary is not None:
        _require_short_text(summary, "summary")
    decision_request = compact.get("user_decision_request")
    if decision_request is not None:
        _require_short_text(decision_request, "user_decision_request")
    status = compact.get("status")
    if status is not None and status not in IMAGE_RESULT_STATUSES:
        raise ValueError("image result status is not recognized")
    metadata = _validate_metadata(compact.get("metadata", {}))
    issues = _validate_issues(compact.get("issues", []))

    for key, value in (
        ("artifact_ids", artifact_ids),
        ("paths", paths),
        ("review_previews", previews),
        ("metadata", metadata),
        ("issues", issues),
    ):
        if key in compact:
            compact[key] = value
    try:
        serialized = json.dumps(
            compact,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("image result must be compact JSON metadata") from error
    if len(serialized) > normalized_context["context_budget"]:
        raise ValueError("image result exceeds the declared context budget")
    return compact


def validate_image_result_envelope(
    context: Mapping[str, Any], result: Mapping[str, Any]
) -> None:
    """Reject leaks or budget overflow anywhere in a persisted image-task result."""
    normalized_context = validate_image_context(context)
    if not isinstance(result, Mapping):
        raise ValueError("image task result must be an object")
    _reject_leaking_content(result)
    try:
        serialized = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("image task result must be compact JSON metadata") from error
    if len(serialized) > normalized_context["context_budget"]:
        raise ValueError("image task result exceeds the declared context budget")


def validate_result_envelope(result: Mapping[str, Any]) -> None:
    """Delegate the universal result boundary to the visual-media runtime."""
    from .visual_media_context import validate_result_envelope as validate_shared

    validate_shared(result)


def validate_image_task_constraints(
    constraints: Mapping[str, Any],
    *,
    capability: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Validate conditional image authority without changing non-image tasks."""
    if not isinstance(constraints, Mapping):
        raise ValueError("constraints must be an object")
    if (
        "visual_operation" in constraints
        and constraints["visual_operation"] not in {"image-generation", "non-image"}
    ):
        raise ValueError(
            "visual_operation must declare image-generation or non-image"
        )
    has_operation = "image_operation" in constraints
    has_context = "image_context" in constraints
    if capability == "structure.validate" and not has_operation:
        raise ValueError("structure.validate requires image_operation")
    if not has_operation and not has_context:
        return None
    if not has_operation:
        raise ValueError("image_context requires image_operation")
    operation = constraints["image_operation"]
    if operation not in {"generate", "structure-only", "image-inspect"}:
        raise ValueError(
            "image_operation must declare generate, structure-only, or image-inspect"
        )
    if capability == "structure.validate" and operation not in {
        "structure-only",
        "image-inspect",
    }:
        raise ValueError(
            "structure.validate image_operation must be structure-only or image-inspect"
        )
    if operation == "structure-only":
        if has_context:
            raise ValueError("structure-only must not include image_context")
        return None
    if not has_context or constraints["image_context"] is None:
        raise ValueError("declared image_operation requires image_context")
    return validate_image_context(constraints["image_context"])


def validate_declared_image_inputs(
    envelope: Mapping[str, Any], artifacts: Mapping[str, Mapping[str, Any]]
) -> bool:
    """Enforce exact image authority for every image-bearing task input."""
    if not isinstance(envelope, Mapping) or not isinstance(artifacts, Mapping):
        raise ValueError("image task authorization requires envelope and artifact maps")
    context = validate_image_task_constraints(
        envelope.get("constraints"), capability=envelope.get("capability")
    )
    inputs = envelope.get("inputs")
    if not isinstance(inputs, list) or not all(_safe_id(item) for item in inputs):
        raise ValueError("image task inputs must contain safe artifact IDs")
    declared_inputs = set(inputs)
    for artifact_id in inputs:
        artifact = artifacts.get(artifact_id)
        if artifact is not None:
            validate_media_artifact_metadata(artifact)
    visible_image_ids = {
        artifact_id
        for artifact_id in inputs
        if artifact_id in artifacts and artifact_is_image_bearing(artifacts[artifact_id])
    }
    capability = envelope.get("capability")
    output_contract = envelope.get("output_contract")
    explicitly_image_capable = (
        isinstance(capability, str) and capability.startswith("image.")
    ) or (
        isinstance(output_contract, str) and "image" in output_contract.lower()
    )
    visual_operation = None
    if isinstance(envelope.get("constraints"), Mapping):
        visual_operation = envelope["constraints"].get("visual_operation")
    if capability == "scene.produce":
        if visual_operation not in {"image-generation", "non-image"}:
            raise ValueError("scene.produce requires visual_operation")
        if visual_operation == "image-generation":
            explicitly_image_capable = True
            if envelope["constraints"].get("image_operation") != "generate":
                if context is None:
                    raise PermissionError("image generation requires image_context")
                raise ValueError("image-generation requires image_operation generate")
        elif envelope["constraints"].get("image_operation") == "generate":
            raise ValueError("non-image scene production cannot generate images")
    if context is None:
        if visible_image_ids or explicitly_image_capable:
            raise PermissionError("image-bearing task inputs require image_context")
        return True

    scope = context["scope_identity"]
    scope_id = scope["id"]
    if scope_id not in declared_inputs:
        raise PermissionError("image scope identity must be a declared task input")
    scope_artifact = artifacts.get(scope_id)
    expected_scope_types = {
        "scene-contract": {"scene-contract"},
        "character-asset-batch": {"character-asset-batch", "character-pack"},
    }
    if (
        scope_artifact is None
        or scope_artifact.get("type") not in expected_scope_types[scope["kind"]]
    ):
        raise PermissionError("image scope identity does not match its artifact")
    pack_ids = context["allowed_character_pack_ids"]
    if scope["kind"] == "scene-contract":
        cross_scope_ids = {
            artifact_id
            for artifact_id in declared_inputs
            if (
                (artifact := artifacts.get(artifact_id)) is not None
                and (
                    artifact.get("type") == "character-asset-batch"
                    or (
                        artifact.get("type") == "character-pack"
                        and artifact_id not in pack_ids
                    )
                )
            )
        }
        matching_scope_ids = {
            artifact_id
            for artifact_id in declared_inputs
            if (artifact := artifacts.get(artifact_id)) is not None
            and artifact.get("type") == "scene-contract"
        }
    else:
        cross_scope_ids = {
            artifact_id
            for artifact_id in declared_inputs
            if (artifact := artifacts.get(artifact_id)) is not None
            and artifact.get("type") == "scene-contract"
        }
        matching_scope_ids = {
            artifact_id
            for artifact_id in declared_inputs
            if (
                (artifact := artifacts.get(artifact_id)) is not None
                and (
                    artifact.get("type") == "character-asset-batch"
                    or (
                        artifact.get("type") == "character-pack"
                        and artifact_id not in pack_ids
                    )
                )
            )
        }
    if cross_scope_ids or matching_scope_ids != {scope_id}:
        raise PermissionError(
            f"image task requires exactly one {scope['kind']} scope input"
        )

    for pack_id in pack_ids:
        if pack_id not in declared_inputs:
            raise PermissionError("undeclared character pack access is forbidden")
        pack = artifacts.get(pack_id)
        if (
            pack is None
            or pack.get("status") != "approved"
            or pack.get("type") not in {"character-pack", "character-identity-metadata"}
        ):
            raise PermissionError("character pack requires approved identity provenance")

    image_ids = list(context["allowed_image_artifact_ids"])
    continuity = context.get("continuity_exception")
    if continuity is not None:
        image_ids.append(continuity["artifact_id"])
    if visible_image_ids - set(image_ids):
        raise PermissionError("undeclared image access is forbidden")
    for artifact_id in image_ids:
        if artifact_id not in declared_inputs:
            raise PermissionError("undeclared image access is forbidden")
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise PermissionError("declared image artifact does not exist")
        if not artifact_is_image_bearing(artifact) and artifact.get("type") != "character-identity-metadata":
            raise PermissionError("declared image artifact is not image-bearing")
        if "historical" not in artifact or not isinstance(artifact["historical"], bool):
            raise ValueError("image artifact requires explicit historical origin metadata")
        character_pack_id = artifact.get("character_pack_id")
        if character_pack_id is not None and character_pack_id not in pack_ids:
            raise PermissionError("image artifact has undeclared character pack provenance")
        authorize_image_access(context, artifact, historical=artifact["historical"])
    return True


def artifact_is_image_bearing(artifact: Mapping[str, Any]) -> bool:
    """Classify an Artifact from immutable metadata without reading its payload."""
    if not isinstance(artifact, Mapping):
        return False
    artifact_type = artifact.get("type")
    if artifact_type == "media":
        media_kind = artifact.get("media_kind")
        mime_type = artifact.get("mime_type")
        return media_kind == "image" or (
            isinstance(mime_type, str) and mime_type.lower().startswith("image/")
        )
    image_types = (
        INDEPENDENT_CHARACTER_ASSET_TYPES
        | {
            "b-roll-frame",
            "b-roll-image",
            "character-image",
            "image",
            "motion-graphics-preview",
            "motion-graphic-screenshot",
            "motion-graphics-screenshot",
            "scene-render",
            "scene-image",
            "storyboard-image",
            "storyboard-frame",
        }
    )
    if artifact_type in image_types:
        return artifact_type != "character-identity-metadata"
    if artifact_type == "promoted-asset":
        promotion = artifact.get("promotion")
        return isinstance(promotion, Mapping) and promotion.get("asset_kind") in PROMOTED_CHARACTER_ASSET_KINDS
    path = artifact.get("path")
    return isinstance(path, str) and PurePosixPath(path).suffix.lower() in IMAGE_FILE_SUFFIXES


def validate_media_artifact_metadata(artifact: Mapping[str, Any]) -> None:
    """Require declared media kind, MIME, and known suffix metadata to agree."""
    if artifact.get("type") != "media":
        return
    media_kind = artifact.get("media_kind")
    mime_type = artifact.get("mime_type")
    mime_kind = None
    if mime_type is not None:
        if not isinstance(mime_type, str) or MIME_TYPE_RE.fullmatch(mime_type) is None:
            raise ValueError("media input requires canonical mime_type")
        mime_top_level = mime_type.split("/", 1)[0]
        mime_kind = KNOWN_MIME_KINDS.get(
            mime_type,
            mime_top_level
            if mime_top_level in {"audio", "image", "video"}
            else "document",
        )
    if media_kind is None:
        if mime_kind is None:
            raise ValueError("media input requires canonical media_kind or mime_type")
        media_kind = mime_kind
    if media_kind not in MEDIA_KINDS:
        raise ValueError("media input has invalid media_kind")
    if mime_kind is not None and mime_kind != media_kind:
        raise ValueError("media_kind does not match mime_type")
    path = artifact.get("path")
    suffix = PurePosixPath(path).suffix.lower() if isinstance(path, str) else ""
    suffix_rule = MEDIA_SUFFIX_RULES.get(suffix)
    if suffix_rule is not None:
        suffix_kind, suffix_mime_types = suffix_rule
        if media_kind != suffix_kind:
            raise ValueError("media_kind conflicts with media suffix")
        if mime_type is not None and mime_type not in suffix_mime_types:
            raise ValueError("mime_type conflicts with media suffix")
    elif suffix:
        if media_kind == "image" or mime_kind == "image":
            raise ValueError("image media requires a recognized image extension")
        raise ValueError("media requires a recognized media suffix")
    else:
        raise ValueError("media requires a recognized media extension")
    if mime_type in KNOWN_MIME_SUFFIXES and suffix not in KNOWN_MIME_SUFFIXES[mime_type]:
        raise ValueError("mime_type conflicts with media suffix")


def validate_image_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized closed context or raise before any image work."""
    if not isinstance(context, Mapping):
        raise ValueError("image context must be an object")
    fields = set(context)
    missing = CONTEXT_REQUIRED_FIELDS - fields
    unknown = fields - CONTEXT_REQUIRED_FIELDS - CONTEXT_OPTIONAL_FIELDS
    if missing:
        raise ValueError("image context is missing fields: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError("image context has unknown fields: " + ", ".join(sorted(unknown)))

    normalized = dict(context)
    scope = normalized["scope_identity"]
    if (
        not isinstance(scope, Mapping)
        or set(scope) != {"kind", "id"}
        or scope.get("kind") not in {"scene-contract", "character-asset-batch"}
        or not _safe_id(scope.get("id"))
    ):
        raise ValueError("scope_identity must name one closed task scope")
    normalized["scope_identity"] = dict(scope)
    images = _id_list(
        normalized["allowed_image_artifact_ids"],
        "allowed_image_artifact_ids",
        max_items=MAX_ALLOWED_IMAGE_ARTIFACT_IDS,
    )
    packs = _id_list(
        normalized["allowed_character_pack_ids"],
        "allowed_character_pack_ids",
        max_items=MAX_ALLOWED_CHARACTER_PACK_IDS,
    )
    if set(images) & set(packs):
        raise ValueError("image context allowlists contain duplicates")
    if not isinstance(normalized["forbidden_scene_image_access"], bool):
        raise ValueError("forbidden_scene_image_access must be boolean")
    max_previews = normalized["max_review_previews"]
    if isinstance(max_previews, bool) or not isinstance(max_previews, int) or not 0 <= max_previews <= 1:
        raise ValueError("max_review_previews must be an integer from 0 to 1")
    budget = normalized["context_budget"]
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 1 <= budget <= MAX_CONTEXT_BUDGET_BYTES
    ):
        raise ValueError(
            f"context_budget must be a positive integer no greater than {MAX_CONTEXT_BUDGET_BYTES}"
        )

    continuity = normalized.get("continuity_exception")
    if continuity is not None:
        if not isinstance(continuity, Mapping):
            raise ValueError("continuity_exception must be an object")
        if set(continuity) != {"artifact_id", "user_requested", "reason"}:
            raise ValueError("continuity_exception must be closed")
        if not _safe_id(continuity.get("artifact_id")):
            raise ValueError("continuity_exception artifact_id must be safe")
        if continuity.get("user_requested") is not True:
            raise ValueError("continuity_exception user_requested must be true")
        reason = continuity.get("reason")
        _require_short_text(reason, "continuity_exception reason")
        if reason != reason.strip():
            raise ValueError("continuity_exception reason must be trimmed")
        if continuity["artifact_id"] in images:
            raise ValueError(
                "continuity_exception artifact_id must not be in the ordinary image allowlist"
            )
        normalized["continuity_exception"] = dict(continuity)

    normalized["allowed_image_artifact_ids"] = images
    normalized["allowed_character_pack_ids"] = packs
    return normalized


def _id_list(
    value: Any, label: str, *, max_items: Optional[int] = None
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if not all(_safe_id(item) for item in value):
        raise ValueError(f"{label} must contain safe artifact IDs")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    if max_items is not None and len(value) > max_items:
        raise ValueError(f"{label} exceeds its {max_items}-item limit")
    return list(value)


def _optional_id_list(value: Mapping[str, Any], key: str) -> list[str]:
    if key not in value:
        return []
    return _id_list(value[key], key)


def _optional_path_list(value: Mapping[str, Any], key: str) -> list[str]:
    if key not in value:
        return []
    paths = value[key]
    if not isinstance(paths, list) or not all(_project_path(path) for path in paths):
        raise ValueError(f"{key} must contain project-contained paths")
    allowed_roots = ("previews/",) if key == "review_previews" else ("artifacts/", "media/")
    if not all(path.startswith(allowed_roots) for path in paths):
        raise ValueError(f"{key} must contain project-contained paths")
    if len(set(paths)) != len(paths):
        raise ValueError(f"{key} must not contain duplicates")
    return list(paths)


def _validate_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    normalized = dict(value)
    for key, item in normalized.items():
        if not _safe_id(key):
            raise ValueError("metadata keys must be safe")
        if isinstance(item, (bytes, bytearray, memoryview, Mapping, list, tuple, set)):
            raise ValueError("metadata must contain compact scalar values")
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("metadata must contain compact scalar values")
        if isinstance(item, str) and (not item.strip() or len(item) > 500):
            raise ValueError("metadata must contain compact scalar values")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("metadata must contain compact scalar values")
    return normalized


def _is_historical_scene_class(artifact: Mapping[str, Any]) -> bool:
    artifact_type = artifact.get("type")
    if artifact_type in HISTORICAL_SCENE_IMAGE_TYPES:
        return True
    if artifact_type != "promoted-asset":
        return False
    promotion = artifact.get("promotion")
    return isinstance(promotion, Mapping) and promotion.get("asset_kind") in {
        "b-roll",
        "motion-graphics",
        "scene",
        "scene-preview",
        "storyboard",
    }


def _is_independent_character_asset(artifact: Mapping[str, Any]) -> bool:
    artifact_type = artifact.get("type")
    if artifact_type in INDEPENDENT_CHARACTER_ASSET_TYPES:
        return True
    if artifact_type != "promoted-asset":
        return False
    promotion = artifact.get("promotion")
    return (
        isinstance(promotion, Mapping)
        and promotion.get("ownership") == "cross-project-registry"
        and promotion.get("scope") == "project-independent"
        and promotion.get("asset_kind") in PROMOTED_CHARACTER_ASSET_KINDS
    )


def _validate_issues(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("issues must be a list")
    issues: list[dict[str, Any]] = []
    for issue in value:
        if not isinstance(issue, Mapping) or not set(issue) <= ISSUE_FIELDS:
            raise ValueError("issues must contain compact issue objects")
        if not _safe_id(issue.get("code")):
            raise ValueError("each image issue requires a stable code")
        if "artifact_id" in issue and not _safe_id(issue["artifact_id"]):
            raise ValueError("image issue artifact_id must be safe")
        for key in ("message", "severity"):
            if key in issue:
                _require_short_text(issue[key], f"image issue {key}")
        issues.append(dict(issue))
    return issues


def _reject_leaking_content(value: Any, *, key: str = "") -> None:
    normalized_key = key.lower().replace("-", "_")
    if normalized_key in PROMPT_HISTORY_FIELD_MARKERS or (
        "prompt" in normalized_key and ("history" in normalized_key or "iteration" in normalized_key)
    ):
        raise ValueError("image result must not contain prompt history")
    if normalized_key in PAYLOAD_FIELD_MARKERS or any(
        marker in normalized_key
        for marker in ("base64", "image_bytes", "image_payload", "data_url")
    ):
        raise ValueError("image result must not contain an image payload")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("image result must not contain an image payload")
    if isinstance(value, str) and value.lstrip().lower().startswith("data:image/"):
        raise ValueError("image result must not contain an image payload")
    if isinstance(value, str):
        compact_text = value.strip().lower()
        if (
            compact_text.startswith(("binary:", "data:"))
            or URI_SCHEME_RE.search(compact_text)
            or DATA_IMAGE_URL_RE.search(compact_text)
        ):
            raise ValueError("image result must not contain an image payload")
        if any(
            marker in compact_text
            for marker in ("prompt history", "prompt_history", "prompt iteration")
        ):
            raise ValueError("image result must not contain prompt history")
        if _contains_base64_token(value):
            raise ValueError("image result must not contain an image payload")
    if normalized_key and (
        normalized_key == "path"
        or normalized_key.endswith("_path")
        or normalized_key.endswith("_paths")
    ):
        raise ValueError("image result contains an undeclared path")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise ValueError("image result keys must be strings")
            _reject_leaking_content(child, key=child_key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_leaking_content(child)


def _contains_base64_token(value: str) -> bool:
    for match in BASE64_TOKEN_RE.finditer(value):
        candidate = match.group(1)
        chunks = re.split(r"\s+", candidate.strip())
        payload_text = "".join(chunks)
        if len(payload_text) < 128 or len(payload_text) % 4 != 0:
            continue
        try:
            decoded = base64.b64decode(payload_text, validate=True)
        except (binascii.Error, ValueError):
            continue
        if _looks_like_media_payload(decoded):
            return True
    return False


def _looks_like_media_payload(value: bytes) -> bool:
    if value.startswith(
        (
            b"\x89PNG\r\n\x1a\n",
            b"\xff\xd8\xff",
            b"GIF87a",
            b"GIF89a",
            b"BM",
            b"II*\x00",
            b"MM\x00*",
            b"\x00\x00\x01\x00",
            b"fLaC",
            b"OggS",
            b"ID3",
        )
    ):
        return True
    if len(value) >= 12 and value.startswith(b"RIFF") and value[8:12] in {
        b"WEBP",
        b"WAVE",
    }:
        return True
    if len(value) >= 12 and value[4:8] == b"ftyp":
        return True
    stripped = value.lstrip().lower()
    return stripped.startswith((b"<svg", b"<?xml")) and b"<svg" in stripped[:512]


def _project_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return False
    path = PurePosixPath(value)
    return all(part not in {"", ".", ".."} for part in path.parts)


def _path_is_bound_to_artifact(value: str, artifact_id: str) -> bool:
    path = PurePosixPath(value)
    return artifact_id in path.parts or path.stem == artifact_id


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and SAFE_ID_RE.fullmatch(value) is not None


def _require_short_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"{label} must be non-empty compact text")

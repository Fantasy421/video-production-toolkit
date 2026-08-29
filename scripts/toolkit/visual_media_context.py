"""Metadata-only runtime boundaries for isolated visual-media tasks.

The functions in this module inspect dictionaries and path strings only.  They
never dereference an Artifact path or invoke a media parser.
"""

import json
import math
import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any, Optional


SAFE_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"
)
HANDOFF_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
MIME_TYPE_RE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*"
)
CHECKSUM_RE = re.compile(r"[A-Fa-f0-9]{8,128}")
BASE64_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9+/_=-])"
    r"([A-Za-z0-9+/_-]+={0,2}(?:\s+[A-Za-z0-9+/_-]+={0,2})*)"
    r"(?![A-Za-z0-9+/_=-])"
)
REMOTE_URL_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:https?|ftp|ftps|file|s3|gs|ipfs|ssh)://[^\s<>\"']+",
    re.IGNORECASE,
)
SCHEME_RELATIVE_URL_RE = re.compile(r"(?<!:)//[^\s<>\"']+")
URI_SCHEME_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,63}:(?=[^\s])"
)
DATA_URL_RE = re.compile(
    r"(?<![A-Za-z0-9_])data\s*:[^,\r\n]*,", re.IGNORECASE
)
HTML_MEDIA_RE = re.compile(
    r"<(?:audio|canvas|embed|img|object|picture|source|svg|video)\b",
    re.IGNORECASE,
)

VISUAL_MEDIA_OPERATIONS = frozenset(
    {
        "none",
        "image-generate",
        "image-edit",
        "image-inspect",
        "video-generate",
        "video-edit",
        "video-render",
        "video-inspect",
        "frame-extract",
        "contact-sheet",
    }
)
ACTIVE_VISUAL_MEDIA_OPERATIONS = VISUAL_MEDIA_OPERATIONS - {"none"}
VISUAL_MEDIA_SCOPE_KINDS = frozenset(
    {"scene-contract", "character-asset-batch", "review-batch"}
)
VISUAL_MEDIA_CAPABILITIES = frozenset(
    {
        "visual.preview",
        "scene.produce",
        "motion.preview",
        "motion.produce",
        "timeline.assemble",
        "review.package",
    }
)
VISUAL_ARTIFACT_TYPES = frozenset(
    {
        "b-roll",
        "b-roll-frame",
        "b-roll-image",
        "app-capture",
        "app-screenshot",
        "browser-capture",
        "browser-screenshot",
        "character-clothing-reference",
        "character-expression-reference",
        "character-image",
        "character-model-sheet",
        "character-pose-reference",
        "character-turnaround",
        "contact-sheet",
        "frame",
        "evidence-capture",
        "evidence-screenshot",
        "image",
        "keyframe",
        "motion-graphic-screenshot",
        "motion-graphics",
        "motion-graphics-preview",
        "motion-graphics-screenshot",
        "motion-preview",
        "review-preview",
        "scene",
        "scene-image",
        "scene-preview",
        "scene-render",
        "scene-video",
        "storyboard",
        "storyboard-frame",
        "storyboard-image",
        "screenshot",
        "thumbnail",
        "transparent-character-action",
        "video",
        "visual-preview",
    }
)
NON_VISUAL_ARTIFACT_TYPES = frozenset(
    {
        "approval",
        "audio",
        "captions",
        "character-asset-batch",
        "character-identity-metadata",
        "character-pack",
        "data",
        "decision-pack",
        "document",
        "input",
        "layout-pack",
        "license-document",
        "motion-contract",
        "narration",
        "project",
        "report",
        "review-pack",
        "scene-contract",
        "semantic-beats",
        "style-pack",
        "task-result",
        "timeline",
        "uploaded-audio",
        "voice-profile",
        "voice-source-decision",
        "voice-timing",
        "voiceover",
    }
)
NON_VISUAL_CAPABILITIES = frozenset(
    {
        "project.manage",
        "narration.plan",
        "voice.prepare",
        "storyboard.plan",
        "structure.validate",
        "captions.produce",
        "representative-slice.produce",
    }
)
VISUAL_NAME_TOKENS = frozenset(
    {
        "image",
        "video",
        "visual",
        "frame",
        "keyframe",
        "preview",
        "render",
        "storyboard",
        "screenshot",
        "thumbnail",
    }
)
AMBIGUOUS_MEDIA_TOKENS = frozenset({"binary", "blob", "capture", "media", "pixel"})
RESERVED_PATH_AUTHORITY_IDS = frozenset(
    {"artifact", "artifacts", "media", "preview", "previews"}
)
INDEPENDENT_CHARACTER_ASSET_TYPES = frozenset(
    {
        "character-clothing-reference",
        "character-expression-reference",
        "character-model-sheet",
        "character-pose-reference",
        "character-turnaround",
        "transparent-character-action",
        "character-identity-metadata",
    }
)
VISUAL_PROMOTED_ASSET_KINDS = frozenset(
    {
        "b-roll",
        "character-action",
        "character-clothing-reference",
        "character-expression-reference",
        "character-model-sheet",
        "character-pose-reference",
        "character-turnaround",
        "motion-graphics",
        "scene",
        "scene-preview",
        "storyboard",
    }
)
CHARACTER_PROMOTED_ASSET_KINDS = frozenset(
    {
        "character-action",
        "character-clothing-reference",
        "character-expression-reference",
        "character-model-sheet",
        "character-pose-reference",
        "character-turnaround",
    }
)

IMAGE_SUFFIXES = frozenset(
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
VIDEO_SUFFIXES = frozenset(
    {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}
)
NON_VISUAL_SUFFIX_KINDS = {
    ".aac": "audio",
    ".csv": "data",
    ".flac": "audio",
    ".json": "data",
    ".m4a": "audio",
    ".md": "document",
    ".mp3": "audio",
    ".pdf": "document",
    ".tsv": "data",
    ".txt": "document",
    ".wav": "audio",
}
MEDIA_SUFFIX_KINDS = {
    **{suffix: "image" for suffix in IMAGE_SUFFIXES},
    **{suffix: "video" for suffix in VIDEO_SUFFIXES},
    **NON_VISUAL_SUFFIX_KINDS,
}
KNOWN_MIME_SUFFIXES = {
    "image/apng": frozenset({".apng"}),
    "image/avif": frozenset({".avif"}),
    "image/bmp": frozenset({".bmp"}),
    "image/gif": frozenset({".gif"}),
    "image/heic": frozenset({".heic"}),
    "image/heif": frozenset({".heif"}),
    "image/vnd.microsoft.icon": frozenset({".ico"}),
    "image/jpeg": frozenset({".jpeg", ".jpg"}),
    "image/jxl": frozenset({".jxl"}),
    "image/png": frozenset({".png"}),
    "image/svg+xml": frozenset({".svg"}),
    "image/tiff": frozenset({".tif", ".tiff"}),
    "image/webp": frozenset({".webp"}),
    "video/mp4": frozenset({".m4v", ".mp4"}),
    "video/mpeg": frozenset({".mpeg", ".mpg"}),
    "video/quicktime": frozenset({".mov"}),
    "video/webm": frozenset({".webm"}),
    "video/x-msvideo": frozenset({".avi"}),
    "video/x-matroska": frozenset({".mkv"}),
}
MEDIA_KINDS = frozenset({"audio", "data", "document", "image", "video"})
VISUAL_RESULT_BUDGET_BYTES = 32_768
MAX_ALLOWED_ARTIFACT_IDS = 16
MAX_REVIEW_BATCH_IDS = 8
MAX_HANDOFF_ITEMS = 8

CONTEXT_FIELDS = frozenset(
    {
        "scope_identity",
        "allowed_artifact_ids",
        "historical_access",
        "continuity_exception",
        "max_review_previews",
        "context_budget_bytes",
    }
)
HANDOFF_FIELDS = frozenset(
    {
        "artifact_ids",
        "paths",
        "media",
        "checks",
        "issues",
        "summary",
        "review_preview_path",
    }
)
MEDIA_METADATA_FIELDS = frozenset(
    {
        "kind",
        "format",
        "mime_type",
        "width",
        "height",
        "duration_ms",
        "fps",
        "readiness",
        "checksum",
    }
)
ISSUE_FIELDS = frozenset({"code", "artifact_id", "message", "severity"})
PROMPT_HISTORY_KEYS = frozenset(
    {
        "generation_history",
        "generation_log",
        "generation_transcript",
        "chat_history",
        "conversation_history",
        "iteration_history",
        "prompt_history",
        "prompt_transcript",
        "prompt_iteration_history",
        "prompt_iteration_transcript",
        "prompt_iterations",
        "prompts",
        "request_messages",
        "system_prompt",
        "negative_prompt",
    }
)
PAYLOAD_KEYS = frozenset(
    {
        "base64",
        "binary",
        "blob",
        "bytes",
        "contact_sheet",
        "contact_sheets",
        "data",
        "data_url",
        "decoded_frames",
        "frame_array",
        "frames",
        "image_bytes",
        "image_data",
        "image_payload",
        "image_url",
        "images",
        "payload",
        "pixel_array",
        "pixels",
        "preview_data",
        "preview_url",
        "screenshot",
        "screenshots",
        "thumbnail",
        "thumbnails",
        "video_bytes",
        "video_data",
        "video_payload",
        "video_url",
    }
)
PAYLOAD_KEY_TOKENS = frozenset(
    {
        "base64",
        "binary",
        "blob",
        "blobs",
        "bytes",
        "data",
        "payload",
        "payloads",
    }
)
HISTORY_KEY_TOKENS = frozenset({"history", "messages", "transcript", "turns"})
HISTORY_CONTEXT_TOKENS = frozenset(
    {
        "assistant",
        "chat",
        "conversation",
        "generation",
        "instruction",
        "iteration",
        "negative",
        "prompt",
        "request",
        "response",
        "system",
    }
)
HISTORY_CONTAINER_TOKENS = frozenset(
    {"history", "log", "logs", "messages", "record", "records", "trace", "turn", "turns"}
)
SAFE_ID_VALUE_KEYS = frozenset(
    {
        "approval_id",
        "artifact_id",
        "artifact_ids",
        "artifacts",
        "character_ids",
        "character_pack_id",
        "claim_token",
        "code",
        "contract_id",
        "gate_target_id",
        "id",
        "inputs",
        "issue_code",
        "narration_id",
        "output_artifact_ids",
        "output_contract",
        "parent_id",
        "parents",
        "profile_id",
        "project_id",
        "scene_id",
        "source_decision_id",
        "target_id",
        "task_id",
        "timeline_id",
        "type",
        "uploaded_audio_id",
        "voice_id",
        "voice_timing_id",
        "voiceover_id",
        "worker_id",
    }
)
TYPED_CHECKSUM_KEYS = frozenset({"checksum", "digest", "hash", "sha256", "sha512"})
TYPED_CHECKSUM_TEXT_RE = re.compile(
    r"(?:md5|sha(?:1|224|256|384|512))[:=][A-Fa-f0-9]{8,128}"
)
SAFE_SCHEME_TOKEN_PREFIXES = {
    "checks": frozenset({"adapter-selected"}),
    "consent_provenance": frozenset({"user"}),
    "decision_provenance": frozenset({"user"}),
    "identity_provenance": frozenset({"user"}),
    "profile_provenance": frozenset({"user"}),
    "provenance": frozenset({"chatcut", "user", "user-upload"}),
    "validation_evidence": frozenset({"isolated-image-inspect"}),
}
VISUAL_INSPECT_OPERATIONS = frozenset({"image-inspect", "video-inspect"})
VISUAL_OUTPUT_OPERATIONS = ACTIVE_VISUAL_MEDIA_OPERATIONS - VISUAL_INSPECT_OPERATIONS


def validate_visual_media_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return a closed normalized visual-media authority context."""
    if not isinstance(context, Mapping):
        raise ValueError("visual media context must be an object")
    fields = set(context)
    missing = CONTEXT_FIELDS - fields
    unknown = fields - CONTEXT_FIELDS
    if missing:
        raise ValueError(
            "visual media context is missing fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise ValueError(
            "visual media context has unknown fields: " + ", ".join(sorted(unknown))
        )

    normalized = dict(context)
    scope = normalized["scope_identity"]
    if not isinstance(scope, Mapping) or set(scope) != {"kind", "id"}:
        raise ValueError("scope_identity must be one closed visual media scope")
    scope_kind = scope.get("kind")
    scope_id = scope.get("id")
    if scope_kind not in VISUAL_MEDIA_SCOPE_KINDS:
        raise ValueError("scope_identity kind is not recognized")
    if scope_kind == "review-batch":
        try:
            scope_id = _id_list(
                scope_id,
                "review-batch scope_identity id",
                min_items=1,
                max_items=MAX_REVIEW_BATCH_IDS,
            )
        except ValueError as error:
            raise ValueError(f"review-batch scope is invalid: {error}") from error
    elif not _safe_id(scope_id):
        raise ValueError("scope_identity id must be one safe Artifact ID")
    normalized["scope_identity"] = {"kind": scope_kind, "id": scope_id}

    allowed = _id_list(
        normalized["allowed_artifact_ids"],
        "allowed_artifact_ids",
        max_items=MAX_ALLOWED_ARTIFACT_IDS,
    )
    normalized["allowed_artifact_ids"] = allowed
    if normalized["historical_access"] != "character-only":
        raise ValueError("historical_access must be character-only")
    max_previews = normalized["max_review_previews"]
    if (
        isinstance(max_previews, bool)
        or not isinstance(max_previews, int)
        or not 0 <= max_previews <= 1
    ):
        raise ValueError("max_review_previews must be an integer from 0 to 1")
    budget = normalized["context_budget_bytes"]
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 1 <= budget <= VISUAL_RESULT_BUDGET_BYTES
    ):
        raise ValueError(
            "context_budget_bytes must be a positive integer no greater than 32768"
        )

    continuity = normalized["continuity_exception"]
    if continuity is not None:
        if not isinstance(continuity, Mapping):
            raise ValueError("continuity_exception must be null or an object")
        if set(continuity) != {"artifact_id", "user_requested", "reason"}:
            raise ValueError("continuity_exception must be closed")
        if not _safe_id(continuity.get("artifact_id")):
            raise ValueError("continuity_exception artifact_id must be safe")
        if continuity.get("user_requested") is not True:
            raise ValueError("continuity_exception user_requested must be true")
        reason = continuity.get("reason")
        _require_text(reason, "continuity_exception reason", max_length=500)
        if reason != reason.strip():
            raise ValueError("continuity_exception reason must be trimmed")
        if continuity["artifact_id"] in allowed:
            raise ValueError(
                "continuity_exception must be separate from allowed_artifact_ids"
            )
        normalized["continuity_exception"] = dict(continuity)
    return normalized


def project_legacy_image_context(
    envelope: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """Project a readable v2 image envelope without mutating persisted history."""
    if not isinstance(envelope, Mapping):
        raise ValueError("legacy image envelope must be an object")
    constraints = envelope.get("constraints")
    if not isinstance(constraints, Mapping):
        return None
    has_operation = "image_operation" in constraints
    has_context = "image_context" in constraints
    if not has_operation and not has_context:
        return None
    if not has_operation:
        raise ValueError("legacy image_context requires image_operation")
    operation = constraints["image_operation"]
    if operation == "structure-only":
        if has_context:
            raise ValueError("legacy structure-only must not include image_context")
        return None
    if operation not in {"generate", "image-inspect"}:
        raise ValueError("legacy image_operation is not recognized")
    if not has_context:
        raise ValueError("legacy visual operation requires image_context")

    # Delayed import keeps image_context free to delegate its universal scrubber
    # back to this module without an import cycle.
    from .image_context import validate_image_context

    old = validate_image_context(constraints["image_context"])
    projected_context = {
        "scope_identity": dict(old["scope_identity"]),
        "allowed_artifact_ids": list(old["allowed_image_artifact_ids"]),
        "historical_access": "character-only",
        "continuity_exception": (
            dict(old["continuity_exception"])
            if old.get("continuity_exception") is not None
            else None
        ),
        "max_review_previews": old["max_review_previews"],
        "context_budget_bytes": old["context_budget"],
    }
    return validate_visual_media_context(projected_context)


def classify_visual_media_artifact(artifact: Mapping[str, Any]) -> str:
    """Classify an Artifact exclusively from its declared metadata."""
    if not isinstance(artifact, Mapping):
        raise ValueError("visual media Artifact metadata must be an object")
    artifact_type = artifact.get("type")
    media_kind = artifact.get("media_kind")
    mime_type = artifact.get("mime_type")
    path = artifact.get("path")
    suffix = PurePosixPath(path).suffix.lower() if isinstance(path, str) else ""

    if "path" in artifact and not _project_path(path):
        raise ValueError("Artifact path must be project-contained")

    if "media_kind" in artifact and media_kind is None:
        raise ValueError("visual media Artifact metadata is ambiguous")
    if media_kind is not None and media_kind not in MEDIA_KINDS:
        raise ValueError("media_kind is not recognized")
    mime_kind = _mime_kind(mime_type)
    suffix_kind = MEDIA_SUFFIX_KINDS.get(suffix)
    type_is_visual = _artifact_type_is_visual(artifact)

    declared_kinds = {
        kind for kind in (media_kind, mime_kind, suffix_kind) if kind is not None
    }
    if "image" in declared_kinds and "video" in declared_kinds:
        raise ValueError("visual media metadata conflicts between image and video")
    if declared_kinds & {"image", "video"} and declared_kinds & {
        "audio",
        "data",
        "document",
    }:
        raise ValueError("visual media metadata conflicts with non-visual media_kind")
    if type_is_visual and declared_kinds & {"audio", "data", "document"}:
        raise ValueError("visual Artifact type conflicts with non-visual metadata")

    if artifact_type == "media" and not declared_kinds:
        raise ValueError("media Artifact requires canonical kind, MIME type, or suffix")
    if media_kind is not None and mime_kind is not None and media_kind != mime_kind:
        raise ValueError("media_kind does not match mime_type")
    if media_kind is not None and suffix_kind is not None and media_kind != suffix_kind:
        raise ValueError("media_kind conflicts with media suffix")
    if mime_kind is not None and suffix_kind is not None and mime_kind != suffix_kind:
        raise ValueError("mime_type conflicts with media suffix")
    if (
        mime_type in KNOWN_MIME_SUFFIXES
        and suffix
        and suffix not in KNOWN_MIME_SUFFIXES[mime_type]
    ):
        raise ValueError("mime_type conflicts with media suffix")

    if media_kind in {"image", "video"}:
        classification = media_kind
    elif mime_kind in {"image", "video"}:
        classification = mime_kind
    elif suffix_kind in {"image", "video"}:
        classification = suffix_kind
    elif type_is_visual:
        classification = "visual"
    elif (
        artifact_type in NON_VISUAL_ARTIFACT_TYPES
        or media_kind in {"audio", "data", "document"}
        or mime_kind in {"audio", "data", "document"}
        or suffix_kind in {"audio", "data", "document"}
    ):
        classification = "non-visual"
    else:
        raise ValueError("visual media Artifact metadata is ambiguous and cannot classify")

    if classification != "non-visual" and "path" in artifact:
        artifact_id = artifact.get("artifact_id")
        if not _safe_id(artifact_id) or not _path_is_bound_to_artifact(
            path, artifact_id
        ):
            raise ValueError("visual Artifact path must be bound to its exact Artifact ID")
    return classification


def classify_visual_media_task(
    envelope: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    produced_artifacts: Iterable[Mapping[str, Any]] = (),
) -> str:
    """Classify a task from every immutable runtime signal."""
    if not isinstance(envelope, Mapping) or not isinstance(artifacts, Mapping):
        raise ValueError("visual media task classification requires mappings")
    constraints = envelope.get("constraints", {})
    if not isinstance(constraints, Mapping):
        raise ValueError("visual media task constraints must be an object")
    operation = constraints.get("visual_media_operation")
    if operation is not None and operation not in VISUAL_MEDIA_OPERATIONS:
        raise ValueError("visual_media_operation is not recognized")
    is_visual = operation in ACTIVE_VISUAL_MEDIA_OPERATIONS
    legacy_visual = constraints.get("image_operation") in {
        "generate",
        "image-inspect",
    }
    is_visual = is_visual or legacy_visual
    capability = envelope.get("capability")
    if capability is not None or not legacy_visual:
        capability_classification = _classify_capability(capability)
        is_visual = is_visual or capability_classification == "visual"
    output_contract = envelope.get("output_contract")
    if output_contract is not None or not legacy_visual:
        output_classification = _classify_output_contract(output_contract)
        is_visual = is_visual or output_classification == "visual"

    inputs = envelope.get("inputs", [])
    if isinstance(inputs, list):
        for artifact_id in inputs:
            artifact = artifacts.get(artifact_id)
            if artifact is not None:
                is_visual = (
                    classify_visual_media_artifact(artifact) != "non-visual"
                    or is_visual
                )
    produced_values: Iterable[Any]
    if isinstance(produced_artifacts, Mapping):
        produced_values = produced_artifacts.values()
    else:
        produced_values = produced_artifacts
    for artifact in produced_values:
        is_visual = classify_visual_media_artifact(artifact) != "non-visual" or is_visual
    return "visual" if is_visual else "non-visual"


def validate_declared_visual_media_inputs(
    envelope: Mapping[str, Any], artifacts: Mapping[str, Mapping[str, Any]]
) -> None:
    """Enforce exact visual scope and Artifact authority before task execution."""
    if not isinstance(envelope, Mapping) or not isinstance(artifacts, Mapping):
        raise ValueError("visual media authorization requires envelope and Artifact maps")
    constraints = envelope.get("constraints")
    if not isinstance(constraints, Mapping):
        raise ValueError("visual media task constraints must be an object")
    has_new = (
        "visual_media_operation" in constraints
        or "visual_media_context" in constraints
    )
    has_legacy = "image_operation" in constraints or "image_context" in constraints
    if has_new and has_legacy:
        raise ValueError("task must not mix visual media and legacy image authority")
    if has_legacy:
        from .image_context import validate_declared_image_inputs

        validate_declared_image_inputs(envelope, artifacts)
        return

    operation = constraints.get("visual_media_operation")
    if operation not in VISUAL_MEDIA_OPERATIONS:
        raise ValueError("task requires a recognized visual_media_operation")
    inputs = _id_list(envelope.get("inputs"), "task inputs")
    if len(inputs) != len(set(inputs)):
        raise ValueError("task inputs must not contain duplicates")
    for artifact_id in inputs:
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise PermissionError(f"task input Artifact does not exist: {artifact_id}")
        declared_id = artifact.get("artifact_id")
        if declared_id is not None and declared_id != artifact_id:
            raise ValueError("Artifact map key does not match artifact_id metadata")
        classify_visual_media_artifact(artifact)

    classification = classify_visual_media_task(envelope, artifacts)
    if operation == "none":
        if "visual_media_context" in constraints:
            raise ValueError("visual_media_operation none must not include context")
        if classification == "visual":
            raise ValueError("visual media task cannot declare operation none")
        return
    if "visual_media_context" not in constraints:
        raise ValueError("visual media operation requires visual_media_context")
    context = validate_visual_media_context(constraints["visual_media_context"])
    if classification != "visual":
        raise ValueError("declared visual media operation did not classify as visual")
    _validate_operation_output_contract(operation, envelope.get("output_contract"))

    input_set = set(inputs)
    scope = context["scope_identity"]
    scope_kind = scope["kind"]
    scope_types = {
        "scene-contract": {"scene-contract"},
        "character-asset-batch": {"character-asset-batch", "character-pack"},
    }
    if scope_kind == "review-batch":
        review_ids = set(scope["id"])
        if review_ids != input_set:
            raise PermissionError(
                "review-batch scope must be the exact declared task input set"
            )
    else:
        scope_id = scope["id"]
        scope_artifact = artifacts.get(scope_id)
        if scope_id not in input_set or (
            scope_artifact is None
            or scope_artifact.get("type") not in scope_types[scope_kind]
        ):
            raise PermissionError("visual media scope identity does not match its Artifact")
        if (
            scope_kind == "character-asset-batch"
            and scope_artifact.get("status") != "approved"
        ):
            raise PermissionError(
                "character-asset-batch scope Artifact must be approved"
            )
        scene_scope_ids = {
            item
            for item in inputs
            if artifacts[item].get("type") == "scene-contract"
        }
        character_scope_ids = {
            item
            for item in inputs
            if artifacts[item].get("type")
            in {"character-asset-batch", "character-pack"}
        }
        matching = scene_scope_ids if scope_kind == "scene-contract" else character_scope_ids
        neighboring = character_scope_ids if scope_kind == "scene-contract" else scene_scope_ids
        if matching != {scope_id} or neighboring:
            raise PermissionError(
                f"visual media task requires exactly one {scope_kind} scope and no neighbor"
            )

    allowed = set(context["allowed_artifact_ids"])
    continuity = context["continuity_exception"]
    continuity_id = continuity["artifact_id"] if continuity is not None else None
    if not allowed <= input_set:
        raise PermissionError("allowed visual Artifact IDs must be declared task inputs")
    for artifact_id in allowed:
        artifact = artifacts[artifact_id]
        if artifact.get("historical") is True and not _is_approved_character_asset(
            artifact
        ):
            raise PermissionError(
                "historical visual access is limited to approved character assets"
            )
        if not _is_approved_character_asset(artifacts[artifact_id]):
            raise PermissionError(
                "ordinary allowed Artifact IDs are limited to independently approved "
                "character assets; scene media requires one continuity exception"
            )
    authorized_visual_ids = set(allowed)
    if continuity_id is not None:
        if continuity_id not in input_set:
            raise PermissionError("continuity exception must be an exact task input")
        authorized_visual_ids.add(continuity_id)
    if scope_kind == "review-batch":
        authorized_visual_ids.update(scope["id"])

    visual_input_ids = {
        artifact_id
        for artifact_id in inputs
        if classify_visual_media_artifact(artifacts[artifact_id]) != "non-visual"
    }
    if scope_kind == "review-batch" and visual_input_ids != set(scope["id"]):
        raise PermissionError("review-batch must be the exact current visual input set")
    undeclared_visual = visual_input_ids - authorized_visual_ids
    if undeclared_visual:
        raise PermissionError(
            "undeclared visual media input is forbidden: "
            + ", ".join(sorted(undeclared_visual))
        )
    if continuity_id is not None and continuity_id not in visual_input_ids:
        raise PermissionError(
            "continuity exception must name one exact current visual Artifact"
        )
    for artifact_id in visual_input_ids:
        artifact = artifacts[artifact_id]
        if "historical" not in artifact or not isinstance(
            artifact["historical"], bool
        ):
            raise ValueError(
                "visual Artifact requires explicit historical origin metadata"
            )
        historical = artifact["historical"]
        if historical and not _is_approved_character_asset(artifact):
            raise PermissionError(
                "historical visual access is limited to approved character assets"
            )
        if artifact_id == continuity_id and historical:
            raise PermissionError("continuity exception must name one current Artifact")


def validate_visual_media_operation_outputs(
    operation: str,
    produced_artifacts: Iterable[Mapping[str, Any]],
    handoff: Optional[Mapping[str, Any]] = None,
    *,
    status: str = "succeeded",
) -> None:
    """Enforce producer outputs and report-only inspection without media access."""
    expected = _operation_output_kind(operation)
    if expected is None:
        return
    produced = list(produced_artifacts)
    produced_kinds = []
    for artifact in produced:
        kind = classify_visual_media_artifact(artifact)
        produced_kinds.append(kind)
        if operation in VISUAL_INSPECT_OPERATIONS and kind != "non-visual":
            raise ValueError(
                f"visual media operation {operation} is report-only and cannot "
                "return visual output"
            )
        if kind == "non-visual":
            continue
        if kind == "visual" or kind != expected:
            raise ValueError(
                f"visual media operation {operation} cannot return {kind} output"
            )
    if handoff is not None:
        media = handoff.get("media") if isinstance(handoff, Mapping) else None
        handoff_kind = media.get("kind") if isinstance(media, Mapping) else None
        handoff_mime = media.get("mime_type") if isinstance(media, Mapping) else None
        if handoff_kind is not None and handoff_kind != expected:
            raise ValueError(
                f"visual media operation {operation} cannot declare {handoff_kind} handoff"
            )
        if handoff_mime is not None and (
            not isinstance(handoff_mime, str)
            or not handoff_mime.startswith(f"{expected}/")
        ):
            raise ValueError(
                f"visual media operation {operation} cannot declare {handoff_mime} handoff"
            )
    else:
        handoff_kind = None
    if (
        status == "succeeded"
        and operation in VISUAL_OUTPUT_OPERATIONS
        and expected not in produced_kinds
    ):
        raise ValueError(
            f"visual media operation {operation} must return at least one compatible "
            "visual output"
        )
    if (
        status == "succeeded"
        and operation in VISUAL_OUTPUT_OPERATIONS
        and handoff_kind != expected
    ):
        raise ValueError(
            f"visual media operation {operation} requires compatible media.kind in its handoff"
        )


def compact_visual_media_result(
    context: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    """Return one closed, bounded, metadata-only visual-media handoff."""
    normalized_context = validate_visual_media_context(context)
    compact = validate_compact_visual_media_handoff(result)
    artifact_ids = compact["artifact_ids"]
    paths = compact["paths"]
    if any(
        not any(_path_is_bound_to_artifact(path, artifact_id) for artifact_id in artifact_ids)
        for path in paths
    ):
        raise ValueError("visual media handoff contains an undeclared path")
    issues = _validate_issues(compact["issues"], artifact_ids, normalized_context)

    preview = compact["review_preview_path"]
    if preview is not None:
        if normalized_context["max_review_previews"] == 0:
            raise ValueError("visual media handoff exceeds the preview budget")
        if not _project_path(preview) or not preview.startswith("previews/"):
            raise ValueError(
                "review_preview_path must be one project-contained preview path"
            )
        if not any(
            _path_is_bound_to_artifact(preview, artifact_id)
            for artifact_id in artifact_ids
        ):
            raise ValueError("visual media handoff contains an undeclared path")
    elif normalized_context["max_review_previews"] not in {0, 1}:
        raise ValueError("visual media handoff has an invalid preview budget")

    compact["issues"] = issues
    serialized = _serialize_json(compact, "visual media handoff")
    if len(serialized) > normalized_context["context_budget_bytes"]:
        raise ValueError("visual media handoff exceeds the declared context budget")
    return compact


def validate_compact_visual_media_handoff(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return one strict, closed handoff without dereferencing any path string.

    This intrinsic boundary validates every shape rule that does not depend on
    a claimed task scope. Callers that have scope authority add exact Artifact
    and preview binding checks after this function succeeds.
    """
    if not isinstance(result, Mapping):
        raise ValueError("visual media handoff must be an object")
    _validate_scrubbed_json(result, budget=VISUAL_RESULT_BUDGET_BYTES)
    fields = set(result)
    missing = HANDOFF_FIELDS - fields
    unknown = fields - HANDOFF_FIELDS
    if missing:
        raise ValueError(
            "visual_media_handoff is missing fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise ValueError(
            "visual_media_handoff has unknown fields: " + ", ".join(sorted(unknown))
        )

    artifact_ids = _id_list(
        result["artifact_ids"], "artifact_ids", max_items=MAX_HANDOFF_ITEMS
    )
    paths = _path_list(
        result["paths"],
        "paths",
        roots=("artifacts/", "media/"),
        max_items=MAX_HANDOFF_ITEMS,
    )
    media = _validate_media_metadata(result["media"])
    checks = _short_text_list(result["checks"], "checks")
    issues = _validate_compact_issues(result["issues"])
    _require_text(result["summary"], "summary", max_length=64)

    preview = result["review_preview_path"]
    if preview is not None and (
        not _valid_handoff_path(preview)
        or not preview.startswith("previews/")
    ):
        raise ValueError("review_preview_path must be one project-contained preview path")

    compact = {
        "artifact_ids": artifact_ids,
        "paths": paths,
        "media": media,
        "checks": checks,
        "issues": issues,
        "summary": result["summary"],
        "review_preview_path": preview,
    }
    _serialize_json(compact, "visual media handoff")
    return compact


def validate_visual_media_result_envelope(
    context: Mapping[str, Any], result: Mapping[str, Any]
) -> None:
    """Validate a complete result and its closed visual-media handoff."""
    normalized_context = validate_visual_media_context(context)
    validate_result_envelope(result)
    handoff = result.get("visual_media_handoff") if isinstance(result, Mapping) else None
    if handoff is None:
        raise ValueError("visual media result requires visual_media_handoff")
    compact_visual_media_result(normalized_context, handoff)
    serialized = _serialize_json(result, "visual media task result")
    if len(serialized) > normalized_context["context_budget_bytes"]:
        raise ValueError("visual media task result exceeds the declared context budget")


def validate_result_envelope(result: Mapping[str, Any]) -> None:
    """Recursively reject payloads and unbounded data in every task result."""
    if not isinstance(result, Mapping):
        raise ValueError("task result must be an object")
    _validate_scrubbed_json(result, budget=VISUAL_RESULT_BUDGET_BYTES)


def validate_coordinator_safe_json(
    value: Mapping[str, Any], *, budget: int = VISUAL_RESULT_BUDGET_BYTES
) -> None:
    """Apply the universal coordinator boundary to any persisted JSON record."""
    if not isinstance(value, Mapping):
        raise ValueError("coordinator-safe metadata must be an object")
    _validate_scrubbed_json(value, budget=budget, allow_empty_text=True)


def _validate_scrubbed_json(
    value: Any, *, budget: int, allow_empty_text: bool = False
) -> None:
    preview_count = _scrub_value(value, allow_empty_text=allow_empty_text)
    if preview_count > 1:
        raise ValueError("visual media result must not contain more than one preview path")
    serialized = _serialize_json(value, "task result")
    if len(serialized) > budget:
        raise ValueError("task result exceeds the fixed result budget")


def _scrub_value(
    value: Any, *, key: str = "", allow_empty_text: bool = False
) -> int:
    normalized_key = _normalized_key(key)
    key_tokens = set(filter(None, normalized_key.split("_")))
    if _has_history_semantics(normalized_key, key_tokens):
        raise ValueError("visual media result must not contain prompt history")
    has_payload_semantics = normalized_key != "size_bytes" and (
        normalized_key in PAYLOAD_KEYS
        or bool(key_tokens & PAYLOAD_KEY_TOKENS)
        or any(
            marker in normalized_key
            for marker in ("base64", "image_bytes", "video_bytes", "pixel_array")
        )
    )
    if has_payload_semantics:
        raise ValueError(
            "visual media result must not contain an image payload or other media payload"
        )
    if isinstance(value, (list, tuple)) and _contains_numeric_leaf(value) and not (
        normalized_key == "segments" and _is_closed_timing_segments(value)
    ):
        raise ValueError(
            "visual media result must not contain untyped numeric arrays"
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(
            "visual media result must not contain an image payload or other media payload"
        )

    preview_count = 0
    is_preview_key = normalized_key in {"review_preview_path", "review_previews"}
    if is_preview_key:
        if value is None:
            preview_count = 0
        elif isinstance(value, str):
            preview_count = 1
        elif isinstance(value, (list, tuple)):
            # Child values are counted during recursion so a legacy singular
            # preview list is not counted once as a container and again as a
            # string value.
            preview_count = 0
        else:
            raise ValueError("visual media preview path must be singular")

    if normalized_key and (
        normalized_key == "path"
        or normalized_key.endswith("_path")
        or normalized_key.endswith("_paths")
        or normalized_key == "paths"
    ):
        path_values = value if isinstance(value, (list, tuple)) else [value]
        if not all(item is None or _project_path(item) for item in path_values):
            raise ValueError("visual media result paths must be project-contained")

    if isinstance(value, str):
        compact = value.strip()
        lowered = compact.lower()
        if not compact and not allow_empty_text:
            raise ValueError("visual media result text must be non-empty compact prose")
        if lowered.startswith("binary:") or DATA_URL_RE.search(value):
            raise ValueError(
                "visual media result must not contain an image payload or other media payload"
            )
        if HTML_MEDIA_RE.search(value):
            raise ValueError("visual media result must not contain HTML media embedding")
        if any(
            marker in lowered
            for marker in (
                "prompt history",
                "prompt_history",
                "prompt iteration",
                "prompt transcript",
                "generation transcript",
                "generation history",
                "conversation history",
                "chat history",
                "system prompt",
                "negative prompt",
            )
        ):
            raise ValueError("visual media result must not contain prompt history")
        typed_checksum = _is_typed_checksum(normalized_key, compact)
        safe_scheme_token = _is_explicit_safe_scheme_token(normalized_key, compact)
        if (
            REMOTE_URL_RE.search(value)
            or SCHEME_RELATIVE_URL_RE.search(value)
            or (
                URI_SCHEME_RE.search(value)
                and not typed_checksum
                and not safe_scheme_token
            )
        ):
            raise ValueError(
                "visual media result must not contain a remote URL or scheme"
            )
        if _contains_binary_like_base64(value, normalized_key):
            raise ValueError(
                "visual media result must not contain a structurally binary-like "
                "Base64 payload; the result budget also forbids oversized values"
            )
    elif isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if not isinstance(child_key, str):
                raise ValueError("visual media result keys must be strings")
            preview_count += _scrub_value(
                child_value, key=child_key, allow_empty_text=allow_empty_text
            )
    elif isinstance(value, (list, tuple)):
        for child in value:
            preview_count += _scrub_value(
                child, key=key, allow_empty_text=allow_empty_text
            )
    return preview_count


def _contains_binary_like_base64(value: str, normalized_key: str) -> bool:
    compact_value = value.strip()
    if _allows_safe_id_value(normalized_key, compact_value) or _is_typed_checksum(
        normalized_key, compact_value
    ):
        return False
    for match in BASE64_CANDIDATE_RE.finditer(value):
        chunks = re.split(r"\s+", match.group(1).strip())
        encoded_length = sum(map(len, chunks))
        if encoded_length < 32:
            continue
        if not any("=" in chunk for chunk in chunks[:-1]):
            if _is_canonical_base64_token("".join(chunks)):
                return True
            continue
        bodies = [chunk.rstrip("=") for chunk in chunks]
        if not all(_is_canonical_base64_token(chunk) for chunk in chunks):
            continue
        symbols = set("".join(bodies))
        if symbols & {"+", "/"} and symbols & {"-", "_"}:
            continue
        return True
    return False


def _normalized_key(key: str) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", separated.casefold()).strip("_")


def _has_history_semantics(normalized_key: str, key_tokens: set[str]) -> bool:
    if normalized_key in PROMPT_HISTORY_KEYS:
        return True
    if key_tokens & HISTORY_KEY_TOKENS:
        return True
    if key_tokens & HISTORY_CONTEXT_TOKENS and key_tokens & HISTORY_CONTAINER_TOKENS:
        return True
    return normalized_key in {
        "negative_prompt",
        "prompt",
        "prompts",
        "request_messages",
        "system_prompt",
    }


def _contains_numeric_leaf(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_contains_numeric_leaf(item) for item in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_closed_timing_segments(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) > 512:
        return False
    for segment in value:
        if not isinstance(segment, Mapping) or set(segment) != {
            "start_ms",
            "end_ms",
            "text",
        }:
            return False
        start, end, text = (
            segment["start_ms"],
            segment["end_ms"],
            segment["text"],
        )
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or not 0 <= start < end <= 36_000_000
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 1_000
        ):
            return False
    return True


def _allows_safe_id_value(normalized_key: str, value: str) -> bool:
    return (
        normalized_key in SAFE_ID_VALUE_KEYS
        and len(value) <= 128
        and SAFE_ID_RE.fullmatch(value) is not None
    )


def _is_typed_checksum(normalized_key: str, value: str) -> bool:
    if normalized_key in TYPED_CHECKSUM_KEYS:
        return CHECKSUM_RE.fullmatch(value) is not None
    return TYPED_CHECKSUM_TEXT_RE.fullmatch(value) is not None


def _is_explicit_safe_scheme_token(normalized_key: str, value: str) -> bool:
    prefix, separator, token = value.partition(":")
    return (
        bool(separator)
        and bool(token)
        and ":" not in token
        and prefix in SAFE_SCHEME_TOKEN_PREFIXES.get(normalized_key, frozenset())
        and len(value) <= 128
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", token) is not None
    )


def _is_canonical_base64_token(value: str) -> bool:
    padding = len(value) - len(value.rstrip("="))
    if padding > 2 or "=" in value[:-padding or None]:
        return False
    body = value.rstrip("=")
    if not body or re.fullmatch(r"[A-Za-z0-9+/_-]+", body) is None:
        return False
    if set(body) & {"+", "/"} and set(body) & {"-", "_"}:
        return False
    if padding:
        return len(value) % 4 == 0 and len(body) % 4 in {2, 3}
    return len(body) % 4 in {0, 2, 3}


def _validate_media_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("visual media handoff media must be a compact object")
    unknown = set(value) - MEDIA_METADATA_FIELDS
    if unknown:
        raise ValueError("visual media metadata has unknown fields: " + ", ".join(sorted(unknown)))
    normalized = dict(value)
    kind = normalized.get("kind")
    if "kind" in normalized and kind not in {"image", "video", "visual"}:
        raise ValueError("visual media metadata kind is not recognized")
    for field in ("format", "readiness"):
        if field in normalized:
            _require_text(normalized[field], f"media {field}", max_length=64)
    if "mime_type" in normalized:
        mime_type = normalized["mime_type"]
        if (
            not isinstance(mime_type, str)
            or len(mime_type) > 128
            or MIME_TYPE_RE.fullmatch(mime_type) is None
        ):
            raise ValueError("media mime_type must be canonical")
        if not mime_type.startswith(("image/", "video/")):
            raise ValueError("media mime_type must be visual")
        if kind in {"image", "video"} and not mime_type.startswith(f"{kind}/"):
            raise ValueError("media mime_type must match media kind")
    if "checksum" in normalized:
        checksum = normalized["checksum"]
        if not isinstance(checksum, str) or CHECKSUM_RE.fullmatch(checksum) is None:
            raise ValueError("media checksum must be a bounded hexadecimal digest")
    for field in ("width", "height"):
        if field in normalized:
            number = normalized[field]
            if (
                isinstance(number, bool)
                or not isinstance(number, int)
                or not 1 <= number <= 16_384
            ):
                raise ValueError(f"media {field} must be a positive bounded integer")
    if "duration_ms" in normalized:
        duration = normalized["duration_ms"]
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 0 <= duration <= 36_000_000
        ):
            raise ValueError("media duration_ms must be a bounded integer")
    if "fps" in normalized:
        fps = normalized["fps"]
        if (
            isinstance(fps, bool)
            or not isinstance(fps, (int, float))
            or not math.isfinite(fps)
            or not 0 < fps <= 240
        ):
            raise ValueError("media fps must be finite and bounded")
    return normalized


def _validate_issues(
    value: Any, artifact_ids: list[str], context: Mapping[str, Any]
) -> list[dict[str, Any]]:
    normalized = _validate_compact_issues(value)
    scope_id = context["scope_identity"]["id"]
    authorized = set(artifact_ids) | set(context["allowed_artifact_ids"])
    authorized.update(scope_id if isinstance(scope_id, list) else [scope_id])
    continuity = context["continuity_exception"]
    if continuity is not None:
        authorized.add(continuity["artifact_id"])
    for issue in normalized:
        if "artifact_id" in issue and issue["artifact_id"] not in authorized:
            raise ValueError("visual media issue names an undeclared Artifact ID")
    return normalized


def _validate_compact_issues(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_HANDOFF_ITEMS:
        raise ValueError("issues must be a bounded list")
    normalized = []
    for issue in value:
        if not isinstance(issue, Mapping) or not set(issue) <= ISSUE_FIELDS:
            raise ValueError("issues must contain closed compact issue objects")
        if not _bounded_safe_id(issue.get("code")):
            raise ValueError("each visual media issue requires a stable code")
        if "artifact_id" in issue and not _bounded_safe_id(issue["artifact_id"]):
            raise ValueError("visual media issue Artifact ID must be safe")
        for field in ("message", "severity"):
            if field in issue:
                _require_text(issue[field], f"issue {field}", max_length=64)
        normalized.append(dict(issue))
    return normalized


def _mime_kind(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or MIME_TYPE_RE.fullmatch(value) is None:
        raise ValueError("media input requires canonical mime_type")
    top_level = value.split("/", 1)[0]
    if top_level in {"image", "video", "audio"}:
        return top_level
    if value in {"application/json", "text/csv", "text/tab-separated-values"}:
        return "data"
    return "document"


def _promoted_is_visual(artifact: Mapping[str, Any]) -> bool:
    if artifact.get("type") != "promoted-asset":
        return False
    promotion = artifact.get("promotion")
    return (
        isinstance(promotion, Mapping)
        and promotion.get("asset_kind") in VISUAL_PROMOTED_ASSET_KINDS
    )


def _artifact_type_is_visual(artifact: Mapping[str, Any]) -> bool:
    artifact_type = artifact.get("type")
    if not isinstance(artifact_type, str) or not artifact_type:
        raise ValueError("visual media Artifact type is ambiguous")
    if artifact_type in VISUAL_ARTIFACT_TYPES or _promoted_is_visual(artifact):
        return True
    normalized = artifact_type.lower().replace("_", "-")
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", normalized)))
    if tokens & VISUAL_NAME_TOKENS:
        return True
    if "capture" in tokens and tokens & {"app", "application", "browser", "evidence"}:
        return True
    # ``media`` is a stable generic Artifact type whose canonical kind, MIME,
    # or suffix resolves its classification in the caller. Other ambiguous
    # binary/pixel labels remain fail-closed.
    if tokens == {"media"}:
        return False
    if tokens & AMBIGUOUS_MEDIA_TOKENS:
        raise ValueError("visual media Artifact type is ambiguous and cannot classify")
    return False


def _classify_capability(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("visual media capability is ambiguous")
    if value in VISUAL_MEDIA_CAPABILITIES:
        return "visual"
    if value in NON_VISUAL_CAPABILITIES:
        return "non-visual"
    normalized = value.lower().replace("_", "-")
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", normalized)))
    if tokens & VISUAL_NAME_TOKENS or (
        "capture" in tokens
        and tokens & {"app", "application", "browser", "evidence"}
    ):
        return "visual"
    raise ValueError("visual media capability is ambiguous and cannot classify")


def _classify_output_contract(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("visual media output contract is ambiguous")
    if _contains_visual_output_marker(value):
        return "visual"
    normalized = value.lower().replace("_", "-")
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", normalized)))
    if "capture" in tokens and tokens & {"app", "application", "browser", "evidence"}:
        return "visual"
    if tokens & AMBIGUOUS_MEDIA_TOKENS:
        raise ValueError("visual media output contract is ambiguous and cannot classify")
    return "non-visual"


def _operation_output_kind(operation: Any) -> Optional[str]:
    if operation in {"image-generate", "image-edit", "image-inspect"}:
        return "image"
    if operation in {
        "video-generate",
        "video-edit",
        "video-render",
        "video-inspect",
    }:
        return "video"
    if operation in {"frame-extract", "contact-sheet"}:
        return "image"
    return None


def _declared_output_kind(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        raise ValueError("visual media output contract is ambiguous")
    normalized = value.lower().replace("_", "-")
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", normalized)))
    image_markers = tokens & {
        "image",
        "screenshot",
        "thumbnail",
        "keyframe",
    }
    video_markers = tokens & {"video"}
    if image_markers and video_markers:
        raise ValueError("visual media output contract has an ambiguous output kind")
    if image_markers:
        return "image"
    if video_markers:
        return "video"
    return None


def _validate_operation_output_contract(operation: str, output_contract: Any) -> None:
    expected = _operation_output_kind(operation)
    declared = _declared_output_kind(output_contract)
    if expected is not None and declared is not None and declared != expected:
        raise ValueError(
            f"visual media operation {operation} is not compatible with "
            f"{declared} output kind"
        )


def _is_approved_character_asset(artifact: Mapping[str, Any]) -> bool:
    if artifact.get("status") != "approved":
        return False
    if artifact.get("type") in INDEPENDENT_CHARACTER_ASSET_TYPES:
        return True
    if artifact.get("type") != "promoted-asset":
        return False
    promotion = artifact.get("promotion")
    return (
        isinstance(promotion, Mapping)
        and promotion.get("ownership") == "cross-project-registry"
        and promotion.get("scope") == "project-independent"
        and promotion.get("asset_kind") in CHARACTER_PROMOTED_ASSET_KINDS
    )


def _contains_visual_output_marker(value: str) -> bool:
    normalized = value.lower().replace("_", "-")
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", normalized)))
    if tokens & VISUAL_NAME_TOKENS:
        return True
    return any(marker in normalized for marker in {"contact-sheet", "motion-preview"})


def _id_list(
    value: Any,
    label: str,
    *,
    min_items: int = 0,
    max_items: Optional[int] = None,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if not min_items <= len(value):
        raise ValueError(f"{label} requires at least {min_items} item")
    if max_items is not None and len(value) > max_items:
        raise ValueError(f"{label} exceeds its {max_items}-item limit")
    if not all(_bounded_safe_id(item) for item in value):
        raise ValueError(f"{label} must contain safe Artifact IDs")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def _path_list(
    value: Any,
    label: str,
    *,
    roots: tuple[str, ...],
    max_items: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > max_items
        or not all(
            _valid_handoff_path(path) and path.startswith(roots)
            for path in value
        )
    ):
        raise ValueError(f"{label} must contain bounded project-contained paths")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def _short_text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_HANDOFF_ITEMS:
        raise ValueError(f"{label} must be a bounded list")
    for item in value:
        _require_text(item, label, max_length=64)
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def _project_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return False
    return all(part not in {"", ".", ".."} for part in PurePosixPath(value).parts)


def _valid_handoff_path(value: Any) -> bool:
    return (
        _project_path(value)
        and len(value) <= 256
        and HANDOFF_PATH_RE.fullmatch(value) is not None
    )


def _path_is_bound_to_artifact(path: str, artifact_id: str) -> bool:
    if artifact_id.casefold() in RESERVED_PATH_AUTHORITY_IDS:
        return False
    parsed = PurePosixPath(path)
    return artifact_id in parsed.parts or parsed.stem == artifact_id


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and SAFE_ID_RE.fullmatch(value) is not None


def _bounded_safe_id(value: Any) -> bool:
    return _safe_id(value) and len(value) <= 128


def _require_text(value: Any, label: str, *, max_length: int) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
    ):
        raise ValueError(f"{label} must be non-empty bounded compact text")


def _serialize_json(value: Any, label: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must contain JSON metadata only") from error

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional


PLUGIN_VERSION = "0.1.4"
VOICE_MEDIA_FORMATS = ["wav", "mp3", "m4a", "aac", "flac"]
VOICE_DURATION_PROBE = {
    "wav": "stdlib-wave-header",
    "compressed": "ffprobe-required",
    "failure_mode": "fail-closed",
}
VISUAL_MEDIA_OPERATIONS = [
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
]
VISUAL_MEDIA_SCOPE_KINDS = [
    "scene-contract",
    "character-asset-batch",
    "review-batch",
]
CURRENT_VISUAL_AUTHORITY_EXCLUSION = {
    "if": {
        "anyOf": [
            {"required": ["visual_media_operation"]},
            {"required": ["visual_media_context"]},
        ]
    },
    "then": {
        "not": {
            "anyOf": [
                {"required": ["visual_operation"]},
                {"required": ["image_operation"]},
                {"required": ["image_context"]},
            ]
        }
    },
}
VISUAL_MEDIA_CONDITIONALS = [
    {
        "if": {
            "properties": {"visual_media_operation": {"const": "none"}},
            "required": ["visual_media_operation"],
        },
        "then": {"not": {"required": ["visual_media_context"]}},
    },
    {
        "if": {
            "properties": {
                "visual_media_operation": {"enum": VISUAL_MEDIA_OPERATIONS[1:]}
            },
            "required": ["visual_media_operation"],
        },
        "then": {
            "required": ["visual_media_context", "execution_context"],
            "properties": {
                "execution_context": {"const": "isolated-child-agent"}
            },
        },
    },
    {
        "if": {"required": ["visual_media_context"]},
        "then": {"required": ["visual_media_operation"]},
    },
    CURRENT_VISUAL_AUTHORITY_EXCLUSION,
]
VISUAL_MEDIA_MIME_CONDITIONALS = [
    {
        "if": {"properties": {"kind": {"const": "image"}}, "required": ["kind"]},
        "then": {"properties": {"mime_type": {"pattern": "^image/"}}},
    },
    {
        "if": {"properties": {"kind": {"const": "video"}}, "required": ["kind"]},
        "then": {"properties": {"mime_type": {"pattern": "^video/"}}},
    },
]
LEGACY_VISUAL_OPERATION = {
    "enum": ["image-generation", "non-image"],
    "deprecated": True,
    "readOnly": True,
}
SCENE_VISUAL_AUTHORITY = {
    "oneOf": [
        {
            "required": ["visual_media_operation"],
            "properties": {
                "visual_media_operation": {"enum": VISUAL_MEDIA_OPERATIONS}
            },
            "not": {
                "anyOf": [
                    {"required": ["visual_operation"]},
                    {"required": ["image_operation"]},
                    {"required": ["image_context"]},
                ]
            },
        },
        {
            "required": ["visual_operation"],
            "properties": {
                "visual_operation": {
                    "enum": ["image-generation", "non-image"]
                }
            },
            "not": {
                "anyOf": [
                    {"required": ["visual_media_operation"]},
                    {"required": ["visual_media_context"]},
                ]
            },
        },
    ]
}
STRUCTURE_VISUAL_AUTHORITY = {
    "oneOf": [
        {
            "required": ["visual_media_operation"],
            "properties": {
                "visual_media_operation": {"enum": ["none", "image-inspect"]}
            },
            "not": {
                "anyOf": [
                    {"required": ["image_operation"]},
                    {"required": ["image_context"]},
                ]
            },
        },
        {
            "required": ["image_operation"],
            "properties": {
                "image_operation": {"enum": ["structure-only", "image-inspect"]}
            },
            "not": {
                "anyOf": [
                    {"required": ["visual_media_operation"]},
                    {"required": ["visual_media_context"]},
                ]
            },
        },
    ]
}
VISUAL_MEDIA_SCOPE_MAPPING = [
    {
        "if": {
            "properties": {
                "kind": {"enum": ["scene-contract", "character-asset-batch"]}
            },
            "required": ["kind"],
        },
        "then": {"properties": {"id": {"$ref": "#/$defs/safeId"}}},
    },
    {
        "if": {
            "properties": {"kind": {"const": "review-batch"}},
            "required": ["kind"],
        },
        "then": {"properties": {"id": {"$ref": "#/$defs/reviewScopeIds"}}},
    },
]
REQUIRED_FILES = (
    ".codex-plugin/plugin.json",
    "agents/openai.yaml",
    "assets/project-template/project.json",
    "assets/project-template/review-pack/index.html",
    "previews/styles/editorial-clean-v1.html",
    "previews/layouts/talking-head-left-explainer-right-v1.html",
    "references/policies/decision-gates.md",
    "references/policies/invalidation.json",
    "references/policies/project-assets.md",
    "references/policies/visual-media-isolation.md",
    "references/schemas/artifact.schema.json",
    "references/schemas/event.schema.json",
    "references/schemas/image-task-context.schema.json",
    "references/schemas/layout-pack.schema.json",
    "references/schemas/project.schema.json",
    "references/schemas/scene-contract.schema.json",
    "references/schemas/scene-timing-contracts.schema.json",
    "references/schemas/style-pack.schema.json",
    "references/schemas/task-envelope.schema.json",
    "references/schemas/task-result.schema.json",
    "references/schemas/semantic-beats.schema.json",
    "references/schemas/timed-semantic-beats.schema.json",
    "references/schemas/timing-validation.schema.json",
    "references/schemas/voice-source-decision.schema.json",
    "references/schemas/voice-profile.schema.json",
    "references/schemas/voiceover.schema.json",
    "references/schemas/voice-timing.schema.json",
    "references/schemas/visual-media-task-context.schema.json",
    "registries/adapters/chatcut.json",
    "registries/styles/editorial-clean/v1/manifest.json",
    "registries/layouts/talking-head-left-explainer-right/v1/manifest.json",
    "scripts/build_review_pack.py",
    "scripts/install_personal_plugin.py",
    "scripts/migration_audit.py",
    "scripts/retire_legacy_skill.py",
    "scripts/validate_package.py",
    "scripts/verify_installation.py",
    "scripts/toolkit/adapters.py",
    "scripts/toolkit/artifacts.py",
    "scripts/toolkit/contracts.py",
    "scripts/toolkit/image_context.py",
    "scripts/toolkit/invalidation.py",
    "scripts/toolkit/orchestrator.py",
    "scripts/toolkit/project_state.py",
    "scripts/toolkit/scene_timing.py",
    "scripts/toolkit/tasks.py",
    "scripts/toolkit/timed_semantic_beats.py",
    "scripts/toolkit/validation.py",
    "scripts/toolkit/visual_media_context.py",
    "scripts/toolkit/voice.py",
    "scripts/toolkit/voice_tasks.py",
    "skills/scene-producer/SKILL.md",
    "skills/motion-director/SKILL.md",
    "skills/storyboard-director/SKILL.md",
    "skills/structural-validator/SKILL.md",
    "skills/timeline-assembler/SKILL.md",
    "skills/video-director/SKILL.md",
    "skills/video-review-packager/SKILL.md",
    "skills/visual-system-designer/SKILL.md",
    "skills/voiceover-producer/SKILL.md",
    "tests/test_end_to_end.py",
    "tests/encoding_boundary_cases.py",
    "tests/test_artifacts.py",
    "tests/test_image_context.py",
    "tests/test_package.py",
    "tests/test_review_pack.py",
    "tests/test_skill_contracts.py",
    "tests/test_scene_timing.py",
    "tests/test_tasks.py",
    "tests/test_timed_semantic_beats.py",
    "tests/test_validation.py",
    "tests/test_visual_media_context.py",
    "tests/test_voice_tasks.py",
)


def validate_package(root: Path) -> list[str]:
    errors = [
        f"missing:{path}" for path in REQUIRED_FILES if not (root / path).is_file()
    ]
    manifest = _read_json_object(root, ".codex-plugin/plugin.json", errors)
    if manifest is not None:
        if manifest.get("id") != "video-production-toolkit":
            errors.append("invalid:plugin-id")
        if manifest.get("name") != "video-production-toolkit":
            errors.append("invalid:plugin-name")
        if manifest.get("version") != PLUGIN_VERSION:
            errors.append("invalid:plugin-version")
        if manifest.get("skills") != "./skills/":
            errors.append("invalid:skills-path")
        if manifest.get("release_fingerprint") != _release_fingerprint(root):
            errors.append("invalid:release-fingerprint")

    chatcut = _read_json_object(root, "registries/adapters/chatcut.json", errors)
    if chatcut is not None:
        if chatcut.get("accepted_voice_media_formats") != VOICE_MEDIA_FORMATS:
            errors.append("invalid:chatcut-voice-formats")
        if chatcut.get("duration_probe") != VOICE_DURATION_PROBE:
            errors.append("invalid:chatcut-duration-probe")
        capability_skills = _mapping(chatcut.get("capability_skills"))
        if (
            chatcut.get("installed_skill") != "chatcut:chatcut-plugin-basics"
            or capability_skills.get("voice.synthesize") != "chatcut:voice"
            or capability_skills.get("voice.time") != "chatcut:voice"
        ):
            errors.append("invalid:chatcut-voice-skills")

    image = _read_json_object(
        root, "references/schemas/image-task-context.schema.json", errors
    )
    artifact = _read_json_object(
        root, "references/schemas/artifact.schema.json", errors
    )
    if image is not None:
        _validate_image_schema(image, errors)
    if artifact is not None:
        _validate_artifact_schema(artifact, errors)

    visual = _read_json_object(
        root, "references/schemas/visual-media-task-context.schema.json", errors
    )
    envelope = _read_json_object(
        root, "references/schemas/task-envelope.schema.json", errors
    )
    result = _read_json_object(
        root, "references/schemas/task-result.schema.json", errors
    )
    if visual is not None:
        _validate_visual_media_schema(visual, errors)
    if envelope is not None:
        _validate_task_envelope_schema(envelope, errors)
    if result is not None:
        _validate_task_result_schema(result, errors)

    source = _read_json_object(
        root, "references/schemas/voice-source-decision.schema.json", errors
    )
    profile = _read_json_object(
        root, "references/schemas/voice-profile.schema.json", errors
    )
    voiceover = _read_json_object(
        root, "references/schemas/voiceover.schema.json", errors
    )
    timing = _read_json_object(
        root, "references/schemas/voice-timing.schema.json", errors
    )
    if source is not None:
        _validate_voice_source_schema(source, errors)
    if profile is not None:
        _validate_voice_profile_schema(profile, errors)
    if voiceover is not None:
        _validate_voiceover_schema(voiceover, errors)
    if timing is not None:
        _validate_voice_timing_schema(timing, errors)

    semantic = _read_json_object(
        root, "references/schemas/semantic-beats.schema.json", errors
    )
    timed = _read_json_object(
        root, "references/schemas/timed-semantic-beats.schema.json", errors
    )
    scenes = _read_json_object(
        root, "references/schemas/scene-timing-contracts.schema.json", errors
    )
    validation = _read_json_object(
        root, "references/schemas/timing-validation.schema.json", errors
    )
    if semantic is not None:
        _validate_semantic_beats_schema(semantic, errors)
    if timed is not None:
        _validate_timed_semantic_beats_schema(timed, errors)
    if scenes is not None:
        _validate_scene_timing_contracts_schema(scenes, errors)
    if validation is not None:
        _validate_timing_validation_schema(validation, errors)
    return errors


def _release_fingerprint(root: Path) -> str:
    """Return the deterministic content identity declared by the release manifest."""
    digest = hashlib.sha256()
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            content = path.read_bytes()
            if relative == ".codex-plugin/plugin.json":
                manifest = json.loads(content)
                if isinstance(manifest, dict):
                    manifest = dict(manifest)
                    manifest.pop("release_fingerprint", None)
                    content = json.dumps(
                        manifest, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
            digest.update(content)
        except OSError:
            digest.update(b"<unreadable>")
        except (TypeError, ValueError, json.JSONDecodeError):
            digest.update(b"<invalid-json>")
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _read_json_object(
    root: Path, relative: str, errors: list[str]
) -> Optional[dict[str, Any]]:
    path = root / relative
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append(f"invalid-json:{relative}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"invalid-json:{relative}")
        return None
    return payload


def _validate_image_schema(schema: Mapping[str, Any], errors: list[str]) -> None:
    required = _required_fields(schema)
    properties = _mapping(schema.get("properties"))
    scope = _mapping(properties.get("scope_identity"))
    variants = scope.get("oneOf")
    kinds = (
        {
            _mapping(
                _mapping(_mapping(variant).get("properties")).get("kind")
            ).get("const")
            for variant in variants
        }
        if isinstance(variants, list)
        else set()
    )
    variants_closed = isinstance(variants, list) and all(
        _mapping(variant).get("additionalProperties") is False
        and _required_fields(_mapping(variant)) == {"kind", "id"}
        for variant in variants
    )
    if (
        "scope_identity" not in required
        or kinds != {"scene-contract", "character-asset-batch"}
        or not variants_closed
    ):
        errors.append("invalid:image-scope-identity")
    definitions = _mapping(schema.get("$defs"))
    if _mapping(definitions.get("uniqueSafeImageIds")).get("maxItems") != 16:
        errors.append("invalid:image-artifact-limit")
    if _mapping(definitions.get("uniqueSafePackIds")).get("maxItems") != 8:
        errors.append("invalid:image-pack-limit")
    if _mapping(properties.get("context_budget")).get("maximum") != 32768:
        errors.append("invalid:image-context-budget")
    if _mapping(properties.get("max_review_previews")).get("maximum") != 1:
        errors.append("invalid:image-preview-limit")


def _validate_artifact_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    definitions = _mapping(schema.get("$defs"))
    safe_id = _mapping(definitions.get("safeId"))
    if safe_id != {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]*(?:\\.[A-Za-z0-9][A-Za-z0-9_-]*)*$",
    }:
        errors.append("invalid:artifact-safe-id")
    if _required_fields(schema) != {
        "artifact_id",
        "type",
        "version",
        "status",
        "parents",
        "path",
    }:
        errors.append("invalid:artifact-shape")
    closed_defs = ("licenseMetadata", "promotionMetadata", "timingSegment")
    if (
        schema.get("additionalProperties") is not False
        or any(
            _mapping(definitions.get(name)).get("additionalProperties") is not False
            for name in closed_defs
        )
        or not {"license", "promotion", "segments"}.issubset(properties)
        or {"beats", "scenes", "semantic_beats_id", "timed_semantic_beats_id"}
        & set(properties)
    ):
        errors.append("invalid:artifact-extension-contract")
    path = _mapping(properties.get("path"))
    if (
        path.get("maxLength") != 512
        or path.get("pattern")
        != "^(?!/)(?![A-Za-z][A-Za-z0-9+.-]*:)(?!\\.{1,2}(?:/|$))(?!.*\\/\\.{1,2}(?:/|$))[^\\\\]+$"
    ):
        errors.append("invalid:artifact-path")
    if _mapping(properties.get("media_kind")).get("enum") != [
        "audio",
        "data",
        "document",
        "image",
        "video",
    ]:
        errors.append("invalid:artifact-media-kind")
    mime = _mapping(properties.get("mime_type"))
    if (
        mime.get("maxLength") != 128
        or mime.get("pattern")
        != "^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
    ):
        errors.append("invalid:artifact-mime")
    if properties.get("voice_timing_id") != {
        "$ref": "#/$defs/safeId",
        "deprecated": True,
        "readOnly": True,
    }:
        errors.append("invalid:legacy-semantic-timing-projection")


def _safe_id_definition() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]*(?:\\.[A-Za-z0-9][A-Za-z0-9_-]*)*$",
    }


def _bounded_windows(definitions: Mapping[str, Any]) -> bool:
    milliseconds = _mapping(definitions.get("milliseconds"))
    window = _mapping(definitions.get("window"))
    return (
        milliseconds == {"type": "integer", "minimum": 0, "maximum": 36000000}
        and window.get("prefixItems")
        == [
            {"$ref": "#/$defs/milliseconds"},
            {"$ref": "#/$defs/milliseconds"},
        ]
        and window.get("items") is False
        and window.get("minItems") == 2
        and window.get("maxItems") == 2
    )


def _timing_window_ruling(schema: Mapping[str, Any]) -> bool:
    comment = schema.get("$comment")
    return (
        isinstance(comment, str)
        and "Draft 2020-12 cannot compare tuple elements" in comment
        and "not sufficient alone" in comment
    )


def _carrier_definition() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "enum": [
            "a-roll",
            "b-roll",
            "scene",
            "demo",
            "motion-graphics",
            "evidence",
        ],
    }


def _validate_semantic_beats_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    definitions = _mapping(schema.get("$defs"))
    beat = _mapping(definitions.get("beat"))
    beats = _mapping(definitions.get("beats"))
    beat_properties = _mapping(beat.get("properties"))
    if (
        schema.get("additionalProperties") is not False
        or _required_fields(schema)
        != {
            "artifact_id", "type", "version", "status", "parents", "path",
            "narration_id", "beats",
        }
        or properties.get("type") != {"const": "semantic-beats"}
        or properties.get("status") != {"const": "approved"}
        or "voice_timing_id" in properties
        or set(properties)
        != {
            "artifact_id", "type", "version", "status", "parents", "path",
            "output_contract", "narration_id", "beats",
        }
        or definitions.get("safeId") != _safe_id_definition()
        or beats.get("minItems") != 1
        or beats.get("maxItems") != 512
        or beats.get("uniqueItems") is not True
        or beat.get("additionalProperties") is not False
        or _required_fields(beat)
        != {
            "beat_id", "text_ref", "keyword", "intent", "priority",
            "preferred_carrier", "approval_provenance",
        }
        or set(beat_properties)
        != {
            "beat_id", "text_ref", "keyword", "intent", "priority",
            "preferred_carrier", "approval_provenance",
        }
        or beat_properties.get("priority") != {"enum": ["primary", "secondary"]}
        or beat_properties.get("preferred_carrier") != {"$ref": "#/$defs/carrier"}
        or definitions.get("carrier") != _carrier_definition()
    ):
        errors.append("invalid:semantic-beats-contract")
    if "approval_provenance" not in _required_fields(beat):
        errors.append("invalid:semantic-beats-approval-provenance")


def _validate_timed_semantic_beats_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    definitions = _mapping(schema.get("$defs"))
    beat = _mapping(definitions.get("beat"))
    beats = _mapping(properties.get("beats"))
    if (
        schema.get("additionalProperties") is not False
        or not {
            "semantic_beats_id", "voice_timing_id", "timing_kind", "beats"
        }.issubset(_required_fields(schema))
        or properties.get("type") != {"const": "timed-semantic-beats"}
        or properties.get("timing_kind") != {"const": "real"}
        or definitions.get("safeId") != _safe_id_definition()
        or beats.get("minItems") != 1
        or beats.get("maxItems") != 512
        or beats.get("uniqueItems") is not True
        or beat.get("additionalProperties") is not False
        or _required_fields(beat)
        != {
            "beat_id", "speech_start_ms", "speech_end_ms", "keyword_start_ms",
            "keyword_end_ms", "emphasis_ms", "visual_window_ms", "approved_anchor_commitment",
        }
        or _mapping(beat.get("properties")).get("approved_anchor_commitment")
        != {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
        or not _timing_window_ruling(schema)
        or not _bounded_windows(definitions)
    ):
        errors.append("invalid:timed-semantic-beats-contract")
    if properties.get("timing_kind") != {"const": "real"}:
        errors.append("invalid:timed-semantic-beats-timing-kind")


def _validate_scene_timing_contracts_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    definitions = _mapping(schema.get("$defs"))
    scene = _mapping(definitions.get("scene"))
    scene_properties = _mapping(scene.get("properties"))
    support = _mapping(definitions.get("supportLayer"))
    if (
        schema.get("additionalProperties") is not False
        or not {"timed_semantic_beats_id", "scenes"}.issubset(
            _required_fields(schema)
        )
        or properties.get("type") != {"const": "scene-timing-contracts"}
        or definitions.get("safeId") != _safe_id_definition()
        or scene.get("additionalProperties") is not False
        or _required_fields(scene)
        != {
            "scene_id", "scene_window_ms", "beat_ids", "primary_carrier",
            "support_layer", "visual_window_ms",
        }
        or scene_properties.get("primary_carrier")
        != {"$ref": "#/$defs/carrier", "minLength": 1}
        or definitions.get("carrier") != _carrier_definition()
        or support != {"type": ["string", "null"], "minLength": 1, "maxLength": 128}
        or not _timing_window_ruling(schema)
        or not _bounded_windows(definitions)
    ):
        errors.append("invalid:scene-timing-contracts-contract")


def _validate_timing_validation_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    definitions = _mapping(schema.get("$defs"))
    examples = _mapping(definitions.get("examples"))
    issue_counts = _mapping(definitions.get("issueCounts"))
    if (
        schema.get("additionalProperties") is not False
        or _required_fields(schema) != {"status", "checks_run"}
        or properties.get("status") != {"enum": ["blocked", "passed"]}
        or properties.get("checks_run")
        != {"type": "integer", "minimum": 0, "maximum": 1000000}
        or examples.get("type") != "object"
        or _mapping(examples.get("additionalProperties")).get("maxItems") != 3
        or _mapping(examples.get("additionalProperties")).get("uniqueItems") is not True
        or issue_counts.get("type") != "object"
    ):
        errors.append("invalid:timing-validation-contract")


def _validate_visual_media_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    scope = _mapping(properties.get("scope_identity"))
    scope_properties = _mapping(scope.get("properties"))
    kinds = _mapping(scope_properties.get("kind")).get("enum")
    if (
        kinds != VISUAL_MEDIA_SCOPE_KINDS
        or _required_fields(scope) != {"kind", "id"}
        or scope.get("additionalProperties") is not False
    ):
        errors.append("invalid:visual-media-scope-kinds")
    if scope.get("allOf") != VISUAL_MEDIA_SCOPE_MAPPING:
        errors.append("invalid:visual-media-scope-mapping")
    definitions = _mapping(schema.get("$defs"))
    if definitions.get("safeId") != {
        "type": "string",
        "maxLength": 128,
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]*(?:\\.[A-Za-z0-9][A-Za-z0-9_-]*)*$",
    }:
        errors.append("invalid:visual-media-safe-id")
    if definitions.get("uniqueSafeArtifactIds") != {
        "type": "array",
        "items": {"$ref": "#/$defs/safeId"},
        "uniqueItems": True,
        "maxItems": 16,
    }:
        errors.append("invalid:visual-media-artifact-limit")
    if definitions.get("reviewScopeIds") != {
        "type": "array",
        "items": {"$ref": "#/$defs/safeId"},
        "uniqueItems": True,
        "minItems": 1,
        "maxItems": 8,
    }:
        errors.append("invalid:visual-media-review-scope-limit")
    if properties.get("historical_access") != {"const": "character-only"}:
        errors.append("invalid:visual-media-historical-access")
    if properties.get("max_review_previews") != {
        "type": "integer",
        "minimum": 0,
        "maximum": 1,
        "default": 1,
    }:
        errors.append("invalid:visual-media-preview-limit")
    if properties.get("context_budget_bytes") != {
        "type": "integer",
        "minimum": 1,
        "maximum": 32768,
    }:
        errors.append("invalid:visual-media-context-budget")
    if (
        _required_fields(schema)
        != {
            "scope_identity",
            "allowed_artifact_ids",
            "historical_access",
            "continuity_exception",
            "max_review_previews",
            "context_budget_bytes",
        }
        or schema.get("additionalProperties") is not False
    ):
        errors.append("invalid:visual-media-context-shape")


def _validate_task_envelope_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    definitions = _mapping(schema.get("$defs"))
    constraints = _mapping(properties.get("constraints"))
    constraint_properties = _mapping(constraints.get("properties"))
    if constraint_properties.get("visual_media_context") != {
        "$ref": "visual-media-task-context.schema.json"
    }:
        errors.append("invalid:visual-media-context-ref")
    operations = _mapping(constraint_properties.get("visual_media_operation")).get(
        "enum"
    )
    if operations != VISUAL_MEDIA_OPERATIONS:
        errors.append("invalid:visual-media-operations")
    if constraint_properties.get("visual_operation") != LEGACY_VISUAL_OPERATION:
        errors.append("invalid:legacy-visual-operation")
    if (
        definitions.get("safeId")
        != {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]*(?:\\.[A-Za-z0-9][A-Za-z0-9_-]*)*$",
        }
        or properties.get("task_id") != {"$ref": "#/$defs/safeId"}
        or _mapping(properties.get("inputs")).get("items")
        != {"$ref": "#/$defs/safeId"}
    ):
        errors.append("invalid:task-generic-safe-id")
    conditions = constraints.get("allOf")
    visual_conditions = (
        [
            condition
            for condition in conditions
            if isinstance(condition, Mapping)
            and _contains_key(condition, "visual_media_operation")
            or isinstance(condition, Mapping)
            and _contains_key(condition, "visual_media_context")
        ]
        if isinstance(conditions, list)
        else []
    )
    if visual_conditions != VISUAL_MEDIA_CONDITIONALS:
        errors.append("invalid:visual-media-conditionals")

    top_level_conditions = schema.get("allOf")
    scene_rules = (
        [
            condition
            for condition in top_level_conditions
            if _mapping(
                _mapping(_mapping(condition).get("if")).get("properties")
            ).get("capability")
            == {"const": "scene.produce"}
        ]
        if isinstance(top_level_conditions, list)
        else []
    )
    scene_authority = (
        _mapping(
            _mapping(
                _mapping(_mapping(scene_rules[0]).get("then")).get("properties")
            ).get("constraints")
        )
        if len(scene_rules) == 1
        else {}
    )
    if scene_authority != SCENE_VISUAL_AUTHORITY:
        errors.append("invalid:scene-visual-authority")

    structure_rules = (
        [
            condition
            for condition in top_level_conditions
            if _mapping(
                _mapping(_mapping(condition).get("if")).get("properties")
            ).get("capability")
            == {"const": "structure.validate"}
        ]
        if isinstance(top_level_conditions, list)
        else []
    )
    structure_authority = (
        _mapping(
            _mapping(
                _mapping(_mapping(structure_rules[0]).get("then")).get("properties")
            ).get("constraints")
        )
        if len(structure_rules) == 1
        else {}
    )
    if structure_authority != STRUCTURE_VISUAL_AUTHORITY:
        errors.append("invalid:structure-visual-authority")


def _validate_task_result_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    handoff = _mapping(properties.get("visual_media_handoff"))
    handoff_properties = _mapping(handoff.get("properties"))
    media = _mapping(handoff_properties.get("media"))
    if (
        media.get("allOf") != VISUAL_MEDIA_MIME_CONDITIONALS
        or _mapping(_mapping(media.get("properties")).get("kind")).get("enum")
        != ["image", "video", "visual"]
        or media.get("additionalProperties") is not False
    ):
        errors.append("invalid:visual-media-mime-contract")
    safe_id = _mapping(_mapping(schema.get("$defs")).get("safeId"))
    if (
        safe_id
        != {
            "type": "string",
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]*(?:\\.[A-Za-z0-9][A-Za-z0-9_-]*)*$",
        }
        or properties.get("task_id") != {"$ref": "#/$defs/safeId"}
        or _mapping(properties.get("inputs")).get("items")
        != {"$ref": "#/$defs/safeId"}
        or _mapping(properties.get("artifacts")).get("items")
        != {"$ref": "#/$defs/safeId"}
    ):
        errors.append("invalid:task-result-generic-safe-id")


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, Mapping):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return value == key


def _validate_voice_source_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    if "decision_provenance" not in _required_fields(schema):
        errors.append("invalid:voice-source-provenance")
    if (
        _mapping(properties.get("decision")).get("const") != "approved"
        or _mapping(properties.get("mode")).get("enum")
        != ["uploaded-voice", "tts"]
    ):
        errors.append("invalid:voice-source-decision")


def _validate_voice_profile_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    required = _required_fields(schema)
    properties = _mapping(schema.get("properties"))
    if not {"consent_provenance", "profile_provenance"}.issubset(required):
        errors.append("invalid:voice-profile-provenance")
    if (
        "source_decision_id" not in required
        or _mapping(properties.get("mode")).get("const") != "tts"
        or _mapping(properties.get("approved")).get("const") is not True
    ):
        errors.append("invalid:voice-profile-lineage")


def _validate_voiceover_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    required = _required_fields(schema)
    properties = _mapping(schema.get("properties"))
    if "provenance" not in required:
        errors.append("invalid:voiceover-provenance")
    if (
        not {"source_decision_id", "media_format"}.issubset(required)
        or _mapping(properties.get("mode")).get("enum")
        != ["uploaded-voice", "tts"]
        or _mapping(properties.get("media_format")).get("enum")
        != VOICE_MEDIA_FORMATS
    ):
        errors.append("invalid:voiceover-media-contract")
    expected_conditions = [
        {
            "if": {"properties": {"mode": {"const": "tts"}}, "required": ["mode"]},
            "then": {
                "required": ["profile_id"],
                "not": {"required": ["uploaded_audio_id"]},
            },
        },
        {
            "if": {
                "properties": {"mode": {"const": "uploaded-voice"}},
                "required": ["mode"],
            },
            "then": {
                "required": ["uploaded_audio_id"],
                "not": {"required": ["profile_id"]},
            },
        },
    ]
    conditions = schema.get("allOf")
    if not isinstance(conditions, list) or any(
        condition not in conditions for condition in expected_conditions
    ):
        errors.append("invalid:voiceover-mode-lineage")


def _validate_voice_timing_schema(
    schema: Mapping[str, Any], errors: list[str]
) -> None:
    properties = _mapping(schema.get("properties"))
    anchors = _mapping(properties.get("keyword_anchors"))
    anchor = _mapping(_mapping(schema.get("$defs")).get("anchor"))
    if (
        not {"voiceover_id", "timing_kind", "duration_ms", "segments"}.issubset(
            _required_fields(schema)
        )
        or "keyword_anchors" in _required_fields(schema)
        or "keyword_anchors" not in properties
        or _mapping(properties.get("timing_kind")).get("const") != "real"
        or anchors.get("type") != "array"
        or anchors.get("minItems") != 0
        or anchors.get("maxItems") != 512
        or anchors.get("uniqueItems") is not True
        or anchors.get("items") != {"$ref": "#/$defs/anchor"}
        or anchor.get("required") != ["beat_id", "keyword", "start_ms", "end_ms"]
        or anchor.get("additionalProperties") is not False
    ):
        errors.append("invalid:voice-timing-contract")


def _required_fields(schema: Mapping[str, Any]) -> set[str]:
    value = schema.get("required")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return set()
    return set(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    import sys

    issues = validate_package(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())
    print("\n".join(issues) if issues else "package valid")
    raise SystemExit(bool(issues))

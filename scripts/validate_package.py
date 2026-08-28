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
        "then": {"required": ["visual_media_context"]},
    },
    {
        "if": {"required": ["visual_media_context"]},
        "then": {"required": ["visual_media_operation"]},
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
    "references/schemas/event.schema.json",
    "references/schemas/image-task-context.schema.json",
    "references/schemas/layout-pack.schema.json",
    "references/schemas/project.schema.json",
    "references/schemas/scene-contract.schema.json",
    "references/schemas/style-pack.schema.json",
    "references/schemas/task-envelope.schema.json",
    "references/schemas/task-result.schema.json",
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
    "scripts/retire_legacy_skill.py",
    "scripts/validate_package.py",
    "scripts/verify_installation.py",
    "scripts/toolkit/adapters.py",
    "scripts/toolkit/contracts.py",
    "scripts/toolkit/image_context.py",
    "scripts/toolkit/invalidation.py",
    "scripts/toolkit/orchestrator.py",
    "scripts/toolkit/project_state.py",
    "scripts/toolkit/tasks.py",
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
    "tests/test_image_context.py",
    "tests/test_package.py",
    "tests/test_review_pack.py",
    "tests/test_skill_contracts.py",
    "tests/test_tasks.py",
    "tests/test_validation.py",
    "tests/test_visual_media_context.py",
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
    if image is not None:
        _validate_image_schema(image, errors)

    visual = _read_json_object(
        root, "references/schemas/visual-media-task-context.schema.json", errors
    )
    envelope = _read_json_object(
        root, "references/schemas/task-envelope.schema.json", errors
    )
    if visual is not None:
        _validate_visual_media_schema(visual, errors)
    if envelope is not None:
        _validate_task_envelope_schema(envelope, errors)

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
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_:-]*(?:\\.[A-Za-z0-9][A-Za-z0-9_:-]*)*$",
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
    if (
        not {"voiceover_id", "timing_kind", "duration_ms", "segments"}.issubset(
            _required_fields(schema)
        )
        or _mapping(properties.get("timing_kind")).get("const") != "real"
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

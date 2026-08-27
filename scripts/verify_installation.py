#!/usr/bin/env python3
"""Verify plugin packaging, personal discovery, adapters, and recovery smoke."""

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.migration_audit import audit_legacy
from scripts.plan_representative_slice import select_representative_slice
from scripts.toolkit.artifacts import approve_artifact, create_artifact
from scripts.toolkit.orchestrator import (
    calculate_ready_tasks,
    invalidate_artifact_descendants,
    resume_project,
)
from scripts.toolkit.project_state import append_event, initialize_project
from scripts.toolkit.tasks import create_task
from scripts.validate_package import validate_package


PLUGIN_ID = "video-production-toolkit"
LEGACY_SKILL = "knowledge-video-visual-director"
MIGRATION_REPORT = Path("docs/migration/knowledge-video-visual-director.md")
BASELINE = Path("references/policies/knowledge-video-visual-director-baseline.json")
_PLUGIN_TABLE = re.compile(
    r"^\[\s*plugins\s*\.\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_.-]+))\s*\]\s*(?:#.*)?$"
)
_ENABLED_VALUE = re.compile(r"^enabled\s*=\s*(true|false)\s*(?:#.*)?$", re.IGNORECASE)


def run_smoke(root: Path, *, legacy_root: Optional[Path] = None) -> dict[str, Any]:
    """Run a metadata-only resume, invalidation, gate, and slice scenario."""
    root = Path(root).resolve()
    checks = {
        "migration_audit": "failed",
        "resume_local_invalidation": "not-run",
        "four_approval_gates": "not-run",
        "representative_slice": "not-run",
        "one_action_only": "not-run",
        "no_media_generation": "not-run",
    }
    migration = _migration_prerequisite(root, legacy_root)
    if not migration["ok"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "migration-audit-required",
                "detail": migration["detail"],
            },
        }
    checks["migration_audit"] = "passed"

    contracts_path = root / "tests" / "fixtures" / "knowledge-video-minimal" / "scene-contracts.json"
    try:
        contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
        selected_slice = select_representative_slice(contracts)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "representative-slice-fixture-invalid", "detail": str(error)},
        }
    if selected_slice.blocked or not (10000 <= selected_slice.duration_ms <= 20000):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "representative-slice-unavailable",
                "detail": selected_slice.blocker,
            },
        }
    selected_contracts = {
        item["primary_carrier"] for item in contracts if item["scene_id"] in selected_slice
    }
    if not {"scene", "motion-graphics"}.issubset(selected_contracts):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {
                "code": "representative-slice-risk-missing",
                "detail": sorted(selected_contracts),
            },
        }
    checks["representative_slice"] = "passed"

    try:
        gates_ok = _check_four_gates()
        resumed = _run_resume_scenario()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "resume-smoke-failed", "detail": str(error)},
        }
    if not gates_ok:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "approval-gate-failed", "detail": "a gate advanced without exact approval"},
        }
    checks["four_approval_gates"] = "passed"
    if resumed["ready_tasks"] != ["scene.produce:S02"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "local-rebuild-failed", "detail": resumed["ready_tasks"]},
        }
    effective = {item["artifact_id"]: item for item in resumed["artifacts"]}
    if (
        effective["scene-S01-v1"]["status"] != "approved"
        or effective["scene-S02-v1"]["status"] != "stale"
    ):
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "local-invalidation-failed", "detail": effective},
        }
    checks["resume_local_invalidation"] = "passed"
    checks["one_action_only"] = "passed"
    if resumed["media_files"]:
        return {
            "ok": False,
            "checks": checks,
            "blocker": {"code": "coordinator-generated-media", "detail": resumed["media_files"]},
        }
    checks["no_media_generation"] = "passed"
    return {
        "ok": True,
        "checks": checks,
        "ready_tasks": resumed["ready_tasks"],
        "representative_slice": {
            "scene_ids": list(selected_slice),
            "ranges": [list(item) for item in selected_slice.ranges],
            "duration_ms": selected_slice.duration_ms,
            "composite": selected_slice.composite,
        },
    }


def verify_installation(
    *,
    repo: Optional[Path] = None,
    home: Optional[Path] = None,
    require_skill: Optional[str] = None,
    forbid_skill: Optional[str] = None,
    check_external_skills: bool = False,
    require_resume_smoke: bool = False,
    legacy_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Return structured package, discovery, external, and smoke status."""
    personal_home = (Path.home() if home is None else Path(home)).resolve()
    warnings: list[str] = []
    errors: list[str] = []
    if repo is None:
        try:
            plugin_root = discover_host_installed_plugin(personal_home, PLUGIN_ID)
            discovery = "host-installed"
        except ValueError as error:
            return {
                "ok": False,
                "plugin": {"id": PLUGIN_ID, "discovery": "missing", "root": None},
                "external_adapters": {},
                "warnings": [],
                "errors": [str(error)],
            }
    else:
        plugin_root = Path(repo).resolve()
        discovery = "repo"
    package_issues = validate_package(plugin_root)
    errors.extend(package_issues)
    skill_names = _plugin_skill_names(plugin_root)
    if require_skill and require_skill not in skill_names:
        errors.append(f"required skill is not discoverable: {require_skill}")
    if forbid_skill and _skill_is_discoverable(personal_home, plugin_root, forbid_skill):
        errors.append(f"forbidden skill remains discoverable: {forbid_skill}")

    external: dict[str, dict[str, Any]] = {}
    if check_external_skills:
        try:
            discovered = _all_personal_skill_names(personal_home)
        except ValueError as error:
            errors.append(str(error))
            discovered = set()
        adapters_root = plugin_root / "registries" / "adapters"
        for path in sorted(adapters_root.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                errors.append(f"invalid adapter manifest: {path.name}: {error}")
                continue
            adapter_id = manifest.get("id", path.stem)
            required = manifest.get("installed_skill")
            available = _matches_installed_skill(required, discovered, adapter_id)
            external[adapter_id] = {
                "installed_skill": required,
                "available": available,
                "required": False,
            }
            if not available:
                warnings.append(f"optional external skill unavailable: {required}")

    smoke: Optional[dict[str, Any]] = None
    if require_resume_smoke:
        effective_legacy = legacy_root
        if effective_legacy is None:
            candidate = personal_home / ".codex" / "skills" / LEGACY_SKILL
            effective_legacy = candidate if candidate.exists() else None
        smoke = run_smoke(plugin_root, legacy_root=effective_legacy)
        if not smoke["ok"]:
            errors.append(f"resume smoke failed: {smoke.get('blocker')}")

    return {
        "ok": not errors,
        "plugin": {
            "id": PLUGIN_ID,
            "discovery": discovery,
            "root": str(plugin_root),
            "valid": not package_issues,
            "skills": sorted(skill_names),
        },
        "external_adapters": external,
        "resume_smoke": smoke,
        "warnings": warnings,
        "errors": errors,
    }


def discover_host_installed_plugin(home: Path, plugin_id: str = PLUGIN_ID) -> Path:
    """Resolve one enabled host cache copy, not merely its marketplace source."""
    home = Path(home).resolve()
    if not _safe_component(plugin_id):
        raise ValueError("plugin id is not a safe component")
    source_root = _discover_personal_plugin(home, plugin_id)
    catalog = _read_personal_marketplace(home)
    marketplace_name = catalog.get("name")
    if not _safe_component(marketplace_name):
        raise ValueError("personal marketplace name is not a safe component")
    config = home / ".codex" / "config.toml"
    if config.is_symlink() or not config.is_file():
        raise ValueError("plugin is not host-installed and enabled")
    plugin_key = f"{plugin_id}@{marketplace_name}"
    if not _plugin_is_enabled(config, plugin_key):
        raise ValueError("plugin is not host-installed and enabled")
    cache_root = (
        home
        / ".codex"
        / "plugins"
        / "cache"
        / marketplace_name
        / plugin_id
    )
    try:
        cache_root.resolve().relative_to(home)
    except ValueError:
        raise ValueError("host-installed plugin cache escapes personal home") from None
    if cache_root.is_symlink():
        raise ValueError("host-installed plugin cache must not be a symlink")
    try:
        manifest = json.loads(
            (source_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("personal plugin manifest is invalid") from error
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not _safe_component(version):
        raise ValueError("personal plugin manifest version is invalid")
    cache = cache_root / version
    # Older local-plugin hosts used a literal `local` cache directory. Keep
    # that layout readable while preferring the manifest-versioned host cache.
    if not cache.exists() and (cache_root / "local").exists():
        cache = cache_root / "local"
    if cache.is_symlink():
        raise ValueError("host-installed plugin cache must not be a symlink")
    try:
        installed = cache.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("plugin is not host-installed and enabled") from error
    if not installed.is_dir():
        raise ValueError("host-installed plugin cache is not a directory")
    return installed


def _check_four_gates() -> bool:
    cases = (
        ("narration.plan", "content", "decision-pack", {}),
        ("storyboard.plan", "visual-direction", "style-pack", {}),
        (
            "scene.produce",
            "storyboard-and-cost",
            "storyboard",
            {"production_scope": "representative-slice"},
        ),
        (
            "scene.produce",
            "representative-slice-and-final-draft",
            "representative-slice",
            {"production_scope": "full-production"},
        ),
    )
    for index, (capability, gate, target_type, extra) in enumerate(cases, 1):
        target_id = f"gate-{index}"
        task = _candidate(
            f"gate-task-{index}", capability, [target_id], gate, target_id, **extra
        )
        artifacts = [_artifact(target_id, target_type)]
        state = {"candidate_tasks": [task], "locked_task_ids": []}
        if calculate_ready_tasks(state, artifacts, []):
            return False
        approval = {"target_id": target_id, "scope": gate, "decision": "approved"}
        if calculate_ready_tasks(
            state,
            [_artifact(target_id, "unrelated-review-artifact")],
            [approval],
        ):
            return False
        if calculate_ready_tasks(state, artifacts, [approval]) != [capability]:
            return False
        descendant_id = f"gate-input-{index}"
        unrelated_task = _candidate(
            f"unrelated-gate-task-{index}",
            capability,
            [descendant_id],
            gate,
            target_id,
            **extra,
        )
        unrelated_state = {
            "candidate_tasks": [unrelated_task],
            "locked_task_ids": [],
        }
        if calculate_ready_tasks(
            unrelated_state,
            [artifacts[0], _artifact(descendant_id, "task-input")],
            [approval],
        ):
            return False
        related_artifacts = [
            artifacts[0],
            _artifact(descendant_id, "task-input", parents=[target_id]),
        ]
        if calculate_ready_tasks(
            unrelated_state,
            related_artifacts,
            [approval],
        ) != [capability]:
            return False
    return True


def _run_resume_scenario() -> dict[str, Any]:
    with TemporaryDirectory() as folder:
        project = Path(folder) / "project"
        initialize_project(project, "kv-resume-smoke", "knowledge-video")
        for item in (
            _artifact("storyboard-v1", "storyboard"),
            _artifact(
                "contract-S01-v1", "scene-contract", parents=["storyboard-v1"], scene_id="S01"
            ),
            _artifact(
                "contract-S02-v1", "scene-contract", parents=["storyboard-v1"], scene_id="S02"
            ),
            _artifact(
                "scene-S01-v1", "media", parents=["contract-S01-v1"], scene_id="S01"
            ),
            _artifact(
                "scene-S02-v1", "media", parents=["contract-S02-v1"], scene_id="S02"
            ),
            _artifact(
                "contract-S02-v2",
                "scene-contract",
                version=2,
                parents=["storyboard-v1"],
                scene_id="S02",
            ),
        ):
            create_artifact(project, item)
        approve_artifact(
            project,
            "storyboard-v1",
            "storyboard-and-cost",
            "representative production approved",
        )
        create_task(
            project,
            _candidate(
                "rebuild-S02",
                "scene.produce",
                ["contract-S02-v2", "storyboard-v1"],
                "storyboard-and-cost",
                "storyboard-v1",
                production_scope="representative-slice",
                scene_id="S02",
            ),
        )
        for phase in (
            "content_ready",
            "direction_ready",
            "voice_ready",
            "storyboard_ready",
        ):
            append_event(
                project,
                {"event": "project.phase_changed", "phase": phase},
            )
        invalidate_artifact_descendants(
            project,
            "contract-S02-v1",
            json.loads(
                (Path(__file__).parents[1] / "references/policies/invalidation.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        first = resume_project(project)
        second = resume_project(project)
        if first != second:
            raise RuntimeError("resume is not deterministic")
        return {**first, "media_files": sorted(path.name for path in (project / "media").iterdir())}


def _migration_prerequisite(root: Path, legacy_root: Optional[Path]) -> dict[str, Any]:
    report = root / MIGRATION_REPORT
    baseline = root / BASELINE
    if not report.is_file() or not baseline.is_file():
        return {"ok": False, "detail": "migration report or baseline is missing"}
    if legacy_root is not None:
        try:
            audit = audit_legacy(legacy_root, root)
        except ValueError as error:
            return {"ok": False, "detail": str(error)}
        if not audit["ok"]:
            return {"ok": False, "detail": audit}
        return {"ok": True, "detail": "live legacy audit passed"}
    default_legacy = Path.home() / ".codex" / "skills" / LEGACY_SKILL
    if default_legacy.is_dir() and not default_legacy.is_symlink():
        try:
            audit = audit_legacy(default_legacy, root)
        except ValueError as error:
            return {"ok": False, "detail": str(error)}
        return {"ok": bool(audit["ok"]), "detail": audit}
    text = report.read_text(encoding="utf-8")
    required = (
        "Missing expected legacy files: 0",
        "Content hash mismatches: 0",
        "Undisposed executable scripts: 0",
    )
    if all(item in text for item in required):
        return {"ok": True, "detail": "committed migration audit passed"}
    return {"ok": False, "detail": "migration report does not record a complete audit"}


def _discover_personal_plugin(home: Path, plugin_id: str) -> Path:
    catalog = _read_personal_marketplace(home)
    plugins = catalog.get("plugins") if isinstance(catalog, dict) else None
    if not isinstance(plugins, list):
        raise ValueError("personal marketplace has no plugin list")
    matches = [item for item in plugins if isinstance(item, dict) and item.get("name") == plugin_id]
    if len(matches) != 1:
        raise ValueError(f"personal marketplace must contain exactly one {plugin_id} entry")
    source = matches[0].get("source")
    value = source.get("path") if isinstance(source, dict) else source
    relative = _safe_marketplace_path(value)
    plugin_root = home.joinpath(*relative.parts)
    try:
        plugin_root = plugin_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("personal plugin source does not exist") from error
    if not plugin_root.is_dir():
        raise ValueError("personal plugin source is not a directory")
    return plugin_root


def _read_personal_marketplace(home: Path) -> dict[str, Any]:
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    if marketplace.is_symlink() or not marketplace.is_file():
        raise ValueError("personal marketplace is missing or unsafe")
    try:
        catalog = json.loads(marketplace.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("personal marketplace is invalid") from error
    if not isinstance(catalog, dict):
        raise ValueError("personal marketplace is invalid")
    return catalog


def _plugin_is_enabled(config: Path, plugin_key: str) -> bool:
    return plugin_key in _enabled_plugin_keys(config)


def _enabled_plugin_keys(config: Path) -> set[str]:
    if not config.exists():
        return set()
    if config.is_symlink() or not config.is_file():
        raise ValueError("Codex plugin configuration is unreadable")
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError("Codex plugin configuration is unreadable") from error
    enabled: set[str] = set()
    current: Optional[str] = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            match = _PLUGIN_TABLE.fullmatch(line)
            current = None if match is None else next(
                value for value in match.groups() if value is not None
            )
            continue
        if current is None:
            continue
        match = _ENABLED_VALUE.fullmatch(line)
        if match is None:
            continue
        if match.group(1).casefold() == "true":
            enabled.add(current)
        else:
            enabled.discard(current)
    return enabled


def _safe_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
    )


def _safe_marketplace_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.startswith("./") or "\\" in value:
        raise ValueError("local plugin source.path must be a ./-prefixed POSIX path")
    path = PurePosixPath(value[2:])
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("local plugin source.path must stay within personal home")
    return path


def _plugin_skill_names(root: Path) -> set[str]:
    names = set()
    for path in (root / "skills").glob("*/SKILL.md"):
        names.add(_frontmatter_name(path) or path.parent.name)
    return names


def _all_personal_skill_names(home: Path) -> set[str]:
    names = set()
    roots = (home / ".codex" / "skills", home / ".agents" / "skills")
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*/SKILL.md"):
            names.add(_frontmatter_name(path) or path.parent.name)
            names.add(path.parent.name)
    config = home / ".codex" / "config.toml"
    cache = home / ".codex" / "plugins" / "cache"
    for plugin_key in sorted(_enabled_plugin_keys(config)):
        plugin_name, separator, marketplace_name = plugin_key.rpartition("@")
        if (
            not separator
            or not _safe_component(plugin_name)
            or not _safe_component(marketplace_name)
        ):
            continue
        versions = cache / marketplace_name / plugin_name
        if versions.is_symlink() or not versions.is_dir():
            continue
        for path in versions.glob("*/skills/*/SKILL.md"):
            if path.is_symlink() or any(
                parent.is_symlink() for parent in list(path.parents)[:3]
            ):
                continue
            for skill_name in (_frontmatter_name(path), path.parent.name):
                identity = _skill_identity(skill_name)
                if identity is not None:
                    names.add(f"{plugin_name}:{identity[1]}")
    return names


def _frontmatter_name(path: Path) -> Optional[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip().strip('"\'')
            return value or None
    return None


def _matches_installed_skill(
    required: Any,
    discovered: set[str],
    adapter_namespace: Any,
) -> bool:
    required_identity = _skill_identity(required)
    if required_identity is None:
        return False
    required_namespace, skill_name = required_identity
    expected_namespace = required_namespace
    if expected_namespace is None and _safe_component(adapter_namespace):
        expected_namespace = adapter_namespace
    allowed = {skill_name}
    if expected_namespace is not None:
        allowed.add(f"{expected_namespace}:{skill_name}")
    return bool(allowed & discovered)


def _skill_identity(value: Any) -> Optional[tuple[Optional[str], str]]:
    if not isinstance(value, str) or not value:
        return None
    parts = value.split(":")
    if len(parts) == 1 and _safe_component(parts[0]):
        return None, parts[0]
    if len(parts) == 2 and all(_safe_component(part) for part in parts):
        return parts[0], parts[1]
    return None


def _skill_is_discoverable(home: Path, plugin_root: Path, name: str) -> bool:
    if name in _plugin_skill_names(plugin_root) or name in _all_personal_skill_names(home):
        return True
    return any(
        path.exists()
        for path in (home / ".codex" / "skills" / name, home / ".agents" / "skills" / name)
    )


def _artifact(
    artifact_id: str,
    artifact_type: str,
    *,
    version: int = 1,
    parents: Optional[list[str]] = None,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "version": version,
        "status": "approved",
        "parents": list(parents or []),
        "path": f"metadata/{artifact_id}.json",
        **metadata,
    }


def _candidate(
    task_id: str,
    capability: str,
    inputs: list[str],
    gate: str,
    target_id: str,
    **constraints: Any,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "capability": capability,
        "inputs": inputs,
        "adapter_preferences": ["chatcut"],
        "output_contract": "task-result-v1",
        "constraints": {
            "required_gate": gate,
            "gate_target_id": target_id,
            **constraints,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--require-skill")
    parser.add_argument("--forbid-skill")
    parser.add_argument("--check-external-skills", action="store_true")
    parser.add_argument("--require-resume-smoke", action="store_true")
    args = parser.parse_args()
    result = verify_installation(
        repo=args.repo,
        home=args.home,
        require_skill=args.require_skill,
        forbid_skill=args.forbid_skill,
        check_external_skills=args.check_external_skills,
        require_resume_smoke=args.require_resume_smoke,
        legacy_root=args.legacy_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit the legacy knowledge-video skill before retirement is considered."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


REPORT_PATH = PurePosixPath("docs/migration/knowledge-video-visual-director.md")
BASELINE_PATH = PurePosixPath(
    "references/policies/knowledge-video-visual-director-baseline.json"
)
ALLOWED_DISPOSITIONS = {"migrated", "replaced", "externalized", "rejected"}
DISPOSITION_CATEGORIES = {
    "migrated": "migrated",
    "replaced": "replaced",
    "externalized": "replaced",
    "rejected": "retired",
}
IGNORED_NAMES = {".DS_Store", "__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}

DISPOSITIONS: dict[str, dict[str, Any]] = {
    "SKILL.md": {
        "disposition": "replaced",
        "owners": ["skills/video-director/SKILL.md"],
        "rationale": "The monolithic entrypoint is split into bounded capability owners.",
    },
    "agents/openai.yaml": {
        "disposition": "replaced",
        "owners": ["agents/openai.yaml"],
        "rationale": "Plugin-facing metadata now names the replacement coordinator.",
    },
    "assets/character-model-sheet.png": {
        "disposition": "rejected",
        "owners": ["references/policies/project-assets.md"],
        "rationale": "A project-specific character baseline must not become a plugin-global asset.",
    },
    "references/audit.md": {
        "disposition": "migrated",
        "owners": [
            "references/policies/narration-and-coverage.md",
            "references/policies/project-assets.md",
            "skills/structural-validator/SKILL.md",
        ],
        "rationale": "Objective coverage, evidence, and asset rules survive; subjective acceptance remains a user review.",
    },
    "references/plan.md": {
        "disposition": "migrated",
        "owners": [
            "references/policies/narration-and-coverage.md",
            "references/policies/visual-carriers.md",
        ],
        "rationale": "Voice timing, semantic coverage, and meaningful holds are retained without universal pacing constants.",
    },
    "references/produce.md": {
        "disposition": "replaced",
        "owners": [
            "skills/scene-producer/SKILL.md",
            "skills/motion-director/SKILL.md",
            "skills/timeline-assembler/SKILL.md",
        ],
        "rationale": "Production is owned by isolated task capabilities and immutable contracts.",
    },
    "references/scene-patterns.json": {
        "disposition": "externalized",
        "owners": [
            "registries/recipes/video-shotcraft-index.json",
            "scripts/toolkit/registry.py",
        ],
        "rationale": "Creative recipes are compact registry metadata loaded through external implementation references.",
    },
    "references/start.md": {
        "disposition": "replaced",
        "owners": [
            "skills/video-project-manager/SKILL.md",
            "references/policies/project-assets.md",
        ],
        "rationale": "Project identity and isolation are enforced by project state and artifact policy.",
    },
    "routing-manifest.json": {
        "disposition": "replaced",
        "owners": [
            "skills/video-director/SKILL.md",
            "skills/video-project-manager/SKILL.md",
        ],
        "rationale": "Project phase and one ready task now drive routing.",
    },
    "scripts/search_assets.py": {
        "disposition": "replaced",
        "owners": [
            "scripts/toolkit/artifacts.py",
            "references/policies/project-assets.md",
        ],
        "rationale": "Machine-local TSV lookup is replaced by project artifacts and explicit promotion policy.",
    },
    "scripts/select_scene_patterns.py": {
        "disposition": "externalized",
        "owners": ["scripts/toolkit/registry.py", "scripts/search_registry.py"],
        "rationale": "Deterministic metadata scoring moved to the versioned registry boundary.",
    },
    "scripts/validate_coverage.py": {
        "disposition": "migrated",
        "owners": ["scripts/toolkit/coverage.py"],
        "rationale": "Deterministic semantic coverage becomes a pure structured-issue evaluator.",
    },
    "scripts/validate_library.py": {
        "disposition": "migrated",
        "owners": [
            "scripts/toolkit/artifacts.py",
            "scripts/toolkit/validation.py",
            "references/policies/project-assets.md",
        ],
        "rationale": (
            "Safe paths, exact legacy filename checks, strict PNG structure and alpha "
            "inspection, neutral action metadata, provenance, and promotion ownership "
            "move to structural validation."
        ),
    },
    "scripts/validate_router.py": {
        "disposition": "replaced",
        "owners": ["scripts/validate_package.py", "tests/test_skill_contracts.py"],
        "rationale": "Package and child-capability contracts replace word-count routing validation.",
    },
    "scripts/validate_state.py": {
        "disposition": "replaced",
        "owners": [
            "scripts/toolkit/project_state.py",
            "scripts/toolkit/artifacts.py",
            "scripts/toolkit/invalidation.py",
            "scripts/toolkit/validation.py",
        ],
        "rationale": "Phase, artifact, invalidation, and structural checks now have separate owners.",
    },
    "tests/test_assets.py": {
        "disposition": "replaced",
        "owners": [
            "tests/test_artifacts.py",
            "tests/test_validation.py",
            "tests/test_migration_audit.py",
        ],
        "rationale": "Replacement tests exercise immutable project assets and audit completeness.",
    },
    "tests/test_coverage.py": {
        "disposition": "migrated",
        "owners": ["tests/test_coverage.py"],
        "rationale": "Coverage regressions are retained at the new pure-library boundary.",
    },
    "tests/test_router.py": {
        "disposition": "replaced",
        "owners": ["tests/test_package.py", "tests/test_skill_contracts.py"],
        "rationale": "Tests target package discovery and exact capability ownership.",
    },
    "tests/test_state.py": {
        "disposition": "replaced",
        "owners": [
            "tests/test_project_state.py",
            "tests/test_artifacts.py",
            "tests/test_invalidation.py",
            "tests/test_validation.py",
        ],
        "rationale": "State behavior is covered through the replacement boundaries.",
    },
}

RETAINED_RULES = (
    "Confirmed real voice timing, not an estimate, drives production timing.",
    "Narration and approved semantic intent remain immutable upstream artifacts.",
    "Every semantic beat needs meaningful visual coverage or stable evidence.",
    "Important evidence, formulas, numbers, and conclusions require declared readable holds.",
    "Character action must teach the beat and belong credibly to its environment.",
    "Real evidence, editable graphics, formulas, and UI are preferred when clearer.",
    "Required Demos keep an explicit lifecycle.",
    "Project assets remain isolated unless an explicit, validated promotion creates a new artifact.",
)
REJECTED_RULES = (
    "A monolithic director owning planning, production, review, and handoff.",
    "Mandatory serial generation for dependency-independent shots.",
    "A blanket ban on frame inspection while claiming real-frame verification.",
    "A single `complete` state that conflates production, audit, and export handoff.",
    "Universal 0.8–1.2 second state changes or 3–4 second explanation groups.",
    "A hardcoded machine-local durable library limited to one character-action class.",
)


def audit_legacy(legacy_root: Path, new_root: Path) -> dict[str, Any]:
    """Return explicit dispositions for every stable file under ``legacy_root``."""
    legacy_root = _directory(legacy_root, "legacy root")
    new_root = _directory(new_root, "new root")
    baseline = _load_baseline(new_root)
    legacy_files, unsafe_legacy_paths = _legacy_files(legacy_root)
    missing_legacy_files = sorted(set(DISPOSITIONS) - set(legacy_files))
    inventory = []
    undisposed_files = []
    undisposed_executables = []
    missing_owners = []
    content_mismatches = []

    for relative in legacy_files:
        disposition = DISPOSITIONS.get(relative)
        if disposition is None:
            undisposed_files.append(relative)
            if _is_executable_script(legacy_root / relative, relative):
                undisposed_executables.append(relative)
            continue
        _validate_disposition(relative, disposition)
        actual_sha256 = _sha256(legacy_root / relative)
        expected_sha256 = baseline[relative]
        item = {
            "legacy_path": relative,
            "category": DISPOSITION_CATEGORIES[disposition["disposition"]],
            "disposition": disposition["disposition"],
            "owners": list(disposition["owners"]),
            "rationale": disposition["rationale"],
            "executable": _is_executable_script(legacy_root / relative, relative),
            "sha256": actual_sha256,
            "expected_sha256": expected_sha256,
        }
        inventory.append(item)
        if actual_sha256 != expected_sha256:
            content_mismatches.append(
                {
                    "legacy_path": relative,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                }
            )
        for owner in item["owners"]:
            owner_path = _owner_path(new_root, owner)
            if not owner_path.is_file():
                missing_owners.append({"legacy_path": relative, "owner": owner})

    disposition_counts = {
        status: sum(item["disposition"] == status for item in inventory)
        for status in sorted(ALLOWED_DISPOSITIONS)
    }
    category_counts = {
        category: sum(item["category"] == category for item in inventory)
        for category in ("migrated", "replaced", "retired")
    }
    executable_count = sum(item["executable"] for item in inventory) + len(
        undisposed_executables
    )
    result = {
        "schema_version": 1,
        "ok": not (
            missing_legacy_files
            or undisposed_files
            or undisposed_executables
            or missing_owners
            or content_mismatches
            or unsafe_legacy_paths
        ),
        "summary": {
            "legacy_files": len(legacy_files),
            "expected_legacy_files": len(DISPOSITIONS),
            "missing_legacy_files": len(missing_legacy_files),
            "content_hash_mismatches": len(content_mismatches),
            "executable_scripts": executable_count,
            "undisposed_executables": len(undisposed_executables),
            "categories": category_counts,
            "dispositions": disposition_counts,
        },
        "inventory": inventory,
        "baseline_manifest": BASELINE_PATH.as_posix(),
        "content_mismatches": sorted(
            content_mismatches, key=lambda item: item["legacy_path"]
        ),
        "missing_legacy_files": missing_legacy_files,
        "undisposed_files": sorted(undisposed_files),
        "undisposed_executables": sorted(undisposed_executables),
        "missing_owners": sorted(
            missing_owners, key=lambda item: (item["legacy_path"], item["owner"])
        ),
        "unsafe_legacy_paths": sorted(unsafe_legacy_paths),
        "retained_rules": list(RETAINED_RULES),
        "rejected_rules": list(REJECTED_RULES),
    }
    return result


def write_migration_report(new_root: Path, result: dict[str, Any]) -> Path:
    """Atomically publish a successful audit under the replacement repository."""
    new_root = _directory(new_root, "new root")
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ValueError("cannot publish an incomplete migration audit")
    destination = new_root.joinpath(*REPORT_PATH.parts)
    _require_inside(new_root, destination.parent, "report path must stay inside the new root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _require_inside(new_root, destination.parent, "report path must stay inside the new root")
    payload = _render_report(result)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, destination)
        temporary = None
        _sync_directory(destination.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def _legacy_files(root: Path) -> tuple[list[str], list[str]]:
    files = []
    unsafe = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_NAMES for part in relative.parts):
            continue
        if path.suffix in IGNORED_SUFFIXES:
            continue
        relative_text = relative.as_posix()
        if path.is_symlink():
            unsafe.append(relative_text)
            continue
        if path.is_file():
            files.append(relative_text)
    return files, unsafe


def _is_executable_script(path: Path, relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts or parts[0] != "scripts":
        return False
    if path.suffix.casefold() in {".py", ".sh"} or os.access(path, os.X_OK):
        return True
    try:
        with path.open("rb") as stream:
            return stream.read(2) == b"#!"
    except OSError:
        return False


def _validate_disposition(relative: str, disposition: dict[str, Any]) -> None:
    if disposition.get("disposition") not in ALLOWED_DISPOSITIONS:
        raise ValueError(f"invalid disposition for {relative}")
    owners = disposition.get("owners")
    if not isinstance(owners, list) or not owners:
        raise ValueError(f"disposition for {relative} needs owner paths")
    for owner in owners:
        _safe_relative(owner, f"owner for {relative}")
    rationale = disposition.get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ValueError(f"disposition for {relative} needs a rationale")


def _owner_path(root: Path, owner: str) -> Path:
    relative = _safe_relative(owner, "owner")
    path = root.joinpath(*relative.parts)
    _require_inside(root, path, "owner path must stay inside the new root")
    return path


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a safe relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a safe relative POSIX path")
    return path


def _load_baseline(root: Path) -> dict[str, str]:
    path = root.joinpath(*BASELINE_PATH.parts)
    _require_inside(root, path, "baseline manifest must stay inside the new root")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"baseline manifest is missing: {BASELINE_PATH.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("baseline manifest is not valid JSON") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "legacy_skill", "files"}
        or payload.get("schema_version") != 1
        or payload.get("legacy_skill") != "knowledge-video-visual-director"
        or not isinstance(payload.get("files"), list)
    ):
        raise ValueError("baseline manifest has an invalid schema")
    baseline: dict[str, str] = {}
    for entry in payload["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("baseline manifest file entry has an invalid schema")
        relative = _safe_relative(entry.get("path"), "baseline legacy path").as_posix()
        digest = entry.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"baseline SHA-256 is invalid for {relative}")
        if relative in baseline:
            raise ValueError(f"baseline legacy path is duplicated: {relative}")
        baseline[relative] = digest
    if set(baseline) != set(DISPOSITIONS):
        raise ValueError("baseline manifest paths must exactly match migration dispositions")
    if list(baseline) != sorted(baseline):
        raise ValueError("baseline manifest file entries must be sorted by path")
    return baseline


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"legacy file cannot be hashed: {path.name}") from error
    return digest.hexdigest()


def _directory(value: Path, label: str) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"{label} must be an existing directory") from error
    if not resolved.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return resolved


def _require_inside(root: Path, path: Path, message: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(message) from None


def _render_report(result: dict[str, Any]) -> str:
    summary = result["summary"]
    counts = summary["dispositions"]
    lines = [
        "# Migration Audit: knowledge-video-visual-director",
        "",
        "This report inventories the installed legacy skill without modifying it. The",
        "legacy root is supplied at audit time; no machine-local legacy path is part of",
        "the replacement library. Every source hash is compared with the committed",
        "baseline, so a same-path content change blocks this auditable retirement gate.",
        "",
        "## Summary",
        "",
        f"- Legacy files inventoried: {summary['legacy_files']}",
        f"- Expected stable legacy files: {summary['expected_legacy_files']}",
        f"- Missing expected legacy files: {summary['missing_legacy_files']}",
        f"- Baseline manifest: `{result['baseline_manifest']}`",
        f"- Content hash mismatches: {summary['content_hash_mismatches']}",
        f"- Executable legacy scripts: {summary['executable_scripts']}",
        f"- Undisposed executable scripts: {summary['undisposed_executables']}",
        "- Lifecycle categories: "
        + ", ".join(
            f"{summary['categories'][status]} {status}"
            for status in ("migrated", "replaced", "retired")
        ),
        "- Dispositions: "
        + ", ".join(
            f"{counts[status]} {status}" for status in ("migrated", "replaced", "externalized", "rejected")
        ),
        "",
        "## File dispositions",
        "",
        "| Legacy file | Source SHA-256 | Category | Disposition | New owner paths | Rationale |",
        "|---|---|---|---|---|---|",
    ]
    for item in result["inventory"]:
        owners = ", ".join(f"`{owner}`" for owner in item["owners"])
        lines.append(
            f"| `{item['legacy_path']}` | `{item['sha256']}` | {item['category']} | {item['disposition']} | {owners} | {item['rationale']} |"
        )
    lines.extend(["", "## Retained rules", ""])
    lines.extend(f"- {rule}" for rule in result["retained_rules"])
    lines.extend(["", "## Rejected rules", ""])
    lines.extend(f"- {rule}" for rule in result["rejected_rules"])
    lines.extend(
        [
            "",
            "## Retirement gate",
            "",
            "This audit only establishes disposition coverage. It does not authorize removal",
            "or modification of the installed legacy skill. Retirement remains blocked until",
            "the replacement plugin is host-installed and enabled, its complete distributable file",
            "inventory and content hashes match the reviewed repository, and required project and",
            "review-pack templates are present. Only generated test/cache and Git scratch are excluded",
            "from that identity check. Its own verifier then runs in an isolated Python subprocess and",
            "must pass the live migration audit, recovery,",
            "four-gate type and lineage counterexamples, a persisted voice-source decision,",
            "current real voice-timing, voice-timing descendant invalidation, and",
            "representative-slice timing-provenance smoke tests before the user gives",
            "execution-time approval for the exact legacy directory. The verifier also reports",
            "capability-scoped external adapters, including ChatCut Voice when it is available;",
            "availability alone does not authorize an undeclared provider fallback.",
            "",
        ]
    )
    return "\n".join(lines)


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit_legacy(args.legacy, args.new)
    except ValueError as error:
        parser.error(str(error))
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    report = write_migration_report(args.new, result)
    print(
        f"migration audit valid: {result['summary']['legacy_files']} legacy files; "
        f"undisposed executables=0; report={report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

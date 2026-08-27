#!/usr/bin/env python3
"""Retire the exact audited legacy skill only after smoke and approval."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.migration_audit import REPORT_PATH, audit_legacy
from scripts.validate_package import validate_package
from scripts.verify_installation import discover_host_installed_plugin


EXPECTED_BASENAME = "knowledge-video-visual-director"
PLUGIN_ID = "video-production-toolkit"
_DISTRIBUTABLE_REQUIRED = {
    ".codex-plugin/plugin.json",
    "agents/openai.yaml",
    "assets/project-template/project.json",
    "assets/project-template/review-pack/index.html",
    "skills/video-director/SKILL.md",
    "skills/voiceover-producer/SKILL.md",
    "scripts/verify_installation.py",
    "scripts/build_review_pack.py",
    "scripts/migration_audit.py",
    "scripts/validate_package.py",
    "scripts/plan_representative_slice.py",
    "scripts/toolkit/adapters.py",
    "scripts/toolkit/artifacts.py",
    "scripts/toolkit/contracts.py",
    "scripts/toolkit/invalidation.py",
    "scripts/toolkit/orchestrator.py",
    "scripts/toolkit/project_state.py",
    "scripts/toolkit/tasks.py",
    "scripts/toolkit/validation.py",
    "scripts/toolkit/voice.py",
    "scripts/toolkit/voice_tasks.py",
    "scripts/toolkit/image_context.py",
    "references/policies/decision-gates.md",
    "references/policies/invalidation.json",
    "references/policies/knowledge-video-visual-director-baseline.json",
    "references/policies/project-assets.md",
    "references/schemas/event.schema.json",
    "references/schemas/image-task-context.schema.json",
    "references/schemas/project.schema.json",
    "references/schemas/scene-contract.schema.json",
    "references/schemas/voice-source-decision.schema.json",
    "references/schemas/voice-profile.schema.json",
    "references/schemas/voiceover.schema.json",
    "references/schemas/voice-timing.schema.json",
    "references/schemas/task-envelope.schema.json",
    "references/schemas/task-result.schema.json",
    "registries/adapters/chatcut.json",
    "skills/scene-producer/SKILL.md",
    "skills/structural-validator/SKILL.md",
    "skills/timeline-assembler/SKILL.md",
    "tests/fixtures/knowledge-video-minimal/scene-contracts.json",
    "docs/migration/knowledge-video-visual-director.md",
}
# Everything outside this explicit generated/Git scratch set participates in
# installed-package identity, including future top-level runtime asset trees.
_NON_DISTRIBUTABLE_NAMES = {
    ".coverage",
    ".DS_Store",
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".tox",
    ".worktrees",
    "__pycache__",
    "htmlcov",
}
_NON_DISTRIBUTABLE_SUFFIXES = {".pyc", ".pyo"}


def retire_legacy_skill(
    legacy_root: Path,
    repo_root: Path,
    *,
    confirmation: Optional[str],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Audit, smoke, and optionally remove one exact legacy directory.

    ``confirmation`` must be the exact resolved target for a destructive run.
    A dry run performs every prerequisite without modifying either directory.
    """
    supplied = Path(legacy_root)
    if supplied.is_symlink():
        raise ValueError("legacy retirement target must not be a symlink")
    try:
        target = supplied.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("legacy retirement target must be an existing directory") from error
    if not target.is_dir():
        raise ValueError("legacy retirement target must be a directory")
    if (
        target.name != EXPECTED_BASENAME
        or target.parent.name != "skills"
        or target.parent.parent.name != ".codex"
    ):
        raise ValueError("legacy retirement target is not the exact expected skill directory")
    if not dry_run and confirmation != str(target):
        raise PermissionError("exact resolved target confirmation is required")
    repo = _existing_repo(repo_root)
    personal_home = target.parents[2]
    installed = _installed_plugin_candidate(personal_home)
    package_issues = validate_package(repo)
    if package_issues:
        missing = [issue for issue in package_issues if issue.startswith("missing:")]
        label = (
            "replacement repository is missing required runtime files"
            if missing
            else "replacement repository package is invalid"
        )
        raise RuntimeError(f"{label}: " + ", ".join(package_issues))
    _require_matching_runtime_packages(repo, installed)

    try:
        audit = audit_legacy(target, repo)
    except ValueError as error:
        raise RuntimeError(f"live migration audit failed: {error}") from error
    if not audit["ok"]:
        raise RuntimeError("live migration audit failed; retirement is blocked")
    verification = _run_installed_verifier(installed, personal_home, target)
    smoke = verification["resume_smoke"]
    report = _retirement_report(repo)
    if dry_run:
        return {
            "status": "ready",
            "target": str(target),
            "migration_audit": "passed",
            "host_installation": "passed",
            "resume_smoke": "passed",
            "deleted": False,
        }

    quarantine = target.parent / f".{target.name}.retiring-{uuid4().hex}"
    original_report = report.read_bytes()
    os.replace(target, quarantine)
    try:
        event = _append_retirement_event(repo, report, target)
    except BaseException:
        if quarantine.exists() and not target.exists():
            os.replace(quarantine, target)
        _restore_report(report, original_report)
        raise
    try:
        shutil.rmtree(quarantine)
    except BaseException as error:
        raise RuntimeError(
            f"retirement event was recorded but quarantine removal failed: {quarantine}"
        ) from error
    return {
        "status": "retired",
        "target": str(target),
        "migration_audit": "passed",
        "host_installation": "passed",
        "resume_smoke": "passed",
        "deleted": True,
        "retirement_event": event,
    }


def _retirement_report(repo: Path) -> Path:
    report = repo.joinpath(*REPORT_PATH.parts)
    if report.is_symlink() or not report.is_file():
        raise RuntimeError("migration report is missing or unsafe")
    try:
        report.resolve().relative_to(repo.resolve())
    except ValueError:
        raise RuntimeError("migration report escapes the repository") from None
    return report


def _append_retirement_event(repo: Path, report: Path, target: Path) -> str:
    if _retirement_report(repo) != report:
        raise RuntimeError("migration report changed before retirement event publication")
    retired_at = datetime.now(timezone.utc).isoformat()
    event = f"- {retired_at} — retired exact audited directory `{target}`."
    original = report.read_text(encoding="utf-8").rstrip()
    heading = "## Retirement events"
    if heading in original:
        payload = f"{original}\n{event}\n"
    else:
        payload = f"{original}\n\n{heading}\n\n{event}\n"
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=report.parent, delete=False
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, report)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return event


def _restore_report(report: Path, payload: bytes) -> None:
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=report.parent, delete=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, report)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _installed_plugin_candidate(home: Path) -> Path:
    try:
        return discover_host_installed_plugin(home, PLUGIN_ID)
    except ValueError as error:
        raise RuntimeError(
            f"replacement plugin is not host-installed: {error}"
        ) from error


def _require_matching_runtime_packages(repo: Path, installed: Path) -> None:
    source_hashes = _distributable_hashes(repo, "replacement repository")
    installed_hashes = _distributable_hashes(installed, "host-installed replacement")
    if source_hashes == installed_hashes:
        return
    missing = sorted(set(source_hashes) - set(installed_hashes))
    extra = sorted(set(installed_hashes) - set(source_hashes))
    changed = sorted(
        relative
        for relative in set(source_hashes) & set(installed_hashes)
        if source_hashes[relative] != installed_hashes[relative]
    )
    detail = []
    if missing:
        detail.append(f"missing={missing}")
    if extra:
        detail.append(f"extra={extra}")
    if changed:
        detail.append(f"changed={changed}")
    raise RuntimeError(
        "host-installed replacement content does not match the repository: "
        + "; ".join(detail)
    )


def _distributable_hashes(root: Path, label: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    def raise_walk_error(error: OSError) -> None:
        raise RuntimeError(f"{label} distributable tree is unreadable") from error

    for directory, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=raise_walk_error,
        followlinks=False,
    ):
        parent = Path(directory)
        distributable_directories = []
        for name in sorted(directory_names):
            if name in _NON_DISTRIBUTABLE_NAMES:
                continue
            path = parent / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                raise RuntimeError(f"{label} distributable directory is a symlink: {relative}")
            distributable_directories.append(name)
        directory_names[:] = distributable_directories

        for name in sorted(file_names):
            if name in _NON_DISTRIBUTABLE_NAMES:
                continue
            path = parent / name
            if path.suffix in _NON_DISTRIBUTABLE_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if path.is_symlink():
                raise RuntimeError(
                    f"{label} distributable file is a symlink: {relative.as_posix()}"
                )
            if not path.is_file():
                raise RuntimeError(
                    f"{label} distributable entry is not a regular file: {relative.as_posix()}"
                )
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as error:
                raise RuntimeError(
                    f"{label} distributable file is unreadable: {relative.as_posix()}"
                ) from error
            hashes[relative.as_posix()] = digest.hexdigest()
    missing_required = sorted(_DISTRIBUTABLE_REQUIRED - set(hashes))
    if missing_required:
        raise RuntimeError(f"{label} is missing required runtime files: {missing_required}")
    return hashes


def _run_installed_verifier(
    installed: Path,
    home: Path,
    legacy: Path,
) -> dict[str, Any]:
    entrypoint = installed / "scripts" / "verify_installation.py"
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    command = [
        sys.executable,
        "-I",
        str(entrypoint),
        "--home",
        str(home),
        "--legacy-root",
        str(legacy),
        "--require-skill",
        "video-director",
        "--require-resume-smoke",
        "--check-external-skills",
    ]
    try:
        with tempfile.TemporaryDirectory() as folder:
            completed = subprocess.run(
                command,
                cwd=folder,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("installed verifier could not execute in isolation") from error
    try:
        result = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        detail = completed.stderr.strip().splitlines()
        suffix = detail[-1] if detail else "no structured verifier result"
        raise RuntimeError(f"installed verifier failed in isolation: {suffix}") from error
    if not isinstance(result, dict):
        raise RuntimeError("installed verifier returned a non-object result")
    plugin = result.get("plugin")
    smoke = result.get("resume_smoke")
    reported_root = plugin.get("root") if isinstance(plugin, dict) else None
    try:
        root_matches = Path(reported_root).resolve() == installed.resolve()
    except (OSError, TypeError):
        root_matches = False
    smoke_checks = smoke.get("checks") if isinstance(smoke, dict) else None
    external = result.get("external_adapters")
    chatcut = external.get("chatcut") if isinstance(external, dict) else None
    capabilities = chatcut.get("capabilities") if isinstance(chatcut, dict) else None
    chatcut_base_available = (
        isinstance(chatcut, dict)
        and chatcut.get("available") is True
        and chatcut.get("installed_skill") == "chatcut:chatcut-plugin-basics"
    )
    chatcut_voice_available = isinstance(capabilities, dict) and all(
        isinstance(capabilities.get(capability), dict)
        and capabilities[capability].get("installed_skill") == "chatcut:voice"
        and capabilities[capability].get("available") is True
        for capability in ("voice.synthesize", "voice.time")
    )
    if (
        completed.returncode != 0
        or result.get("ok") is not True
        or not isinstance(plugin, dict)
        or plugin.get("discovery") != "host-installed"
        or plugin.get("valid") is not True
        or not root_matches
        or not isinstance(smoke, dict)
        or smoke.get("ok") is not True
        or not isinstance(smoke_checks, dict)
        or smoke_checks.get("migration_audit") != "passed"
        or not chatcut_base_available
        or not chatcut_voice_available
    ):
        if not chatcut_base_available or not chatcut_voice_available:
            raise RuntimeError(
                "installed verifier blocked retirement: ChatCut base skill and "
                "ChatCut Voice capabilities voice.synthesize/voice.time are required"
            )
        raise RuntimeError(
            "installed verifier blocked retirement: "
            + repr(result.get("errors") or smoke or result)
        )
    return result


def _existing_repo(value: Path) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ValueError("replacement repository must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("replacement repository must be an existing directory") from error
    if not resolved.is_dir() or not (resolved / ".codex-plugin" / "plugin.json").is_file():
        raise ValueError("replacement repository is not the toolkit plugin")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--confirm-exact-path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(args.legacy.resolve())
    try:
        result = retire_legacy_skill(
            args.legacy,
            args.repo,
            confirmation=args.confirm_exact_path,
            dry_run=args.dry_run,
        )
    except (PermissionError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

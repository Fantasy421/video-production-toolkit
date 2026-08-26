#!/usr/bin/env python3
"""Retire the exact audited legacy skill only after smoke and approval."""

import argparse
import json
import os
import shutil
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
from scripts.verify_installation import discover_host_installed_plugin, run_smoke


EXPECTED_BASENAME = "knowledge-video-visual-director"


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
    try:
        installed = discover_host_installed_plugin(personal_home)
    except ValueError as error:
        raise RuntimeError(f"replacement plugin is not host-installed: {error}") from error
    package_issues = validate_package(installed)
    if package_issues:
        raise RuntimeError(
            "host-installed replacement plugin is invalid: " + ", ".join(package_issues)
        )
    if _plugin_manifest(installed) != _plugin_manifest(repo):
        raise RuntimeError("host-installed replacement release does not match the repository")

    try:
        audit = audit_legacy(target, repo)
    except ValueError as error:
        raise RuntimeError(f"live migration audit failed: {error}") from error
    if not audit["ok"]:
        raise RuntimeError("live migration audit failed; retirement is blocked")
    try:
        installed_audit = audit_legacy(target, installed)
    except ValueError as error:
        raise RuntimeError(f"host-installed migration audit failed: {error}") from error
    if not installed_audit["ok"]:
        raise RuntimeError("host-installed migration audit failed; retirement is blocked")
    smoke = run_smoke(installed, legacy_root=target)
    if not smoke["ok"]:
        raise RuntimeError(f"resume and representative-slice smoke failed: {smoke['blocker']}")
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


def _plugin_manifest(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            (root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("replacement plugin manifest is unreadable") from error
    if not isinstance(value, dict):
        raise RuntimeError("replacement plugin manifest is invalid")
    return value


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

#!/usr/bin/env python3
"""Register a local plugin source in the supported personal Codex marketplace."""

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

from scripts.validate_package import validate_package


def install_personal_plugin(
    source: Path,
    *,
    home: Optional[Path] = None,
    mode: str = "link",
    replace: bool = False,
) -> dict[str, Any]:
    """Register *source* below a personal home and update its local marketplace.

    Existing same-ID targets are never replaced implicitly. Explicit replacement
    moves the old target into a recoverable backup directory before publishing
    the new link or copy. Registration makes the source available to the host;
    the user must still install and enable it from the Plugins Directory.
    """
    source = _existing_directory(source, "plugin source")
    issues = validate_package(source)
    if issues:
        raise ValueError(f"plugin package is invalid: {', '.join(issues)}")
    if mode not in {"link", "copy"}:
        raise ValueError("mode must be link or copy")
    manifest = _read_manifest(source)
    plugin_id = _plugin_id(manifest)
    personal_home = Path.home() if home is None else Path(home)
    personal_home.mkdir(parents=True, exist_ok=True)
    personal_home = personal_home.resolve()
    plugins_root = personal_home / ".codex" / "plugins"
    marketplace_path = personal_home / ".agents" / "plugins" / "marketplace.json"
    target = plugins_root / plugin_id
    _require_inside(personal_home, target, "plugin target must remain below personal home")
    _require_inside(
        personal_home,
        marketplace_path,
        "personal marketplace must remain below personal home",
    )

    marketplace = _read_marketplace(marketplace_path)
    existing_entry = next(
        (entry for entry in marketplace["plugins"] if entry.get("name") == plugin_id),
        None,
    )
    if (_lexists(target) or existing_entry is not None) and not replace:
        raise FileExistsError(
            f"personal plugin already exists: {plugin_id}; use replace to preserve a backup"
        )

    backup: Optional[Path] = None
    published = False
    plugins_root.mkdir(parents=True, exist_ok=True)
    try:
        if _lexists(target):
            backup = _backup_target(plugins_root, target, plugin_id)
        if mode == "link":
            target.symlink_to(source, target_is_directory=True)
        else:
            shutil.copytree(
                source,
                target,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    ".git", ".worktrees", ".superpowers", "__pycache__", "*.pyc"
                ),
            )
        published = True
        entry = {
            "name": plugin_id,
            "source": {
                "source": "local",
                "path": f"./.codex/plugins/{plugin_id}",
            },
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": "Video",
        }
        marketplace["plugins"] = [
            item for item in marketplace["plugins"] if item.get("name") != plugin_id
        ] + [entry]
        _write_json_atomically(marketplace_path, marketplace)
    except BaseException:
        if published:
            _remove_exact_target(target)
        if backup is not None and _lexists(backup) and not _lexists(target):
            os.replace(backup, target)
        raise

    return {
        "plugin_id": plugin_id,
        "plugin_version": manifest["version"],
        "release_fingerprint": manifest["release_fingerprint"],
        "plugin_path": str(target),
        "marketplace_path": str(marketplace_path),
        "mode": mode,
        "backup_path": None if backup is None else str(backup),
        "host_installed": False,
        "restart_required": True,
    }


def _read_manifest(source: Path) -> dict[str, Any]:
    path = source / ".codex-plugin" / "plugin.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("plugin manifest is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("plugin manifest must be an object")
    return value


def _plugin_id(manifest: dict[str, Any]) -> str:
    value = manifest.get("id")
    if value is None:
        value = manifest.get("name")
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError("plugin manifest needs a safe id or name")
    return value


def _read_marketplace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": "personal",
            "interface": {"displayName": "Personal Plugins"},
            "plugins": [],
        }
    if path.is_symlink():
        raise ValueError("personal marketplace must not be a symlink")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("personal marketplace is not valid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("plugins"), list):
        raise ValueError("personal marketplace must contain a plugins list")
    if any(not isinstance(item, dict) for item in value["plugins"]):
        raise ValueError("personal marketplace plugin entries must be objects")
    return value


def _backup_target(plugins_root: Path, target: Path, plugin_id: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = plugins_root / ".backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{plugin_id}-{stamp}-{uuid4().hex[:8]}"
    os.replace(target, backup)
    return backup


def _write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _remove_exact_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _existing_directory(value: Path, label: str) -> Path:
    path = Path(value)
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"{label} must be an existing directory") from error
    if not resolved.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return resolved


def _require_inside(root: Path, path: Path, message: str) -> None:
    try:
        path.parent.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(message) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mode", choices=("link", "copy"), default="link")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args()
    try:
        result = install_personal_plugin(
            args.source,
            home=args.home,
            mode=args.mode,
            replace=args.replace,
        )
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))
    print(result["plugin_path"])
    print(result["marketplace_path"])
    if result["backup_path"]:
        print(f"backup={result['backup_path']}")
    print("restart, then install and enable from the Plugins Directory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

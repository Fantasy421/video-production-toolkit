"""Symlink-safe path boundaries for a runtime video project."""

from pathlib import Path
from typing import Union


PathLike = Union[str, Path]


def project_root(root: PathLike, *, create: bool = False) -> Path:
    """Return a real directory path while rejecting a symlink as the project root."""
    value = Path(root)
    if value.is_symlink():
        raise ValueError("runtime project root must not be a symlink")
    if create:
        value.mkdir(parents=True, exist_ok=True)
    if not value.is_dir():
        raise ValueError("runtime project root must be a directory")
    return value


def project_path(root: PathLike, relative: PathLike) -> Path:
    """Resolve a lexical child without following a symlink inside project storage."""
    base = project_root(root)
    raw_child = str(relative)
    child = Path(relative)
    if (
        not child.parts
        or child.is_absolute()
        or "\\" in raw_child
        or (len(raw_child) >= 2 and raw_child[0].isalpha() and raw_child[1] == ":")
        or any(part in {"", ".", ".."} for part in child.parts)
    ):
        raise ValueError("runtime path must be a safe project-relative path")
    current = base
    for part in child.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"runtime path component must not be a symlink: {current}")
    try:
        current.resolve(strict=False).relative_to(base.resolve(strict=True))
    except (FileNotFoundError, ValueError):
        raise ValueError("runtime path must remain inside the project root") from None
    return current


def storage_directory(root: PathLike, name: str, *, create: bool = False) -> Path:
    """Return one top-level runtime storage directory without following symlinks."""
    directory = project_path(root, name)
    if create:
        directory.mkdir(exist_ok=True)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"runtime storage directory is unsafe: {name}")
    return directory

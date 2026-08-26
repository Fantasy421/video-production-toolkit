#!/usr/bin/env python3
"""Index VideoShotCraft gallery metadata without copying recipe or demo bodies."""

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


DESTINATION = Path(__file__).parents[1] / "registries" / "recipes" / "video-shotcraft-index.json"


def index_video_shotcraft(source: Path) -> dict[str, Any]:
    """Return a metadata-only recipe index from an installed VideoShotCraft skill."""
    index_path = _gallery_index(Path(source))
    try:
        gallery = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid VideoShotCraft gallery index: {index_path}") from error
    cards = gallery.get("cards")
    if not isinstance(cards, list):
        raise ValueError(f"VideoShotCraft gallery has no cards list: {index_path}")

    recipes = []
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("name"), str):
            continue
        source_ref = card.get("source") or card.get("sourceUrl")
        implementation_ref = _implementation_reference(source_ref)
        for style in card.get("styles", []):
            if not isinstance(style, dict) or not isinstance(style.get("key"), str):
                continue
            media = style.get("media") if isinstance(style.get("media"), dict) else {}
            recipes.append(
                {
                    "id": f"video-shotcraft:{card['name']}:{style['key']}",
                    "version": str(gallery.get("revision", "external")),
                    "job": card.get("use", card.get("category", "motion recipe")),
                    "preview": media.get("url", ""),
                    "renderer": "remotion",
                    "implementation_ref": implementation_ref,
                    "license": "Apache-2.0",
                    "mechanism": card.get("category", "motion"),
                    "participants": card.get("tags", []),
                    "duration": _duration_metadata(card.get("duration")),
                    "canvas": ["16:9"],
                    "carriers": card.get("tags", []),
                }
            )
    recipes.sort(key=lambda recipe: recipe["id"])
    return {
        "schema_version": 1,
        "source": _index_reference(index_path, Path(source)),
        "revision": gallery.get("revision", "external"),
        "recipes": recipes,
    }


def _gallery_index(source: Path) -> Path:
    candidates = [source] if source.is_file() else [
        source / "gallery" / "api" / "library.json",
        source / "api" / "library.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"VideoShotCraft gallery index not found below: {source}")


def _index_reference(index_path: Path, source: Path) -> str:
    """Persist a portable external reference rather than a machine-local path."""
    try:
        return f"video-shotcraft:{index_path.relative_to(source)}"
    except ValueError:
        return f"video-shotcraft:{index_path.name}"


def _implementation_reference(source_ref: Any) -> str:
    """Return only a safe, portable external reference from gallery metadata."""
    if source_ref is None:
        return "video-shotcraft:gallery"
    if not isinstance(source_ref, str) or not source_ref:
        raise ValueError("VideoShotCraft source reference must be a non-empty relative POSIX path")
    if "\\" in source_ref or any(ord(character) < 32 or ord(character) == 127 for character in source_ref):
        raise ValueError(f"unsafe VideoShotCraft source reference: {source_ref!r}")
    parts = source_ref.split("/")
    path = PurePosixPath(source_ref)
    if path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe VideoShotCraft source reference: {source_ref!r}")
    return f"video-shotcraft:{source_ref}"


def _duration_metadata(value: Any) -> dict[str, int]:
    """Extract a range from gallery display text without opening recipe bodies."""
    if not isinstance(value, str):
        return {"min": 0, "max": 0}
    seconds = re.search(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\s*s", value)
    if seconds:
        return {"min": int(float(seconds.group(1))), "max": int(float(seconds.group(2)))}
    single_seconds = re.search(r"(?:约|~)?\s*(\d+(?:\.\d+)?)\s*s", value)
    if single_seconds:
        duration = int(float(single_seconds.group(1)))
        return {"min": duration, "max": duration}
    frames = re.search(r"(\d+)\s*f\s*@\s*(\d+)\s*fps", value, re.IGNORECASE)
    if frames and int(frames.group(2)):
        duration = int(round(int(frames.group(1)) / int(frames.group(2))))
        return {"min": duration, "max": duration}
    return {"min": 0, "max": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a metadata-only VideoShotCraft recipe index.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    index = index_video_shotcraft(args.source)
    if not args.check_only:
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        DESTINATION.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"indexed {len(index['recipes'])} VideoShotCraft recipes")


if __name__ == "__main__":
    main()

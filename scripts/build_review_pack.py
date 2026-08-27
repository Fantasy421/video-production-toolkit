#!/usr/bin/env python3
"""Build a static, link-only review bundle for a runtime project."""

import argparse
import html
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

try:
    from scripts.toolkit.runtime_paths import project_path, project_root
    from scripts.toolkit.validation import read_effective_artifacts, resolve_active_timeline, validate_project
except ModuleNotFoundError:
    from toolkit.runtime_paths import project_path, project_root
    from toolkit.validation import read_effective_artifacts, resolve_active_timeline, validate_project


PREVIEW_SUFFIXES = {".html", ".htm", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".wav", ".mp3"}
DECISION_GATE = "Representative slice and final draft"


def build_review_pack(root: Path, output: Path) -> Path:
    """Atomically write ``index.html`` and ``review.json`` below *root*.

    The pack exposes relative file links only.  It deliberately does not embed
    preview bytes or generate creative commentary; subjective decisions remain
    explicit requests for the user.
    """
    lexical_root = project_root(root).absolute()
    requested_output = Path(output)
    if requested_output.is_absolute():
        try:
            relative_output = requested_output.relative_to(lexical_root)
        except ValueError:
            raise ValueError("review pack output must remain inside the project") from None
    else:
        relative_output = requested_output
    root = lexical_root.resolve(strict=True)
    try:
        output = project_path(root, relative_output)
    except ValueError:
        raise ValueError("review pack output must remain inside the project") from None
    output.mkdir(parents=True, exist_ok=True)
    project_path(root, output.relative_to(root) / ".bundles")
    current = output / "current"
    if current.exists() and not current.is_symlink():
        raise ValueError("review pack current pointer must be a symlink")
    validation = validate_project(root)
    previews = _preview_links(root, current)
    active_timeline = resolve_active_timeline(root)
    scenes = _scene_rows(active_timeline[1]) if active_timeline is not None else []
    decision_requests = [{
        "gate": DECISION_GATE,
        "request": "Confirm the representative editable slice and final draft, or record a scoped revision.",
    }]
    review = {
        "schema_version": 1,
        "previews": previews,
        "scenes": scenes,
        "timecoded_warnings": validation["warnings"],
        "structural_errors": validation["errors"],
        "decision_requests": decision_requests,
    }
    return _publish_bundle(output, review, _render_html(previews, scenes, validation, decision_requests))


def _preview_links(root: Path, output: Path) -> list[dict[str, str]]:
    preview_root = root / "previews"
    if not preview_root.is_dir():
        return []
    links = []
    artifacts = read_effective_artifacts(root)
    for artifact_id in sorted(artifacts):
        artifact = artifacts[artifact_id]
        if artifact["status"] != "approved":
            continue
        try:
            path = project_path(root, artifact["path"])
        except ValueError:
            continue
        if not path.is_file() or path.suffix.lower() not in PREVIEW_SUFFIXES:
            continue
        try:
            label = path.relative_to(preview_root).as_posix()
        except ValueError:
            continue
        links.append(
            {
                "artifact_id": artifact_id,
                "label": label,
                "href": os.path.relpath(path, output).replace(os.sep, "/"),
                "status": artifact["status"],
            }
        )
    return links


def _scene_rows(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    tracks = timeline.get("tracks", [])
    clips = timeline.get("clips", []) if isinstance(timeline.get("clips"), list) else [clip for track in tracks if isinstance(track, dict) for clip in track.get("clips", []) if isinstance(clip, dict)]
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get("scene_id"), str) or not clip["scene_id"]:
            continue
        scene_id = clip["scene_id"]
        rows[scene_id] = {"scene_id": scene_id, "start_ms": clip.get("start_ms"), "end_ms": clip.get("end_ms")}
    return [rows[scene_id] for scene_id in sorted(rows)]


def _publish_bundle(output: Path, review: dict[str, Any], rendered_html: str) -> Path:
    """Publish an all-or-nothing bundle through an atomic ``current`` pointer."""
    bundles = output / ".bundles"
    bundles.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=bundles))
    generation = bundles / uuid4().hex
    pointer = output / "current"
    next_pointer = output / f".current-{uuid4().hex}"
    published = False
    try:
        _write_text_atomically(stage / "review.json", json.dumps(review, ensure_ascii=False, indent=2) + "\n")
        _write_text_atomically(stage / "index.html", rendered_html)
        stage.replace(generation)
        next_pointer.symlink_to(generation.relative_to(output))
        os.replace(next_pointer, pointer)
        published = True
        return pointer / "index.html"
    finally:
        next_pointer.unlink(missing_ok=True)
        if not published:
            if generation.exists():
                shutil.rmtree(generation)
            elif stage.exists():
                shutil.rmtree(stage)


def _render_html(previews: list[dict[str, str]], scenes: list[dict[str, Any]], validation: dict[str, list[dict[str, Any]]], decision_requests: list[dict[str, str]]) -> str:
    preview_items = "\n".join(
        f'<li><a href="{html.escape(item["href"], quote=True)}">{html.escape(item["label"])} [{html.escape(item["status"])}]</a></li>'
        for item in previews
    ) or "<li>No preview files were found.</li>"
    scene_items = "\n".join(
        f'<li data-scene-id="{html.escape(scene["scene_id"], quote=True)}">{html.escape(scene["scene_id"])} · {html.escape(str(scene.get("start_ms")))}–{html.escape(str(scene.get("end_ms"))) } ms</li>'
        for scene in scenes
    ) or "<li>No timecoded scenes were found.</li>"
    warning_items = "\n".join(f"<li>{html.escape(item['code'])}</li>" for item in validation["warnings"]) or "<li>None</li>"
    error_items = "\n".join(f"<li>{html.escape(item['code'])}</li>" for item in validation["errors"]) or "<li>None</li>"
    decision_items = "\n".join(f"<li><strong>{html.escape(item['gate'])}</strong>: {html.escape(item['request'])}</li>" for item in decision_requests)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Video review pack</title></head>
<body>
  <main>
    <h1>Video review pack</h1>
    <h2>Preview links</h2><ul>{preview_items}</ul>
    <h2>Scenes</h2><ul>{scene_items}</ul>
    <h2>Timecoded structural warnings</h2><ul>{warning_items}</ul>
    <h2>Structural blockers</h2><ul>{error_items}</ul>
    <h2>Decision requests</h2><ul>{decision_items}</ul>
  </main>
</body>
</html>
"""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_text_atomically(destination: Path, text: str) -> None:
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.replace(destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact link-only video review pack.")
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(build_review_pack(args.root, args.output))


if __name__ == "__main__":
    main()

"""Batch objective media checks with compact, model-safe failure summaries."""

import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from .runtime_paths import project_path, project_root


MAX_BATCH_ITEMS = 6
MAX_EXAMPLES_PER_CODE = 3
_CHECKS = (
    ("json-valid", None),
    ("files-present", "FILE_MISSING"),
    ("duration-valid", "DURATION_MISMATCH"),
    ("av-valid", "AV_STREAM_MISSING"),
    ("black-frame-valid", "BLACK_FRAME_DETECTED"),
    ("cue-order-valid", "CUE_ORDER_INVALID"),
)
_BLACK = re.compile(
    r"black_start:(?P<start>[0-9.]+)\s+black_end:(?P<end>[0-9.]+)"
)


def validate_media_batch_json(
    root: Path,
    manifest_json: str,
    *,
    probe_results: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Validate one JSON batch and return only codes, counts, and bounded examples."""
    try:
        manifest = json.loads(manifest_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _invalid_json_result()
    try:
        items = _validate_manifest(manifest)
    except (TypeError, ValueError):
        return _invalid_json_result()
    root = project_root(root)
    issues: dict[str, list[str]] = {}
    probes = probe_results or {}
    for item in items:
        scene_id = item["scene_id"]
        try:
            media_path = project_path(root, item["path"])
        except ValueError:
            _add_issue(issues, "FILE_MISSING", scene_id)
            continue
        if not media_path.is_file():
            _add_issue(issues, "FILE_MISSING", scene_id)
            continue
        probe = probes.get(item["path"])
        if probe is None:
            try:
                probe = _probe_media(media_path)
            except (OSError, ValueError, subprocess.SubprocessError):
                _add_issue(issues, "PROBE_FAILED", scene_id)
                continue
        if not _duration_matches(probe.get("duration_ms"), item["expected_duration_ms"]):
            _add_issue(issues, "DURATION_MISMATCH", scene_id)
        streams = probe.get("streams")
        if not isinstance(streams, list) or not set(item["required_streams"]) <= set(streams):
            _add_issue(issues, "AV_STREAM_MISSING", scene_id)
        black = probe.get("black_intervals_ms")
        if not isinstance(black, list) or black:
            _add_issue(issues, "BLACK_FRAME_DETECTED", scene_id)
        if not _cues_are_ordered(item):
            _add_issue(issues, "CUE_ORDER_INVALID", scene_id)
    issue_counts = {code: len(ids) for code, ids in sorted(issues.items())}
    examples = {
        code: ids[:MAX_EXAMPLES_PER_CODE] for code, ids in sorted(issues.items())
    }
    failed_codes = set(issues)
    checks = [
        check
        for check, failure_code in _CHECKS
        if failure_code is None or failure_code not in failed_codes
    ]
    return {
        "status": "blocked" if issues else "passed",
        "checks": checks,
        "issue_counts": issue_counts,
        "examples": examples,
    }


def _validate_manifest(manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(manifest, Mapping) or set(manifest) != {"items"}:
        raise ValueError("media batch manifest must be closed")
    items = manifest["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
        raise ValueError("media batch must contain one to six items")
    normalized = []
    scene_ids: set[str] = set()
    for raw in items:
        required = {
            "scene_id",
            "path",
            "start_ms",
            "end_ms",
            "expected_duration_ms",
            "required_streams",
            "cues",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ValueError("media batch item fields are invalid")
        item = dict(raw)
        scene_id = item["scene_id"]
        if not isinstance(scene_id, str) or not scene_id or scene_id in scene_ids:
            raise ValueError("media batch scene IDs must be unique strings")
        scene_ids.add(scene_id)
        if not isinstance(item["path"], str) or not item["path"]:
            raise ValueError("media batch path is invalid")
        start, end, duration = (
            item["start_ms"],
            item["end_ms"],
            item["expected_duration_ms"],
        )
        if (
            any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end, duration))
            or not 0 <= start < end <= 36_000_000
            or duration != end - start
        ):
            raise ValueError("media batch timing is invalid")
        streams = item["required_streams"]
        if (
            not isinstance(streams, list)
            or not streams
            or not set(streams) <= {"audio", "video"}
            or len(streams) != len(set(streams))
        ):
            raise ValueError("media batch required streams are invalid")
        if not isinstance(item["cues"], list) or len(item["cues"]) > 64:
            raise ValueError("media batch cues are invalid")
        normalized.append(item)
    return normalized


def _cues_are_ordered(item: Mapping[str, Any]) -> bool:
    previous = -1
    seen: set[str] = set()
    for cue in item["cues"]:
        if not isinstance(cue, Mapping) or set(cue) != {"cue_id", "at_ms"}:
            return False
        cue_id, at_ms = cue["cue_id"], cue["at_ms"]
        if (
            not isinstance(cue_id, str)
            or not cue_id
            or cue_id in seen
            or isinstance(at_ms, bool)
            or not isinstance(at_ms, int)
            or not item["start_ms"] <= at_ms < item["end_ms"]
            or at_ms <= previous
        ):
            return False
        seen.add(cue_id)
        previous = at_ms
    return True


def _duration_matches(actual: Any, expected: int) -> bool:
    return (
        not isinstance(actual, bool)
        and isinstance(actual, int)
        and abs(actual - expected) <= 100
    )


def _probe_media(path: Path) -> dict[str, Any]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise ValueError("ffprobe failed")
    payload = json.loads(probe.stdout)
    duration = float(payload["format"]["duration"])
    streams = sorted(
        {
            item.get("codec_type")
            for item in payload.get("streams", [])
            if item.get("codec_type") in {"audio", "video"}
        }
    )
    black = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "info",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.2:pix_th=0.98",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if black.returncode != 0:
        raise ValueError("ffmpeg blackdetect failed")
    intervals = [
        [round(float(match.group("start")) * 1_000), round(float(match.group("end")) * 1_000)]
        for match in _BLACK.finditer(black.stderr)
    ]
    return {
        "duration_ms": round(duration * 1_000),
        "streams": streams,
        "black_intervals_ms": intervals,
    }


def _add_issue(issues: dict[str, list[str]], code: str, scene_id: str) -> None:
    issues.setdefault(code, []).append(scene_id)


def _invalid_json_result() -> dict[str, Any]:
    return {
        "status": "blocked",
        "checks": [],
        "issue_counts": {"INVALID_MANIFEST_JSON": 1},
        "examples": {"INVALID_MANIFEST_JSON": []},
    }

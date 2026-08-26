"""Create and recover the small, event-backed state of a toolkit project."""

import json
import tempfile
from pathlib import Path
from typing import Any


PHASES = (
    "initialized",
    "content_ready",
    "direction_ready",
    "storyboard_ready",
    "production_ready",
    "assembled",
    "review_ready",
    "handoff_ready",
)

RUNTIME_DIRECTORIES = (
    "artifacts",
    "tasks",
    "events",
    "approvals",
    "previews",
    "media",
    "timeline",
)


def initialize_project(target: Path, project_id: str, workflow: str) -> dict[str, Any]:
    """Initialize *target* with an atomic project snapshot and initial event."""
    root = Path(target)
    project_path = root / "project.json"
    event_log = root / "events" / "events.jsonl"
    if project_path.exists() or event_log.exists():
        raise FileExistsError(f"project state already exists at {root}")

    root.mkdir(parents=True, exist_ok=True)
    for directory in RUNTIME_DIRECTORIES:
        (root / directory).mkdir(exist_ok=True)

    state = {
        "schema_version": 1,
        "project_id": project_id,
        "workflow": workflow,
        "phase": "initialized",
    }
    _write_project_atomically(root, state)
    event_log.write_text("", encoding="utf-8")
    append_event(
        root,
        {
            "event": "project.initialized",
            "schema_version": 1,
            "project_id": project_id,
            "workflow": workflow,
        },
    )
    return state


def append_event(root: Path, event: dict[str, Any]) -> None:
    """Append one JSON event and refresh the compact derived project snapshot."""
    root = Path(root)
    event_log = root / "events" / "events.jsonl"
    with event_log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, separators=(",", ":")) + "\n")
    state = replay_events(root)
    if state:
        _write_project_atomically(root, state)


def set_active_timeline(root: Path, active_timeline_id: str) -> dict[str, Any]:
    """Durably select the timeline used by validation and review surfaces."""
    if not _safe_component(active_timeline_id):
        raise ValueError("active_timeline_id must be a safe single path component")
    root = Path(root)
    append_event(
        root,
        {
            "event": "project.active_timeline_changed",
            "active_timeline_id": active_timeline_id,
        },
    )
    return replay_events(root)


def replay_events(root: Path) -> dict[str, Any]:
    """Restore project state from its initial event and later phase changes."""
    state: dict[str, Any] = {}
    event_log = Path(root) / "events" / "events.jsonl"
    for line in event_log.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["event"] == "project.initialized":
            state = {
                "schema_version": event["schema_version"],
                "project_id": event["project_id"],
                "workflow": event["workflow"],
                "phase": "initialized",
            }
        elif event["event"] == "project.phase_changed":
            state["phase"] = event["phase"]
        elif event["event"] == "project.active_timeline_changed":
            state["active_timeline_id"] = event["active_timeline_id"]
    return state


def _write_project_atomically(root: Path, state: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=root, delete=False
    ) as stream:
        json.dump(state, stream, separators=(",", ":"))
        stream.write("\n")
        temporary_path = Path(stream.name)
    temporary_path.replace(root / "project.json")


def _safe_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
    )

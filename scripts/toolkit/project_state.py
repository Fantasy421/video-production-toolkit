"""Create and recover the small, event-backed state of a toolkit project."""

import errno
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

from .runtime_paths import project_path, project_root, storage_directory
from .voice import validate_project_authoritative_voice_bundle
from .invalidation import invalidated_artifact_ids
from .artifacts import validate_artifact_record


PHASES = (
    "initialized",
    "content_ready",
    "direction_ready",
    "voice_ready",
    "storyboard_ready",
    "production_ready",
    "assembled",
    "review_ready",
    "handoff_ready",
)

# The v3 workflow is deliberately kept separate from the historical phase
# tuple.  A v1/v2 event log must replay with its original phase names and
# ordering; a v3 log is never silently interpreted as one of those histories.
V3_PHASES = (
    "script_confirmed",
    "semantic_beats_confirmed",
    "visual_direction_previewed",
    "voiceover_ready",
    "timing_bound",
    "storyboard_timed",
    "representative_scene_ready",
    "production_ready",
)

LEGACY_PROJECT_SCHEMA_VERSION = 1
V2_PROJECT_SCHEMA_VERSION = 2
CURRENT_PROJECT_SCHEMA_VERSION = 3
PROJECT_SCHEMA_VERSIONS = frozenset(
    {LEGACY_PROJECT_SCHEMA_VERSION, V2_PROJECT_SCHEMA_VERSION, CURRENT_PROJECT_SCHEMA_VERSION}
)
V3_PROJECT_SCHEMA_VERSION = 3

# Version-one event logs predate ``voice_ready``.  They remain replayable only
# through the replay compatibility path below; append_event always uses PHASES.
LEGACY_PHASES = (
    "initialized",
    "content_ready",
    "direction_ready",
    "storyboard_ready",
    "production_ready",
    "assembled",
    "review_ready",
    "handoff_ready",
)
_LEGACY_COMPATIBLE_SCHEMA_VERSIONS = frozenset({LEGACY_PROJECT_SCHEMA_VERSION})
_VOICE_REQUIRED_RECOVERY_PHASES = frozenset(
    {
        "storyboard_ready",
        "production_ready",
        "assembled",
        "review_ready",
        "handoff_ready",
    }
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

_EVENT_FIELDS = {
    "project.initialized": {"event", "schema_version", "project_id", "workflow"},
    "project.schema_upgraded": {"event", "schema_version"},
    "project.phase_changed": {"event", "phase"},
    "project.active_timeline_changed": {"event", "active_timeline_id"},
    "artifacts.invalidated": {"event", "changed_id", "artifact_ids"},
}


def initialize_project(
    target: Path,
    project_id: str,
    workflow: str,
    *,
    schema_version: int = V2_PROJECT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Initialize *target* with an event-first, atomically derived snapshot."""
    raw_root = Path(target)
    if raw_root.is_symlink():
        raise ValueError("runtime project root must not be a symlink")
    if raw_root.exists() and (
        (raw_root / "project.json").exists()
        or (raw_root / "events" / "events.jsonl").exists()
    ):
        raise FileExistsError(f"project state already exists at {raw_root}")
    root = project_root(raw_root, create=True)
    storage_directory(root, "events", create=True)
    with _state_lock(root, exclusive=True):
        project_file = project_path(root, "project.json")
        event_log = project_path(root, "events/events.jsonl")
        if project_file.exists() or event_log.exists():
            raise FileExistsError(f"project state already exists at {root}")
        for directory in RUNTIME_DIRECTORIES:
            storage_directory(root, directory, create=True)
        event = {
            "event": "project.initialized",
            "schema_version": schema_version,
            "project_id": project_id,
            "workflow": workflow,
        }
        _validate_event(event, {})
        _create_event_log(event_log, event)
        state = _replay_events_unlocked(root)
        _write_project_atomically(root, state)
        return state


def initialize_v3_project(target: Path, project_id: str, workflow: str) -> dict[str, Any]:
    """Initialize the voice-timed v3 workflow explicitly.

    ``initialize_project`` retains its v2 default for callers that create
    historical-compatible fixtures.  New production callers should use this
    named entry point (or pass ``schema_version=3``) so the workflow contract
    is unambiguous.
    """
    return initialize_project(
        target, project_id, workflow, schema_version=V3_PROJECT_SCHEMA_VERSION
    )


def append_event(root: Path, event: dict[str, Any]) -> None:
    """Durably append one legal event and refresh the compact snapshot under lock."""
    root = project_root(root)
    with _state_lock(root, exclusive=True):
        state = _replay_events_unlocked(root)
        _validate_event_contract(event)
        if (
            event.get("event") == "project.phase_changed"
            and event.get("phase") == "voice_ready"
        ):
            voice = validate_project_authoritative_voice_bundle(root)
            if not voice["ok"]:
                codes = ",".join(
                    sorted({issue["code"] for issue in voice["issues"]})
                )
                raise ValueError(
                    "voice_ready requires an authoritative header-verified "
                    f"voice bundle and readable audio: {codes}"
                )
        if (
            event.get("event") == "project.phase_changed"
            and state.get("schema_version") == V3_PROJECT_SCHEMA_VERSION
        ):
            _validate_v3_phase_gate(root, event["phase"])
        upgrade = _schema_upgrade_for(event, state)
        if upgrade is not None:
            _validate_event(upgrade, state)
            _append_event_durably(project_path(root, "events/events.jsonl"), upgrade)
            state = _replay_events_unlocked(root)
        _validate_event(event, state)
        _append_event_durably(project_path(root, "events/events.jsonl"), event)
        _write_project_atomically(root, _replay_events_unlocked(root))


def set_active_timeline(root: Path, active_timeline_id: str) -> dict[str, Any]:
    """Durably select the timeline used by validation and review surfaces."""
    if not _safe_component(active_timeline_id):
        raise ValueError("active_timeline_id must be a safe single path component")
    root = project_root(root)
    append_event(
        root,
        {
            "event": "project.active_timeline_changed",
            "active_timeline_id": active_timeline_id,
        },
    )
    return replay_events(root)


def replay_events(root: Path) -> dict[str, Any]:
    """Restore project state while validating every event and phase transition."""
    root = project_root(root)
    storage_directory(root, "events")
    with _state_lock(root, exclusive=False):
        return _replay_events_unlocked(root)


def project_recovery_view(
    root: Path,
    artifacts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a non-persisted recovery view for projects predating voice gates.

    Recovery uses the same authoritative file-backed verifier as a live phase
    transition; callers cannot substitute a metadata-only predicate.
    """
    state = replay_events(root)
    if state.get("schema_version") == V3_PROJECT_SCHEMA_VERSION:
        issues = _v3_recovery_issues(root, artifacts)
        if issues:
            return {
                **state,
                "phase": "semantic_beats_confirmed",
                "migration_requirement": {
                    "code": "timing-recovery-blocked",
                    "recorded_phase": state["phase"],
                    "issues": issues,
                },
            }
        return state
    if state["phase"] not in _VOICE_REQUIRED_RECOVERY_PHASES:
        return state
    if validate_project_authoritative_voice_bundle(root, artifacts)["ok"]:
        return state
    return {
        **state,
        "phase": "direction_ready",
        "migration_requirement": {
            "code": "voice-artifacts-required",
            "recorded_phase": state["phase"],
        },
    }


def _v3_recovery_issues(
    root: Path, artifacts: Iterable[Mapping[str, Any]]
) -> list[str]:
    """Return stable compact blockers for a v3 persisted late-phase state."""
    state = replay_events(root)
    phase = state.get("phase")
    if phase not in V3_PHASES or V3_PHASES.index(phase) < V3_PHASES.index("timing_bound"):
        return []
    records = [dict(item) for item in artifacts if isinstance(item, Mapping)]
    approved = [item for item in records if item.get("status") == "approved"]
    voice_bundle = validate_project_authoritative_voice_bundle(root, records)
    voice_timing_id = voice_bundle.get("voice_timing_id")
    voice_matches = [
        item
        for item in approved
        if item.get("type") == "voice-timing"
        and item.get("artifact_id") == voice_timing_id
    ]
    voice = voice_matches[0] if len(voice_matches) == 1 else None
    issues: list[str] = []
    if (
        voice is None
        or voice.get("timing_kind") != "real"
        or not voice_bundle.get("ok")
    ):
        issues.append("VOICE_TIMING_REQUIRED")
        return issues
    timed = max(
        (
            item
            for item in approved
            if item.get("type") == "timed-semantic-beats"
            and item.get("voice_timing_id") == voice.get("artifact_id")
        ),
        key=lambda item: (item.get("version", 0), item.get("artifact_id", "")),
        default=None,
    )
    if timed is None:
        issues.append("TIMED_SEMANTIC_BEATS_REQUIRED")
        return issues
    if voice.get("artifact_id") not in timed.get("parents", []):
        issues.append("TIMED_SEMANTIC_BEATS_REQUIRED")
        return issues
    if V3_PHASES.index(phase) >= V3_PHASES.index("storyboard_timed"):
        scenes = max(
            (
                item
                for item in approved
                if item.get("type") == "scene-timing-contracts"
                and item.get("timed_semantic_beats_id") == timed.get("artifact_id")
            ),
            key=lambda item: (item.get("version", 0), item.get("artifact_id", "")),
            default=None,
        )
        if scenes is None or timed.get("artifact_id") not in scenes.get("parents", []):
            issues.append("SCENE_TIMING_CONTRACTS_REQUIRED")
        elif phase == "production_ready":
            validations = [
                item
                for item in approved
                if item.get("type") == "timing-validation"
                and scenes.get("artifact_id") in item.get("parents", [])
            ]
            validation = max(
                validations,
                key=lambda item: (item.get("version", 0), item.get("artifact_id", "")),
                default=None,
            )
            compact = validation.get("timing_validation") if validation else None
            if not isinstance(compact, Mapping) or compact.get("status") != "passed":
                issues.append("TIMING_VALIDATION_REQUIRED")
    return issues


def _replay_events_unlocked(root: Path) -> dict[str, Any]:
    state: dict[str, Any] = {}
    event_log = project_path(root, "events/events.jsonl")
    try:
        lines = event_log.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"project event log is unavailable: {event_log}") from error
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid project event at line {number}") from error
        try:
            _validate_replayed_event(event, state)
        except ValueError as error:
            raise ValueError(f"invalid project event at line {number}: {error}") from error
        if event["event"] == "project.initialized":
            state = {
                "schema_version": event["schema_version"],
                "project_id": event["project_id"],
                "workflow": event["workflow"],
                "phase": (
                    V3_PHASES[0]
                    if event["schema_version"] == V3_PROJECT_SCHEMA_VERSION
                    else "initialized"
                ),
            }
        elif event["event"] == "project.schema_upgraded":
            state["schema_version"] = event["schema_version"]
        elif event["event"] == "project.phase_changed":
            state["phase"] = event["phase"]
        elif event["event"] == "project.active_timeline_changed":
            state["active_timeline_id"] = event["active_timeline_id"]
    return state


def _validate_event(event: Any, state: dict[str, Any]) -> None:
    _validate_event_contract(event)
    event_name = event["event"]
    if event_name == "project.initialized":
        if state:
            raise ValueError("project.initialized must be the first event")
        if event["schema_version"] not in PROJECT_SCHEMA_VERSIONS:
            raise ValueError("unsupported project schema version")
        for field in ("project_id", "workflow"):
            if not _nonempty_text(event[field]):
                raise ValueError(f"{field} must be non-empty text")
        return
    if not state:
        raise ValueError("project event log must begin with project.initialized")
    if event_name == "project.schema_upgraded":
        if event["schema_version"] != V2_PROJECT_SCHEMA_VERSION:
            raise ValueError("unsupported project schema upgrade version")
        if (
            state.get("schema_version") != LEGACY_PROJECT_SCHEMA_VERSION
            or state.get("phase") != "direction_ready"
        ):
            raise ValueError("project schema upgrade requires legacy direction_ready")
    elif event_name == "project.phase_changed":
        phase = event["phase"]
        current = state.get("phase")
        schema_version = state.get("schema_version")
        phase_order = (
            V3_PHASES
            if schema_version == V3_PROJECT_SCHEMA_VERSION
            else PHASES
        )
        if phase not in phase_order:
            raise ValueError("project phase is not recognized")
        if (
            schema_version == LEGACY_PROJECT_SCHEMA_VERSION
            and phase not in LEGACY_PHASES
        ):
            raise ValueError("project phase requires a schema upgrade")
        if current not in phase_order:
            raise ValueError(f"illegal project phase transition: {current!r} -> {phase!r}")
        # The preview phase is optional: semantic_beats_confirmed may advance
        # directly to voiceover_ready, but the preview may not jump over the
        # voice/timing/storyboard checkpoints.
        legal = (
            phase_order.index(phase) == phase_order.index(current) + 1
            or (
                schema_version == V3_PROJECT_SCHEMA_VERSION
                and current == "semantic_beats_confirmed"
                and phase == "voiceover_ready"
            )
        )
        if not legal:
            raise ValueError(f"illegal project phase transition: {current!r} -> {phase!r}")
    elif event_name == "project.active_timeline_changed":
        if not _safe_component(event["active_timeline_id"]):
            raise ValueError("active_timeline_id must be a safe component")
    else:
        if not _safe_component(event["changed_id"]):
            raise ValueError("changed_id must be a safe component")
        artifact_ids = event["artifact_ids"]
        if (
            not isinstance(artifact_ids, list)
            or len(artifact_ids) != len(set(artifact_ids))
            or any(not _safe_component(item) for item in artifact_ids)
        ):
            raise ValueError("artifact_ids must be unique safe components")


def _validate_event_contract(event: Any) -> None:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    event_name = event.get("event")
    if event_name not in _EVENT_FIELDS or set(event) != _EVENT_FIELDS[event_name]:
        raise ValueError("event does not match a supported event contract")


def _validate_replayed_event(event: Any, state: dict[str, Any]) -> None:
    """Validate persisted events, admitting only known v1 pre-voice history."""
    try:
        _validate_event(event, state)
    except ValueError:
        if not _is_legacy_phase_transition(event, state):
            raise


def _is_legacy_phase_transition(event: Any, state: Mapping[str, Any]) -> bool:
    """Recognize the one phase-order difference in readable version-one logs."""
    if (
        not isinstance(event, dict)
        or set(event) != _EVENT_FIELDS["project.phase_changed"]
        or event.get("event") != "project.phase_changed"
    ):
        return False
    if state.get("schema_version") not in _LEGACY_COMPATIBLE_SCHEMA_VERSIONS:
        return False
    current = state.get("phase")
    phase = event.get("phase")
    return (
        current in LEGACY_PHASES
        and phase in LEGACY_PHASES
        and LEGACY_PHASES.index(phase) == LEGACY_PHASES.index(current) + 1
    )


def _schema_upgrade_for(event: Mapping[str, Any], state: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Return the appended upgrade required before a legacy project enters voice work."""
    if (
        state.get("schema_version") == LEGACY_PROJECT_SCHEMA_VERSION
        and event.get("event") == "project.phase_changed"
        and event.get("phase") == "voice_ready"
    ):
        return {
            "event": "project.schema_upgraded",
            "schema_version": V2_PROJECT_SCHEMA_VERSION,
        }
    return None


def _validate_v3_phase_gate(root: Path, phase: str) -> None:
    """Enforce the only state transition that can authorize full production.

    Intermediate v3 phase events describe workflow progress and are therefore
    replayable from metadata alone.  The production transition is different:
    it is an authorization boundary and must prove the current real timing
    chain plus a passed compact timing validation record.  No media payload is
    read here; only Artifact JSON and the validator's compact result are used.
    """
    if phase != "production_ready":
        return
    records = _runtime_artifacts(root)
    invalidated = invalidated_artifact_ids(root)
    records = [
        {**record, "status": "stale"}
        if record.get("artifact_id") in invalidated
        else record
        for record in records
    ]
    voice_bundle = validate_project_authoritative_voice_bundle(root, records)
    if not voice_bundle.get("ok"):
        raise ValueError("production_ready requires current real voice timing")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("status") == "approved":
            by_type.setdefault(record.get("type", ""), []).append(record)

    def latest(artifact_type: str) -> Optional[dict[str, Any]]:
        candidates = by_type.get(artifact_type, [])
        return max(candidates, key=lambda item: (item.get("version", 0), item["artifact_id"]), default=None)

    voice_timing_id = voice_bundle.get("voice_timing_id")
    voice_timing_matches = [
        item
        for item in by_type.get("voice-timing", [])
        if item.get("artifact_id") == voice_timing_id
    ]
    voice_timing = voice_timing_matches[0] if len(voice_timing_matches) == 1 else None
    if voice_timing is None or voice_timing.get("timing_kind") != "real":
        raise ValueError("production_ready requires current real voice timing")
    timed = latest("timed-semantic-beats")
    if (
        timed is None
        or timed.get("voice_timing_id") != voice_timing.get("artifact_id")
        or voice_timing.get("artifact_id") not in timed.get("parents", [])
    ):
        raise ValueError("production_ready requires current timed semantic beats")
    scenes = latest("scene-timing-contracts")
    if (
        scenes is None
        or scenes.get("timed_semantic_beats_id") != timed.get("artifact_id")
        or timed.get("artifact_id") not in scenes.get("parents", [])
    ):
        raise ValueError("production_ready requires current scene timing contracts")

    validation = latest("timing-validation")
    if validation is None or scenes.get("artifact_id") not in validation.get("parents", []):
        raise ValueError("production_ready requires passed timing validation")
    compact = validation.get("timing_validation")
    if not isinstance(compact, Mapping) or compact.get("status") != "passed":
        raise ValueError("production_ready requires passed timing validation")


def _runtime_artifacts(root: Path) -> list[dict[str, Any]]:
    """Read only strictly valid persisted Artifact records for a state gate."""
    artifacts_root = project_path(root, "artifacts")
    if not artifacts_root.is_dir() or artifacts_root.is_symlink():
        return []
    records: list[dict[str, Any]] = []
    for type_directory in sorted(artifacts_root.iterdir()):
        if type_directory.name == ".locks":
            continue
        if not type_directory.is_dir() or type_directory.is_symlink():
            continue
        for path in sorted(type_directory.glob("*.json")):
            if path.is_symlink():
                raise ValueError(f"invalid artifact metadata: {path}")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid artifact metadata: {path}") from error
            if not isinstance(value, dict):
                raise ValueError(f"invalid artifact metadata: {path}")
            try:
                validate_artifact_record(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid artifact metadata: {path}") from error
            if path.name != f"{value.get('artifact_id')}.json":
                raise ValueError(f"invalid artifact metadata: {path}")
            records.append(value)
    return records


@contextmanager
def _state_lock(root: Path, *, exclusive: bool) -> Iterator[None]:
    lock_path = project_path(root, "events/.state.lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _create_event_log(path: Path, event: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, _event_payload(event))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _append_event_durably(path: Path, event: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    try:
        _write_all(descriptor, _event_payload(event))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _event_payload(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("event write made no progress")
        remaining = remaining[written:]


def _write_project_atomically(root: Path, state: dict[str, Any]) -> None:
    destination = project_path(root, "project.json")
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, delete=False
        ) as stream:
            json.dump(state, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary_path = Path(stream.name)
        temporary_path.replace(destination)
        _fsync_directory(root)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in {errno.EBADF, errno.EINVAL}:
                raise
    finally:
        os.close(descriptor)


def _safe_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
    )


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and all(
        ord(character) >= 32 and ord(character) != 127 for character in value
    )

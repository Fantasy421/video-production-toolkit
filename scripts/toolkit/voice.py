"""Pure validation for immutable narration voice artifacts."""

from collections.abc import Iterable, Mapping
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from .artifacts import _artifact_paths_by_id, _read_valid_artifact
from .invalidation import invalidated_artifact_ids
from .runtime_paths import project_path, project_root


VOICE_SOURCE = "voice-source-decision"
VOICE_PROFILE = "voice-profile"
VOICEOVER = "voiceover"
VOICE_TIMING = "voice-timing"
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_:-]*(?:\.[A-Za-z0-9][A-Za-z0-9_:-]*)*$"
PROJECT_PATH_PATTERN = r"^(?!/)(?![A-Za-z]:)(?!\.{1,2}(?:/|$))(?!.*\/\.{1,2}(?:/|$))[^\\]+$"
SAFE_ID_RE = re.compile(SAFE_ID_PATTERN)
PROJECT_PATH_RE = re.compile(PROJECT_PATH_PATTERN)
_VOICE_TYPES = frozenset({VOICE_SOURCE, VOICE_PROFILE, VOICEOVER, VOICE_TIMING})
ACCEPTED_VOICE_MEDIA_FORMATS = frozenset({"wav", "mp3", "m4a", "aac", "flac"})
_ARTIFACT_REQUIRED_FIELDS = (
    "artifact_id",
    "type",
    "version",
    "status",
    "parents",
    "path",
)
_ARTIFACT_STATUSES = frozenset({"draft", "approved", "stale", "superseded", "invalid"})
_VOICE_REQUIRED_FIELDS = {
    VOICE_SOURCE: frozenset(
        {"narration_id", "mode", "decision", "decision_provenance"}
    ),
    VOICE_PROFILE: frozenset(
        {
            "narration_id",
            "source_decision_id",
            "mode",
            "language",
            "provider",
            "voice_id",
            "speaking_rate",
            "emotion",
            "pronunciations",
            "approved",
            "consent_provenance",
            "profile_provenance",
        }
    ),
    VOICEOVER: frozenset(
        {
            "narration_id",
            "source_decision_id",
            "mode",
            "media_path",
            "media_format",
            "duration_ms",
            "provenance",
        }
    ),
    VOICE_TIMING: frozenset(
        {"voiceover_id", "timing_kind", "duration_ms", "segments"}
    ),
}
_VOICE_ALLOWED_FIELDS = {
    artifact_type: frozenset(_ARTIFACT_REQUIRED_FIELDS)
    | required_fields
    | (
        {"output_contract", "profile_id", "uploaded_audio_id"}
        if artifact_type == VOICEOVER
        else {"output_contract"}
    )
    for artifact_type, required_fields in _VOICE_REQUIRED_FIELDS.items()
}


def validate_voice_bundle(
    artifacts: Iterable[Mapping[str, Any]], narration_id: str
) -> dict[str, Any]:
    """Return compact lineage findings for one approved narration revision.

    Artifact metadata is treated as untrusted project content: a malformed or
    stale record becomes a stable issue, never an exception.  Only API misuse
    (a non-iterable/non-mapping bundle or invalid narration selector) raises.
    """
    raw_records = _artifact_records(artifacts)
    _require_narration_id(narration_id)
    issues: list[dict[str, Any]] = []
    records = _valid_voice_records(raw_records, issues)

    source = _current_source(records, narration_id, issues)
    voiceover = _current_voiceover(records, narration_id, issues)
    profile = _current_profile(records, source, narration_id, issues)
    timing = _timing_for_voiceover(records, voiceover, issues)

    _validate_source(source, narration_id, issues)
    _validate_profile(profile, source, narration_id, issues)
    _validate_voiceover(
        voiceover,
        narration_id,
        source,
        profile,
        raw_records,
        issues,
    )
    _validate_timing(timing, voiceover, issues)

    sorted_issues = _sorted_unique_issues(issues)
    if sorted_issues:
        return {
            "ok": False,
            "voiceover_id": None,
            "voice_timing_id": None,
            "issues": sorted_issues,
        }
    return {
        "ok": True,
        "voiceover_id": voiceover["artifact_id"],
        "voice_timing_id": timing["artifact_id"],
        "issues": [],
    }


def validate_authoritative_voice_bundle(
    artifacts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate voice only for the one current approved narration DAG head."""
    records = _artifact_records(artifacts)
    narration = _authoritative_narration(records)
    if narration is None:
        approved = [
            item
            for item in records
            if item.get("type") == "narration" and item.get("status") == "approved"
        ]
        return {
            "ok": False,
            "narration_id": None,
            "voiceover_id": None,
            "voice_timing_id": None,
            "issues": [
                {
                    "code": (
                        "authoritative-narration-ambiguous"
                        if approved
                        else "authoritative-narration-missing"
                    )
                }
            ],
        }
    narration_id = narration["artifact_id"]
    result = validate_voice_bundle(records, narration_id)
    return {**result, "narration_id": narration_id}


def validate_project_voice_bundle(
    root: Path,
    artifacts: Iterable[Mapping[str, Any]],
    narration_id: str,
) -> dict[str, Any]:
    """Validate immutable lineage against the real project-contained audio.

    This is the canonical readiness verifier used by transitions, routing,
    task completion, structural QA, and installation smoke.  Metadata-only
    validation remains available for diagnostics, but it cannot authorize a
    production gate.
    """
    root = project_root(root)
    records = _artifact_records(artifacts)
    result = validate_voice_bundle(records, narration_id)
    if not result["ok"]:
        return result
    voiceover = _record_with_id(records, result["voiceover_id"])
    timing = _record_with_id(records, result["voice_timing_id"])
    issues: list[dict[str, Any]] = []
    if voiceover is None or timing is None:
        _add_issue(issues, "voice-bundle-artifact-missing")
        return _failed_bundle(result, issues)
    media_path = voiceover.get("media_path")
    try:
        media = project_path(root, media_path)
    except (TypeError, ValueError):
        _add_issue(issues, "unsafe-voiceover-media-path", voiceover)
        return _failed_bundle(result, issues)
    if media.is_symlink():
        _add_issue(issues, "voiceover-media-symlink", voiceover)
        return _failed_bundle(result, issues)
    if not media.is_file():
        _add_issue(issues, "voiceover-media-missing", voiceover)
        return _failed_bundle(result, issues)
    try:
        with media.open("rb") as stream:
            stream.read(1)
    except OSError:
        _add_issue(issues, "voiceover-media-unreadable", voiceover)
        return _failed_bundle(result, issues)
    actual_duration = probe_audio_duration_ms(media, voiceover.get("media_format"))
    if actual_duration is None:
        _add_issue(issues, "voiceover-media-duration-unverifiable", voiceover)
        return _failed_bundle(result, issues)
    if actual_duration != voiceover.get("duration_ms"):
        _add_issue(issues, "voiceover-duration-mismatch", voiceover)
    if actual_duration != timing.get("duration_ms") or any(
        isinstance(segment, Mapping)
        and isinstance(segment.get("end_ms"), int)
        and not isinstance(segment.get("end_ms"), bool)
        and segment["end_ms"] > actual_duration
        for segment in timing.get("segments", [])
        if isinstance(timing.get("segments"), list)
    ):
        _add_issue(issues, "voice-timing-out-of-bounds", timing)
    if issues:
        return _failed_bundle(result, issues)
    return {**result, "audio_duration_ms": actual_duration}


def validate_project_authoritative_voice_bundle(
    root: Path,
    artifacts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Validate the one authoritative narration and its real audio file."""
    root = project_root(root)
    records = (
        _load_effective_project_artifacts(root)
        if artifacts is None
        else _artifact_records(artifacts)
    )
    authoritative = validate_authoritative_voice_bundle(records)
    narration_id = authoritative.get("narration_id")
    if not authoritative["ok"] or not isinstance(narration_id, str):
        return authoritative
    result = validate_project_voice_bundle(root, records, narration_id)
    return {**result, "narration_id": narration_id}


def probe_audio_duration_ms(path: Path, media_format: Any) -> Optional[int]:
    """Return header/probe-derived duration for one accepted voice format.

    PCM WAV is always supported through the Python standard library.  MP3,
    M4A, AAC, and FLAC are accepted only when a local ``ffprobe`` executable is
    available; absence, malformed output, or timeout fails closed.
    """
    source = Path(path)
    if (
        not isinstance(media_format, str)
        or media_format not in ACCEPTED_VOICE_MEDIA_FORMATS
        or source.suffix.lower() != f".{media_format}"
    ):
        return None
    if media_format == "wav":
        try:
            with wave.open(str(source), "rb") as audio:
                frame_rate = audio.getframerate()
                frame_count = audio.getnframes()
            if frame_rate <= 0 or frame_count < 0:
                return None
            return round(frame_count * 1_000 / frame_rate)
        except (EOFError, OSError, wave.Error):
            return None
    executable = shutil.which("ffprobe")
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=duration",
                "-of",
                "json",
                str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    candidates: list[Any] = []
    if isinstance(payload, Mapping):
        format_record = payload.get("format")
        if isinstance(format_record, Mapping):
            candidates.append(format_record.get("duration"))
        streams = payload.get("streams")
        if isinstance(streams, list):
            candidates.extend(
                stream.get("duration")
                for stream in streams
                if isinstance(stream, Mapping)
            )
    for candidate in candidates:
        try:
            seconds = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and seconds > 0:
            return round(seconds * 1_000)
    return None


def has_current_voice_lineage(
    artifacts: Iterable[Mapping[str, Any]], narration_id: Optional[str] = None
) -> bool:
    """Report whether a bundle contains a complete current approved lineage."""
    records = _artifact_records(artifacts)
    if narration_id is not None:
        _require_narration_id(narration_id)
        return validate_voice_bundle(records, narration_id)["ok"]
    narration_ids = sorted(
        {
            item["narration_id"]
            for item in records
            if item.get("type") == VOICE_SOURCE
            and _safe_id(item.get("narration_id"))
        }
    )
    return any(validate_voice_bundle(records, candidate)["ok"] for candidate in narration_ids)


def _authoritative_narration(
    records: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in records:
        artifact_id = item.get("artifact_id")
        if not _safe_id(artifact_id) or not _safe_id_list(item.get("parents")):
            continue
        if artifact_id in by_id:
            return None
        by_id[artifact_id] = item
    narrations = [item for item in by_id.values() if _valid_narration_record(item)]
    current = [
        item
        for item in narrations
        if item["status"] == "approved"
        and not any(
            candidate["status"] == "approved"
            and candidate["version"] > item["version"]
            and _is_descendant(candidate, item["artifact_id"], by_id)
            for candidate in narrations
        )
    ]
    return current[0] if len(current) == 1 else None


def _valid_narration_record(record: Mapping[str, Any]) -> bool:
    return (
        record.get("type") == "narration"
        and _safe_id(record.get("artifact_id"))
        and isinstance(record.get("version"), int)
        and not isinstance(record.get("version"), bool)
        and record["version"] > 0
        and record.get("status")
        in {"draft", "approved", "stale", "superseded", "invalid"}
        and _safe_id_list(record.get("parents"))
    )


def _is_descendant(
    candidate: Mapping[str, Any],
    ancestor_id: str,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> bool:
    pending = list(candidate.get("parents", []))
    seen: set[str] = set()
    while pending:
        artifact_id = pending.pop()
        if artifact_id == ancestor_id:
            return True
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        parent = artifacts.get(artifact_id)
        if parent is not None:
            pending.extend(parent.get("parents", []))
    return False


def _artifact_records(artifacts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(artifacts, (Mapping, str, bytes)):
        raise ValueError("artifacts must be an iterable of mappings")
    try:
        raw_records = list(artifacts)
    except TypeError as error:
        raise ValueError("artifacts must be an iterable of mappings") from error
    if not all(isinstance(item, Mapping) for item in raw_records):
        raise ValueError("artifacts must contain mappings")
    return [dict(item) for item in raw_records]


def _require_narration_id(narration_id: Any) -> None:
    if not _safe_id(narration_id):
        raise ValueError("narration_id must be a safe non-empty component")


def _valid_voice_records(
    records: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for record in records:
        artifact_type = record.get("type")
        if not isinstance(artifact_type, str) or artifact_type not in _VOICE_TYPES:
            continue
        if not _valid_voice_record(record):
            _add_issue(issues, "malformed-voice-artifact", record)
            continue
        valid.append(record)
    return valid


def _valid_voice_record(record: Mapping[str, Any]) -> bool:
    artifact_type = record.get("type")
    if not isinstance(artifact_type, str) or artifact_type not in _VOICE_TYPES:
        return False
    if not all(field in record for field in _ARTIFACT_REQUIRED_FIELDS):
        return False
    if not _VOICE_REQUIRED_FIELDS[artifact_type].issubset(record):
        return False
    if not set(record).issubset(_VOICE_ALLOWED_FIELDS[artifact_type]):
        return False
    if "output_contract" in record and not _nonempty_text(record["output_contract"]):
        return False
    if not _safe_id(record["artifact_id"]) or not _safe_id(record["type"]):
        return False
    if (
        isinstance(record["version"], bool)
        or not isinstance(record["version"], int)
        or record["version"] < 1
        or not isinstance(record["status"], str)
        or record["status"] not in _ARTIFACT_STATUSES
        or not _safe_project_relative_path(record["path"])
        or not _safe_id_list(record["parents"])
    ):
        return False
    if artifact_type == VOICE_SOURCE:
        return _safe_id(record["narration_id"])
    if artifact_type == VOICE_PROFILE:
        return (
            _safe_id(record["narration_id"])
            and _safe_id(record["source_decision_id"])
        )
    if artifact_type == VOICEOVER:
        if not (
            _safe_id(record["narration_id"])
            and _safe_id(record["source_decision_id"])
            and record.get("mode") in {"uploaded-voice", "tts"}
        ):
            return False
        if record["mode"] == "tts":
            return _safe_id(record.get("profile_id")) and "uploaded_audio_id" not in record
        return _safe_id(record.get("uploaded_audio_id")) and "profile_id" not in record
    if artifact_type == VOICE_TIMING:
        return _safe_id(record["voiceover_id"])
    return True


def _safe_id_list(value: Any) -> bool:
    if not isinstance(value, list) or not all(_safe_id(item) for item in value):
        return False
    return len(value) == len(set(value))


def _current_source(
    records: list[dict[str, Any]], narration_id: str, issues: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    sources = [
        item
        for item in records
        if item.get("type") == VOICE_SOURCE and item.get("narration_id") == narration_id
    ]
    current = _latest_approved(sources)
    if current is None:
        _add_issue(
            issues,
            "voice-source-decision-unapproved" if sources else "voice-source-decision-missing",
        )
    return current


def _current_voiceover(
    records: list[dict[str, Any]], narration_id: str, issues: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    voiceovers = [
        item
        for item in records
        if item.get("type") == VOICEOVER and item.get("narration_id") == narration_id
    ]
    current = _latest_approved(voiceovers)
    if current is None:
        _add_issue(
            issues, "voiceover-unapproved" if voiceovers else "voiceover-missing"
        )
    return current


def _current_profile(
    records: list[dict[str, Any]],
    source: Optional[dict[str, Any]],
    narration_id: str,
    issues: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if source is None or source.get("mode") != "tts":
        return None
    profiles = [
        item
        for item in records
        if item.get("type") == VOICE_PROFILE
        and item.get("narration_id") == narration_id
        and item.get("source_decision_id") == source.get("artifact_id")
    ]
    current = _latest_approved(profiles)
    if current is None:
        _add_issue(
            issues, "voice-profile-unapproved" if profiles else "voice-profile-missing"
        )
    return current


def _timing_for_voiceover(
    records: list[dict[str, Any]],
    voiceover: Optional[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if voiceover is None:
        _add_issue(issues, "voice-timing-missing")
        return None
    voiceover_id = voiceover.get("artifact_id")
    timings = [
        item
        for item in records
        if item.get("type") == VOICE_TIMING and item.get("voiceover_id") == voiceover_id
    ]
    current = _latest_approved(timings)
    if current is None:
        _add_issue(
            issues, "voice-timing-unapproved" if timings else "voice-timing-missing"
        )
    return current


def _latest_approved(records: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    approved = [item for item in records if item.get("status") == "approved"]
    if not approved:
        return None
    return max(approved, key=lambda item: (_version(item), str(item.get("artifact_id", ""))))


def _version(artifact: Mapping[str, Any]) -> int:
    value = artifact.get("version")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _validate_source(
    source: Optional[dict[str, Any]],
    narration_id: str,
    issues: list[dict[str, Any]],
) -> None:
    if source is not None:
        if source.get("narration_id") != narration_id:
            _add_issue(issues, "voice-source-decision-lineage-mismatch", source)
        if not _valid_mode(source.get("mode")):
            _add_issue(issues, "voice-source-decision-invalid-mode", source)
        if source.get("decision") != "approved":
            _add_issue(issues, "voice-source-decision-unapproved", source)
        if source.get("parents") != [narration_id]:
            _add_issue(issues, "voice-source-decision-lineage-mismatch", source)
        if not _nonempty_text(source.get("decision_provenance")):
            _add_issue(issues, "voice-source-decision-provenance-missing", source)


def _validate_profile(
    profile: Optional[dict[str, Any]],
    source: Optional[dict[str, Any]],
    narration_id: str,
    issues: list[dict[str, Any]],
) -> None:
    if profile is None:
        return
    if profile.get("mode") != "tts":
        _add_issue(issues, "voice-profile-invalid-mode", profile)
    if profile.get("approved") is not True:
        _add_issue(issues, "voice-profile-unapproved", profile)
    source_id = source.get("artifact_id") if source is not None else None
    if (
        profile.get("narration_id") != narration_id
        or profile.get("source_decision_id") != source_id
        or set(profile.get("parents", [])) != {narration_id, source_id}
        or len(profile.get("parents", [])) != 2
    ):
        _add_issue(issues, "voice-profile-lineage-mismatch", profile)
    for field in (
        "language",
        "provider",
        "emotion",
        "consent_provenance",
        "profile_provenance",
    ):
        if not _nonempty_text(profile.get(field)):
            _add_issue(issues, "invalid-voice-profile", profile)
            break
    if not _safe_id(profile.get("voice_id")):
        _add_issue(issues, "invalid-voice-profile", profile)
    rate = profile.get("speaking_rate")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0:
        _add_issue(issues, "invalid-voice-profile", profile)
    pronunciations = profile.get("pronunciations")
    if not isinstance(pronunciations, list) or not all(
        _nonempty_text(item) for item in pronunciations
    ) or len(pronunciations) != len(set(pronunciations)):
        _add_issue(issues, "invalid-voice-profile", profile)


def _validate_voiceover(
    voiceover: Optional[dict[str, Any]],
    narration_id: str,
    source: Optional[dict[str, Any]],
    profile: Optional[dict[str, Any]],
    all_records: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    if voiceover is None:
        return
    if voiceover.get("narration_id") != narration_id:
        _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
    source_id = source.get("artifact_id") if source is not None else None
    mode = source.get("mode") if source is not None else None
    if (
        voiceover.get("source_decision_id") != source_id
        or voiceover.get("mode") != mode
    ):
        _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
    profile_id = profile.get("artifact_id") if profile is not None else None
    expected_parents: set[Any]
    if mode == "tts":
        if voiceover.get("profile_id") != profile_id or "uploaded_audio_id" in voiceover:
            _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
        expected_parents = {narration_id, source_id, profile_id}
    elif mode == "uploaded-voice":
        upload_id = voiceover.get("uploaded_audio_id")
        upload = _record_with_id(all_records, upload_id)
        if "profile_id" in voiceover or not _valid_uploaded_audio(
            upload, narration_id, source_id
        ):
            _add_issue(issues, "voiceover-upload-lineage-mismatch", voiceover)
        expected_parents = {narration_id, source_id, upload_id}
    else:
        expected_parents = {narration_id, source_id}
    parents = voiceover.get("parents")
    if (
        not isinstance(parents, list)
        or len(parents) != len(set(parents))
        or set(parents) != expected_parents
    ):
        _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
    if not _safe_project_relative_path(voiceover.get("media_path")):
        _add_issue(issues, "unsafe-voiceover-media-path", voiceover)
    media_format = voiceover.get("media_format")
    suffix = (
        PurePosixPath(voiceover["media_path"]).suffix.lower()
        if isinstance(voiceover.get("media_path"), str)
        else ""
    )
    if (
        media_format not in ACCEPTED_VOICE_MEDIA_FORMATS
        or suffix != f".{media_format}"
    ):
        _add_issue(issues, "voiceover-media-format-mismatch", voiceover)
    if not _positive_milliseconds(voiceover.get("duration_ms")):
        _add_issue(issues, "invalid-voiceover-duration", voiceover)
    if not _nonempty_text(voiceover.get("provenance")):
        _add_issue(issues, "invalid-voiceover-provenance", voiceover)


def _validate_timing(
    timing: Optional[dict[str, Any]],
    voiceover: Optional[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    if timing is None:
        return
    if timing.get("timing_kind") != "real":
        _add_issue(issues, "real-voice-timing-required", timing)
    voiceover_id = voiceover.get("artifact_id") if voiceover is not None else None
    if (
        timing.get("voiceover_id") != voiceover_id
        or timing.get("parents") != [voiceover_id]
    ):
        _add_issue(issues, "voice-timing-lineage-mismatch", timing)
    duration = timing.get("duration_ms")
    if not _positive_milliseconds(duration):
        _add_issue(issues, "invalid-voice-timing-duration", timing)
        return
    if voiceover is not None and duration != voiceover.get("duration_ms"):
        _add_issue(issues, "voice-timing-duration-mismatch", timing)
    _validate_segments(timing.get("segments"), duration, timing, issues)


def _validate_segments(
    segments: Any,
    duration_ms: int,
    timing: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    if not isinstance(segments, list) or not segments:
        _add_issue(issues, "voice-timing-text-coverage", timing)
        return
    previous_start: Optional[int] = None
    previous_end: Optional[int] = None
    for segment in segments:
        if not isinstance(segment, Mapping):
            _add_issue(issues, "invalid-voice-timing-segment", timing)
            continue
        if set(segment) != {"start_ms", "end_ms", "text"}:
            _add_issue(issues, "invalid-voice-timing-segment", timing)
            continue
        start, end, text = segment.get("start_ms"), segment.get("end_ms"), segment.get("text")
        if not _nonnegative_milliseconds(start) or not _positive_milliseconds(end) or end <= start:
            _add_issue(issues, "invalid-voice-timing-segment", timing)
            continue
        if end > duration_ms:
            _add_issue(issues, "voice-timing-out-of-bounds", timing)
        if not _nonempty_text(text):
            _add_issue(issues, "voice-timing-text-coverage", timing)
        if previous_start is not None and start < previous_start:
            _add_issue(issues, "voice-timing-unordered", timing)
        if previous_end is not None and start < previous_end:
            _add_issue(issues, "voice-timing-overlap", timing)
        previous_start = start
        previous_end = end


def _valid_uploaded_audio(
    record: Optional[Mapping[str, Any]],
    narration_id: str,
    source_id: Any,
) -> bool:
    if record is None:
        return False
    return (
        record.get("type") in {"audio", "audio-asset", "uploaded-audio"}
        and record.get("status") == "approved"
        and _safe_id(record.get("artifact_id"))
        and _safe_project_relative_path(record.get("media_path"))
        and _safe_id_list(record.get("parents"))
        and len(record["parents"]) == 2
        and set(record["parents"]) == {narration_id, source_id}
    )


def _record_with_id(
    records: Iterable[Mapping[str, Any]], artifact_id: Any
) -> Optional[dict[str, Any]]:
    if not _safe_id(artifact_id):
        return None
    matches = [dict(record) for record in records if record.get("artifact_id") == artifact_id]
    return matches[0] if len(matches) == 1 else None


def _failed_bundle(
    valid_result: Mapping[str, Any], issues: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        **dict(valid_result),
        "ok": False,
        "voiceover_id": None,
        "voice_timing_id": None,
        "issues": _sorted_unique_issues(issues),
    }


def _load_effective_project_artifacts(root: Path) -> list[dict[str, Any]]:
    paths = _artifact_paths_by_id(root / "artifacts")
    invalidated = invalidated_artifact_ids(root)
    records: list[dict[str, Any]] = []
    for artifact_id, path in sorted(paths.items()):
        record = _read_valid_artifact(path)
        if record is None or record.get("artifact_id") != artifact_id:
            raise ValueError(f"invalid artifact metadata: {path}")
        if artifact_id in invalidated:
            record = {**record, "status": "stale"}
        records.append(record)
    return records


def _safe_project_relative_path(value: Any) -> bool:
    return _nonempty_text(value) and PROJECT_PATH_RE.fullmatch(value) is not None


def _safe_id(value: Any) -> bool:
    return _nonempty_text(value) and SAFE_ID_RE.fullmatch(value) is not None


def _valid_mode(value: Any) -> bool:
    return isinstance(value, str) and value in {"uploaded-voice", "tts"}


def _positive_milliseconds(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_milliseconds(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _nonempty_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def _add_issue(issues: list[dict[str, Any]], code: str, artifact: Optional[Mapping[str, Any]] = None) -> None:
    issue: dict[str, Any] = {"code": code}
    artifact_id = artifact.get("artifact_id") if artifact is not None else None
    if _safe_id(artifact_id):
        issue["artifact_id"] = artifact_id
    issues.append(issue)


def _sorted_unique_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (issue["code"], issue.get("artifact_id", "")): issue
        for issue in issues
    }
    return [by_key[key] for key in sorted(by_key)]

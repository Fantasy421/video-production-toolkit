"""Pure validation for immutable narration voice artifacts."""

from collections.abc import Iterable, Mapping
import re
from typing import Any, Optional


VOICE_SOURCE = "voice-source-decision"
VOICE_PROFILE = "voice-profile"
VOICEOVER = "voiceover"
VOICE_TIMING = "voice-timing"
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_:-]*(?:\.[A-Za-z0-9][A-Za-z0-9_:-]*)*$"
PROJECT_PATH_PATTERN = r"^(?!/)(?![A-Za-z]:)(?!\.{1,2}(?:/|$))(?!.*\/\.{1,2}(?:/|$))[^\\]+$"
SAFE_ID_RE = re.compile(SAFE_ID_PATTERN)
PROJECT_PATH_RE = re.compile(PROJECT_PATH_PATTERN)
_VOICE_TYPES = frozenset({VOICE_SOURCE, VOICE_PROFILE, VOICEOVER, VOICE_TIMING})
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
    VOICE_SOURCE: frozenset({"narration_id", "mode", "decision"}),
    VOICE_PROFILE: frozenset(
        {
            "mode",
            "language",
            "provider",
            "voice_id",
            "speaking_rate",
            "emotion",
            "pronunciations",
            "approved",
        }
    ),
    VOICEOVER: frozenset(
        {
            "narration_id",
            "profile_id",
            "media_path",
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
    | {"output_contract"}
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
    profile = _profile_for_voiceover(records, voiceover, issues)
    timing = _timing_for_voiceover(records, voiceover, issues)

    _validate_source_and_profile(source, profile, narration_id, issues)
    _validate_voiceover(voiceover, narration_id, profile, issues)
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
    if artifact_type == VOICEOVER:
        return _safe_id(record["narration_id"]) and _safe_id(record["profile_id"])
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


def _profile_for_voiceover(
    records: list[dict[str, Any]],
    voiceover: Optional[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if voiceover is None:
        _add_issue(issues, "voice-profile-missing")
        return None
    profile_id = voiceover.get("profile_id")
    profiles = [
        item
        for item in records
        if item.get("type") == VOICE_PROFILE and item.get("artifact_id") == profile_id
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


def _validate_source_and_profile(
    source: Optional[dict[str, Any]],
    profile: Optional[dict[str, Any]],
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
    if profile is not None:
        if not _valid_mode(profile.get("mode")):
            _add_issue(issues, "voice-profile-invalid-mode", profile)
        if profile.get("approved") is not True:
            _add_issue(issues, "voice-profile-unapproved", profile)
        for field in ("language", "provider", "emotion"):
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
        if source is not None and profile.get("mode") != source.get("mode"):
            _add_issue(issues, "voice-profile-lineage-mismatch", profile)


def _validate_voiceover(
    voiceover: Optional[dict[str, Any]],
    narration_id: str,
    profile: Optional[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    if voiceover is None:
        return
    if voiceover.get("narration_id") != narration_id:
        _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
    profile_id = profile.get("artifact_id") if profile is not None else None
    if voiceover.get("profile_id") != profile_id:
        _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
    expected_parents = {narration_id, profile_id}
    parents = voiceover.get("parents")
    if (
        not isinstance(parents, list)
        or len(parents) != len(set(parents))
        or set(parents) != expected_parents
    ):
        _add_issue(issues, "voiceover-lineage-mismatch", voiceover)
    if not _safe_project_relative_path(voiceover.get("media_path")):
        _add_issue(issues, "unsafe-voiceover-media-path", voiceover)
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

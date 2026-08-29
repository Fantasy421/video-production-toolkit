"""Durable immutable artifacts and user approvals for toolkit projects."""

import json
import math
import os
import tempfile
import time
import fcntl
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any, Optional
from uuid import uuid4

from .runtime_paths import project_path, project_root, storage_directory
from .visual_media_context import (
    CHECKSUM_RE,
    MEDIA_KINDS,
    MIME_TYPE_RE,
    SAFE_ID_RE,
    VISUAL_RESULT_BUDGET_BYTES,
    validate_coordinator_safe_json,
)


ARTIFACT_REQUIRED_KEYS = (
    "artifact_id",
    "type",
    "version",
    "status",
    "parents",
    "path",
)
ARTIFACT_STATUSES = {"draft", "approved", "stale", "superseded", "invalid"}
APPROVAL_DECISIONS = {"approved", "delegated", "skipped"}
APPROVAL_REQUIRED_KEYS = (
    "approval_id",
    "target_id",
    "scope",
    "decision",
    "notes",
)
LEGACY_APPROVAL_KEYS = set(APPROVAL_REQUIRED_KEYS) - {"decision"}
COORDINATOR_SAFE_ARTIFACT_FIELDS = (
    "artifact_id",
    "type",
    "version",
    "status",
    "parents",
    "path",
    "output_contract",
    "media_kind",
    "mime_type",
    "format",
    "width",
    "height",
    "duration_ms",
    "fps",
    "file_size",
    "size_bytes",
    "checksum",
    "readiness",
    "historical",
)
ARTIFACT_BUSINESS_METADATA_FIELDS = frozenset(
    {
        "approval_id",
        "approved",
        "beats",
        "character_ids",
        "character_pack_id",
        "consent_provenance",
        "decision",
        "decision_provenance",
        "emotion",
        "identity_provenance",
        "language",
        "license",
        "media_format",
        "media_path",
        "mode",
        "narration_id",
        "notes",
        "profile_id",
        "profile_provenance",
        "promotion",
        "pronunciations",
        "provenance",
        "provider",
        "scene_id",
        "scenes",
        "scope",
        "segments",
        "source_decision_id",
        "speaking_rate",
        "semantic_beats_id",
        "target_id",
        "text",
        "timing_kind",
        "timed_semantic_beats_id",
        "uploaded_audio_id",
        "voice_id",
        "voice_timing_id",
        "voiceover_id",
    }
)
ARTIFACT_ALLOWED_FIELDS = frozenset(COORDINATOR_SAFE_ARTIFACT_FIELDS) | ARTIFACT_BUSINESS_METADATA_FIELDS
ARTIFACT_ID_METADATA_FIELDS = frozenset(
    {
        "approval_id",
        "character_pack_id",
        "narration_id",
        "profile_id",
        "scene_id",
        "semantic_beats_id",
        "source_decision_id",
        "target_id",
        "timed_semantic_beats_id",
        "uploaded_audio_id",
        "voice_id",
        "voice_timing_id",
        "voiceover_id",
    }
)
ARTIFACT_TEXT_METADATA_BOUNDS = {
    "consent_provenance": 500,
    "decision": 64,
    "decision_provenance": 500,
    "emotion": 128,
    "identity_provenance": 500,
    "language": 64,
    "media_format": 64,
    "mode": 64,
    "notes": 2_000,
    "profile_provenance": 500,
    "provenance": 500,
    "provider": 128,
    "scope": 128,
    "text": 8_192,
    "timing_kind": 64,
}
PROMOTION_FIELDS = frozenset(
    {
        "action",
        "alpha",
        "applicability",
        "asset_kind",
        "orientation",
        "ownership",
        "provenance",
        "scene",
        "scope",
        "source_or_license",
        "subject",
        "validation_evidence",
    }
)


def create_artifact(root: Path, artifact: dict[str, Any]) -> Path:
    """Persist one immutable artifact metadata record and return its path."""
    root = project_root(root)
    _validate_artifact(artifact)
    project_path(root, artifact["path"])
    payload = _serialize_json(artifact)
    artifacts_root = storage_directory(root, "artifacts", create=True)
    existing = _artifact_paths_by_id(artifacts_root)
    artifact_id = artifact["artifact_id"]
    if artifact_id in existing:
        raise FileExistsError(f"artifact already exists: {artifact_id}")

    missing_parents = [parent for parent in artifact["parents"] if parent not in existing]
    if missing_parents:
        raise ValueError(f"artifact parents do not exist: {', '.join(missing_parents)}")

    destination = artifacts_root / artifact["type"] / f"{artifact_id}.json"
    _require_within(artifacts_root, destination)
    lock = _acquire_artifact_lock(artifacts_root, artifact_id)
    try:
        if artifact_id in _artifact_paths_by_id(artifacts_root):
            raise FileExistsError(f"artifact already exists: {artifact_id}")
        _publish_json(destination, payload)
    finally:
        _release_artifact_lock(lock)
    return destination


def validate_artifact_record(artifact: Mapping[str, Any]) -> None:
    """Validate one full immutable Artifact record at every trust boundary."""
    if not isinstance(artifact, dict):
        artifact = dict(artifact) if isinstance(artifact, Mapping) else artifact
    _validate_artifact(artifact)


def coordinator_safe_artifact_projection(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only compact structural Artifact metadata for the coordinator."""
    validate_artifact_record(artifact)
    return {
        field: artifact[field]
        for field in COORDINATOR_SAFE_ARTIFACT_FIELDS
        if field in artifact
    }


def approve_artifact(
    root: Path,
    target_id: str,
    scope: str,
    notes: str,
    decision: str = "approved",
) -> str:
    """Create a durable approval record for an existing artifact."""
    root = project_root(root)
    artifacts_root = storage_directory(root, "artifacts")
    if target_id not in _artifact_paths_by_id(artifacts_root):
        raise ValueError(f"approval target does not exist: {target_id}")
    if not isinstance(scope, str) or not scope:
        raise ValueError("approval scope must be a non-empty string")
    if not isinstance(notes, str):
        raise ValueError("approval notes must be a string")
    if not isinstance(decision, str) or decision not in APPROVAL_DECISIONS:
        raise ValueError("approval decision is not recognized")

    approval_id = f"approval-{uuid4().hex}"
    approval = {
        "approval_id": approval_id,
        "target_id": target_id,
        "scope": scope,
        "decision": decision,
        "notes": notes,
    }
    _validate_approval(approval)
    payload = _serialize_json(approval)
    approvals_root = storage_directory(root, "approvals", create=True)
    approval_path = project_path(root, Path("approvals") / f"{approval_id}.json")
    _require_within(approvals_root, approval_path)
    _publish_json(approval_path, payload)
    return approval_id


def read_approval(root: Path, approval_id: str) -> dict[str, Any]:
    """Return a schema-shaped approval view without rewriting legacy history.

    Approval records created before decision values existed are immutable legacy
    artifacts. Their in-memory view therefore defaults to approved while the
    source JSON remains unchanged.
    """
    root = project_root(root)
    _require_safe_component(approval_id, "approval_id")
    approvals_root = storage_directory(root, "approvals")
    path = project_path(root, Path("approvals") / f"{approval_id}.json")
    _require_within(approvals_root, path)
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid approval record: {approval_id}") from error
    normalized = _normalize_approval(approval)
    if normalized["approval_id"] != approval_id:
        raise ValueError(f"approval record ID does not match path: {approval_id}")
    return normalized


def _artifact_paths_by_id(artifacts_root: Path) -> dict[str, Path]:
    if artifacts_root.is_symlink():
        raise ValueError("artifact storage must not be a symlink")
    if not artifacts_root.is_dir():
        return {}
    paths: dict[str, Path] = {}
    for type_directory in artifacts_root.iterdir():
        if type_directory.name == ".locks":
            if type_directory.is_symlink():
                raise ValueError("artifact lock storage must not be a symlink")
            continue
        if type_directory.is_symlink():
            raise ValueError("artifact type storage must not be a symlink")
        if not type_directory.is_dir():
            continue
        for path in type_directory.glob("*.json"):
            if path.is_symlink():
                raise ValueError("artifact metadata must not be a symlink")
            artifact = _read_valid_artifact(path)
            if artifact is None:
                continue
            artifact_id = artifact["artifact_id"]
            if artifact_id in paths:
                raise ValueError(f"duplicate artifact id in project: {artifact_id}")
            paths[artifact_id] = path
    return paths


def _read_valid_artifact(path: Path) -> Optional[dict[str, Any]]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        _validate_artifact(artifact)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if path.name != f"{artifact['artifact_id']}.json":
        return None
    return artifact


def _acquire_artifact_lock(artifacts_root: Path, artifact_id: str) -> tuple[Path, int]:
    lock = artifacts_root / ".locks" / f"{artifact_id}.json"
    owner_token = uuid4().hex
    payload = _serialize_json(
        {"pid": os.getpid(), "timestamp": time.time(), "owner_token": owner_token}
    )
    while True:
        try:
            _publish_json(lock, payload)
            return _hold_published_lock(lock)
        except FileExistsError:
            _remove_lock_if_owned(lock, owner_token)
            if artifact_id in _artifact_paths_by_id(artifacts_root):
                raise FileExistsError(f"artifact already exists: {artifact_id}") from None
            try:
                guard = _hold_lock(lock)
            except FileNotFoundError:
                continue
            except BlockingIOError:
                raise FileExistsError(f"artifact is locked: {artifact_id}") from None
            try:
                if not _is_current_lock(lock, guard[1]):
                    continue
                owner = _read_lock(lock)
                if owner is None or _pid_is_alive(owner["pid"]):
                    raise FileExistsError(f"artifact is locked: {artifact_id}")
                lock.unlink(missing_ok=True)
            finally:
                os.close(guard[1])
        except BaseException:
            _remove_lock_if_owned(lock, owner_token)
            raise


def _hold_published_lock(lock: Path) -> tuple[Path, int]:
    while True:
        try:
            return _hold_lock(lock)
        except BlockingIOError:
            time.sleep(0.001)


def _hold_lock(lock: Path) -> tuple[Path, int]:
    descriptor = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(descriptor)
        raise
    return lock, descriptor


def _release_artifact_lock(lock: tuple[Path, int]) -> None:
    path, descriptor = lock
    try:
        if _is_current_lock(path, descriptor):
            path.unlink(missing_ok=True)
    finally:
        os.close(descriptor)


def _remove_lock_if_owned(lock: Path, owner_token: str) -> None:
    try:
        descriptor = os.open(lock, os.O_RDONLY)
    except FileNotFoundError:
        return
    try:
        if _lock_owner_token(descriptor) != owner_token:
            return
        if _is_current_lock(lock, descriptor):
            lock.unlink(missing_ok=True)
    finally:
        os.close(descriptor)


def _lock_owner_token(descriptor: int) -> Optional[str]:
    try:
        owner = json.loads(os.read(descriptor, 65_537).decode("utf-8"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(owner, dict):
        return None
    owner_token = owner.get("owner_token")
    return owner_token if isinstance(owner_token, str) else None


def _is_current_lock(lock: Path, descriptor: int) -> bool:
    try:
        return os.stat(lock).st_ino == os.fstat(descriptor).st_ino
    except FileNotFoundError:
        return False


def _read_lock(lock: Path) -> Optional[dict[str, Any]]:
    try:
        owner = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(owner, dict):
        return None
    pid = owner.get("pid")
    timestamp = owner.get("timestamp")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return None
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    return owner


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _serialize_json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":")) + "\n"


def _publish_json(destination: Path, payload: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as stream:
            stream.write(payload)
            temporary_path = Path(stream.name)
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _require_within(root: Path, destination: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("artifact storage must not contain symlinks")
    try:
        destination.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("artifact destination must remain inside its storage directory") from None


def _validate_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")
    validate_coordinator_safe_json(artifact, budget=VISUAL_RESULT_BUDGET_BYTES)
    unknown = set(artifact) - ARTIFACT_ALLOWED_FIELDS
    if unknown:
        raise ValueError(
            "artifact has unknown metadata fields: " + ", ".join(sorted(unknown))
        )
    missing = [key for key in ARTIFACT_REQUIRED_KEYS if key not in artifact]
    if missing:
        raise ValueError(f"artifact is missing required keys: {', '.join(missing)}")
    for key in ("artifact_id", "type", "path"):
        value = artifact[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"artifact {key} must be a non-empty string")
    if not _bounded_safe_id(artifact["artifact_id"]) or not _bounded_safe_id(
        artifact["type"]
    ):
        raise ValueError("artifact_id and type must be bounded safe IDs")
    if not _project_contained_path(artifact["path"]):
        raise ValueError("artifact path must be one project-contained path")
    if isinstance(artifact["version"], bool) or not isinstance(artifact["version"], int) or artifact["version"] < 1:
        raise ValueError("artifact version must be a positive integer")
    if not isinstance(artifact["status"], str) or artifact["status"] not in ARTIFACT_STATUSES:
        raise ValueError("artifact status is not recognized")
    if not isinstance(artifact["parents"], list) or not all(
        isinstance(parent, str) and parent for parent in artifact["parents"]
    ):
        raise ValueError("artifact parents must be a list of non-empty IDs")
    if len(artifact["parents"]) > 256:
        raise ValueError("artifact parents must be a bounded list")
    if len(set(artifact["parents"])) != len(artifact["parents"]):
        raise ValueError("artifact parents must not contain duplicates")
    if any(not _bounded_safe_id(parent) for parent in artifact["parents"]):
        raise ValueError("artifact parents must contain bounded safe IDs")
    if "output_contract" in artifact:
        value = artifact["output_contract"]
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError("artifact output_contract must be bounded text")
    if "media_kind" in artifact and artifact["media_kind"] not in MEDIA_KINDS:
        raise ValueError("artifact media_kind is not recognized")
    if "mime_type" in artifact:
        mime_type = artifact["mime_type"]
        if (
            not isinstance(mime_type, str)
            or len(mime_type) > 128
            or MIME_TYPE_RE.fullmatch(mime_type) is None
        ):
            raise ValueError("artifact mime_type must be canonical")
    if "historical" in artifact and not isinstance(artifact["historical"], bool):
        raise ValueError("artifact historical must be boolean")
    for key in ("format", "readiness"):
        if key in artifact:
            value = artifact[key]
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError(f"artifact {key} must be bounded text")
    if "checksum" in artifact and (
        not isinstance(artifact["checksum"], str)
        or CHECKSUM_RE.fullmatch(artifact["checksum"]) is None
    ):
        raise ValueError("artifact checksum must be a bounded hexadecimal digest")
    for key, minimum, maximum in (
        ("width", 1, 16_384),
        ("height", 1, 16_384),
        ("duration_ms", 0, 36_000_000),
        ("file_size", 0, 1_099_511_627_776),
        ("size_bytes", 0, 1_099_511_627_776),
    ):
        if key in artifact:
            value = artifact[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise ValueError(f"artifact {key} is outside its structural bound")
    if "fps" in artifact:
        fps = artifact["fps"]
        if (
            isinstance(fps, bool)
            or not isinstance(fps, (int, float))
            or not math.isfinite(fps)
            or not 0 < fps <= 240
        ):
            raise ValueError("artifact fps is outside its structural bound")
    _validate_artifact_business_metadata(artifact)


def _validate_artifact_business_metadata(artifact: Mapping[str, Any]) -> None:
    for field in ARTIFACT_ID_METADATA_FIELDS:
        if field in artifact and not _bounded_safe_id(artifact[field]):
            raise ValueError(f"artifact {field} must be a bounded safe ID")
    for field, max_length in ARTIFACT_TEXT_METADATA_BOUNDS.items():
        if field not in artifact:
            continue
        value = artifact[field]
        allow_empty = field == "notes"
        if (
            not isinstance(value, str)
            or (not allow_empty and not value.strip())
            or len(value) > max_length
        ):
            raise ValueError(f"artifact {field} must be bounded text")
    if "approved" in artifact and not isinstance(artifact["approved"], bool):
        raise ValueError("artifact approved must be boolean")
    if "speaking_rate" in artifact:
        rate = artifact["speaking_rate"]
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or not 0 < rate <= 4
        ):
            raise ValueError("artifact speaking_rate must be finite and bounded")
    if "media_path" in artifact and not _project_contained_path(
        artifact["media_path"]
    ):
        raise ValueError("artifact media_path must be project-contained")
    if "character_ids" in artifact:
        _validate_safe_id_list(artifact["character_ids"], "character_ids", 64)
    if "pronunciations" in artifact:
        _validate_text_list(artifact["pronunciations"], "pronunciations", 256, 500)
    if "segments" in artifact:
        _validate_segments(artifact["segments"])
    for field in ("beats", "scenes"):
        if field in artifact and (
            not isinstance(artifact[field], list)
            or len(artifact[field]) > 512
            or not all(isinstance(item, Mapping) for item in artifact[field])
        ):
            raise ValueError(f"artifact {field} must be a bounded object list")
    if "license" in artifact:
        _validate_license_metadata(artifact["license"])
    if "promotion" in artifact:
        _validate_promotion_metadata(artifact["promotion"])


def _validate_safe_id_list(value: Any, label: str, max_items: int) -> None:
    if (
        not isinstance(value, list)
        or len(value) > max_items
        or not all(_bounded_safe_id(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"artifact {label} must be a bounded unique safe-ID list")


def _validate_text_list(
    value: Any, label: str, max_items: int, max_length: int, *, allow_empty: bool = False
) -> None:
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"artifact {label} must be a bounded text list")
    for item in value:
        if (
            not isinstance(item, str)
            or (not allow_empty and not item.strip())
            or len(item) > max_length
        ):
            raise ValueError(f"artifact {label} must contain bounded text")
    if len(set(value)) != len(value):
        raise ValueError(f"artifact {label} must not contain duplicates")


def _validate_segments(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 512:
        raise ValueError("artifact segments must be a bounded list")
    for segment in value:
        if not isinstance(segment, Mapping) or set(segment) != {
            "start_ms",
            "end_ms",
            "text",
        }:
            raise ValueError("artifact segments must contain closed timing records")
        start = segment["start_ms"]
        end = segment["end_ms"]
        text = segment["text"]
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or not 0 <= start < end <= 36_000_000
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 1_000
        ):
            raise ValueError("artifact segment values are outside structural bounds")


def _validate_license_metadata(value: Any) -> None:
    if not isinstance(value, Mapping) or not set(value) <= {
        "owner",
        "territories",
        "expires",
    }:
        raise ValueError("artifact license metadata must be closed")
    owner = value.get("owner")
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 500:
        raise ValueError("artifact license owner must be bounded text")
    if "territories" in value:
        _validate_text_list(value["territories"], "license territories", 64, 128)
    expires = value.get("expires")
    if expires is not None and (
        not isinstance(expires, str) or not expires.strip() or len(expires) > 128
    ):
        raise ValueError("artifact license expiry must be null or bounded text")


def _validate_promotion_metadata(value: Any) -> None:
    if not isinstance(value, Mapping) or not set(value) <= PROMOTION_FIELDS:
        raise ValueError("artifact promotion metadata must be closed")
    for field in (
        "action",
        "alpha",
        "asset_kind",
        "orientation",
        "ownership",
        "scope",
        "source_or_license",
        "subject",
    ):
        if field in value:
            item = value[field]
            if not isinstance(item, str) or len(item) > 500:
                raise ValueError(f"artifact promotion {field} must be bounded text")
    if "scene" in value:
        scene = value["scene"]
        if not isinstance(scene, str) or len(scene) > 500:
            raise ValueError("artifact promotion scene must be bounded text")
    if "applicability" in value:
        _validate_text_list(
            value["applicability"],
            "promotion applicability",
            64,
            500,
            allow_empty=True,
        )
    if "validation_evidence" in value:
        evidence = value["validation_evidence"]
        if not isinstance(evidence, list) or len(evidence) > 64:
            raise ValueError("artifact promotion validation_evidence must be bounded")
        evidence_strings: set[str] = set()
        has_empty_object = False
        for item in evidence:
            if isinstance(item, str):
                if len(item) > 500:
                    raise ValueError(
                        "artifact promotion validation_evidence must be bounded"
                    )
                if item in evidence_strings:
                    raise ValueError(
                        "artifact promotion validation_evidence must not contain duplicates"
                    )
                evidence_strings.add(item)
            elif not isinstance(item, Mapping) or item:
                raise ValueError(
                    "artifact promotion validation_evidence must contain typed values"
                )
            elif has_empty_object:
                raise ValueError(
                    "artifact promotion validation_evidence must not contain duplicates"
                )
            else:
                has_empty_object = True
    if "provenance" in value:
        provenance = value["provenance"]
        if not isinstance(provenance, Mapping) or not set(provenance) <= {
            "artifact_id",
            "project_id",
        }:
            raise ValueError("artifact promotion provenance must be closed")
        if any(not _bounded_safe_id(item) for item in provenance.values()):
            raise ValueError("artifact promotion provenance must contain safe IDs")


def _normalize_approval(approval: Any) -> dict[str, Any]:
    if not isinstance(approval, dict):
        raise ValueError("approval must be an object")
    normalized = dict(approval)
    if set(normalized) == LEGACY_APPROVAL_KEYS:
        normalized["decision"] = "approved"
    _validate_approval(normalized)
    return normalized


def _validate_approval(approval: dict[str, Any]) -> None:
    if set(approval) != set(APPROVAL_REQUIRED_KEYS):
        raise ValueError("approval has invalid fields")
    for key in ("approval_id", "target_id", "scope"):
        value = approval[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"approval {key} must be a non-empty string")
    _require_safe_component(approval["approval_id"], "approval_id")
    if not isinstance(approval["notes"], str):
        raise ValueError("approval notes must be a string")
    if (
        not isinstance(approval["decision"], str)
        or approval["decision"] not in APPROVAL_DECISIONS
    ):
        raise ValueError("approval decision is not recognized")


def _require_safe_component(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value or not _is_safe_component(value):
        raise ValueError(f"{label} must be a safe single path component")


def _is_safe_component(value: str) -> bool:
    return value not in {".", ".."} and "/" not in value and "\\" not in value


def _bounded_safe_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and SAFE_ID_RE.fullmatch(value) is not None
    )


def _project_contained_path(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value.startswith("/")
        or "\\" in value
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
    ):
        return False
    return all(part not in {".", ".."} for part in value.split("/"))

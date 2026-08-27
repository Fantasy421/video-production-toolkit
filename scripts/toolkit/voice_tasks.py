"""Preparation checkpoints for immutable uploaded and ChatCut voice tasks."""

from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
from typing import Any, Optional

from .adapters import select_adapter
from .runtime_paths import project_path, project_root
from .tasks import _validate_envelope, _validate_result
from .voice import validate_voice_bundle


_CHATCUT_ADAPTER = "chatcut"
_CHATCUT_VOICE_SKILL = "chatcut:voice"
_UPLOAD_TYPES = frozenset({"audio", "audio-asset", "uploaded-audio"})


def prepare_voice_task(
    root: Path,
    envelope: Mapping[str, Any],
    artifacts: Iterable[Mapping[str, Any]],
    installed_skills: Iterable[str],
) -> dict[str, Any]:
    """Prepare one immutable ``voice.prepare`` task without producing media.

    A waiting result is deliberately resumable: no audio ID is returned until
    the declared external work has published a valid voice lineage.  The only
    success path reports artifacts already present in the supplied immutable
    project view.
    """
    root = project_root(root)
    task = _task_envelope(envelope)
    records = _artifact_records(artifacts)
    skills = _installed_skills(installed_skills)
    inputs = list(task["inputs"])
    output_ids = task["constraints"]["output_artifact_ids"]
    declared_records = _declared_records(records, [*inputs, *output_ids])
    source = _current_source(
        declared_records, task["constraints"]["voice_source_id"]
    )
    if source is None:
        return _result(
            task,
            "waiting_user",
            warnings=["voice-source-decision-required"],
            user_decision_request="Choose uploaded-voice or tts for the approved narration.",
        )

    narration_id = source.get("narration_id")
    if not _approved_source(source, narration_id, inputs):
        return _result(
            task,
            "waiting_user",
            warnings=["voice-source-decision-required"],
            user_decision_request="Approve a current voice source decision for the declared narration.",
        )

    mode = source["mode"]
    if mode == "uploaded-voice":
        upload = _declared_upload(root, declared_records, inputs)
        if upload is None:
            return _result(
                task,
                "waiting_user",
                warnings=["voice-upload-required"],
                user_decision_request="Upload the declared narration recording.",
            )
        adapter = _select_chatcut("voice.time", "narration", "voice-timing", task, skills)
        if adapter is None:
            return _result(
                task,
                "waiting_external",
                warnings=["chatcut-voice-unavailable"],
                error="external-provider-pending",
            )
        complete, warning = _completed_outputs(
            root, declared_records, narration_id, output_ids
        )
        if complete is not None:
            return _result(task, "succeeded", artifacts=complete, checks=["voice-artifacts-valid"])
        return _result(
            task,
            "waiting_external",
            checks=["adapter-selected:chatcut", "voice-timing-job-prepared"],
            warnings=[warning],
            error="external-provider-pending",
        )

    if mode != "tts":
        return _result(
            task,
            "waiting_user",
            warnings=["voice-source-decision-required"],
            user_decision_request="Choose uploaded-voice or tts for the approved narration.",
        )

    profile = _current_profile(
        declared_records, task["constraints"]["voice_profile_id"]
    )
    if not _approved_tts_profile(profile):
        return _result(
            task,
            "waiting_user",
            warnings=["voice-profile-approval-required"],
            user_decision_request="Approve the declared ChatCut Voice profile before synthesis.",
        )
    if profile["provider"] != _CHATCUT_ADAPTER:
        return _result(
            task,
            "waiting_user",
            warnings=["chatcut-voice-profile-required"],
            user_decision_request="Approve a ChatCut Voice profile; no other provider is declared for this task.",
        )
    adapter = _select_chatcut("voice.synthesize", "voice-profile", "voiceover", task, skills)
    if adapter is None:
        return _result(
            task,
            "waiting_external",
            warnings=["chatcut-voice-unavailable"],
            error="external-provider-pending",
        )
    complete, warning = _completed_outputs(
        root, declared_records, narration_id, output_ids
    )
    if complete is not None:
        return _result(task, "succeeded", artifacts=complete, checks=["voice-artifacts-valid"])
    return _result(
        task,
        "waiting_external",
        checks=["adapter-selected:chatcut", "voice-synthesis-job-prepared"],
        warnings=[warning],
        error="external-provider-pending",
    )


def _task_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, Mapping):
        raise ValueError("task envelope must be a mapping")
    task = dict(envelope)
    required = {
        "task_id",
        "capability",
        "inputs",
        "adapter_preferences",
        "output_contract",
        "constraints",
    }
    if set(task) != required:
        raise ValueError("task envelope must match the declared task schema")
    _validate_envelope(task)
    if task["capability"] != "voice.prepare":
        raise ValueError("prepare_voice_task requires voice.prepare")
    for field in ("task_id", "output_contract"):
        if not isinstance(task[field], str) or not task[field]:
            raise ValueError(f"task envelope {field} must be a non-empty string")
    if not isinstance(task["inputs"], list) or not all(
        isinstance(value, str) and value for value in task["inputs"]
    ) or len(task["inputs"]) != len(set(task["inputs"])):
        raise ValueError("task envelope inputs must be a unique string list")
    if not isinstance(task["adapter_preferences"], list) or not all(
        isinstance(value, str) and value for value in task["adapter_preferences"]
    ) or not task["adapter_preferences"] or len(task["adapter_preferences"]) != len(
        set(task["adapter_preferences"])
    ):
        raise ValueError("task envelope adapter_preferences must be a unique non-empty string list")
    if not isinstance(task["constraints"], Mapping):
        raise ValueError("task envelope constraints must be a mapping")
    task["constraints"] = dict(task["constraints"])
    for field in ("worker_id", "claim_token", "voice_source_id", "voice_profile_id"):
        if not isinstance(task["constraints"].get(field), str) or not task["constraints"][field]:
            raise ValueError(f"voice task constraints must include {field}")
    if (
        task["constraints"]["voice_source_id"] not in task["inputs"]
        or task["constraints"]["voice_profile_id"] not in task["inputs"]
    ):
        raise ValueError("voice task source and profile IDs must be declared inputs")
    output_ids = task["constraints"].get("output_artifact_ids")
    if (
        not isinstance(output_ids, list)
        or len(output_ids) != 3
        or any(not isinstance(value, str) or not value for value in output_ids)
        or len(set(output_ids)) != 3
        or set(output_ids) & set(task["inputs"])
    ):
        raise ValueError("voice task constraints must include three distinct output_artifact_ids")
    return task


def _artifact_records(artifacts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(artifacts, (str, bytes, Mapping)):
        raise ValueError("artifacts must be an iterable of mappings")
    try:
        records = list(artifacts)
    except TypeError as error:
        raise ValueError("artifacts must be an iterable of mappings") from error
    if not all(isinstance(record, Mapping) for record in records):
        raise ValueError("artifacts must contain mappings")
    return [dict(record) for record in records]


def _declared_records(
    records: list[dict[str, Any]], allowed_ids: list[str]
) -> list[dict[str, Any]]:
    """Return only exact task input/output records; duplicate IDs are unusable."""
    allowed = set(allowed_ids)
    selected = [record for record in records if record.get("artifact_id") in allowed]
    counts = {artifact_id: 0 for artifact_id in allowed}
    for record in selected:
        artifact_id = record.get("artifact_id")
        if isinstance(artifact_id, str):
            counts[artifact_id] += 1
    return [record for record in selected if counts[record["artifact_id"]] == 1]


def _installed_skills(installed_skills: Iterable[str]) -> list[str]:
    if isinstance(installed_skills, (str, bytes, Mapping)):
        raise ValueError("installed_skills must be an iterable of strings")
    try:
        skills = list(installed_skills)
    except TypeError as error:
        raise ValueError("installed_skills must be an iterable of strings") from error
    if not all(isinstance(skill, str) and skill for skill in skills) or len(skills) != len(set(skills)):
        raise ValueError("installed_skills must be a unique string list")
    return skills


def _current_source(
    records: list[dict[str, Any]], source_id: str
) -> Optional[dict[str, Any]]:
    candidates = [
        record
        for record in records
        if record.get("type") == "voice-source-decision"
        and record.get("artifact_id") == source_id
    ]
    return _latest(candidates)


def _current_profile(
    records: list[dict[str, Any]], profile_id: str
) -> Optional[dict[str, Any]]:
    candidates = [
        record
        for record in records
        if record.get("type") == "voice-profile" and record.get("artifact_id") == profile_id
    ]
    return _latest(candidates)


def _latest(records: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not records:
        return None
    return max(
        records,
        key=lambda record: (
            record.get("version") if isinstance(record.get("version"), int) else -1,
            str(record.get("artifact_id", "")),
        ),
    )


def _approved_source(source: dict[str, Any], narration_id: Any, inputs: list[str]) -> bool:
    return (
        source.get("status") == "approved"
        and source.get("decision") == "approved"
        and source.get("mode") in {"uploaded-voice", "tts"}
        and isinstance(narration_id, str)
        and narration_id in inputs
    )


def _approved_tts_profile(profile: Optional[dict[str, Any]]) -> bool:
    return bool(
        profile
        and profile.get("status") == "approved"
        and profile.get("mode") == "tts"
        and profile.get("approved") is True
        and isinstance(profile.get("provider"), str)
        and profile["provider"]
        and isinstance(profile.get("voice_id"), str)
        and profile["voice_id"]
    )


def _declared_upload(
    root: Path, records: list[dict[str, Any]], inputs: list[str]
) -> Optional[dict[str, Any]]:
    candidates = [
        record
        for record in records
        if record.get("artifact_id") in inputs
        and record.get("type") in _UPLOAD_TYPES
        and record.get("status") == "approved"
    ]
    if len(candidates) != 1:
        return None
    upload = candidates[0]
    media_path = upload.get("media_path")
    if not isinstance(media_path, str) or not media_path:
        return None
    try:
        path = project_path(root, media_path)
    except ValueError:
        return None
    return upload if path.is_file() and not path.is_symlink() else None


def _completed_outputs(
    root: Path,
    records: list[dict[str, Any]],
    narration_id: Any,
    output_ids: list[str],
) -> tuple[Optional[list[str]], str]:
    if not isinstance(narration_id, str) or not narration_id:
        return None, "voice-artifacts-pending"
    voiceover = _record_by_id(records, output_ids[0])
    if voiceover is not None and not _safe_readable_voiceover(root, voiceover):
        return None, "voiceover-media-unavailable"
    bundle = validate_voice_bundle(records, narration_id)
    if not bundle["ok"]:
        return None, "voice-artifacts-pending"
    timing_id = bundle["voice_timing_id"]
    beats = _record_by_id(records, output_ids[2])
    if (
        bundle["voiceover_id"] != output_ids[0]
        or timing_id != output_ids[1]
        or beats is None
        or beats.get("type") != "semantic-beats"
        or beats.get("status") != "approved"
        or beats.get("voice_timing_id") != timing_id
        or beats.get("parents") != [timing_id]
    ):
        return None, "voice-artifacts-pending"
    return [output_ids[0], output_ids[1], output_ids[2]], ""


def _record_by_id(records: list[dict[str, Any]], artifact_id: str) -> Optional[dict[str, Any]]:
    matches = [record for record in records if record.get("artifact_id") == artifact_id]
    return matches[0] if len(matches) == 1 else None


def _safe_readable_voiceover(root: Path, voiceover: dict[str, Any]) -> bool:
    if voiceover.get("type") != "voiceover":
        return False
    media_path = voiceover.get("media_path")
    if not isinstance(media_path, str) or not media_path:
        return False
    try:
        path = project_path(root, media_path)
    except ValueError:
        return False
    return path.is_file() and not path.is_symlink() and os.access(path, os.R_OK)


def _select_chatcut(
    capability: str,
    contract: str,
    output: str,
    task: dict[str, Any],
    skills: list[str],
) -> Optional[dict[str, Any]]:
    if _CHATCUT_ADAPTER not in task["adapter_preferences"]:
        return None
    manifests = _packaged_manifests()
    try:
        selected = select_adapter(
            capability,
            {
                "adapter_preferences": list(task["adapter_preferences"]),
                "preferred_adapter": _CHATCUT_ADAPTER,
                "installed_skills": skills,
                "contract": contract,
                "output": output,
            },
            manifests,
        )
    except ValueError:
        return None
    if (
        selected["id"] != _CHATCUT_ADAPTER
        or selected["installed_skill"] != _CHATCUT_VOICE_SKILL
        or selected["fallback"] is not None
    ):
        return None
    return selected


def _packaged_manifests() -> list[dict[str, Any]]:
    manifests_root = Path(__file__).parents[2] / "registries" / "adapters"
    manifests = []
    for path in sorted(manifests_root.glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid packaged adapter manifest: {path}") from error
        manifests.append(manifest)
    return manifests


def _result(
    task: dict[str, Any],
    status: str,
    *,
    artifacts: Optional[list[str]] = None,
    checks: Optional[list[str]] = None,
    warnings: Optional[list[str]] = None,
    error: Optional[str] = None,
    user_decision_request: Optional[str] = None,
) -> dict[str, Any]:
    result = {
        "task_id": task["task_id"],
        "status": status,
        "inputs": list(task["inputs"]),
        "artifacts": [] if artifacts is None else list(artifacts),
        "checks": [] if checks is None else list(checks),
        "warnings": [] if warnings is None else list(warnings),
        "worker_id": task["constraints"]["worker_id"],
        "claim_token": task["constraints"]["claim_token"],
    }
    if error is not None:
        result["error"] = error
    if user_decision_request is not None:
        result["user_decision_request"] = user_decision_request
    _validate_result(result)
    return result

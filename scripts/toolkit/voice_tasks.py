"""Preparation checkpoints for immutable uploaded and ChatCut voice tasks."""

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any, Optional

from .adapters import select_adapter
from .artifacts import validate_artifact_record
from .semantic_beats import validate_semantic_beats
from .tasks import _validate_result, validate_current_task_envelope
from .timed_semantic_beats import bind_semantic_beats
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
    task = _task_envelope(envelope)
    records = _artifact_records(artifacts)
    skills = _installed_skills(installed_skills)
    inputs = list(task["inputs"])
    output_ids = task["constraints"]["output_artifact_ids"]
    declared_records = _declared_records(records, [*inputs, *output_ids])
    source_id = task["constraints"].get("voice_source_id")
    source = _current_source(declared_records, source_id)
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
        upload_id = task["constraints"].get("uploaded_audio_id")
        upload = _declared_upload(
            declared_records,
            upload_id,
            narration_id,
            source["artifact_id"],
        )
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
            declared_records,
            narration_id,
            source["artifact_id"],
            None,
            upload_id,
            task["constraints"]["semantic_beats_id"],
            output_ids,
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

    profile_id = task["constraints"].get("voice_profile_id")
    profile = _current_profile(declared_records, profile_id)
    if not _approved_tts_profile(profile, narration_id, source["artifact_id"]):
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
        declared_records,
        narration_id,
        source["artifact_id"],
        profile_id,
        None,
        task["constraints"]["semantic_beats_id"],
        output_ids,
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
    validate_current_task_envelope(task)
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
    for field in ("worker_id", "claim_token"):
        if not isinstance(task["constraints"].get(field), str) or not task["constraints"][field]:
            raise ValueError(f"voice task constraints must include {field}")
    for field in ("voice_source_id", "voice_profile_id", "uploaded_audio_id"):
        value = task["constraints"].get(field)
        if value is not None and (
            not isinstance(value, str) or not value or value not in task["inputs"]
        ):
            raise ValueError(f"voice task {field} must be a declared input")
    if task["constraints"].get("voice_source_id") is None and any(
        task["constraints"].get(field) is not None
        for field in ("voice_profile_id", "uploaded_audio_id")
    ):
        raise ValueError("voice task dependent inputs require voice_source_id")
    semantic_beats_id = task["constraints"].get("semantic_beats_id")
    if (
        not isinstance(semantic_beats_id, str)
        or not semantic_beats_id
        or semantic_beats_id not in task["inputs"]
    ):
        raise ValueError("voice task requires a declared semantic_beats_id input")
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
    records: list[dict[str, Any]], source_id: Any
) -> Optional[dict[str, Any]]:
    if not isinstance(source_id, str) or not source_id:
        return None
    candidates = [
        record
        for record in records
        if record.get("type") == "voice-source-decision"
        and record.get("artifact_id") == source_id
    ]
    return _latest(candidates)


def _current_profile(
    records: list[dict[str, Any]], profile_id: Any
) -> Optional[dict[str, Any]]:
    if not isinstance(profile_id, str) or not profile_id:
        return None
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
        and source.get("parents") == [narration_id]
        and isinstance(source.get("decision_provenance"), str)
        and bool(source["decision_provenance"].strip())
    )


def _approved_tts_profile(
    profile: Optional[dict[str, Any]], narration_id: Any, source_id: str
) -> bool:
    parents = profile.get("parents") if profile is not None else None
    return bool(
        profile
        and profile.get("status") == "approved"
        and profile.get("mode") == "tts"
        and profile.get("approved") is True
        and isinstance(profile.get("provider"), str)
        and profile["provider"]
        and isinstance(profile.get("voice_id"), str)
        and profile["voice_id"]
        and profile.get("narration_id") == narration_id
        and profile.get("source_decision_id") == source_id
        and isinstance(parents, list)
        and all(isinstance(parent, str) for parent in parents)
        and len(parents) == 2
        and set(parents) == {narration_id, source_id}
        and isinstance(profile.get("consent_provenance"), str)
        and bool(profile["consent_provenance"].strip())
        and isinstance(profile.get("profile_provenance"), str)
        and bool(profile["profile_provenance"].strip())
    )


def _declared_upload(
    records: list[dict[str, Any]],
    uploaded_audio_id: Any,
    narration_id: Any,
    source_id: str,
) -> Optional[dict[str, Any]]:
    if not isinstance(uploaded_audio_id, str) or not uploaded_audio_id:
        return None
    upload = _record_by_id(records, uploaded_audio_id)
    if (
        upload is None
        or upload.get("type") not in _UPLOAD_TYPES
        or upload.get("status") != "approved"
        or not isinstance(narration_id, str)
        or upload.get("parents") != [narration_id, source_id]
    ):
        return None
    return upload if isinstance(upload.get("media_path"), str) and upload["media_path"] else None


def _completed_outputs(
    records: list[dict[str, Any]],
    narration_id: Any,
    source_id: str,
    profile_id: Optional[str],
    uploaded_audio_id: Optional[str],
    semantic_beats_id: str,
    output_ids: list[str],
) -> tuple[Optional[list[str]], str]:
    if not isinstance(narration_id, str) or not narration_id:
        return None, "voice-artifacts-pending"
    lineage_ids = [source_id, semantic_beats_id, *output_ids]
    if profile_id is not None:
        lineage_ids.append(profile_id)
    if uploaded_audio_id is not None:
        lineage_ids.append(uploaded_audio_id)
    narration_records = [
        record for record in records if record.get("artifact_id") == narration_id
    ]
    completion_records = [
        *narration_records,
        *_declared_records(records, lineage_ids),
    ]
    bundle = validate_voice_bundle(completion_records, narration_id)
    if not bundle["ok"]:
        return None, "voice-artifacts-pending"
    timing_id = bundle["voice_timing_id"]
    semantic = _record_by_id(completion_records, semantic_beats_id)
    timed = _record_by_id(completion_records, output_ids[2])
    timing = _record_by_id(completion_records, timing_id)
    if (
        bundle["voiceover_id"] != output_ids[0]
        or timing_id != output_ids[1]
        or not _valid_timed_semantic_output(
            semantic, timed, timing, narration_id, semantic_beats_id, timing_id
        )
    ):
        return None, "voice-artifacts-pending"
    return [output_ids[0], output_ids[1], output_ids[2]], ""


def _valid_timed_semantic_output(
    semantic: Optional[dict[str, Any]],
    timed: Optional[dict[str, Any]],
    timing: Optional[dict[str, Any]],
    narration_id: str,
    semantic_beats_id: str,
    timing_id: str,
) -> bool:
    """Confirm that completion only adds real timing to frozen decisions."""
    if (
        semantic is None
        or timed is None
        or timing is None
    ):
        return False
    try:
        validate_artifact_record(semantic)
        validate_artifact_record(timed)
        validate_artifact_record(timing)
    except (KeyError, TypeError, ValueError):
        return False
    if (
        semantic.get("type") != "semantic-beats"
        or semantic.get("status") != "approved"
        or semantic.get("narration_id") != narration_id
        or semantic.get("parents") != [narration_id]
        or timed.get("type") != "timed-semantic-beats"
        or timed.get("status") != "approved"
        or timed.get("semantic_beats_id") != semantic_beats_id
        or timed.get("voice_timing_id") != timing_id
        or timed.get("parents") != [semantic_beats_id, timing_id]
    ):
        return False
    try:
        validate_semantic_beats(
            {"narration_id": semantic["narration_id"], "beats": semantic["beats"]}
        )
        expected = bind_semantic_beats(
            {"narration_id": semantic["narration_id"], "beats": semantic["beats"]},
            timing,
            timing["keyword_anchors"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    return {
        "voice_timing_id": timed["voice_timing_id"],
        "timing_kind": timed["timing_kind"],
        "beats": timed["beats"],
    } == expected


def _record_by_id(records: list[dict[str, Any]], artifact_id: str) -> Optional[dict[str, Any]]:
    matches = [record for record in records if record.get("artifact_id") == artifact_id]
    return matches[0] if len(matches) == 1 else None


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

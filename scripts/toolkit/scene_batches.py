"""Plan clean 4--6 scene production batches from frozen full-film timing."""

import re
from collections.abc import Mapping, Sequence
from typing import Any


MIN_BATCH_SCENES = 4
MAX_BATCH_SCENES = 6
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$")
_TIMING_IDS = (
    "voice_timing_id",
    "timed_semantic_beats_id",
    "scene_timing_contracts_id",
    "timing_validation_id",
)


def plan_scene_batches(
    scene_contracts: Sequence[Mapping[str, Any]],
    timing_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return ordered chapter-local batches that each require a fresh context."""
    contracts = _validate_contracts(scene_contracts)
    _validate_frozen_timing(timing_state, contracts)
    chapters: list[tuple[str, list[dict[str, Any]]]] = []
    seen_chapters: set[str] = set()
    for contract in contracts:
        chapter_id = contract["chapter_id"]
        if not chapters or chapters[-1][0] != chapter_id:
            if chapter_id in seen_chapters:
                raise ValueError("scene contracts must keep each chapter contiguous")
            chapters.append((chapter_id, []))
            seen_chapters.add(chapter_id)
        chapters[-1][1].append(contract)

    batches: list[dict[str, Any]] = []
    for chapter_id, chapter_contracts in chapters:
        offset = 0
        for batch_number, size in enumerate(_batch_sizes(len(chapter_contracts)), 1):
            selected = chapter_contracts[offset : offset + size]
            offset += size
            contract_ids = [item["contract_id"] for item in selected]
            scene_ids = [item["scene_id"] for item in selected]
            batches.append(
                {
                    "batch_id": f"{chapter_id}-batch-{batch_number:02d}",
                    "chapter_id": chapter_id,
                    "scene_ids": scene_ids,
                    "scene_contract_ids": contract_ids,
                    "time_window_ms": [
                        selected[0]["start_ms"],
                        selected[-1]["end_ms"],
                    ],
                    "context_policy": "fresh",
                    "contract_summary": {
                        "chapter_id": chapter_id,
                        "scene_ids": scene_ids,
                        "scene_contract_ids": contract_ids,
                    },
                }
            )
    return batches


def _batch_sizes(count: int) -> list[int]:
    if count <= MAX_BATCH_SCENES:
        return [count]
    batch_count = (count + MAX_BATCH_SCENES - 1) // MAX_BATCH_SCENES
    while batch_count * MIN_BATCH_SCENES > count and batch_count > 1:
        batch_count -= 1
    if batch_count == 1:
        return [count]
    base, extra = divmod(count, batch_count)
    return [base + (1 if index < extra else 0) for index in range(batch_count)]


def _validate_contracts(
    scene_contracts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(scene_contracts, (str, bytes)) or not isinstance(
        scene_contracts, Sequence
    ):
        raise ValueError("scene contracts must be an ordered sequence")
    required = {"contract_id", "chapter_id", "scene_id", "start_ms", "end_ms"}
    contracts: list[dict[str, Any]] = []
    previous_end = -1
    for item in scene_contracts:
        if not isinstance(item, Mapping) or not required <= set(item):
            raise ValueError("scene batch requires compact scene contract metadata")
        contract = {field: item[field] for field in required}
        for field in ("contract_id", "chapter_id", "scene_id"):
            if not isinstance(contract[field], str) or not _SAFE_ID.fullmatch(
                contract[field]
            ):
                raise ValueError(f"scene batch {field} must be safe")
        start, end = contract["start_ms"], contract["end_ms"]
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or start < previous_end
        ):
            raise ValueError("scene batch timing must be ordered and non-overlapping")
        previous_end = end
        contracts.append(contract)
    if not contracts:
        raise ValueError("scene batch requires at least one contract")
    for field in ("contract_id", "scene_id"):
        values = [item[field] for item in contracts]
        if len(values) != len(set(values)):
            raise ValueError(f"scene batch {field} values must be unique")
    return contracts


def _validate_frozen_timing(
    timing_state: Mapping[str, Any], contracts: list[dict[str, Any]]
) -> None:
    if not isinstance(timing_state, Mapping):
        raise ValueError("full timing must be frozen before production batching")
    ids_valid = all(
        isinstance(timing_state.get(field), str)
        and _SAFE_ID.fullmatch(timing_state[field])
        for field in _TIMING_IDS
    )
    expected_contracts = [item["contract_id"] for item in contracts]
    if (
        timing_state.get("timing_kind") != "real"
        or timing_state.get("keywords_frozen") is not True
        or timing_state.get("timing_validation_status") != "passed"
        or timing_state.get("frozen_scene_contract_ids") != expected_contracts
        or not ids_valid
    ):
        raise ValueError("full timing and keywords must be frozen before production batching")

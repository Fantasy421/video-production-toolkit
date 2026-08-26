#!/usr/bin/env python3
"""Plan a compact, risk-led representative editable production slice."""

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any, Optional


_CARRIERS = {"a-roll", "b-roll", "scene", "demo", "motion-graphics", "evidence"}
_WEIGHTS = {
    "new-character-baseline": 5,
    "scene-image-generation": 4,
    "motion-graphics": 4,
    "demo": 4,
    "generated-video": 3,
    "b-roll-placement": 2,
    "captions": 1,
}


class RepresentativeSlice(list[str]):
    """List-compatible IDs plus explicit metadata needed to render a review gate."""

    def __init__(
        self,
        scene_ids: list[str],
        ranges: tuple[tuple[int, int], ...],
        composite: bool,
        blocker: Optional[dict[str, Any]] = None,
    ):
        super().__init__(scene_ids)
        self.ranges = ranges
        self.composite = composite
        self.blocker = blocker
        self.blocked = blocker is not None

    @property
    def duration_ms(self) -> int:
        return sum(end - start for start, end in self.ranges)


def select_representative_slice(scene_contracts: Sequence[Mapping[str, Any]]) -> RepresentativeSlice:
    """Choose one 10--20 second adjacent range, or an explicit composite sample.

    Contracts are metadata only.  The result carries scene IDs rather than paths
    or media, which keeps the representative-slice gate deterministic and safe
    to pass through the coordinator.
    """
    contracts = _normalize_contracts(scene_contracts)
    if not contracts:
        return RepresentativeSlice([], (), False)
    candidates = _range_candidates(contracts)
    plans = _valid_plans(candidates, contracts)
    if not plans:
        return _duration_blocker(contracts)
    best = min(plans, key=lambda plan: _plan_key(plan, contracts))
    return _slice_from_ranges(best, contracts)


def _normalize_contracts(scene_contracts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(scene_contracts, (str, bytes)) or not isinstance(scene_contracts, Sequence):
        raise ValueError("scene_contracts must be a sequence")
    normalized = []
    for contract in scene_contracts:
        if not isinstance(contract, Mapping):
            raise ValueError("scene contract must be a mapping")
        _validate_contract_shape(contract)
        scene_id = contract["scene_id"]
        _safe_id(scene_id)
        start, end = contract.get("start_ms"), contract.get("end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise ValueError("scene contract requires non-overlapping positive millisecond timing")
        carrier = contract.get("primary_carrier")
        if carrier not in _CARRIERS:
            raise ValueError("scene contract has an unknown primary carrier")
        normalized.append({"id": scene_id, "start": start, "end": end, "carrier": carrier, "risks": _risks(contract, carrier)})
    normalized.sort(key=lambda item: (item["start"], item["end"], item["id"]))
    if len({item["id"] for item in normalized}) != len(normalized):
        raise ValueError("scene contract IDs must be unique")
    for previous, current in zip(normalized, normalized[1:]):
        if current["start"] < previous["end"]:
            raise ValueError("scene contracts must not overlap")
    return normalized


def _risks(contract: Mapping[str, Any], carrier: str) -> frozenset[str]:
    risks = set()
    if contract.get("new_character_baseline"):
        risks.add("new-character-baseline")
    if carrier == "scene" and contract.get("scene_image_generation", True):
        risks.add("scene-image-generation")
    if carrier == "motion-graphics":
        risks.add("motion-graphics")
    if carrier == "demo":
        risks.add("demo")
    if contract.get("generated_video"):
        risks.add("generated-video")
    if carrier == "b-roll":
        risks.add("b-roll-placement")
    if contract.get("captions"):
        risks.add("captions")
    return frozenset(risks)


def _range_candidates(contracts: list[dict[str, Any]]) -> list[tuple[int, int]]:
    candidates = []
    for start_index, first in enumerate(contracts):
        for end_index in range(start_index, len(contracts)):
            duration = contracts[end_index]["end"] - first["start"]
            if duration > 20000:
                break
            candidates.append((start_index, end_index))
    return candidates


def _valid_plans(
    candidates: list[tuple[int, int]], contracts: list[dict[str, Any]]
) -> list[tuple[tuple[int, int], ...]]:
    plans = [(candidate,) for candidate in candidates if _duration((candidate,), contracts) >= 10000]
    for position, left in enumerate(candidates):
        for right in candidates[position + 1 :]:
            if left[1] >= right[0] and right[1] >= left[0]:
                continue
            plan = tuple(sorted((left, right)))
            if 10000 <= _duration(plan, contracts) <= 20000:
                plans.append(plan)
    return plans


def _plan_key(plan: tuple[tuple[int, int], ...], contracts: list[dict[str, Any]]) -> tuple[Any, ...]:
    selected = [item for start, end in plan for item in contracts[start : end + 1]]
    risks = frozenset().union(*(item["risks"] for item in selected))
    high_carriers = frozenset(
        item["carrier"]
        for item in selected
        if any(_WEIGHTS[risk] >= 4 for risk in item["risks"])
    )
    carriers = frozenset(item["carrier"] for item in selected)
    return (
        -len(high_carriers),
        _duration(plan, contracts),
        -sum(_WEIGHTS[risk] for risk in risks),
        -len(risks),
        -len(carriers),
        len(plan),
        tuple((contracts[start]["start"], contracts[end]["end"]) for start, end in plan),
        tuple(item["id"] for item in selected),
    )


def _duration(plan: tuple[tuple[int, int], ...], contracts: list[dict[str, Any]]) -> int:
    return sum(contracts[end]["end"] - contracts[start]["start"] for start, end in plan)


def _slice_from_ranges(ranges: tuple[tuple[int, int], ...], contracts: list[dict[str, Any]]) -> RepresentativeSlice:
    selected = [item for start, end in ranges for item in contracts[start : end + 1]]
    return RepresentativeSlice(
        [item["id"] for item in selected],
        tuple((contracts[start]["start"], contracts[end]["end"]) for start, end in ranges),
        len(ranges) == 2,
    )


def _duration_blocker(contracts: list[dict[str, Any]]) -> RepresentativeSlice:
    required = sorted({
        item["carrier"]
        for item in contracts
        if any(_WEIGHTS[risk] >= 4 for risk in item["risks"])
    })
    return RepresentativeSlice(
        [],
        (),
        False,
        {
            "status": "blocked",
            "code": "representative-slice-duration-unavailable",
            "required_high_risk_carriers": required,
        },
    )


def _safe_id(value: Any) -> None:
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:-]*(?:\.[A-Za-z0-9][A-Za-z0-9_:-]*)*", value):
        raise ValueError("scene_id must be a safe artifact token")


def _validate_contract_shape(contract: Mapping[str, Any]) -> None:
    allowed = {"scene_id", "start_ms", "end_ms", "primary_carrier", "secondary_layer", "purpose", "new_character_baseline", "scene_image_generation", "generated_video", "captions"}
    required = {"scene_id", "start_ms", "end_ms", "primary_carrier", "purpose"}
    if set(contract) - allowed or required - set(contract):
        raise ValueError("scene contract does not match scene-contract-v1")
    _safe_id(contract["scene_id"])
    for field in ("purpose", "secondary_layer"):
        if field in contract and (not isinstance(contract[field], str) or not contract[field]):
            raise ValueError(f"scene contract {field} must be a non-empty string")
    for field in ("new_character_baseline", "scene_image_generation", "generated_video", "captions"):
        if field in contract and not isinstance(contract[field], bool):
            raise ValueError(f"scene contract {field} must be a boolean")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a compact representative production slice.")
    parser.add_argument("contracts", help="JSON file containing an array of scene contracts")
    args = parser.parse_args()
    with open(args.contracts, encoding="utf-8") as handle:
        contracts = json.load(handle)
    selected = select_representative_slice(contracts)
    print(json.dumps({"scene_ids": list(selected), "ranges": selected.ranges, "composite": selected.composite, "blocker": selected.blocker}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

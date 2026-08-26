#!/usr/bin/env python3
"""Plan a compact, risk-led representative editable production slice."""

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any


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

    def __init__(self, scene_ids: list[str], ranges: tuple[tuple[int, int], ...], composite: bool):
        super().__init__(scene_ids)
        self.ranges = ranges
        self.composite = composite

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
    candidates = _adjacent_candidates(contracts)
    candidates.sort(key=lambda candidate: _candidate_key(candidate, contracts), reverse=True)
    has_scene = any("scene-image-generation" in item["risks"] for item in contracts)
    has_motion = any("motion-graphics" in item["risks"] for item in contracts)
    covers_both = [candidate for candidate in candidates if _covers_scene_and_motion(candidate, contracts)]
    if has_scene and has_motion and not covers_both:
        return _composite_slice(contracts)
    if candidates:
        best = candidates[0]
        return _slice_from_indexes(best, contracts, composite=False)
    return _fallback_slice(contracts)


def _normalize_contracts(scene_contracts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(scene_contracts, (str, bytes)) or not isinstance(scene_contracts, Sequence):
        raise ValueError("scene_contracts must be a sequence")
    normalized = []
    for contract in scene_contracts:
        if not isinstance(contract, Mapping):
            raise ValueError("scene contract must be a mapping")
        scene_id = contract.get("scene_id", contract.get("artifact_id", contract.get("id")))
        _safe_id(scene_id)
        start, end = contract.get("start_ms"), contract.get("end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise ValueError("scene contract requires non-overlapping positive millisecond timing")
        carrier = contract.get("primary_carrier")
        if carrier not in _CARRIERS:
            raise ValueError("scene contract has an unknown primary carrier")
        normalized.append({"id": scene_id, "start": start, "end": end, "risks": _risks(contract, carrier)})
    normalized.sort(key=lambda item: (item["start"], item["end"], item["id"]))
    if len({item["id"] for item in normalized}) != len(normalized):
        raise ValueError("scene contract IDs must be unique")
    for previous, current in zip(normalized, normalized[1:]):
        if current["start"] < previous["end"]:
            raise ValueError("scene contracts must not overlap")
    return normalized


def _risks(contract: Mapping[str, Any], carrier: str) -> frozenset[str]:
    risks = set()
    if contract.get("new_character_baseline") or contract.get("new_character"):
        risks.add("new-character-baseline")
    if carrier == "scene" and contract.get("scene_image_generation", True):
        risks.add("scene-image-generation")
    if carrier == "motion-graphics":
        risks.add("motion-graphics")
    if carrier == "demo":
        risks.add("demo")
    if contract.get("generated_video") or contract.get("media_type") == "generated-video":
        risks.add("generated-video")
    if carrier == "b-roll":
        risks.add("b-roll-placement")
    if contract.get("captions") or contract.get("caption_required"):
        risks.add("captions")
    return frozenset(risks)


def _adjacent_candidates(contracts: list[dict[str, Any]]) -> list[tuple[int, int]]:
    candidates = []
    for start_index, first in enumerate(contracts):
        for end_index in range(start_index, len(contracts)):
            duration = contracts[end_index]["end"] - first["start"]
            if duration > 20000:
                break
            if duration >= 10000:
                candidates.append((start_index, end_index))
    return candidates


def _candidate_key(candidate: tuple[int, int], contracts: list[dict[str, Any]]) -> tuple[int, int, int, int, int]:
    start_index, end_index = candidate
    selected = contracts[start_index : end_index + 1]
    risks = frozenset().union(*(item["risks"] for item in selected))
    high_risks = {risk for risk in risks if _WEIGHTS[risk] >= 4}
    duration = selected[-1]["end"] - selected[0]["start"]
    # reverse=True means negative duration gives the shortest range after the
    # requested maximum high-risk coverage, before lower-risk extras can win.
    return len(high_risks), -duration, sum(_WEIGHTS[risk] for risk in risks), len(risks), -start_index


def _covers_scene_and_motion(candidate: tuple[int, int], contracts: list[dict[str, Any]]) -> bool:
    risks = frozenset().union(*(item["risks"] for item in contracts[candidate[0] : candidate[1] + 1]))
    return {"scene-image-generation", "motion-graphics"} <= risks


def _slice_from_indexes(candidate: tuple[int, int], contracts: list[dict[str, Any]], composite: bool) -> RepresentativeSlice:
    selected = contracts[candidate[0] : candidate[1] + 1]
    return RepresentativeSlice(
        [item["id"] for item in selected],
        ((selected[0]["start"], selected[-1]["end"]),),
        composite,
    )


def _composite_slice(contracts: list[dict[str, Any]]) -> RepresentativeSlice:
    scene_index = _best_index_with_risk(contracts, "scene-image-generation")
    motion_index = _best_index_with_risk(contracts, "motion-graphics")
    selected = sorted({scene_index, motion_index})
    return RepresentativeSlice(
        [contracts[index]["id"] for index in selected],
        tuple((contracts[index]["start"], contracts[index]["end"]) for index in selected),
        True,
    )


def _fallback_slice(contracts: list[dict[str, Any]]) -> RepresentativeSlice:
    best = max(
        range(len(contracts)),
        key=lambda index: (sum(_WEIGHTS[risk] for risk in contracts[index]["risks"]), -contracts[index]["start"], contracts[index]["id"]),
    )
    return _slice_from_indexes((best, best), contracts, composite=False)


def _best_index_with_risk(contracts: list[dict[str, Any]], required: str) -> int:
    indexes = [index for index, item in enumerate(contracts) if required in item["risks"]]
    return max(indexes, key=lambda index: (sum(_WEIGHTS[risk] for risk in contracts[index]["risks"]), -contracts[index]["start"], contracts[index]["id"]))


def _safe_id(value: Any) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."} or ".." in value or "/" in value or "\\" in value:
        raise ValueError("scene_id must be a safe artifact token")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a compact representative production slice.")
    parser.add_argument("contracts", help="JSON file containing an array of scene contracts")
    args = parser.parse_args()
    with open(args.contracts, encoding="utf-8") as handle:
        contracts = json.load(handle)
    selected = select_representative_slice(contracts)
    print(json.dumps({"scene_ids": list(selected), "ranges": selected.ranges, "composite": selected.composite}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

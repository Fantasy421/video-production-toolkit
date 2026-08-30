#!/usr/bin/env python3
"""Measure model-visible Skill context with a deterministic static estimator."""

import argparse
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any


ESTIMATOR = "utf8-bytes-ceil-div-4-v1"
DEFAULT_MAX_ESTIMATED_TOKENS = 3_000
COMMON_REFERENCES = (
    "references/schemas/task-envelope.schema.json",
    "references/schemas/task-result.schema.json",
    "references/policies/decision-gates.md",
)
MODEL_FORBIDDEN_REFERENCES = frozenset(COMMON_REFERENCES)
_REFERENCE = re.compile(r"`(\.\./\.\./(?:references|scripts)/[^`]+)`")


def _estimated_tokens(byte_count: int) -> int:
    return math.ceil(byte_count / 4)


def _explicit_references(root: Path, skill: Path) -> list[Path]:
    text = skill.read_text(encoding="utf-8")
    references: list[Path] = []
    for relative in _REFERENCE.findall(text):
        path = (skill.parent / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file() and path not in references:
            references.append(path)
    return references


def measure_context(root: Path) -> dict[str, Any]:
    """Return stable byte and estimated-token measurements for every Skill."""
    root = Path(root).resolve()
    common_bytes = sum((root / relative).stat().st_size for relative in COMMON_REFERENCES)
    skills = []
    for skill in sorted((root / "skills").glob("*/SKILL.md")):
        references = _explicit_references(root, skill)
        paths = [skill, *references]
        byte_count = sum(path.stat().st_size for path in paths)
        skills.append(
            {
                "skill": skill.parent.name,
                "bytes": byte_count,
                "estimated_tokens": _estimated_tokens(byte_count),
                "explicit_references": [
                    path.relative_to(root).as_posix() for path in references
                ],
            }
        )
    return {
        "estimator": ESTIMATOR,
        "common_reference_bytes": common_bytes,
        "common_reference_estimated_tokens": _estimated_tokens(common_bytes),
        "skills": skills,
    }


def validate_context_budget(
    report: dict[str, Any],
    *,
    max_estimated_tokens: int = DEFAULT_MAX_ESTIMATED_TOKENS,
) -> list[dict[str, Any]]:
    """Return compact stable issues for oversized or schema-reading Skills."""
    issues: list[dict[str, Any]] = []
    for skill in report.get("skills", []):
        name = skill.get("skill", "unknown")
        tokens = skill.get("estimated_tokens")
        if not isinstance(tokens, int) or tokens > max_estimated_tokens:
            issues.append(
                {
                    "code": "SKILL_CONTEXT_BUDGET_EXCEEDED",
                    "skill": name,
                    "estimated_tokens": tokens,
                    "limit": max_estimated_tokens,
                }
            )
        for relative in skill.get("explicit_references", []):
            if relative in MODEL_FORBIDDEN_REFERENCES:
                issues.append(
                    {
                        "code": "MODEL_READS_COMMON_CONTRACT",
                        "skill": name,
                        "path": relative,
                    }
                )
    return issues


def compare_to_baseline(report: dict[str, Any], baseline_path: Path) -> dict[str, Any]:
    """Compare one current report with a checked-in report from a named commit."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    if baseline.get("estimator") != report.get("estimator"):
        raise ValueError("context baseline estimator does not match")
    before = {item["skill"]: item for item in baseline.get("skills", [])}
    after = {item["skill"]: item for item in report.get("skills", [])}
    if not before or set(before) != set(after):
        raise ValueError("context baseline skill set does not match")
    before_values = [before[name]["estimated_tokens"] for name in sorted(before)]
    after_values = [after[name]["estimated_tokens"] for name in sorted(after)]
    before_summary = _summary(before_values)
    after_summary = _summary(after_values)
    reduction = round(
        100
        * (before_summary["mean_estimated_tokens"] - after_summary["mean_estimated_tokens"])
        / before_summary["mean_estimated_tokens"],
        1,
    )
    return {
        "source_commit": baseline.get("source_commit"),
        "before": before_summary,
        "after": after_summary,
        "reduction_percent": reduction,
        "skills": [
            {
                "skill": name,
                "before_estimated_tokens": before[name]["estimated_tokens"],
                "after_estimated_tokens": after[name]["estimated_tokens"],
                "reduction_percent": round(
                    100
                    * (before[name]["estimated_tokens"] - after[name]["estimated_tokens"])
                    / before[name]["estimated_tokens"],
                    1,
                ),
            }
            for name in sorted(before)
        ],
    }


def _summary(values: list[int]) -> dict[str, int]:
    return {
        "min_estimated_tokens": min(values),
        "median_estimated_tokens": round(statistics.median(values)),
        "mean_estimated_tokens": round(statistics.mean(values)),
        "max_estimated_tokens": max(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = measure_context(args.repo)
    issues = validate_context_budget(report)
    baseline_path = args.repo / "references/policies/context-budget-baseline.json"
    comparison = (
        compare_to_baseline(report, baseline_path) if baseline_path.is_file() else None
    )
    output = {**report, "baseline_comparison": comparison, "issues": issues}
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 1 if args.check and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Relay a verified visual-media handoff into a compact user review manifest."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.toolkit.visual_media_context import compact_visual_media_result


def build_review_pack(
    root: Path,
    handoff: Mapping[str, Any],
    *,
    visual_media_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact review metadata without accessing the preview path.

    ``handoff`` has already passed visual-media validation.  ``root`` is kept
    in the public interface for callers, but is intentionally not used: this
    relay must not resolve, open, probe, or otherwise dereference visual media.
    """
    del root
    if visual_media_context is None:
        raise ValueError(
            "build_review_pack requires a validated visual_media_context"
        )
    compact = compact_visual_media_result(visual_media_context, handoff)
    return {
        **compact,
        "decision_status": "waiting_user",
        "subjective_acceptance_authority": "user",
        "allowed_user_decisions": ["approve", "reject", "request_revision"],
    }

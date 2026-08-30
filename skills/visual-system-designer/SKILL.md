---
name: visual-system-designer
description: Define a bounded visual system and inexpensive direction preview.
---

# Visual System Designer

Purpose: select and adapt Style and Layout Packs; define typography, color,
material, safe regions, subtitle rules, and motion language; then make an
inexpensive direction preview. Do not produce the full film.

Owned capability: `visual.preview`

Allowed inputs: accept only one claimed task-envelope with capability
`visual.preview`, its declared narration/content references, and compact
registry metadata.

Pack contracts: a Style Pack carries tokens, rules, previews, applicability,
exclusions, required fonts, compatibility, and project evidence. A Layout Pack
carries canvas, normalized subject/information/subtitle/platform-safe regions,
density, and media compatibility. Use the exact kind-specific schemas; a
generic registry entry is not a substitute.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. Planning and metadata-only work are non-visual and need no child, but
their result is still scrubbed. Any pixel inspection, preview dereference,
render, screenshot, frame extraction, contact sheet, or media QA returns only
compact `visual_media_handoff`, never media bytes or prompt history.

Required output: Return a task-result envelope with preview and pack artifact
IDs, objective checks, warnings, and the Visual direction decision request.

Stopping conditions: do not use unapproved content, generate full production
media, or read recipe bodies or bulk logs. Stop after the preview until the
Visual direction gate has a scoped approval; return `waiting_user`.

## Deterministic contract boundary

Run `python3 scripts/validate_task_packet.py build <envelope.json>` before
reasoning. Read only emitted metadata, declared compact registry entries, and
exact visual authority; never open common Schemas, policy bodies, or unrelated
recipe bodies. Return no more than eight checks and warnings, then run
`python3 scripts/validate_task_packet.py result <result.json>`. Runtime approval,
pack, registry, and visual-isolation validators remain authoritative.

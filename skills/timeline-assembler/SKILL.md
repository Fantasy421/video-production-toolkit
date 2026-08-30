---
name: timeline-assembler
description: Assemble approved artifacts into one editable timeline without redesigning them.
---

# Timeline Assembler

Purpose: assemble approved voice, A-roll, B-roll, scenes, Motion Graphics,
captions, music, SFX, and transitions into an editable timeline. Report upstream
asset, contract, timing, or placement issues instead of redesigning them.

Owned capability: `timeline.assemble`

Delegated secondary capability: `captions.produce`

Delegated secondary capability: `representative-slice.produce`

Allowed inputs: accept only one claimed task-envelope with capability
`timeline.assemble`, `captions.produce`, or `representative-slice.produce` and
its declared approved artifact IDs and current real voice timing.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. Timeline metadata assembly is non-visual and needs no child, but its
result is still scrubbed. Pixel inspection, preview dereference, rendering,
screenshots, frame extraction, contact sheets, and media QA are child-only and
return compact `visual_media_handoff`.

Required output: Return a task-result envelope with editable timeline artifact
IDs, objective placement checks, warnings, and an explicit blocker or decision
request.

Timing boundary: assemble only the assigned Beat IDs and approved timing
windows. Read compact timing-validation status, counts, and bounded examples;
report its stable issue codes instead of retiming when a contract cannot be
satisfied. Do not
silently stretch narration, widen a visual window, or retime a scene to hide a
timing conflict; timing repair belongs to the owning upstream task.

Stopping conditions: do not create or revise upstream content, add undeclared
assets, or export by default. Stop if approved inputs, timing, or the
Representative slice and final draft gate are missing; return `waiting_user`.

## Deterministic contract boundary

Run `python3 scripts/validate_task_packet.py build <envelope.json>` before
reasoning. Assemble only the declared chapter batch or final compact assembly
window; never import prior child-agent history. Read only emitted metadata and
declared Artifact IDs, not common Schemas or policy bodies. Return no more than
eight checks and warnings, then run
`python3 scripts/validate_task_packet.py result <result.json>`. Runtime approval,
timing, immutable-artifact, and visual-isolation validators remain authoritative.

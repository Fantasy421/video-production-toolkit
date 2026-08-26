---
name: timeline-assembler
description: Assemble approved artifacts into one editable timeline without redesigning them.
---

# Timeline Assembler

Purpose: assemble approved voice, A-roll, B-roll, scenes, Motion Graphics,
captions, music, SFX, and transitions into an editable timeline. Report upstream
asset, contract, timing, or placement issues instead of redesigning them.

Owned capability: `timeline.assemble`

Allowed inputs: accept only one claimed task-envelope with capability
`timeline.assemble` and its declared approved artifact IDs and timings.

Required output: Return a task-result envelope with editable timeline artifact
IDs, objective placement checks, warnings, and an explicit blocker or decision
request.

Stopping conditions: do not create or revise upstream content, add undeclared
assets, or export by default. Stop if approved inputs, timing, or the
Representative slice and final draft gate are missing; return `waiting_user`.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`, and
`../../references/policies/decision-gates.md`.

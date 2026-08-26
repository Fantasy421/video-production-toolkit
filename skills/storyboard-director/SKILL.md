---
name: storyboard-director
description: Produce bounded visual arrangements and immutable scene contracts.
---

# Storyboard Director

Purpose: create the visual arrangement table, select a carrier per beat,
retrieve compact recipe metadata, calculate media scope, and produce immutable
scene contracts. Do not produce media.

Owned capability: `storyboard.plan`

Allowed inputs: accept only one claimed task-envelope with capability
`storyboard.plan` and its declared beat, style, layout, and registry references.

Required output: Return a task-result envelope with storyboard and scene
contract IDs, checks, warnings, and the Storyboard and cost decision request.

Stopping conditions: stop when a beat lacks exactly one primary carrier or has
more than one secondary layer; request a revised contract. Stop for a missing
Visual direction or Storyboard and cost approval and return `waiting_user`.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/visual-carriers.md`.

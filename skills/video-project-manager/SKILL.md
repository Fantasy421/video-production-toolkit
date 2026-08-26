---
name: video-project-manager
description: Manage recoverable video-project state, artifact versions, and task recovery.
---

# Video Project Manager

Purpose: create or resume project state, apply immutable artifact and event
updates, enforce task recovery, and report invalidation. Do not interpret
narration or design visuals.

Owned capability: `project.manage`

Allowed inputs: accept only one claimed task-envelope with capability
`project.manage`, compact project references, and declared artifact IDs. Read
only those references and their schema-required metadata.

Required output: Return a task-result envelope with compact artifact IDs,
checks, warnings, and a user decision request only when recovery cannot proceed.

Stopping conditions: stop on a missing, stale, conflicting, or unlocked input;
do not overwrite artifacts or `project.json` directly. Stop at any required
approval gate and return `waiting_user`.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/invalidation.json`.

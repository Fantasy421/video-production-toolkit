---
name: video-project-manager
description: Manage recoverable video-project state, artifact versions, and task recovery.
---

# Video Project Manager

Purpose: create or resume project state, apply immutable artifact and event
updates, enforce task recovery, and report invalidation. Do not interpret
narration or design visuals.

## Voice-timed v3 recovery

The v3 lineage is `semantic-beats` → `timed-semantic-beats` →
`scene-timing-contracts` → downstream production Artifacts. Treat
`timing_bound`, `storyboard_timed`, and `production_ready` as distinct states;
never promote one from an estimate or a stale parent. Recovery must use the
current approved Artifact IDs and compact `timing-validation` status only.
never load detailed timing diagnostics, full narration, transcripts, audio, or
visual payloads into the coordinator context. Preserve immutable history and
return one bounded repair action for affected Beat IDs when timing is missing
or stale; expose at most three Beat IDs per issue code and do not rewrite the
source Artifact.

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

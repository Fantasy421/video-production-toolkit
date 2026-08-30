# Compact task packets in v0.3.0

Version 0.3.0 keeps durable task envelopes, task results, approvals, Artifact
lineage, visual isolation, and recovery records unchanged. Existing projects
and persisted one-scene tasks remain readable and resumable; no migration
rewrites historical files.

New execution uses a transient packet derived by
`scripts/validate_task_packet.py build`. The packet contains only one
capability, declared Artifact IDs, an exact time window, a capability-specific
contract summary, fixed result limits, and exact visual authority when needed.
Workers no longer read the common task Schemas or decision-policy body.

New scene production should use chapter-local `scene-batch` scopes. A regular
batch contains four to six consecutive scenes; a chapter with one to three
scenes may use one short batch. Each batch starts with a clean child-agent
context. Legacy `scene-contract` scopes remain valid for persisted tasks.

Batch planning is allowed only after real voice timing, approved keyword
anchors, timed semantic beats, scene timing contracts, and compact timing
validation are current and frozen for the full input set. Objective media QA
runs through `scripts/validate_media_batch.py` and returns stable issue counts
with at most three Scene IDs per code.

Adapters do not need a payload migration. They must accept the compact packet,
respect the exact declared batch scope, and keep checks and warnings to at most
eight unique strings of 64 characters each.

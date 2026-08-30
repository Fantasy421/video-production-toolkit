---
name: scene-producer
description: Produce one approved chapter-local batch from exact scene contracts.
---

# Scene Producer

Purpose: produce one contracted chapter-local scene batch, including B-roll,
A-roll selection, evidence capture, character action, Demo, or motion-ready
assets. A batch normally contains four to six consecutive scenes; a chapter of
one to three scenes may use one bounded short batch.

Owned capability: `scene.produce`

Allowed inputs: accept only one claimed task-envelope with capability
`scene.produce` and the exact approved scene-contract, style, and asset IDs for
one `scene-batch` scope. The batch must have one chapter and one continuous
time window derived after full-film real timing and keywords are frozen.
New tasks declare `visual_media_operation`: `none` for non-visual work, or one
active operation with the closed `visual_media_context`. The active context has
one exact `scope_identity` and exact `allowed_artifact_ids`; it is never
inferred from a generic output contract. The image-only fields
`image_operation`, `image_context`, `allowed_image_artifact_ids`, and
`allowed_character_pack_ids` are persisted legacy runtime compatibility; workers
MUST NOT author/use for new tasks.

Visual-media boundary: visual execution is isolated child agent only. Start a
fresh child context for every batch and never continue or reuse a child from a
previous batch or chapter. The child uses one claimed immutable envelope, one
exact `scope_identity`, and its exact Artifact allowlist; it must not crawl the
project or discover neighboring scenes. `visual_media_operation: none` and
non-image work are non-visual and need no child, but their result is still
scrubbed. Pixel inspection, preview
dereference, rendering, screenshots, frame extraction, contact sheets, and
media QA are child-only and return compact `visual_media_handoff`.

Required output: Return a task-result envelope with compact asset IDs, contract
checks, warnings, and any required user decision request.
For visual-media work, return only compact `visual_media_handoff` metadata:
Artifact IDs, project-contained paths, structural metadata, stable issue codes,
a short summary, decision status, and the optional singular
`review_preview_path` declared by the task contract.
It must not return image or video payloads, bytes, base64/data URLs, or prompt
histories.

Stopping conditions: do not rewrite narration, teaching goals, visual direction,
carrier choice, or shot purpose. Stop on missing Storyboard and cost approval,
an invalid contract, or an unclassified adapter failure; return `waiting_user`
or `blocked` as applicable.

## Deterministic contract boundary

Run `python3 scripts/validate_task_packet.py build <envelope.json>` before
reasoning. Read only the emitted capability, Artifact IDs, exact time window,
contract summary, and visual authority. Do not load common Schemas, neighboring
contracts, prior batch history, or prompt history. Validate produced media in
one call with `python3 scripts/validate_media_batch.py <project> <manifest.json>`
and receive only compact issue counts/examples. Return no more than eight
checks and warnings, then run
`python3 scripts/validate_task_packet.py result <result.json>`.

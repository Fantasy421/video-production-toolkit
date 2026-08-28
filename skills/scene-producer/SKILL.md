---
name: scene-producer
description: Produce one approved scene or visual asset from one scene contract.
---

# Scene Producer

Purpose: produce one contracted scene, B-roll item, A-roll selection, evidence
capture, character action, or Demo. It is one task per scene or asset.

Owned capability: `scene.produce`

Allowed inputs: accept only one claimed task-envelope with capability
`scene.produce` and declared approved scene-contract, style, and asset IDs.
Every envelope declares `visual_operation` as exactly `image-generation` or
`non-image`; image generation additionally requires `image_operation: generate`
and the closed `image_context`. The discriminator may never be omitted or
inferred from a generic output contract.

All image generation is an isolated child operation. It handles exactly one Scene Contract or one character-asset batch and receives a closed
`image_context` under task constraints. Its closed `scope_identity` names that
one Scene Contract or character-asset batch. Enforce at most 16
`allowed_image_artifact_ids`, at most 8 `allowed_character_pack_ids`,
`forbidden_scene_image_access`, `max_review_previews`, and a maximum 32,768-byte
`context_budget`; the worker must not discover or load undeclared images. Historical access is limited to declared approved
independent character assets and identity metadata. Historical Scene,
Storyboard, B-roll, Motion Graphics, and scene-preview imagery is forbidden,
including imagery containing the same character. A current Scene image must not appear in the ordinary image allowlist.
It is available only through one
exact `continuity_exception` recording its Artifact ID, `user_requested: true`,
and a trimmed non-empty reason.
Immediately before every image read or image-tool invocation, resolve the
declared Artifact metadata and call `authorize_image_access`; a denial is a
contract error and cannot broaden the context.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. `visual_media_operation: none` and non-image work are non-visual and
need no child, but their result is still scrubbed. Pixel inspection, preview
dereference, rendering, screenshots, frame extraction, contact sheets, and
media QA are child-only and return compact `visual_media_handoff`.

Required output: Return a task-result envelope with compact asset IDs, contract
checks, warnings, and any required user decision request.
For image work, return only a compact image handoff containing Artifact IDs,
project-contained paths, structural metadata, stable issue codes, a short
summary, decision status, and no more than the declared review previews. It must not return image bytes, base64/data URLs, or prompt histories.

Stopping conditions: do not rewrite narration, teaching goals, visual direction,
carrier choice, or shot purpose. Stop on missing Storyboard and cost approval,
an invalid contract, or an unclassified adapter failure; return `waiting_user`
or `blocked` as applicable.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/schemas/image-task-context.schema.json`,
`../../references/schemas/visual-media-task-context.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/visual-carriers.md`, and
`../../references/policies/visual-media-isolation.md`.

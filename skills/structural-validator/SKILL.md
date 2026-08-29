---
name: structural-validator
description: Verify objective project and timeline properties without aesthetic judgment.
---

# Structural Validator

Purpose: check schemas, paths, duration, gaps, overlaps, safe regions, contract
coverage, stale versions, fonts, saved-project state, and Demo lifecycle. Do
not perform extended subjective aesthetic critique.

Owned capability: `structure.validate`

Allowed inputs: accept only one claimed task-envelope with capability
`structure.validate` and declared timeline, contract, and project references.
New tasks declare `visual_media_operation`: `none` for structure-only
validation, or `image-inspect` with the closed `visual_media_context`. The
active context has one exact `scope_identity` and exact `allowed_artifact_ids`;
it is never inferred from input paths or output contracts. The image-only fields
`image_operation`, `image_context`, `allowed_image_artifact_ids`, and
`allowed_character_pack_ids` are persisted legacy runtime compatibility; workers
MUST NOT author/use for new tasks.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. `visual_media_operation: none` is non-visual and needs no child, but
its result is still scrubbed. Pixel
inspection, preview dereference, rendering, screenshots, frame extraction,
contact sheets, and media QA are child-only and return compact
`visual_media_handoff`.

Required output: Return a task-result envelope with validation artifact IDs,
objective checks, compact warnings, and blockers or user decision requests.
For visual-media inspection, return only compact `visual_media_handoff`
metadata: Artifact IDs, project-contained paths, structural metadata, stable
issue codes, a short summary, decision status, and at most the declared review
previews. Inspection is report-only and must not register a new image or video
Artifact. It must not return image or video payloads, bytes, base64/data URLs,
or prompt histories. Aesthetic acceptance remains a user decision.

Stopping conditions: do not mutate the timeline, repair source media, or clear
a failed validation. Stop when an input is missing, stale, or malformed, and
return `blocked`; leave subjective findings for the review package.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`, and
`../../references/schemas/visual-media-task-context.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/visual-media-isolation.md`.

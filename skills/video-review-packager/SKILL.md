---
name: video-review-packager
description: Build compact user-review artifacts and route feedback to versioned inputs.
---

# Video Review Packager

Purpose: through an isolated child agent, build low-resolution previews, contact
sheets, keyframes, version comparisons, timecoded warnings, and explicit
decision requests for concentrated user review. The primary coordinator does
not execute that visual-media work or choose creative direction.

Owned capability: `review.package`

Allowed inputs: accept only one claimed task-envelope with capability
`review.package` and declared approved timeline, validation, preview, and
version references.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. Metadata-only review planning is non-visual and needs no child, but its
result is still scrubbed. Pixel inspection, preview dereference, rendering,
screenshots, frame extraction, contact sheets, and media QA are child-only and
return compact `visual_media_handoff`; a review preview is for the user only.

Required output: Return a task-result envelope with review-pack artifact IDs,
included checks and warnings, and the Representative slice and final draft
decision request.

Stopping conditions: do not alter media, approve a draft, or convert feedback
into upstream edits. Stop when structural validation or required approval is
missing and return `waiting_user` or `blocked` with compact references.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`, and
`../../references/schemas/visual-media-task-context.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/visual-media-isolation.md`.

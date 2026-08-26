---
name: video-review-packager
description: Build compact user-review artifacts and route feedback to versioned inputs.
---

# Video Review Packager

Purpose: build low-resolution previews, contact sheets, keyframes, version
comparisons, timecoded warnings, and explicit decision requests for concentrated
user review. Do not perform production or choose creative direction.

Owned capability: `review.package`

Allowed inputs: accept only one claimed task-envelope with capability
`review.package` and declared approved timeline, validation, preview, and
version references.

Required output: Return a task-result envelope with review-pack artifact IDs,
included checks and warnings, and the Representative slice and final draft
decision request.

Stopping conditions: do not alter media, approve a draft, or convert feedback
into upstream edits. Stop when structural validation or required approval is
missing and return `waiting_user` or `blocked` with compact references.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`, and
`../../references/policies/decision-gates.md`.

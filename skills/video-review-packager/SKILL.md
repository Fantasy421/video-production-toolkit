---
name: video-review-packager
description: Build compact user-review artifacts and route feedback to versioned inputs.
---

# Video Review Packager

Purpose: relay one already validated compact `visual_media_handoff` into a
concentrated user-review manifest. It reports structural metadata and stable
check/issue codes; it does not create a preview, keyframe, contact sheet, or
other visual derivative. The primary coordinator does not execute visual-media
work or choose creative direction.

Owned capability: `review.package`

Allowed inputs: accept only one claimed task-envelope with capability
`review.package` and one already validated `visual_media_handoff`. Relay only
its compact scalars: declared Artifact IDs and paths, structural `media`
metadata, short summary, bounded checks/issues, and zero or one
`review_preview_path`. Do not retain prompt history, payloads, media URLs, or
undeclared fields.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. This metadata-only relay runs through an isolated child agent but must
not dereference, resolve, open, probe, render, screenshot, frame-extract, or
inspect `review_preview_path`; it must not generate a keyframe, contact sheet,
preview, or media QA result. A review preview is for the user only.

Required output: Return a task-result envelope with the compact review manifest,
included check/issue codes, the single path string when declared, and a
Representative slice and final draft decision request. The coordinator relays
the path string verbatim to the user, then stops and waits for the user's
explicit approval, rejection, or revision request. Subjective acceptance stays
with the user; this Skill must never approve a draft.

Stopping conditions: do not alter media, approve a draft, or convert feedback
into upstream edits. After relaying the manifest, return `waiting_user`; stop
when structural validation or required approval is missing and return
`waiting_user` or `blocked` with compact references.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`, and
`../../references/schemas/visual-media-task-context.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/visual-media-isolation.md`.

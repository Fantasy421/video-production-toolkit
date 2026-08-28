# Visual-Media Isolation

This policy is the authority for any image or video operation. It applies before
routing, planning, production, validation, review, or adapter selection.

## Primary-context prohibition

The primary coordinator and all non-child contexts must never generate, edit,
open, import, inspect, preview, dereference, render, screenshot, extract frames
or keyframes, create contact sheets, or perform media QA on image or video
payloads. They must never invoke visual-media tools or adapters. Audio-only
preparation is outside this policy; it neither grants nor implies visual-media
access.

The coordinator may persist or relay compact metadata only: declared Artifact
IDs, project-contained paths, structural media fields, checks, stable issue
codes, a short summary, decision status, and the one declared review-preview
path. It must never open, dereference, or visually inspect that preview path.

## Isolated child scope

Each visual-media operation runs in exactly one isolated child agent with one
claimed immutable task envelope and one closed `visual_media_context`. Its
`scope_identity` is exactly one `scene-contract`, one `character-asset-batch`,
or one `review-batch` (the latter has one to eight declared IDs). The exact
`allowed_artifact_ids` are the whole Artifact allowlist: the child must not
crawl the project, enumerate media, or discover neighboring scenes, paths, or
assets. The context has at most one review preview and a 32,768-byte result
budget.

Historical access is `character-only`: it needs an exact declared approved,
project-independent character asset or identity record. Historical scenes,
storyboards, B-roll, Motion Graphics, and scene previews remain forbidden,
even for the same character. A current Scene Artifact is inaccessible through
the ordinary allowlist. One exact `continuity_exception` may authorize it only
when the user requested it and the envelope records its Artifact ID and a
trimmed non-empty reason; it authorizes nothing else.

The child returns only a compact `visual_media_handoff`: allowlisted Artifact
IDs and project paths, bounded structural metadata, checks, stable issues, a
short summary, decision status, and at most one review-preview path. Recursively
scrub binary media, image/video URLs, data URLs, base64, prompt history, and
undeclared paths from every result field. The preview path is a user-review
boundary, not an authorization for primary-context access or automated visual
acceptance; subjective acceptance remains the user's decision.

`visual_media_operation: none` and legacy `image_operation: structure-only`
are non-visual modes: they require the same output scrub, but do not create or
require a visual child agent.

## Child-only visual adapters

Only the isolated child agent may invoke HyperFrames, VideoShotCraft, Remotion,
ChatCut, or any current or future visual adapter. An adapter receives only the
claimed immutable envelope and cannot broaden scope, inspect unallowlisted
media, or override routing, approvals, or this policy.

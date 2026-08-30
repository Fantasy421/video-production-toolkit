# Visual-Media Isolation

This policy is the authority for any image or video operation. It applies before
routing, planning, production, validation, review, or adapter selection.

## Primary-context prohibition

The primary coordinator and all non-child contexts must never generate, edit,
open, play, decode, render, screenshot, frame-extract, display, or perceptually
inspect image or video; nor may they import, preview, dereference, extract
keyframes, create contact sheets, or perform media QA on visual-media payloads.
They must never invoke visual-media tools or adapters, and must never
dereference a preview path. Audio-only preparation is outside this policy; it
neither grants nor implies visual-media access.

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

Base64 screening is structural and never decodes content. Whitespace is
removed before checking canonical tokens and padding, including whitespace
before or within `=` padding. Explicit padding, Base64/Base64URL symbols, long
single tokens, low-entropy or short-period repetitions, and repeated canonical
padded fragments, including a canonical unpadded tail, are rejected. A
normalized candidate is measurably low entropy when one symbol occupies at
least three quarters of it or its distinct-symbol count is at most one eighth
of its length. Pure alphabetic unpadded Base64 split at word boundaries is
otherwise lexically indistinguishable from ordinary prose without decoding;
the deterministic conservative boundary accepts bounded, non-periodic ASCII
multiword sequences outside those low-entropy criteria as prose. This
deliberate ambiguity is not authority to relay encoded content: producers must
use typed IDs/checksums and compact natural-language fields, while all explicit
or structurally repeated encoding forms remain forbidden.

Successful generate, edit, render, frame-extract, and contact-sheet operations
must register at least one Artifact of the operation's exact image/video kind,
and the handoff must declare the same non-empty `media.kind`. `image-inspect`
and `video-inspect` are explicitly report-only: they may register bounded
non-visual report metadata, but must not mint a new image or video Artifact.
Their handoff may omit `media.kind`; when it declares a kind or MIME type, the
values describe the inspected kind and must agree.

`visual_media_operation: none` is the non-visual, structure-only mode: it
requires the same output scrub, but does not create or require a visual child
agent. `image_operation: structure-only` is persisted legacy runtime
compatibility only; workers MUST NOT author/use it for new tasks.

## Child-only visual adapters

Only the isolated child agent may route to or invoke HyperFrames, VideoShotCraft,
Remotion, ChatCut, or any current or future visual adapter. An adapter receives
only the claimed immutable envelope and cannot broaden scope, inspect
unallowlisted media, or override routing, approvals, or this policy.

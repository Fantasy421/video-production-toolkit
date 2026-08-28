# Visual Media Subagent Isolation Design

Date: 2026-08-29

## Status

Proposed for user review.

## Context

The toolkit already isolates image generation and inspection behind bounded
image tasks. The coordinator can still encounter video operations and some
visual payloads through render, frame extraction, contact-sheet generation,
preview inspection, or workers that declare themselves non-visual. This can
fill the primary conversation context with media, make the coordinator perform
work that belongs to a production worker, and allow an incorrectly declared
task to bypass the intended boundary.

The user requires a stronger global rule: every operation that creates,
modifies, opens, plays, renders, extracts, or visually inspects an image or
video must run in an isolated child agent. The primary conversation is a
stateful coordinator and user-decision surface only.

## Goals

1. Make visual-media delegation the highest-priority toolkit rule.
2. Prohibit the primary coordinator from directly handling image or video
   payloads, even for quick checks or quality assurance.
3. Require one bounded visual-media scope for every child task.
4. Return compact structural handoffs rather than media payloads.
5. Preserve user review: the coordinator may relay one declared preview path,
   but the user, not the coordinator, opens and judges it.
6. Enforce the rule in Skill instructions, schemas, runtime validation,
   persisted recovery, and regression tests.
7. Preserve the existing voice-first workflow and audio preparation behavior.

## Non-goals

- This change does not redesign visual direction, layout quality, or shot
  aesthetics.
- It does not add a new renderer or copy external Skill implementations.
- It does not require the user to approve every child-task execution.
- It does not prohibit structural audio metadata processing. Audio playback or
  perceptual listening remains outside the coordinator, but voice preparation
  continues to be owned by `voiceover-producer`.
- It does not allow a child agent to discover the entire project media tree.

## Priority Rule

The following rule is evaluated before adapter selection, visual direction,
storyboarding, production, review, and recovery:

> If an operation can create, modify, decode, render, open, play, extract,
> display, or perceptually inspect an image or video, the primary coordinator
> must not execute it. It must create or route exactly one bounded child task,
> and the claimed task must be executed inside an isolated child agent.

Natural-language instructions that say `quickly inspect`, `check one frame`,
`open the preview`, `watch the render`, or similar do not weaken the rule.

## Operation Classification

### Visual operations

The following operations always require an isolated child agent:

- image generation or editing;
- image opening, decoding, viewing, screenshotting, or perceptual inspection;
- video generation or editing;
- video playback, opening, decoding, viewing, or perceptual inspection;
- rendering a video or visual preview;
- extracting frames, thumbnails, stills, or contact sheets;
- visual comparison, visual QA, style review, composition review, or motion
  review based on pixels;
- browser or application screenshots used as production or review evidence;
- media transcoding when the output is an image or video;
- use of image/video generation, editing, playback, rendering, or inspection
  tools.

### Coordinator-safe operations

The coordinator may read only compact structural information:

- Artifact IDs and immutable lineage;
- project-contained paths without dereferencing them;
- media kind, format, dimensions, frame rate, duration, file size, checksum,
  and readiness status;
- task status, check codes, issue codes, and short summaries;
- one declared `review_preview_path`, solely for relay to the user;
- approvals and user decisions.

The coordinator must not open, play, dereference, render, or visually inspect
the relayed preview path.

## Architecture

### Coordinator

`video-director` remains a one-action coordinator. It classifies the next
operation, creates or routes one task, and stops. It never invokes visual media
tools itself and never embeds media in its response.

The coordinator may delegate to existing bounded workers such as
`visual-system-designer`, `scene-producer`, `motion-director`,
`structural-validator`, and `video-review-packager`. A worker Skill that owns a
visual capability must state that it executes only inside an isolated child
agent.

### Child agent

A visual-media child agent receives exactly one claimed immutable task
envelope and only the Artifact metadata declared by that envelope. It may use
the necessary visual tools within that child context. It must not broaden the
scope, inspect neighboring scenes, crawl project media, or return pixels.

### Task runtime

The task runtime enforces visual-media classification at task creation, claim,
completion, and persisted-project validation. Worker self-description is not
trusted. Runtime classification uses capability, declared operation, input
Artifact types, output contract, and returned Artifact metadata.

## Visual Media Task Context

The existing image context becomes the compatibility foundation for a closed
visual-media context. Existing v2 image-task records remain readable.

A current visual-media task declares:

```json
{
  "visual_media_operation": "image-generate",
  "visual_media_context": {
    "scope_identity": {
      "kind": "scene-contract",
      "id": "scene-contract-S03-v2"
    },
    "allowed_artifact_ids": ["character-action-lin-wave-v3"],
    "historical_access": "character-only",
    "continuity_exception": null,
    "max_review_previews": 1,
    "context_budget_bytes": 32768
  }
}
```

Allowed operations form a closed enum:

- `none`
- `image-generate`
- `image-edit`
- `image-inspect`
- `video-generate`
- `video-edit`
- `video-render`
- `video-inspect`
- `frame-extract`
- `contact-sheet`

`none` is valid only when capability, inputs, outputs, and result are all
structurally non-visual. A visual input or output cannot opt out by declaring
`none`.

## Scope Rules

Every visual-media task has exactly one scope:

1. one Scene Contract; or
2. one approved character-asset batch; or
3. one explicit review batch containing an exact bounded list of current
   Artifact IDs.

Rules:

- Scene scope cannot contain another Scene Contract or character batch.
- Character-batch scope cannot contain a Scene Contract or another batch.
- Review-batch scope contains only its exact current Artifact IDs and has a
  small fixed maximum.
- Neighboring scene media are never implied.
- Historical scene images, scene video, storyboards, B-roll, motion previews,
  rendered drafts, contact sheets, and review previews are forbidden by
  default.
- Historical access remains limited to independently approved character
  assets.
- One user-requested continuity exception may name one exact current visual
  Artifact ID and a non-empty reason.
- Paths are not authority. Every media path must belong to an authorized
  Artifact ID.

## Compact Result Contract

A visual-media worker returns a closed handoff:

```json
{
  "artifact_ids": ["media-S03-v4"],
  "paths": ["artifacts/media/media-S03-v4.json"],
  "media": {
    "kind": "video",
    "format": "mp4",
    "width": 1080,
    "height": 1920,
    "duration_ms": 12400
  },
  "checks": ["render-complete", "safe-region-valid"],
  "issues": [],
  "summary": "Scene S03 render is ready for user review.",
  "review_preview_path": "previews/S03-v4-low.mp4"
}
```

The coordinator-visible result must not contain:

- image bytes, video bytes, binary-like values, blobs, or Base64;
- data URLs or remote media URLs;
- decoded frames, pixel arrays, thumbnails, screenshots, or contact sheets;
- prompt transcripts or verbose generation histories;
- embedded HTML containing media payloads;
- more than one preview path;
- undeclared paths or Artifact IDs;
- unbounded checks, warnings, errors, or decision-request text.

The entire serialized result, not only the handoff field, is recursively
scrubbed and constrained by a fixed byte budget. The same scrub runs for every
task result, including tasks declared non-visual, so worker honesty is never a
security boundary.

## User Review Boundary

The user remains the authority for subjective visual quality.

1. A child agent creates the review artifact and optional low-cost preview.
2. The child returns one preview path and a compact issue summary.
3. The coordinator relays that path without opening it.
4. The user opens the preview and approves, rejects, or requests a revision.
5. Feedback creates a new immutable task input or approval event.

The coordinator and automatic validators may check structural facts, but they
must not replace the user's aesthetic decision with autonomous repeated visual
QA.

## Skill Contract Changes

### `video-director`

- Put the isolation rule before all routing instructions.
- Prohibit direct visual tool use and media dereferencing.
- Require exactly one isolated child agent for each visual-media action.
- Allow only compact handoff relay.

### Visual worker Skills

The following Skills declare isolated-child execution and compact results:

- `visual-system-designer`
- `storyboard-director` when it creates or inspects visual previews
- `scene-producer`
- `motion-director`
- `structural-validator` in pixel-inspection mode
- `timeline-assembler` when it renders or visually inspects output
- `video-review-packager`

Workers that perform structure-only metadata operations remain non-visual but
must still pass the universal result scrub.

### External adapters

HyperFrames, VideoShotCraft, Remotion, ChatCut, and any future image/video
adapter are callable only from the isolated visual worker context. Adapter
availability never authorizes the coordinator to invoke it directly.

## Recovery And Compatibility

- Existing image task records retain their original semantics and are
  projected into the visual-media compatibility view.
- New tasks use the visual-media context and operation enum.
- Recovery revalidates persisted visual tasks under the current closed rules.
- A legacy task that cannot prove its scope becomes blocked and returns to the
  last safe pre-production phase; it is not silently broadened.
- No immutable event or task history is rewritten.

## Failure Handling

- Missing child-agent delegation: block before tool execution.
- Missing or ambiguous scope: reject task creation.
- Visual media input on a `none` task: reject creation or claim.
- Visual result from a `none` task: reject completion.
- Undeclared media Artifact or path: reject completion.
- Payload or prompt-history leak: reject result publication.
- Preview overflow: reject result publication.
- Child task failure: persist a compact failure result without media payloads;
  the coordinator routes one recovery action.

## Verification

Automated tests must prove:

1. Every named visual operation requires an isolated child task context.
2. The coordinator Skill explicitly forbids image/video tools and direct media
   handling.
3. Each visual worker Skill states isolated-child execution.
4. Image generation/edit/inspection remains isolated.
5. Video generation/edit/render/playback/inspection and frame/contact-sheet
   work are isolated.
6. Visual inputs or outputs cannot hide behind `none` or a non-visual
   capability.
7. Task creation, claim, completion, recovery, and structural validation apply
   identical scope rules.
8. Scene, character-batch, and review-batch scopes are mutually exclusive and
   bounded.
9. Historical scene image/video and neighboring media remain inaccessible.
10. The continuity exception authorizes exactly one Artifact and reason.
11. The entire task result rejects image/video URLs, data URLs, binary payloads,
    decoded frames, contact sheets, prompt histories, and multiple previews.
12. Harmless checksums, IDs, prose, duration, dimensions, and local metadata do
    not produce false positives.
13. The coordinator may relay one preview path but cannot open it.
14. The installed package fingerprint includes the new policy, schemas,
    runtime, Skill changes, and tests.
15. Host-installed recovery smoke proves the isolation rule without opening or
    generating media in the primary verification context.

All test fixtures use synthetic metadata and deterministic tiny media headers.
The primary implementation and verification conversation must not open,
generate, play, or inspect image/video payloads.

## Release And Retirement Safety

The plugin patch version is incremented so Codex creates a fresh personal
plugin cache. Before replacing the installed version:

1. run the full repository verification matrix;
2. perform an independent whole-branch review;
3. install and enable the new patch version;
4. verify the host-installed cache, not the repository;
5. confirm visual worker routing, universal result scrubbing, exact scope, and
   one-preview relay;
6. keep the existing installed version available until the new cache passes.

## Success Criteria

The design succeeds when the primary conversation can manage an entire video
project without ever decoding or perceptually inspecting a visual payload,
while isolated child agents can perform every required visual operation inside
one immutable bounded scope and return only compact structural handoffs for
user review.

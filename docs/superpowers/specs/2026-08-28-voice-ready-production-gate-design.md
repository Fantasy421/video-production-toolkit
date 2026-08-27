# Voice-ready Production Gate Design

## Problem

The toolkit can reach `production_ready` without a produced narration track or
confirmed real timing. The narration policy says production must use real voice
timing, but the state machine and coordinator do not provide a voice-production
capability or enforce voice artifacts before storyboard and scene production.
This lets representative shots, captions, Motion Graphics, and timelines be
planned against estimates or no timing source at all.

## Decision

Add an explicit `voice_ready` phase and a bounded `voiceover-producer` child
Skill owning `voice.prepare`. Projects support both user-uploaded narration and
TTS. The user chooses the source per project; silence is not a choice.

The coordinator remains routing-only. It dispatches one claimed `voice.prepare`
task and never synthesizes, imports, or analyzes audio itself.

## Revised Phase Flow

The ordered phases become:

1. `initialized`
2. `content_ready`
3. `direction_ready`
4. `voice_ready`
5. `storyboard_ready`
6. `production_ready`
7. `assembled`
8. `review_ready`
9. `handoff_ready`

`visual.preview` remains legal at `content_ready`. After visual direction is
approved and the project reaches `direction_ready`, the next production action
is `voice.prepare`. `storyboard.plan` becomes legal only at `voice_ready`.

A transition into `voice_ready` requires current, valid artifacts from the same
approved narration lineage:

- one `voice-source-decision`;
- one `voice-profile`;
- one `voiceover` media artifact; and
- one `voice-timing` artifact derived from that exact voiceover.

`semantic-beats` used by storyboard and production must reference the current
`voice-timing`. A project restored from older state that lacks these artifacts
must stop at `direction_ready`; it must not infer or fabricate readiness.

## User Decision and Voice Sources

At `direction_ready`, `voice.prepare` first requires a durable voice-source
decision with one of:

- `uploaded-voice`: wait for the user to supply a narration recording;
- `tts`: ask the user to approve a voice profile, then synthesize narration.

For uploaded narration, the worker returns `waiting_user` until the declared
audio exists. It then analyzes that audio to produce real timing.

For TTS, `voice-profile` records provider, voice identity, language, speaking
rate, emotional direction, pronunciation notes, and consent/provenance where
applicable. The user must approve the profile before synthesis. The initial TTS
adapter is ChatCut Voice. Adapter absence or provider failure returns
`waiting_external` and follows the existing bounded retry policy; it never
falls back to an undeclared voice or silently changes the approved profile.

## Child Skill Contract

Add `skills/voiceover-producer/SKILL.md` with owned capability
`voice.prepare`.

Inputs are a single claimed task envelope containing current IDs for:

- approved narration;
- visual-direction/style decision;
- voice-source decision;
- voice profile when TTS is selected; and
- uploaded audio when uploaded narration is selected.

The result envelope may contain only produced Artifact IDs, objective checks,
compact warnings, and a decision request. It returns:

- `waiting_user` for a missing source choice, profile approval, or upload;
- `waiting_external` for an in-progress or unavailable declared provider;
- `succeeded` only after `voiceover`, `voice-timing`, and timing-linked
  `semantic-beats` have been published and structurally validated.

The Skill may delegate TTS or timing extraction to the declared external
adapter. External providers cannot change routing, approvals, script text, or
voice-profile fields.

## Artifact Contracts

Add schemas for:

- `voice-source-decision`: source mode and decision provenance;
- `voice-profile`: approved voice parameters and provider requirements;
- `voiceover`: media reference, duration, source/profile lineage, and
  provenance;
- `voice-timing`: word or segment timing, total duration, and exact voiceover
  parent.

Artifact paths must remain project-contained and immutable. Timing segments
must be ordered, non-overlapping, non-negative, and bounded by the voiceover
duration. The structural validator rejects missing audio, unreadable duration,
timing gaps required by a declared narration segment, timing beyond duration,
and mismatched narration/profile/voiceover lineage.

## Routing and Readiness

Add `voice.prepare` to the coordinator and route it only to
`voiceover-producer`. Legal phase/capability pairs become:

- `direction_ready` → `voice.prepare`;
- `voice_ready` → `storyboard.plan`;
- later production phases keep their existing capabilities.

`storyboard.plan`, representative-slice production, `motion.preview`,
`motion.produce`, and `timeline.assemble` must include the current
`voice-timing` in their immutable task inputs. Scene Contracts must derive
their intervals from that timing version. Missing or stale voice artifacts make
these tasks not ready even if a candidate envelope or approval exists.

`production_ready` is invalid unless its current Artifact DAG contains a valid
`voiceover` and `voice-timing` pair from the approved narration lineage.

## Invalidation

The shipped invalidation policy must apply these descendant rules:

- narration change invalidates voice profile approval as appropriate,
  voiceover, voice timing, semantic beats, storyboard, Scene Contracts, media,
  Motion Graphics, timeline, and review pack;
- voice-source or voice-profile change invalidates voiceover and every timing
  descendant;
- uploaded voice replacement invalidates voice timing and every downstream
  timing consumer;
- voice-timing change invalidates semantic beats, storyboard, Scene Contracts,
  captions, media placement, Motion Graphics timing, timeline, and review pack.

Style-only changes do not invalidate approved narration or an unchanged
voiceover, but they invalidate visual descendants as already defined.

## Backward Compatibility

Project-state schema advances with an explicit compatibility path. When replay
encounters a pre-voice phase sequence, it preserves valid historical events but
normalizes any `storyboard_ready` or `production_ready` snapshot lacking current
voice artifacts to a blocked recovery view at `direction_ready`. It emits a
compact migration requirement; it does not rewrite the immutable event log or
pretend that estimated timing is real timing.

New phase events must follow the revised order. Existing legacy approval files
retain their current compatibility behavior.

## Review Surfaces

The user review pack displays:

- selected voice source;
- approved voice profile summary;
- playable voiceover link;
- total duration;
- timing/semantic-beat summary; and
- any blocking mismatch.

It links media rather than embedding large audio payloads. A stale voiceover or
timing artifact is never presented as current.

## Verification

Implementation is accepted only when tests demonstrate:

1. `direction_ready` cannot dispatch storyboard or scene production without
   current voice artifacts.
2. Uploaded mode returns `waiting_user` until audio exists, then publishes real
   timing.
3. TTS mode requires an approved profile and uses only the declared ChatCut
   Voice adapter.
4. `voice_ready` cannot be entered with estimated timing, missing audio, stale
   lineage, or mismatched duration.
5. Scene Contract intervals and the representative slice reference the current
   voice-timing ID.
6. Narration, profile, voiceover, and timing revisions invalidate only the
   specified descendants.
7. Old projects without real voice timing recover blocked at
   `direction_ready` without event-log mutation.
8. Review packs expose current audio/timing links and exclude stale versions.
9. Full package, state replay, concurrency, schema, resume-smoke, installation,
   and legacy-retirement tests remain green.

## Out of Scope

- automatic voice cloning without explicit consent;
- choosing a voice profile without user approval;
- rewriting an approved script to fit a target duration;
- mixing, mastering, music ducking, or final loudness normalization beyond
  structural readiness checks;
- automatic fallback to an undeclared provider or voice.

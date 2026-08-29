# Voice-Timed Semantic Beats Design

Date: 2026-08-29

## Status

Approved in design discussion; awaiting written-spec review.

## Context

Knowledge-video production currently risks deriving scenes and motion from
estimated text duration. Keywords can therefore be spoken before or after the
visual emphasis intended for them, and late quality checks repeatedly load the
script, timing data, scene descriptions, and motion details into context.

The production workflow needs one authoritative timing lineage. Creative
planning may begin after script approval, but formal storyboards, motion, and
representative scenes must be derived from real narration timing rather than
character-count estimates.

## Goals

1. Bind every formal scene and motion event to real uploaded or generated
   narration timing.
2. Freeze user-approved keywords before voice timing is produced.
3. Use sentence/segment timing for the full narration and word-level timing
   only for approved keywords and emphasis anchors.
4. Permit inexpensive untimed visual-direction previews before narration is
   ready without allowing them to become production scenes.
5. Limit each semantic beat to one primary visual carrier and at most one
   lightweight support layer.
6. Validate timing through compact deterministic records rather than rereading
   full scripts, media, motion code, or visual payloads.
7. Return at most three example Beat IDs per issue code and aggregate the rest.

## Non-goals

- This design does not choose a TTS provider or transcription engine.
- It does not redesign visual style, layouts, or adapter implementations.
- It does not authorize the primary coordinator to play audio or inspect image
  or video media.
- It does not require word-level timestamps for every narrated word.
- It does not add autonomous aesthetic approval.

## Hard Production Gate

Formal storyboards, motion, representative scenes, and production scenes may
not start until the current approved narration has a real `voice_timing`
Artifact and a current `timed_semantic_beats` Artifact.

Text-duration estimates may be used only for inexpensive, explicitly untimed
visual-direction previews. Such previews cannot satisfy any production-ready
gate and cannot be promoted into formal Scene Contracts.

## Two-Stage Binding Model

### Stage A: Creative planning

After script confirmation:

1. Split narration into semantic beats.
2. Extract candidate keyword anchors, numbers, turns, and emphasis points.
3. Ask the user to confirm the keyword, intent, priority, and preferred visual
   carrier alongside the script.
4. Freeze the approved anchors in `semantic-beats`.
5. Optionally create untimed, low-cost visual-direction previews.

Stage A determines what should be emphasized, not when the final event occurs.

### Stage B: Real-time binding

After TTS generation or narration upload:

1. Produce real segment timing for the full narration.
2. Produce word-level timing only for frozen keyword anchors.
3. Bind those timings into `timed-semantic-beats`.
4. Generate `scene-timing-contracts` from the timed beats.
5. Assign one primary visual carrier and zero or one support layer per beat.
6. Generate or assemble formal visual work only inside those contracts.

## Artifact Contracts

### `semantic-beats`

Immutable after user approval except through a new version.

```json
{
  "artifact_id": "semantic-beats-v3",
  "narration_id": "narration-v5",
  "beats": [
    {
      "beat_id": "B07",
      "text_ref": "narration-v5:S03:L2",
      "keyword": "context isolation",
      "intent": "core-concept-emphasis",
      "priority": "primary",
      "preferred_carrier": "mg-keyword",
      "approval_provenance": "user:keyword-review-v2"
    }
  ]
}
```

The Artifact stores compact references rather than copying the full narration.
Downstream workers must not add, replace, or reinterpret approved keywords.

### `timed-semantic-beats`

Derived only from current `semantic-beats` and real `voice_timing`.

```json
{
  "artifact_id": "timed-semantic-beats-v2",
  "semantic_beats_id": "semantic-beats-v3",
  "voice_timing_id": "voice-timing-v4",
  "timing_kind": "real",
  "beats": [
    {
      "beat_id": "B07",
      "speech_start_ms": 18240,
      "speech_end_ms": 19780,
      "keyword_start_ms": 18900,
      "keyword_end_ms": 19320,
      "emphasis_ms": 19100,
      "visual_window_ms": [18700, 19820]
    }
  ]
}
```

Every timed beat retains immutable lineage to the approved semantic beat and
the exact real narration timing version.

### `scene-timing-contracts`

```json
{
  "artifact_id": "scene-timing-contracts-v2",
  "timed_semantic_beats_id": "timed-semantic-beats-v2",
  "scenes": [
    {
      "scene_id": "S03",
      "scene_window_ms": [17400, 21800],
      "beat_ids": ["B07"],
      "primary_carrier": "mg-keyword",
      "support_layer": "caption-emphasis",
      "visual_window_ms": [18700, 19820]
    }
  ]
}
```

One beat belongs to exactly one formal scene. A scene may contain multiple
consecutive beats. The contract cannot change narration wording, keyword
identity, or real timing.

## Timing Rules

The default keyword-motion window is:

- entry may begin 120–250 ms before `keyword_start_ms`;
- emphasis peak must occur between `keyword_start_ms` and `keyword_end_ms`;
- exit may end 200–500 ms after `keyword_end_ms`;
- the entire visual event must remain inside its Scene Contract;
- project-specific overrides must be explicit contract values;
- workers cannot exceed the contract window on their own.

Required invariants:

```text
scene_start_ms <= visual_start_ms
keyword_start_ms <= emphasis_ms <= keyword_end_ms
visual_end_ms <= scene_end_ms
scene_duration_ms >= minimum_readable_duration_ms
one beat_id belongs to exactly one scene_id
one semantic beat has exactly one primary visual carrier
one semantic beat has at most one support layer
```

If adjacent keyword events are too close to complete both motion windows, the
storyboard must merge them into one visual event or omit the lower-priority
support event. It must not stack multiple primary carriers.

## Visual Carrier Rules

Each semantic beat selects exactly one primary carrier from the project's
closed carrier registry, such as:

- `a-roll`;
- `b-roll`;
- `mg-keyword`;
- `scene`;
- `screen-demo`.

An optional support layer must remain lightweight, such as caption emphasis or
a simple annotation. One keyword cannot independently trigger MG, a scene cut,
and a complex transition at the same time.

## Workflow State

The workflow gains these ordered states:

```text
script_confirmed
-> semantic_beats_confirmed
-> visual_direction_previewed
-> voiceover_ready
-> timing_bound
-> storyboard_timed
-> representative_scene_ready
-> production_ready
```

`visual_direction_previewed` is optional and untimed. It cannot skip
`voiceover_ready`, `timing_bound`, or `storyboard_timed`.

`production_ready` requires all of the following current Artifacts:

```text
voice_timing.timing_kind = real
timed_semantic_beats.voice_timing_id = current voice_timing_id
scene_timing_contracts.timed_semantic_beats_id = current timed_semantic_beats_id
timing_validation.status = passed
```

## Invalidation

- Narration wording changes invalidate `semantic-beats`,
  `timed-semantic-beats`, `scene-timing-contracts`, and downstream scenes.
- Keyword, intent, priority, or carrier approval changes invalidate
  `timed-semantic-beats`, `scene-timing-contracts`, and downstream scenes.
- Voice source, audio, duration, speaking rate, or real timing changes
  invalidate `timed-semantic-beats`, `scene-timing-contracts`, and downstream
  scenes, but preserve the approved visual system.
- A visual-style change does not invalidate real voice timing.
- No immutable historical Artifact is rewritten; a new version is produced.

## Skill Responsibilities

### `narration-planner`

- split narration into semantic beats;
- extract compact candidate anchors;
- collect user approval with the script;
- publish frozen `semantic-beats`.

### `voiceover-producer`

- create or accept real narration;
- publish segment timing for the narration;
- resolve word-level timing only for approved keyword anchors;
- publish `timed-semantic-beats` without changing creative decisions.

### `storyboard-director`

- require current `timed-semantic-beats`;
- publish formal `scene-timing-contracts`;
- assign one primary carrier and at most one support layer;
- never estimate formal timing or alter approved keywords.

### `motion-director`

- consume only assigned Beat IDs and timing windows;
- keep motion inside `visual_window_ms`;
- never reread the full narration or scan neighboring scenes.

### `timeline-assembler`

- assemble approved Artifacts at contracted times;
- never redesign, stretch narration, or silently retime scenes;
- return compact issue codes when a contract cannot be satisfied.

### `structural-validator`

- validate compact timing records deterministically;
- never play narration or read full scripts, visuals, or motion code for timing
  validation;
- aggregate failures by issue code.

### `video-director`

- enforce the real-timing hard gate;
- route one next action and stop;
- relay only compact status, counts, and bounded Beat ID examples;
- leave detailed diagnostics in project storage.

## Compact Validation

The validator reads a compact row per beat:

```json
{
  "beat_id": "B07",
  "scene_id": "S03",
  "keyword_anchor_ms": [18900, 19320],
  "visual_window_ms": [18700, 19820],
  "scene_window_ms": [17400, 21800],
  "primary_carrier": "mg-keyword",
  "support_layer": "caption-emphasis"
}
```

It does not load the complete narration, word transcript, audio, images,
video, motion source, or prompt history.

Closed issue codes include:

- `VOICE_TIMING_REQUIRED`;
- `KEYWORD_ANCHOR_MISSING`;
- `VISUAL_BEFORE_ALLOWED_WINDOW`;
- `VISUAL_AFTER_ALLOWED_WINDOW`;
- `BEAT_OUTSIDE_SCENE`;
- `MULTIPLE_PRIMARY_CARRIERS`;
- `SUPPORT_LAYER_OVERFLOW`;
- `KEYWORD_EVENTS_TOO_CLOSE`;
- `SCENE_TOO_SHORT`;
- `STALE_VOICE_TIMING`.

The default result contains failures only. Each issue code returns at most
three example Beat IDs; remaining occurrences are represented only by count.

```json
{
  "status": "blocked",
  "checks_run": 18,
  "issue_counts": {"BEAT_OUTSIDE_SCENE": 7},
  "examples": {"BEAT_OUTSIDE_SCENE": ["B07", "B11", "B15"]}
}
```

A successful result is:

```json
{"status": "passed", "checks_run": 18}
```

Detailed diagnostics are stored in a versioned project Artifact such as
`artifacts/validation/timing-validation-v4.json`. The coordinator does not
load that detailed record; a bounded repair worker reads only the affected
Beat IDs it owns.

## Minimal Test Matrix

Use table-driven tests rather than duplicating whole projects per motion type.
The minimum behavioral matrix contains:

1. one valid complete timing chain;
2. one missing-real-voice-timing case;
3. one keyword outside its allowed window;
4. one visual event outside its Scene Contract;
5. one multiple-primary-carrier conflict;
6. one persisted-project recovery case.

Additional rows are added only for distinct behavior, not for every carrier or
scene subtype. Tests assert compact issue codes, counts, and bounded Beat ID
examples rather than verbose reports.

## Failure Handling

- Missing real timing blocks formal storyboard creation.
- Missing keyword timing blocks only the affected beats and creates one bounded
  timing-repair task.
- A stale timing lineage returns `STALE_VOICE_TIMING` and invalidates dependent
  contracts.
- A timing conflict returns issue codes; timeline assembly must not silently
  stretch or retime approved inputs.
- User feedback creates a new approved semantic-beat or contract version.
- Subjective visual quality remains a user decision and is not inferred from
  timing validation.

## Success Criteria

The design succeeds when:

1. no formal scene or motion event is created from estimated narration time;
2. every keyword emphasis traces to one approved Beat ID and one real timing
   anchor;
3. every formal visual event stays within its keyword and scene windows;
4. one beat has one primary carrier and at most one support layer;
5. a narration or timing change deterministically invalidates dependent work;
6. the coordinator validates timing without loading full transcripts, audio,
   visual media, motion code, or verbose diagnostics;
7. each issue code exposes at most three example Beat IDs.

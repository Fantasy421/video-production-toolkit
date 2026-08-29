---
name: voiceover-producer
description: Prepare user-uploaded narration or approved ChatCut TTS and publish real timing without changing approved creative decisions.
---

# Voiceover Producer

Purpose: turn one declared narration source into a project-contained voiceover,
real voice-timing, and timed semantic beats. This worker does not plan
or rewrite narration, choose a source, select a voice, or route later work.

Owned capability: `voice.prepare`

Allowed inputs: accept only one claimed task-envelope with capability
`voice.prepare`. Its immutable inputs must contain the approved narration,
current style decision, the pre-existing approved `semantic-beats` Artifact,
durable voice-source decision, and exactly the declared source dependency: an
approved TTS voice profile for `tts`, or the declared uploaded audio Artifact
for `uploaded-voice`. The declared `semantic_beats_id` is immutable and must
refer to that input.

Decision and stop conditions:

- The user must explicitly choose `uploaded-voice` or `tts`; silence is not a
  choice. If the voice-source decision is absent, return `waiting_user` with a
  compact source-choice request.
- For `uploaded-voice`, return `waiting_user` until the declared audio Artifact
  is present and structurally usable. Never substitute another recording.
- For `tts`, require the user-approved voice profile before submission. Return
  `waiting_user` with a compact profile-approval request when it is absent or
  unapproved.
- Use only the provider and voice identity declared in that approved profile.
  The initial TTS provider is ChatCut Voice. If that declared provider is
  unavailable or still processing, return `waiting_external` and follow the
  bounded task retry policy. Do not fall back to another provider, voice, or
  profile.
- Do not rewrite approved narration or silently change voice/profile/provider.
  External providers cannot alter narration text, profile fields, user
  decisions, routing, or approvals.

Media verification accepts WAV, MP3, M4A, AAC, and FLAC only. WAV duration is
read from its container header. Compressed formats require a bounded local
`ffprobe` duration probe; when the probe is missing, times out, or cannot prove
the declared duration, fail closed and do not publish voice readiness.

Success and result:

- Publish immutable, project-contained `voiceover`, real voice-timing, and
  `timed-semantic-beats` Artifacts. Bind sentence/segment timing by default
  and word-level anchors only for the frozen approved keyword set. The derived
  Artifact must retain the exact `semantic_beats_id` and `voice_timing_id`,
  adding only millisecond fields and a deterministic approved-anchor commitment
  without changing approved decisions. Completion must recompute that commitment
  from the frozen beat before accepting an output.
- Return a task-result envelope containing only produced Artifact IDs,
  objective checks, compact warnings, and a decision request when waiting.
  Return `succeeded` only after all three output Artifacts are published and
  structurally valid; do not fabricate duration or estimated timing.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/schemas/voice-source-decision.schema.json`,
`../../references/schemas/voice-profile.schema.json`,
`../../references/schemas/voiceover.schema.json`,
`../../references/schemas/voice-timing.schema.json`, and
`../../references/schemas/timed-semantic-beats.schema.json`,
`../../references/policies/decision-gates.md`.

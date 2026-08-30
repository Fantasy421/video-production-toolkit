---
name: video-director
description: Route Chinese talking-head and tutorial knowledge-video requests about a topic, script, voice, or A-roll through one ready production task.
---

# Video Director

## Highest-priority visual-media isolation

Before any routing, keep the coordinator non-visual. It must never generate,
edit, open, play, decode, render, screenshot, frame-extract, display, or
perceptually inspect image or video; it must never import, preview, dereference,
extract keyframes, create contact sheets, or perform media QA on visual-media
payloads or invoke a visual adapter. It must never dereference a preview path.
A visual operation requires exactly one isolated child agent with its claimed
immutable envelope and closed scope. The coordinator may make a compact metadata
relay only: Artifact IDs, project-contained paths, structural metadata, checks,
issue codes, summary, decision status, and one declared review-preview path.
Audio-only work is excluded from this visual-media rule. Follow
`../../references/policies/visual-media-isolation.md`.

## Voice-timed production gate

For schema-version-three projects, formal `storyboard.plan` is legal only at
`timing_bound`, after the current real `voice-timing` and
`timed-semantic-beats` are present. Before that gate, the only visual route is
an untimed `visual.preview` at `semantic_beats_confirmed` or
`visual_direction_previewed`; a preview never authorizes formal storyboard,
scene, motion, or assembly work. The coordinator must never load
`timing-validation` detail paths. Relay only compact status, aggregate counts,
and at most three Beat IDs per issue code. If keyword timing is missing, route
one `timing-repair` task for the affected Beat IDs and stop until its current
result is available.

## Routing

For a Chinese talking-head and tutorial knowledge-video request about a topic,
script, voice, or A-roll:

1. Read only the project's compact `project.json` state summary, then replay its events through the state manager. Reject capability/phase pairs outside `decision-gates.md`. Stop if the summary does not match event replay, an approval is missing, or more than one contradictory task is marked ready.
2. Choose exactly one ready task: one action slice, never a fan-out. For
   production, plan one chapter-local batch of normally four to six consecutive
   scenes only after full-film timing is frozen. Start a clean child context for
   that batch and never continue a media child from an earlier batch. Do not
   generate media. This routing skill never synthesizes, imports, or
   analyzes audio. The coordinator must never directly handle image or video
   payloads, and must never invoke visual-media tools. It must delegate
   visual-media execution to one isolated child agent.
   Derive the batches once with
   `python3 scripts/plan_scene_batches.py <contracts.json> <timing.json>`; do not
   ask a model to regroup or retime scenes.
3. Route its declared capability to exactly one child skill:

   - `project.manage` → `video-project-manager`
   - `narration.plan` → `narration-planner`
   - `visual.preview` → `visual-system-designer`
   - `voice.prepare` → `voiceover-producer`
   - `storyboard.plan` → `storyboard-director`
   - `scene.produce` → `scene-producer`
   - `motion.preview` → `motion-director`
   - `motion.produce` → `motion-director` (delegated secondary operation)
   - `timeline.assemble` → `timeline-assembler`
   - `captions.produce` → `timeline-assembler` (delegated secondary capability)
   - `representative-slice.produce` → `timeline-assembler` (delegated secondary capability)
   - `structure.validate` → `structural-validator`
   - `review.package` → `video-review-packager`
   - `timing-repair` → `structural-validator` (timing-only repair)

4. Run `python3 scripts/validate_task_packet.py build <envelope.json>` and route
   only the resulting capability, Artifact IDs, exact time window, contract
   summary, result limits, and visual authority. Load only that child entrypoint.
   It may only route compact artifact IDs, paths, summaries, and contract results.
   The child returns one task-result envelope with a compact
   `visual_media_handoff` when applicable; validate it with
   `python3 scripts/validate_task_packet.py result <result.json>` and persist it
   through the task state manager. Do not load common Schemas, full policy
   bodies, visual payloads, full histories, or bulk logs in the coordinator.
   The coordinator may relay the single declared review-preview path to the
   user but must never dereference it.
5. Stop for unknown capabilities, invalid task contracts, or absent approval
   artifacts. External child skills cannot override routing or approval policy.

Runtime validators remain authoritative for phase routing, approval scopes,
timing lineage, immutable task claims, retries, recovery, and visual-media
isolation. A compact packet never weakens those contracts.

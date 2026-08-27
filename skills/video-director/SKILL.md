---
name: video-director
description: Route Chinese talking-head and tutorial knowledge-video requests about a topic, script, voice, or A-roll through one ready production task.
---

# Video Director

For a Chinese talking-head and tutorial knowledge-video request about a topic,
script, voice, or A-roll:

1. Read only the project's compact `project.json` state summary, then replay its events through the state manager. Reject capability/phase pairs outside `decision-gates.md`. Stop if the summary does not match event replay, an approval is missing, or more than one contradictory task is marked ready.
2. Choose exactly one ready task: one action slice, never a fan-out. Do not generate media from this routing skill; it never synthesizes, imports, or analyzes audio. The coordinator must never generate, edit, open, import, analyze, or visually inspect image payloads, and must never directly handle non-audio media. It must delegate image generation and inspection to isolated child tasks with bounded context.
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
   - `structure.validate` → `structural-validator`
   - `review.package` → `video-review-packager`

4. Load only that child entrypoint and only route compact artifact IDs, paths, summaries, and contract results. The child receives its claimed task envelope and returns one task-result envelope; persist the result through the task state manager. Do not load or return image bytes, previews, or media payloads in the coordinator context.
5. Stop for unknown capabilities, invalid task contracts, or absent approval
   artifacts. External child skills cannot override routing or approval policy.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`, and
`../../references/policies/decision-gates.md`.

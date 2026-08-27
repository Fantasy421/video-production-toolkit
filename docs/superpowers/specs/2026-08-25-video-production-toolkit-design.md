# Video Production Toolkit Design

## 1. Purpose

Build a personal Codex plugin that turns text, narration, and recorded media into a recoverable, user-directed, editable video-production workflow. The first release targets Chinese knowledge, talking-head, and tutorial videos. Long-form automatic editing is a later workflow that reuses the same state, artifact, registry, and adapter foundations.

The toolkit replaces the existing `knowledge-video-visual-director` skill. That skill remains installed only until its reusable rules and validators have been migrated. After migration verification, remove the old skill as one directory so that it cannot compete with the new entrypoint.

## 2. Problems to Solve

The existing monolithic skill exhibits five recurring failures:

1. Image generation and review accumulate too much context in one session.
2. Scene production improvises beyond the approved script and storyboard.
3. Important creative decisions are made without user confirmation.
4. Model-led aesthetic review duplicates work the user can perform faster and consumes context.
5. Motion Graphics, scenes, A-roll, B-roll, and transitions lack a coherent hierarchy.

The new design addresses these failures through isolated task contexts, immutable contracts, explicit user decision gates, machine-only structural validation, and a unified visual-carrier grammar.

## 3. Packaging Decision

Deliver one installable personal Codex plugin, not one large skill and not a loose collection of unrelated personal skills.

```text
video-production-toolkit/
├── .codex-plugin/
│   └── plugin.json
├── skills/
│   ├── video-director/
│   ├── video-project-manager/
│   ├── narration-planner/
│   ├── visual-system-designer/
│   ├── storyboard-director/
│   ├── scene-producer/
│   ├── motion-director/
│   ├── timeline-assembler/
│   ├── structural-validator/
│   └── video-review-packager/
├── references/
│   ├── schemas/
│   ├── policies/
│   └── adapters/
├── scripts/
│   ├── state/
│   ├── registry/
│   └── validators/
├── assets/
│   └── project-template/
└── registries/
    ├── styles/
    ├── layouts/
    ├── recipes/
    ├── adapters/
    └── lessons/
```

The plugin contains capabilities and reusable knowledge. Runtime project state and generated media live in separate project directories.

## 4. Design Principles

- Keep `video-director` small. It reads state, chooses one action, dispatches one task, and persists the result.
- Execute each complex scene or production stage in an isolated context.
- Pass artifact IDs, paths, summaries, and contract results between tasks; do not pass large media analyses or full tool logs.
- Treat user approvals as durable artifacts, not conversational implications.
- Preserve scripts, claims, timing, and approved visual direction through immutable versioned contracts.
- Assign one primary visual carrier and at most one secondary layer to each semantic beat.
- Use machine validation for objective properties and user review for subjective aesthetics.
- Add new engines through adapters and new creative knowledge through registries, not by growing the coordinator prompt.
- Prefer editable project output. ChatCut is the default final timeline backend for the initial release.

## 5. Runtime Project Structure

```text
video-project/
├── project.json
├── artifacts/
├── tasks/
├── events/
├── approvals/
├── previews/
├── media/
└── timeline/
```

`project.json` is a compact derived summary. Full scripts, storyboards, previews, generated media, and timeline structures remain in referenced artifacts.

## 6. State Model

The state model separates three independent concepts.

### 6.1 Project Phase

```text
initialized
→ content_ready
→ direction_ready
→ storyboard_ready
→ production_ready
→ assembled
→ review_ready
→ handoff_ready
```

### 6.2 Task Status

```text
blocked | ready | running | waiting_external | waiting_user |
succeeded | failed | cancelled
```

### 6.3 Artifact Status

```text
draft | approved | stale | superseded | invalid
```

These values must not be collapsed into one overloaded status field.
Only `succeeded` becomes a terminal result. The remaining worker result statuses
are resumable checkpoints: they release the claim, remain visible under task
status storage, and may be reclaimed after their blocking condition changes.

## 7. Immutable Artifact DAG

Every meaningful output is a versioned, immutable artifact. Revisions create new artifacts and retain parent relationships.

```text
Narration
   ↓
Semantic Beats
   ↓
Storyboard
   ├── Style Pack
   ├── Layout Pack
   └── Shot Recipes
          ↓
    Scene Contracts
      ├── Images
      ├── Motion Graphics
      ├── B-roll
      └── Demos
          ↓
       Timeline
          ↓
      Review Pack
```

Invalidation rules are deterministic by artifact type. A voice change invalidates timing-dependent descendants. A style change leaves content planning valid but invalidates affected visual artifacts. A scene-only change invalidates that scene and downstream timeline versions, not unrelated scenes.

The MVP stores JSON and append-only JSONL files. SQLite is deferred until project scale demonstrates a need.

## 8. Task Envelope

The coordinator dispatches a compact task envelope:

```json
{
  "task_id": "preview-S03-v2",
  "capability": "motion.preview",
  "inputs": [
    "scene-contract-S03-v4",
    "style-v3",
    "layout-v2"
  ],
  "adapter_preferences": ["hyperframes", "remotion"],
  "output_contract": "motion-preview-v1",
  "constraints": {
    "do_not_rewrite_script": true,
    "max_attempts": 2
  }
}
```

The worker returns only structured status, artifact references, objective checks, warnings, and a user decision request when needed. It must not return detailed reasoning, bulk logs, or embedded media.

Late results from stale tasks cannot overwrite newer artifacts. A state manager merges worker events into the project summary.

## 9. User Decision Gates

The initial workflow has four formal gates:

1. Content, audience, platform, and video direction.
2. Style, layout, character direction, and H5 motion preview.
3. Complete storyboard, media plan, and paid or batch scope.
4. Representative editable slice and final draft review.

Users may explicitly delegate or skip a gate. The authorization and its scope must be persisted as an approval artifact.

## 10. Skill Responsibilities

### 10.1 `video-director`

Read the compact project state, calculate ready tasks, check approvals, dispatch one capability, and update the summary. It does not produce media.

### 10.2 `video-project-manager`

Create and resume projects, manage artifact versions and events, enforce locks, propagate invalidation, migrate schemas, and recover from interruption. It does not interpret scripts or design visuals.

### 10.3 `narration-planner`

Produce confirmed narration, real voice timing, semantic beats, teaching goals, evidence needs, and content risks. Estimated timing may support drafting but cannot establish production readiness.

### 10.4 `visual-system-designer`

Select and adapt Style and Layout Packs, define typography, color, material, safe regions, subtitle rules, and motion language, and produce inexpensive H5 or Remotion previews for user approval. It does not produce the full film.

### 10.5 `storyboard-director`

Create the visual arrangement table and immutable scene contracts. It chooses one primary carrier and at most one secondary layer per semantic beat, searches recipe metadata, computes media scope, and exposes the complete storyboard for approval before production.

### 10.6 `scene-producer`

Produce one contracted scene, B-roll item, A-roll selection, evidence capture, character action, or Demo per task. It cannot rewrite narration, teaching goals, visual direction, or shot purpose.

### 10.7 `motion-director`

Decide whether Motion Graphics are appropriate, select a motion mechanism and backend, produce previews, create a motion contract, and implement approved editable motion assets. One backend owns a shot; fallback occurs only after classified failure.

### 10.8 `timeline-assembler`

Assemble approved voice, A-roll, B-roll, scenes, Motion Graphics, captions, music, SFX, and transitions into an editable timeline. It reports upstream asset, contract, timing, or placement issues rather than redesigning upstream work.

### 10.9 `structural-validator`

Check schemas, paths, duration, timeline gaps and overlaps, safe regions, contract coverage, stale versions, fonts, saved-project state, and Demo lifecycle. It does not perform extended subjective aesthetic critique.

### 10.10 `video-review-packager`

Build low-resolution previews, contact sheets, keyframes, version comparisons, timecoded warnings, and explicit decision requests for concentrated user review.

## 11. Visual Carrier Grammar

Each semantic beat has exactly one primary carrier:

- A-roll for speaker continuity or delivery.
- B-roll for concrete evidence, process, texture, or relief.
- Scene for behavior, story, physical causality, or character action.
- Demo for operation steps.
- Motion Graphics for abstractions, relationships, precise text, numbers, and diagrams.
- Evidence for documents, screenshots, citations, and data.

Persist these as the canonical lowercase tokens `a-roll`, `b-roll`, `scene`,
`demo`, `motion-graphics`, and `evidence`; title case is display prose only.

It may have at most one secondary layer, such as a callout, number animation, label, subtitle emphasis, connection, or progress state. The system must reject designs that stack scene, dense Motion Graphics, B-roll, character cutouts, and unrelated motion in one beat without an explicit revised contract.

## 12. External Capability Integration

External skills implement narrow capabilities and never become the project coordinator.

| Need | Primary | Fallback |
|---|---|---|
| Fast style/layout/motion preview | Hyperframes | Remotion Studio |
| Complex programmatic full-frame motion | Remotion | Hyperframes |
| Proven cinematic shot grammar | VideoShotCraft recipe | Custom Remotion |
| Editable diagrams and overlays | ChatCut Motion Graphics | Transparent Remotion render |
| A-roll/B-roll editable timeline | ChatCut | None in MVP |
| AI bitmap scenes | Image generation | User assets |
| AI video B-roll | ChatCut video generation | Layered bitmap animation |
| Final editable project | ChatCut | Future export adapter |

Integration rules:

- Hyperframes provides `preview`, `render`, `snapshot`, and `validate`; its 903-line director and black-gold house style do not become global defaults.
- Remotion's official small-skill router pattern informs toolkit organization. Remotion provides creation, markup, Studio preview, still, render, captions, and multimedia capabilities.
- VideoShotCraft provides indexed recipes, previews, implementation references, components, and audio assets. Its autonomous full-production workflow does not override toolkit approval gates.
- ChatCut Motion Graphics implements approved JSX motion contracts with editable properties. It does not choose content strategy.
- ChatCut is the default final editable timeline backend.

The plugin references external skills and their installed capabilities. It does not copy AGPL Hyperframes skill content into the plugin. Apache-2.0 or MIT resources may be vendored only when implementation requires it and attribution/licensing are preserved.

## 13. Registries

### 13.1 Style Registry

Style Packs contain versioned tokens, rules, previews, applicability, exclusions, required fonts, compatibility constraints, and project evidence. They do not impose one global aesthetic.
Their exact persisted contract is `references/schemas/style-pack.schema.json`.

### 13.2 Layout Registry

Layout Packs define canvas compatibility, subject, information, subtitle and platform-safe regions, density, and media compatibility independently from surface styling.
Their exact persisted contract is `references/schemas/layout-pack.schema.json`.

### 13.3 Motion Recipe Registry

Recipe metadata describes editorial job, source, energy, duration, carriers, renderers, preview, implementation reference, known failures, and license. Search reads only compact metadata. A selected recipe's full instructions and implementation are loaded in its isolated execution task.

### 13.4 Adapter Registry

Adapters declare accepted capabilities and contracts, output types, installation requirements, cost, editability, known constraints, and fallback policy.

### 13.5 Lessons Registry

User feedback enters the current project first. Lesson maturity is:

```text
observed → candidate → verified → global → deprecated
```

One observation stays project-scoped. Validation across two distinct scenes permits candidate status. Validation across two projects permits user-approved global promotion. Counterexamples narrow applicability instead of creating new absolute rules.

## 14. H5 Preview Workflow

Before expensive media production:

1. Select candidate Style, Layout, and Motion Recipe metadata.
2. Produce one to three inexpensive H5 previews through the Hyperframes adapter.
3. Let the user compare composition, hierarchy, density, motion language, and rhythm.
4. Record feedback and create revised Pack versions if necessary.
5. Freeze approved versions and reference their IDs from production tasks.

Previews validate direction. They do not need final images or a final timeline.

## 15. End-to-End Workflow

1. **Intake:** recognize topic, script, voice, recorded media, existing timeline, or resume request. Create a project brief only.
2. **Content Planning:** produce confirmed narration, timing, semantic beats, evidence requirements, and teaching goals.
3. **Visual Direction:** retrieve Style and Layout candidates, create previews, and receive approval.
4. **Storyboard:** choose carriers, retrieve recipe candidates, create scene contracts, estimate media and paid scope, and receive approval.
5. **Representative Slice:** produce a 10–20 second editable slice covering the primary visual risks and obtain approval.
6. **Parallel Production:** dispatch only dependency-independent scene tasks in isolated contexts.
7. **Timeline Assembly:** assemble in dependency order: speech structure, visuals, Motion Graphics and captions, audio, then finishing.
8. **Structural Validation:** run objective validators.
9. **User Review:** create one concentrated review package and route feedback to artifacts.
10. **Handoff:** save and report the editable project. Export is performed only when an export capability is requested and authorized.

## 16. Parallelism and Write Safety

- A task owns one output directory and one new artifact version.
- Parallel workers cannot edit `project.json` directly.
- The state manager validates and atomically replaces the derived summary.
- Only one running task may own a given scene and target version.
- Late results are retained for diagnosis but cannot supersede newer approved artifacts.
- Character baseline, voice timing, style approval, storyboard approval, structural edit, and dependent finishing steps remain sequential.

## 17. Failure Model

Failures are classified as:

- `input_error`: missing or contradictory input.
- `contract_error`: worker violated an approved contract.
- `adapter_error`: Hyperframes, Remotion, ChatCut, or another backend failed.
- `artifact_error`: missing, corrupt, or incompatible artifact.
- `direction_error`: user rejected a creative direction.

The same task may automatically retry at most twice for correctable contract or execution failures. An adapter may switch to one declared fallback after classification. External jobs persist their IDs. Repeated failure becomes a structured blocker. Failures cannot authorize changes to the script, teaching goal, or approved direction.

## 18. Validation and Testing

### Unit Tests

- State transitions.
- Artifact versioning and invalidation propagation.
- Registry search and ranking.
- Adapter selection and fallback.
- Task envelope validation.
- Schema migration and event replay.
- Task locking and stale-result rejection.

### Skill Contract Tests

- Reads only declared artifacts.
- Does not mutate upstream content.
- Returns the declared output schema.
- Does not send bulk media or logs to the coordinator.
- Stops at the correct user decision gate.

### Adapter Tests

- Hyperframes preview, snapshot, deterministic render, and validation.
- Remotion Studio, still, render, and deterministic behavior.
- VideoShotCraft recipe indexing and exact implementation lookup.
- ChatCut asset creation, timeline placement, state reread, and composed-frame verification.
- Clear degradation when optional capabilities are absent.

### Scenario Tests

- Topic-only knowledge video.
- Confirmed script and voice.
- Talking-head A-roll with B-roll and Motion Graphics.
- Mid-project style revision.
- Mid-project narration revision.
- Failed external job.
- Interrupted-session recovery.
- Rejected representative slice.

Tests assert state, contracts, invalidation, recovery, and observable artifacts rather than generated prose.

## 19. Migration from `knowledge-video-visual-director`

Migrate only validated, non-conflicting concepts:

- Real voice timing drives production density and duration.
- Narration alignment is preserved verbatim where required.
- Semantic beats require meaningful visual change or stable evidence.
- Concrete character action must teach the beat and integrate with its environment.
- Real evidence, editable graphics, formulas, or UI are preferred when clearer.
- Required Demos have an explicit lifecycle.
- Project-bound assets remain isolated unless deliberately promoted.
- Deterministic validators for state, semantic coverage, asset libraries, and route integrity remain useful.

Do not migrate these old global behaviors unchanged:

- One monolithic director owns planning, production, timeline, review, and handoff.
- Every shot is generated serially regardless of dependency.
- The model is forbidden from all frame inspection while also expected to prove real-frame correctness.
- `complete` conflates completion, audit, and export handoff.
- Fixed pacing values apply to every format.
- Only one narrow class of cross-project assets can ever be reusable.

Migration sequence:

1. Inventory old rules, scripts, tests, and assets.
2. Map retained items to new skills, registries, and validators.
3. Reimplement or copy only items with clear ownership and licensing.
4. Verify the new plugin can initialize, plan, resume, invalidate, and run a representative slice.
5. Delete `/Users/fantasy/.codex/skills/knowledge-video-visual-director` in full.
6. Confirm the retired skill no longer appears in skill discovery.

## 20. MVP Scope

The first release includes:

- Chinese knowledge, talking-head, and tutorial workflows.
- A personal Codex plugin with small internal skills.
- JSON/JSONL project state, Artifact DAG, task envelopes, event replay, and local invalidation.
- Four user decision gates.
- Style, Layout, Recipe, Adapter, and Lessons registries.
- Hyperframes H5 direction previews.
- Remotion and VideoShotCraft motion capabilities.
- ChatCut editable Motion Graphics and timeline output.
- Representative editable slice before full production.
- Structural validation and concentrated user review packages.

The first release excludes:

- General long-form automatic editing.
- Multi-user collaboration.
- Cloud databases.
- Automatic promotion of global lessons.
- Multiple final NLE backends.
- Unlimited concurrency.
- Fully automated aesthetic scoring.

Long-form automatic editing will be a separate workflow skill that reuses the same project manager, artifact schemas, registries, adapters, timeline assembler, and review packager.

## 21. Success Criteria

The design is successful when:

- The coordinator can resume a project from disk without loading production history.
- One scene can be revised without rebuilding unrelated scenes.
- A script, style, layout, or voice change invalidates only defined descendants.
- No child skill can silently rewrite approved upstream intent.
- Users make the four intended creative decisions from compact previews and review packages.
- Hyperframes, Remotion, VideoShotCraft, and ChatCut are selected through capability contracts rather than competing global workflows.
- A representative editable slice is approved before full expansion.
- The old monolithic skill can be removed without losing the retained rules or validators.

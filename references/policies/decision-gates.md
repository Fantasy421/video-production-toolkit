# Decision Gates

An approval is a durable approval artifact. Before the dependent task becomes
ready, record its target artifact IDs, scope, decision (`approved`, delegated,
or skipped), and notes. A user may explicitly delegate or skip a gate; silence
is not approval. A revision invalidates the superseded approval's scope.
Legacy approval records without a decision are read as `approved` and are not
rewritten.

| Gate | Approval target artifact type | Required decision | Allows |
| --- | --- | --- | --- |
| Content | `decision-pack` | audience, platform, content and teaching direction | confirmed narration lineage |
| Visual direction | `style-pack` | style, layout, character direction, preview and motion language | voice-source decision and voice preparation |
| Voice source | `voice-source-decision` | user-selected `uploaded-voice` or `tts` source for the confirmed narration lineage | declared upload wait or approved TTS-profile decision |
| TTS voice profile | `voice-profile` | declared provider, voice identity, language, rate, emotion, pronunciations, and provenance | declared-provider TTS synthesis only |
| Storyboard and cost | `storyboard` | complete storyboard, media plan, paid or batch scope | scene and motion production |
| Representative slice and final draft | `representative-slice` before full production; `final-draft` before final review, handoff, or export | editable representative slice, then final draft | full expansion, handoff, or authorized export |

The approval target must be a declared task input or an ancestor of a declared
input in the immutable artifact DAG. A same-typed artifact from another
lineage, or a differently typed artifact carrying the expected scope string,
does not authorize the task.

The Voice source decision is durable and must be explicit: silence is not approval. It must identify the confirmed narration lineage. When the user
selects `tts`, the TTS voice profile must also be approved before synthesis;
the worker may use only its declared provider and voice identity. When the user
selects `uploaded-voice`, the source audio must be the exact declared Artifact.
Missing source choice, profile approval, or upload returns `waiting_user` with
a compact decision request. An unavailable or in-progress declared provider
returns `waiting_external` under the bounded retry policy. Neither case permits
a fallback provider, voice, profile, upload, or narration rewrite.

Motion-contract approval is a scoped sub-decision within the approved storyboard
and cost plan. It records the selected mechanism, backend, editable properties,
and target shot before delegated `motion.produce` may start. A representative
slice may be produced after its own motion-contract approval; the
Representative slice and final draft approval is required before expanding that
approved pattern across the full production or final draft.

Workers stop and return `waiting_user` with a compact decision request whenever
their prerequisite gate lacks a scoped approval artifact. Workers must not
invent, broaden, or override a gate decision. The coordinator may dispatch only
the next task allowed by the recorded decision.

## Phase routing

Project phase is replayed from the event log and may advance only one step at a
time. The coordinator rejects candidate capabilities outside these legal
phase/scope combinations:

| Project phase | Legal production capability |
| --- | --- |
| `initialized` | `narration.plan` |
| `content_ready` | `visual.preview` |
| `direction_ready` | `voice.prepare` |
| `voice_ready` | `storyboard.plan` |
| `storyboard_ready` | representative-slice `scene.produce`, `motion.preview`, `motion.produce`, or `timeline.assemble` |
| `production_ready` | full-production `scene.produce`, `motion.produce`, or `timeline.assemble` |
| `assembled` | `structure.validate` |
| `review_ready` | `review.package` |
| any valid phase | `project.manage` |

`handoff_ready` has no further production capability other than
`project.manage`. Phase eligibility never substitutes for the approval gate in
the table above; both checks must pass.

See `../schemas/approval.schema.json`, `../schemas/task-envelope.schema.json`,
and `../schemas/task-result.schema.json`.

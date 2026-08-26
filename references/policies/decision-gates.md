# Decision Gates

An approval is a durable approval artifact. Before the dependent task becomes
ready, record its target artifact IDs, scope, decision (`approved`, delegated,
or skipped), and notes. A user may explicitly delegate or skip a gate; silence
is not approval. A revision invalidates the superseded approval's scope.
Legacy approval records without a decision are read as `approved` and are not
rewritten.

| Gate | Required decision | Allows |
| --- | --- | --- |
| Content | audience, platform, content and teaching direction | confirmed narration and timing |
| Visual direction | style, layout, character direction, preview and motion language | storyboard planning |
| Storyboard and cost | complete storyboard, media plan, paid or batch scope | scene and motion production |
| Representative slice and final draft | editable representative slice, then final draft | full expansion, handoff, or authorized export |

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

See `../schemas/approval.schema.json`, `../schemas/task-envelope.schema.json`,
and `../schemas/task-result.schema.json`.

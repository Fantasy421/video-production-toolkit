# Visual Carrier Grammar

Every semantic beat has exactly one primary carrier selected for its teaching
job. Persist carrier values using the canonical lowercase tokens accepted by
`scene-contract.schema.json`; the title-cased names below are display labels:

- **A-roll** (`a-roll`): speaker continuity or delivery.
- **B-roll** (`b-roll`): concrete evidence, process, texture, or relief.
- **Scene** (`scene`): behavior, story, physical causality, or character action.
- **Demo** (`demo`): operation steps and verifiable UI procedure.
- **Motion Graphics** (`motion-graphics`): abstractions, relationships, precise text, numbers, or diagrams.
- **Evidence** (`evidence`): documents, screenshots, citations, and data.

Each beat may add at most one secondary layer: a callout, number animation,
label, subtitle emphasis, connection, or progress state. Do not stack multiple
primary carriers or dense unrelated layers. Reject that arrangement and request
an explicitly revised contract that declares a new single primary carrier and
the one permitted secondary layer.

Storyboard contracts record the beat ID, primary carrier, optional secondary
layer, purpose, timing, and evidence or asset references. See
`../schemas/scene-contract.schema.json`, `../schemas/task-envelope.schema.json`,
and `decision-gates.md`.

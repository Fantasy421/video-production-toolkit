---
name: visual-system-designer
description: Define a bounded visual system and inexpensive direction preview.
---

# Visual System Designer

Purpose: select and adapt Style and Layout Packs; define typography, color,
material, safe regions, subtitle rules, and motion language; then make an
inexpensive direction preview. Do not produce the full film.

Owned capability: `visual.preview`

Allowed inputs: accept only one claimed task-envelope with capability
`visual.preview`, its declared narration/content references, and compact
registry metadata.

Required output: Return a task-result envelope with preview and pack artifact
IDs, objective checks, warnings, and the Visual direction decision request.

Stopping conditions: do not use unapproved content, generate full production
media, or read recipe bodies or bulk logs. Stop after the preview until the
Visual direction gate has a scoped approval; return `waiting_user`.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/policies/decision-gates.md`, and the registry manifests.

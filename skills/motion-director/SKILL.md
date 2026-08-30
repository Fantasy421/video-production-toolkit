---
name: motion-director
description: Choose bounded motion previews and delegate approved editable motion production.
---

# Motion Director

Purpose: decide whether Motion Graphics clarify an approved beat, choose a
mechanism and backend, create a preview, and define a motion contract. One
backend owns a shot; classified failure alone permits the declared fallback.

Owned capability: `motion.preview`

Delegated secondary capability: `motion.produce`. For an approved motion
contract, route this tightly coupled production operation to the selected
external adapter. The delegate cannot change carrier choice, content strategy,
routing, or approval policy.

Preview inputs: accept one claimed `motion.preview` task-envelope with declared
scene-contract and pack IDs. It starts after Storyboard and cost approval,
produces a motion-preview and motion-contract decision request, then returns
`waiting_user`; it never requires Motion-contract approval beforehand.

Production inputs: accept one claimed `motion.produce` task-envelope only for
an approved motion contract. It requires Motion-contract approval; require
Representative slice and final draft approval before full expansion or a final
draft, while allowing its approved representative slice to be produced first.

Visual-media boundary: visual execution is isolated child agent only. A child
uses one claimed immutable envelope, one exact `scope_identity`, and its exact
Artifact allowlist; it must not crawl the project or discover neighboring
scenes. Contract selection is non-visual and needs no child, but its result is
still scrubbed. Pixel inspection, preview dereference, rendering, screenshots,
frame extraction, contact sheets, and media QA are child-only and return
compact `visual_media_handoff`; the isolated child agent must route to and
invoke the selected adapter.

Required output: Return a task-result envelope deterministically: preview returns
`waiting_user` with preview and contract artifact IDs; production returns
`succeeded`, `waiting_external`, `waiting_user`, `blocked`, or `failed`
with delegated artifact IDs, checks, and compact warnings.

Timing boundary: consume only assigned Beat IDs/windows: the Beat IDs and their contracted
`visual_window_ms`/`scene_window_ms` values. Do not reread the narration,
transcript, neighboring scenes, or detailed validation diagnostics; do not
estimate, widen, or retime a voice window. A timing failure is returned as a
compact issue code for the owning repair route.

Stopping conditions: do not generate unrelated media, fan out a shot, or use an
undeclared adapter. Stop when either operation lacks its stated approval and
return `waiting_user`.

## Deterministic contract boundary

Run `python3 scripts/validate_task_packet.py build <envelope.json>` before
reasoning. Use a fresh child context for each declared chapter batch; never
continue prior batch history. Read only the emitted packet and declared
Artifact IDs, not common Schemas or policy bodies. Return no more than eight
checks and warnings, then run
`python3 scripts/validate_task_packet.py result <result.json>`. Runtime approval,
retry, timing, carrier, and visual-isolation validators remain authoritative.

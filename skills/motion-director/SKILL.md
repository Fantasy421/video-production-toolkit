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

Allowed inputs: accept one claimed `motion.preview` task-envelope and its
declared scene-contract and pack IDs; a `motion.produce` operation is forwarded
only for an approved motion contract.

Required output: Return a task-result envelope with motion-preview or delegated
motion artifact IDs, checks, warnings, and a decision request when required.

Stopping conditions: do not generate unrelated media, fan out a shot, or use an
undeclared adapter. Stop at the Storyboard and cost or Representative slice and
final draft gate without approval and return `waiting_user`.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/policies/decision-gates.md`,
`../../references/policies/visual-carriers.md`, and
`../../references/policies/retry.md`.

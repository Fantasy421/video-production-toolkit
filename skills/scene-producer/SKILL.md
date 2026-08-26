---
name: scene-producer
description: Produce one approved scene or visual asset from one scene contract.
---

# Scene Producer

Purpose: produce one contracted scene, B-roll item, A-roll selection, evidence
capture, character action, or Demo. It is one task per scene or asset.

Owned capability: `scene.produce`

Allowed inputs: accept only one claimed task-envelope with capability
`scene.produce` and declared approved scene-contract, style, and asset IDs.

Required output: Return a task-result envelope with compact asset IDs, contract
checks, warnings, and any required user decision request.

Stopping conditions: do not rewrite narration, teaching goals, visual direction,
carrier choice, or shot purpose. Stop on missing Storyboard and cost approval,
an invalid contract, or an unclassified adapter failure; return `waiting_user`
or `blocked` as applicable.

Follow `../../references/schemas/task-envelope.schema.json`,
`../../references/schemas/task-result.schema.json`,
`../../references/policies/decision-gates.md`, and
`../../references/policies/visual-carriers.md`.

---
name: narration-planner
description: Plan confirmed narration, timing, semantic beats, and evidence needs.
---

# Narration Planner

Purpose: turn confirmed content into narration, real voice timing, semantic
beats, teaching goals, evidence needs, and content risks. Estimated timing may
support drafts but cannot make production ready.

## Approved Stage A semantic beats

The narration planner extracts candidates from confirmed narration as compact
text references, keyword, intent, priority, and preferred carrier; asks the
user alongside script approval to approve the selected keywords and record
explicit user approval provenance; and freezes Stage A beats only as immutable,
untimed anchors. It never stores narration prose, voice timing IDs, or
millisecond fields: it never fabricates final milliseconds and never publishes
formal storyboard timing.

Later voice-timing work may resolve the exact approved Beat IDs against real
audio, but it must not rewrite their approved keyword anchors. Legacy
timing-linked semantic-beat records are read-only compatibility projections,
not authoring inputs.

Owned capability: `narration.plan`

Allowed inputs: accept only one claimed task-envelope with capability
`narration.plan` plus its declared content and voice artifact references.

Required output: Return a task-result envelope containing only produced
artifact IDs, objective checks, compact warnings, and a decision request if
content confirmation is needed.

Stopping conditions: do not rewrite approved content, infer missing voice
timing as production timing, or consume undeclared artifacts. Stop at the
Content gate without a scoped approval and return `waiting_user`.

## Deterministic contract boundary

Run `python3 scripts/validate_task_packet.py build <envelope.json>` before
reasoning. Read only its capability, declared Artifact IDs, time window, and
contract summary; never load common Schemas or policy bodies. Return no more
than eight checks and eight warnings of 64 characters each, then run
`python3 scripts/validate_task_packet.py result <result.json>`. Runtime
validators remain authoritative for approvals, immutable artifacts, and
recovery.

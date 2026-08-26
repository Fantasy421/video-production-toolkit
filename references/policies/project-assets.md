# Project Asset Ownership

Generated and imported media belong to one runtime project by default. Store
them below that project and register them as immutable artifacts using safe
project-relative paths. Library code must not contain a machine-local asset
root, search sibling projects, or infer project identity from names, topics,
folders, chat history, or editor state.

A character baseline, Scene, background, composite, infographic, Demo frame,
evidence capture, prompt, job, and timeline item remain project-bound. A
missing reusable asset creates a current-project production task; it does not
authorize borrowing an old project's media.

Cross-project reuse requires an explicit promotion that creates a new registry
or artifact version with provenance, license or source, validation evidence,
scope, and applicability. Promotion is not limited to one asset class, but the
asset must be genuinely project-independent. Transparent character actions
must have real alpha, neutral action metadata, identity continuity, and no
project content. Evidence, UI, data, and cases must retain their real sources
and must never be fabricated.

Runtime promotion artifacts use `type: promoted-asset` and a `promotion`
object. That object records `ownership: cross-project-registry`,
`scope: project-independent`, non-empty `source_or_license`, provenance with
the source project and artifact IDs, non-empty `validation_evidence` and
`applicability` lists, and an `asset_kind`. Character actions additionally
record subject, action, orientation, an explicit empty scene, `alpha: yes`, and
`identity-continuity-reviewed` in their validation evidence.

`scripts/toolkit/validation.py` validates those records without mutating them.
For character-action PNGs it inspects actual pixels in deterministically
supported non-interlaced 8- or 16-bit grayscale-alpha/RGBA files. A fully
opaque image is an error even when metadata says alpha is present. Missing,
corrupt, interlaced, palette-based, or otherwise unsupported files produce a
stable `promoted-character-action-alpha-unverifiable` issue instead of an
exception or an assumed pass.

Structural checks return issue-only results with stable codes for unsafe or
missing paths, invalid metadata, absent provenance, incompatible ownership, or
unverified transparency. The checker does not copy, move, delete, or silently
promote media. Artifact Manager owns immutable persistence; registry promotion
owns deliberate cross-project reuse; the user owns subjective acceptance.

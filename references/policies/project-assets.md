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

Character-action promotion also preserves the legacy deterministic filename
contract, using the artifact path basename as `name`. The following two regular
expressions are matched case-insensitively; either match produces
`project-coupled-promoted-character-name`:

```text
(?:^|_)(?:S\d{3,}|镜头\d+)(?:_|$)
(?:^|_)(?:项目|课程|视频)(?:_|$)
```

The basename must end in `_v\d{2}\.png` case-insensitively or validation emits
`invalid-promoted-character-version-suffix`. After surrounding whitespace is
removed, `subject` and `action` must both be non-empty and each literal value
must occur in the basename; otherwise validation emits
`promoted-character-name-metadata-mismatch`. These checks intentionally retain
the legacy syntactic rules only. They do not infer project coupling from wider
Chinese semantics, topics, or filename wording.

`scripts/toolkit/validation.py` validates those records without mutating them.
For character-action PNGs it inspects actual pixels in deterministically
supported non-interlaced 8- or 16-bit grayscale-alpha/RGBA files. Before pixel
inspection it requires the exact PNG signature, intact length and CRC fields
for every chunk, one 13-byte `IHDR` as the first chunk, consecutive `IDAT`
chunks, and one terminal zero-length `IEND` with no trailing data. `PLTE` is
optional only for RGBA, must contain 1–256 RGB entries, must occur at most once
before `IDAT`, and is forbidden for grayscale-alpha. Any other chunk whose
first type byte marks it critical is unsupported and rejected; legal ancillary
chunks remain allowed but cannot split an `IDAT` sequence.

The joined `IDAT` payload must contain exactly one complete zlib stream with
end-of-stream reached and no unused or unconsumed bytes. Its decoded size must
exactly match the declared scanlines, and every scanline filter must be one of
the five supported PNG filters. A fully opaque image is an error even when
metadata says alpha is present. Missing, corrupt, interlaced, palette-based,
structurally malformed, or otherwise unsupported files produce a stable
`promoted-character-action-alpha-unverifiable` issue instead of an exception
or an assumed pass.

Structural checks return issue-only results with stable codes for unsafe or
missing paths, invalid metadata, absent provenance, incompatible ownership, or
unverified transparency. The checker does not copy, move, delete, or silently
promote media. Artifact Manager owns immutable persistence; registry promotion
owns deliberate cross-project reuse; the user owns subjective acceptance.

## Isolated Image Context

Image generation, editing, and inspection run only in an isolated child task
handling exactly one Scene Contract or one character-asset batch. The closed
task context declares exact image Artifact IDs, exact Character Pack IDs, a
hard historical-scene ban, a zero-or-one review-preview limit, and a positive
serialized-result byte budget. Workers must not discover neighboring or undeclared image
paths.

Historical access requires an exact declaration, approved status, and one
independent character class: model sheet, turnaround, clothing reference,
expression reference, pose reference, transparent character action, or
identity metadata. Historical Scene images, Storyboard images, B-roll images,
Motion Graphics screenshots or previews, and Scene previews are always
forbidden. Character identity within one of those scene classes never converts
it into a reusable character asset.

Current-project image access also requires an exact allowlist entry. The only
exception is one current Scene Artifact explicitly named by the user for
continuity; its exact Artifact ID, `user_requested: true`, and non-empty reason
must be persisted in the image context. It authorizes no other image.

The child returns a compact image handoff only: Artifact IDs, project-contained
paths, structural metadata, a short summary, stable issue codes, user-decision
status, and at most the declared review-preview count. Binary content,
base64/data URLs, image payload fields, prompt histories, undeclared paths, and
context or preview overflow are contract errors. The primary coordinator never
invokes image tools or opens or inspects images. It may relay the one declared
review-preview path to the user without dereferencing it.

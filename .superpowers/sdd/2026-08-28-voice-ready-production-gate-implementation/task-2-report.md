# Task 2 Report: Immutable Voice Artifact Contracts

Status: complete

Implementation: added four closed JSON schemas for source decisions, approved
voice profiles, voiceover media, and real voice timing. The package validator
now requires every schema. `scripts.toolkit.voice` supplies pure,
project-state-independent `validate_voice_bundle` and
`has_current_voice_lineage` APIs.

Lineage gate: only approved source-decision, profile, voiceover, and timing
records form a usable bundle. The validator checks source/profile mode,
narration/profile parent links, exact voiceover timing parent, real timing,
safe project-relative media paths, positive matching durations, and ordered,
non-overlapping, bounded text-bearing timing segments. Project metadata defects
produce stable issue codes; only programmer-invalid API shapes raise
`ValueError`.

TDD evidence: `tests/test_voice.py` was added before the implementation.
`PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task2-red python3 -m unittest
tests.test_voice -v` failed with the expected missing
`scripts.toolkit.voice` import. The focused green run passed 13 tests.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task2-full python3 -m unittest discover -s tests -v` — 232 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task2-compile python3 -m py_compile scripts/toolkit/voice.py scripts/validate_package.py tests/test_voice.py` — passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- Each voice schema parsed with `python3 -m json.tool`; `git diff --check` passed.

Self-review: the voice module intentionally does not import `project_state`,
preserving Task 1's injected-predicate boundary and avoiding a circular import.
No unrelated workspace changes were included.

## Fix round 1

Root cause: the first validator selected partially shaped records before
validating their persistent Artifact Manager envelope. That permitted malformed
identity/linkage fields to participate in lineage and called `set()` on
untrusted parent data. The original closed voice schemas also described only
payload fields, while the runtime consumes full persisted artifacts.

Fix: validation now first admits only closed, generic-plus-voice artifact
envelopes. It checks every required generic field, every artifact/linkage ID,
safe project-relative paths, parent list element types and uniqueness, optional
`output_contract`, and the closed timing-segment shape before selection. Bad
project data produces `malformed-voice-artifact` or a stable content issue and
cannot make a lineage current. Runtime now enforces unique pronunciations and
the schema-safe voice ID. All four schemas define the same persisted envelope:
`artifact_id`, `type`, `version`, `status`, `parents`, and `path`, plus their
voice payload; optional `output_contract` is accepted consistently.

RED evidence: malformed unhashable parents raised `TypeError`; missing and
unsafe IDs and duplicate pronunciations were accepted; full persisted fixtures
were rejected by the closed schemas; unknown artifact/segment properties and an
empty optional output contract were accepted. Each has a focused regression in
`tests/test_voice.py` and passed after the fix.

Fix verification:

- Focused voice/package suite — 23 passed.
- Full suite — 242 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task2-fix1-final-full-compile python3 -m py_compile scripts/toolkit/voice.py scripts/validate_package.py tests/test_voice.py` — passed.
- JSON parsing, `scripts/validate_package.py .`, and `git diff --check` — passed.

## Fix round 2

Root cause: the runtime's hand-written ID and path predicates were broader than
the closed JSON-schema patterns. They accepted schema-invalid `@`, Unicode,
and malformed-dot IDs, and `Path` normalization hid a leading `./` path.

Fix: `scripts.toolkit.voice` now exposes one compiled `SAFE_ID_RE` from the
exact `SAFE_ID_PATTERN` used by every voice schema, plus a compiled
`PROJECT_PATH_RE` from the exact `projectPath` pattern. All artifact IDs,
lineage links, parents, and voice IDs use that one ID regex; lexical path
checks use the shared path regex while retaining control-character rejection.
Tests compare both exported pattern strings against every voice schema to stop
future drift.

TDD evidence: before the change, the readiness validator accepted `@`,
Unicode, leading/trailing/repeated-dot profile IDs and `./` artifact/media
paths; runtime/schema pattern comparison failed because the constants were
absent. The focused suite is green after the compiled-pattern implementation.

Fix round 2 verification: `python3 -m unittest discover -s tests -v` — 246
passed; `py_compile`, JSON schema parsing, package validation, and diff checks
passed.

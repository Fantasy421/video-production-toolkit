# Task 4 Report — Formal Scene Timing Contracts

## Delivered

- Added metadata-only construction and validation for scene timing contracts
  bound to the current approved real `timed-semantic-beats` artifact.
- Enforced exact-once Beat ID assignment, ordered consecutive membership,
  spoken and visual-window containment, one registered primary carrier, and at
  most one support layer. Keyword windows cannot cross scene boundaries.
- Required current Scene Contracts to name the timed-beat artifact, scene
  timing artifact, and exact Beat IDs. Legacy voice-timing-only records remain
  readable only through the explicit compatibility flag.
- Updated representative-slice recovery and installation smoke to opt into
  legacy reads deliberately, and added the new runtime/test files to the
  package fingerprint surface.

## Verification

- RED: the focused scene-timing test initially required the new module; after
  the interrupted implementation was resumed, the focused suite passed.
- Focused GREEN: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache
  uv run --offline --with jsonschema python -m unittest
  tests.test_scene_timing tests.test_representative_slice
  tests.test_skill_contracts -v` — 40 tests passed.
- Full suite: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run
  --offline --with jsonschema python -m unittest discover -s tests -p
  'test_*.py' -q` — 536 tests passed, 4 skipped.
- Package validation: `python3 scripts/validate_package.py .` returned no
  errors after refreshing the release fingerprint.
- `git diff --check` passed. No media was opened, generated, rendered, or
  inspected.

## Concerns

The host `python3` is 3.9 and lacks `jsonschema`; verification therefore uses
the already-cached offline UV Python 3.10 environment and dependency.

## Fix Round 1

- Closed C1 by requiring current Scene Contracts to resolve the authoritative
  approved real voice/timed/semantic lineage and scene-timing artifact, verify
  parent links, and validate the complete scene-timing payload through the
  canonical validator. The legacy flag no longer relaxes current contracts.
- Closed I1/I2 by sharing strict timed-beat and scene-timing validation between
  construction, Scene Contract reads, and persisted project graph checks.
  Reversed/out-of-speech keywords, reordered or omitted Beats, and visual or
  keyword boundary crossings now fail closed.
- Closed I3 by requiring strict non-zero windows in the schema, Artifact
  runtime, and graph validator, with schema/runtime parity regressions.
- Fix-round verification: focused timing/contract/artifact/package checks pass;
  full offline suite passes with 540 tests and 4 skips; package validation is
  valid; release fingerprint equality is true; `git diff --check` passes.

## Fix Round 2

- Closed the remaining Scene Contract lineage gap by validating the resolved
  semantic and narration records, requiring the semantic narration to be the
  authoritative narration and a declared parent, and requiring ordered timed
  and semantic Beat ID lists to match exactly.
- Kept the established `[start_ms, end_ms]` timing interface because it is
  consumed throughout the existing timing/runtime contracts. Draft 2020-12
  cannot express a cross-element `start_ms < end_ms` relation; the schemas now
  document this limitation explicitly and are structural only. Strict ordering
  remains authoritative in Artifact admission, scene-timing construction, and
  persisted graph validation, with package checks requiring the ruling marker.
- Added representative semantic-lineage regressions and schema/runtime cases
  for reversed and zero-duration windows. No standalone schema is treated as
  sufficient timing authority.

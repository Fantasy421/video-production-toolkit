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

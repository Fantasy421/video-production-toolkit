# Task 5 Report — Compact Deterministic Timing Validator

## Delivered

- Added `validate_timing_rows(rows, *, minimum_readable_duration_ms)` with a
  closed compact-row boundary, table-driven timing rules, deterministic issue
  aggregation, and no more than three Beat IDs per issue code.
- Covered real-timing gating, keyword/visual and scene windows, carrier/layer
  density, stale lineage, scene readability, and adjacent-event proximity.
- Added the six-case RED matrix, seven-failure aggregation regression, closed
  metadata-only input check, and non-mutation check.
- Updated structural-validator, motion-director, and timeline-assembler
  contracts with compact timing-row and no-retiming boundaries.

## Verification

- RED: `python3 -m unittest tests.test_timing_validation -v` initially failed
  with the expected missing-module error.
- Focused GREEN: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache
  uv run --offline python -m unittest tests.test_timing_validation
  tests.test_skill_contracts -q` — 25 tests passed.
- Full offline suite: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache
  uv run --offline --with jsonschema python -m unittest discover -s tests -p
  'test_*.py' -q` — passed.
- `git diff --check` passed. No media or payloads were opened, generated,
  decoded, rendered, or inspected.

## Release fingerprint verification

- Refreshed `.codex-plugin/plugin.json` with the canonical validator output:
  `sha256:682652f53fdeedb85f55d5f9b8b5969aa323760c5669ce0ef12d58ddf8dd71ce`.
- `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline
  --with jsonschema python scripts/validate_package.py .` — `package valid`.
- Explicit declared/computed equality check — both values were
  `sha256:682652f53fdeedb85f55d5f9b8b5969aa323760c5669ce0ef12d58ddf8dd71ce`.

## Fix Round 1

- Closed C1: complete compact rows are checked before the rule table; required
  IDs/windows, strict ordered bounded windows, scalar carriers/layers, and
  lineage metadata cannot silently yield `passed`.
- Closed I1: one-element collections, empty support, and unknown support are
  rejected; registered multi-primary/multi-support conflicts remain bounded
  issue outcomes.
- Closed I2/I3: optional lineage IDs use canonical safe-ID validation, and
  claimed/current voice or timed-semantic-beats mismatches (including explicit
  empty values) return `STALE_VOICE_TIMING`.
- Fix-round focused suite: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache
  uv run --offline --with jsonschema python -m unittest
  tests.test_timing_validation tests.test_skill_contracts -q` — 28 passed.
- Fix-round full suite: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache
  uv run --offline --with jsonschema python -m unittest discover -s tests -p
  'test_*.py' -q` — passed.
- Fix-round package check: `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache
  uv run --offline --with jsonschema python scripts/validate_package.py .` —
  `package valid`.
- Fix-round fingerprint equality: declared and computed values both remain
  `sha256:682652f53fdeedb85f55d5f9b8b5969aa323760c5669ce0ef12d58ddf8dd71ce`.
- `git diff --check` passed; no media or payloads were accessed.

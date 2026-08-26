# Task 9 Report: Validated Legacy Rules and Validators

## Delivered

- Published a hard-gate migration audit before porting implementation code. It
  inventories all 19 stable legacy files, disposes all six executable scripts,
  requires the complete expected legacy tree, assigns replacement owner paths,
  and verifies every source against the committed SHA-256 baseline manifest.
  The generated report records each full source hash, retained and rejected
  rules, lifecycle category, finer disposition, and replacement owners.
- Added pure `evaluate_coverage(shots)` behavior for meaningful/decorative
  classification, matching semantic beats, item-declared readable holds, and
  exact uncovered intervals. Findings carry stable issue codes plus source
  artifact and shot IDs; the compact result does not echo input shot records,
  and the evaluator performs no file I/O or persistence. Known state kinds have
  non-overridable canonical roles; only unknown extension kinds may declare a
  `coverage_role`.
- Removed the legacy universal pacing assumptions. Readable-hold thresholds are
  supplied by immutable shot data, and policy defers pacing to confirmed voice,
  format, information density, and declared holds.
- Added project-asset ownership policy. Assets use safe project-relative
  artifact paths; promotion is explicit, provenance-bearing, and no longer tied
  to a hardcoded machine-local character library. Structural validation checks
  promotion ownership/scope, provenance/source, validation evidence,
  applicability, neutral character-action metadata, exact legacy filename
  syntax, and actual PNG alpha when deterministically inspectable. PNG parsing
  validates every chunk length and CRC, exact `IHDR`/`IDAT` ordering, and a
  terminal `IEND` without trailing data. File, checksum, structure, and format
  failures return stable issues. Review round 3 additionally enforces legal
  `PLTE` placement and shape for the supported color types, rejects unknown
  critical chunks, and requires exactly one complete zlib stream with exact
  decoded scanline size and valid filters.
- Added `audit_legacy(legacy_root, new_root)` and its CLI. Roots are supplied at
  runtime, owner paths are constrained to the new repository, symlink escapes
  are rejected, cache files are ignored, incomplete audits cannot be published,
  partial, damaged, or same-path content-changed legacy trees cannot satisfy the
  gate, and successful Markdown reports are atomically replaced and
  directory-synced. Both audit and coverage results declare `schema_version: 1`
  for Task 10 consumers.
- The installed legacy skill at
  `/Users/fantasy/.codex/skills/knowledge-video-visual-director` was read only;
  no legacy file was modified or removed.

## Test-first evidence

- `python3 -m unittest tests.test_coverage -v` initially failed with the expected
  missing `scripts.toolkit.coverage` import, then passed the original coverage
  regressions. The takeover red run additionally proved missing result schema
  and zero-duration rejection. Review round 1 then proved the known-kind role
  override before the final 12 coverage tests passed.
- `python3 -m unittest tests.test_migration_audit -v` initially failed with the
  expected missing `scripts.migration_audit` import. The takeover red run proved
  that partial-tree gating and lifecycle categories were absent. Review round 1
  proved filename-only auditing accepted changed content before the final 10
  audit tests passed.
- `python3 -m unittest tests.test_validation -v` proved that promoted-asset
  alpha, ownership, provenance, neutrality, and malformed metadata checks were
  absent before the original 17 validation tests passed. Review round 2 then
  failed all six new regression methods (eight assertions) against CRC,
  terminal-`IEND`, malformed chunk order, project-coupled naming, version
  suffix, and metadata/filename drift before the final 23 validation tests
  passed. Review round 3 then failed the exact three added regression methods
  (seven assertions) for illegal `PLTE`, unknown critical chunks, and trailing
  or concatenated zlib data before the final 26 validation tests passed.
- Regressions cover decorative-only motion, beat ownership, exact interval
  gaps, narration-language beat labels, contract-declared hold thresholds,
  invalid timing, unknown executable validators, missing expected legacy files,
  same-path source drift, missing owners, cache stability, safe report paths,
  atomic report ownership, promoted-asset metadata, opaque/corrupt/transparent
  PNG behavior, CRC and terminal structure, critical-chunk legality, complete
  zlib streams, exact legacy filename syntax, malformed evidence, and JSON-safe
  results.

## Migration audit

`python3 scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .`

- 19 legacy files inventoried.
- 19 expected stable legacy files present; 0 missing.
- 19 source hashes matched the committed baseline; 0 content mismatches.
- 6 executable legacy scripts inventoried.
- 0 undisposed executable scripts.
- 5 migrated, 11 replaced, 2 externalized, and 1 rejected file.
- Lifecycle roll-up: 5 migrated, 13 replaced, and 1 retired file.
- Report: `docs/migration/knowledge-video-visual-director.md`.

## Verification

- `python3 -m unittest discover -s tests -v` — 142 tests passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-task9-fix3-pycache python3 -m py_compile $(rg --files scripts tests -g '*.py')` — passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- Installed legacy audit — passed with zero undisposed executables.
- Installed legacy read-only snapshot — all 19 pre-task SHA-256 hashes unchanged.
- `git diff --check` — no whitespace errors.

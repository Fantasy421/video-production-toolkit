# Task 9 Report: Validated Legacy Rules and Validators

## Delivered

- Published a hard-gate migration audit before porting implementation code. It
  inventories all 19 stable legacy files, disposes all six executable scripts,
  requires the complete expected legacy tree, assigns replacement owner paths,
  and explicitly records retained and rejected rules. Lifecycle categories are
  `migrated`, `replaced`, or `retired`; the plan's finer `externalized` and
  `rejected` dispositions remain visible.
- Added pure `evaluate_coverage(shots)` behavior for meaningful/decorative
  classification, matching semantic beats, item-declared readable holds, and
  exact uncovered intervals. Findings carry stable issue codes plus source
  artifact and shot IDs; the compact result does not echo input shot records,
  and the evaluator performs no file I/O or persistence.
- Removed the legacy universal pacing assumptions. Readable-hold thresholds are
  supplied by immutable shot data, and policy defers pacing to confirmed voice,
  format, information density, and declared holds.
- Added project-asset ownership policy. Assets use safe project-relative
  artifact paths; promotion is explicit, provenance-bearing, and no longer tied
  to a hardcoded machine-local character library.
- Added `audit_legacy(legacy_root, new_root)` and its CLI. Roots are supplied at
  runtime, owner paths are constrained to the new repository, symlink escapes
  are rejected, cache files are ignored, incomplete audits cannot be published,
  partial or damaged legacy trees cannot satisfy the gate, and successful
  Markdown reports are atomically replaced and directory-synced. Both audit and
  coverage results declare `schema_version: 1` for Task 10 consumers.
- The installed legacy skill at
  `/Users/fantasy/.codex/skills/knowledge-video-visual-director` was read only;
  no legacy file was modified or removed.

## Test-first evidence

- `python3 -m unittest tests.test_coverage -v` initially failed with the expected
  missing `scripts.toolkit.coverage` import, then passed the original coverage
  regressions. The takeover red run additionally proved missing result schema
  and zero-duration rejection before the final nine coverage tests passed.
- `python3 -m unittest tests.test_migration_audit -v` initially failed with the
  expected missing `scripts.migration_audit` import. The takeover red run proved
  that partial-tree gating and lifecycle categories were absent before the final
  nine audit tests passed.
- Regressions cover decorative-only motion, beat ownership, exact interval
  gaps, narration-language beat labels, contract-declared hold thresholds,
  invalid timing, unknown executable validators, missing expected legacy files,
  missing owners, cache stability, safe report paths, atomic report ownership,
  and JSON-safe results.

## Migration audit

`python3 scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .`

- 19 legacy files inventoried.
- 19 expected stable legacy files present; 0 missing.
- 6 executable legacy scripts inventoried.
- 0 undisposed executable scripts.
- 4 migrated, 12 replaced, 2 externalized, and 1 rejected file.
- Lifecycle roll-up: 4 migrated, 14 replaced, and 1 retired file.
- Report: `docs/migration/knowledge-video-visual-director.md`.

## Verification

- `python3 -m unittest discover -s tests -v` — 122 tests passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-task9-pycache python3 -m py_compile $(rg --files scripts tests -g '*.py')` — passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- Installed legacy audit — passed with zero undisposed executables.
- Installed legacy read-only snapshot — all 19 pre-task SHA-256 hashes unchanged.
- `git diff --check` — no whitespace errors.

# Task 8 Pre-install Verification Report

Status: CODE REGRESSIONS RESOLVED; FULL MATRIX ENVIRONMENT-BLOCKED

Bundled interpreter used for every Python command:
`/Users/fantasy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`

| Command | Exit | Count / summary |
|---|---:|---|
| `/Users/fantasy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -c 'import jsonschema; print(jsonschema.__version__)'` | 1 | `ModuleNotFoundError: No module named 'jsonschema'` |
| `PYTHONDONTWRITEBYTECODE=1 /Users/fantasy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -v` | 1 | 408 run; 4 failures, 2 errors, 4 skipped |
| `PYTHONDONTWRITEBYTECODE=1 /Users/fantasy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/validate_package.py` | 0 | `package valid` |
| `PYTHONDONTWRITEBYTECODE=1 /Users/fantasy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/migration_audit.py --help` | 0 | Required flags are `--legacy LEGACY --new NEW`; plan command `--source .` is unsupported |
| `PYTHONDONTWRITEBYTECODE=1 /Users/fantasy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .` | 2 | Correct equivalent live-audit command; legacy root is not an existing directory, so no report was written |
| `rg -n "T[B]D|T[O]DO|implement l[a]ter|similar t[o]|read_bytes\(|Image\.open|cv2\.|ffmpeg|ffprobe" scripts/toolkit/visual_media_context.py references/policies/visual-media-isolation.md skills tests/test_visual_media_context.py` | 0 | 1 match: audio-only `ffprobe` documentation in `skills/voiceover-producer/SKILL.md`; no visual coordinator/runtime call |
| `rg -n "T[B]D|T[O]DO|implement l[a]ter|similar t[o]" scripts/toolkit/visual_media_context.py references/policies/visual-media-isolation.md skills tests/test_visual_media_context.py` | 1 | 0 placeholder matches |
| `rg -n "read_bytes\(|Image\.open|cv2\.|ffmpeg|ffprobe" scripts/toolkit/visual_media_context.py` | 1 | 0 forbidden visual-media access/probe matches |
| `rg -n "subprocess|os\.system|Popen|run\(|check_output|check_call" scripts/toolkit/visual_media_context.py` | 1 | 0 process-spawn matches |
| `git diff --check HEAD` | 0 | no whitespace errors |
| `git diff --cached --check` | 0 | no staged whitespace errors |
| `git diff --stat HEAD` | 0 | no tracked diff |
| `git diff --name-status HEAD` | 0 | no tracked diff |
| `git status --short --branch` | 0 | branch `codex/visual-media-isolation`; untracked: `scripts/__pycache__/`, `scripts/toolkit/__pycache__/`, `tests/__pycache__/` |

Failure summary:

- Environment/import blocker: bundled Python cannot import `jsonschema`; consequently `test_package` fails to import.
- Code import error: `test_voice_tasks` cannot import `_validate_envelope` from `scripts.toolkit.tasks`.
- Code failures: `test_reserved_visual_operation_is_validated_for_every_capability`; `test_scene_production_requires_an_explicit_visual_operation`; `test_validator_rejects_malformed_conditional_image_context`; `test_validator_rejects_scene_scope_with_an_unlisted_character_pack`.
- Migration prerequisite blocker: the live legacy root is absent, and the plan's `--source .` syntax does not match the current CLI.
- No code changes, dependency install, plugin install, host-cache mutation, media inspection, commit, or push performed.

## Systematic debugging: Phase 1–3

### Reproduction and traceback evidence (RED)

All focused commands used the bundled Python with `PYTHONDONTWRITEBYTECODE=1`.

- `tests.test_voice_tasks`: import fails deterministically at
  `scripts/toolkit/voice_tasks.py:11`; `_validate_envelope` no longer exists in
  `scripts.toolkit.tasks`.
- `TaskTests.test_reserved_visual_operation_is_validated_for_every_capability`:
  deterministic assertion mismatch; current task creation raises
  `legacy visual authority is read-only` before the stale test reaches its
  intended unknown-operation branch.
- `TaskTests.test_scene_production_requires_an_explicit_visual_operation`:
  deterministic assertion mismatch in the second case; the fixture mixes
  deprecated `visual_operation` with current `visual_media_operation`, so the
  current-task legacy gate correctly runs before the missing-context check.
- `ValidationTests.test_validator_rejects_malformed_conditional_image_context`:
  deterministic failure; actual issue is `legacy-visual-task-blocked`, not
  `invalid-task-envelope`.
- `ValidationTests.test_validator_rejects_scene_scope_with_an_unlisted_character_pack`:
  deterministic failure; actual task issue is `visual-media-context-invalid`.
  Read-only instrumentation showed `classify_visual_media_task` raises
  `Artifact path must be bound to its exact Artifact ID` before input-scope
  validation. No media was opened, played, displayed, or content-inspected.

The missing `jsonschema` import remains an environment-only blocker and is not
part of this repair.

### Recent changes and working patterns

- `git blame` / `git log -S` identifies `cb2d65a` as the change that split
  `_validate_envelope` into current, persisted, and shape validators. It
  updated `tasks.py` call sites but left `voice_tasks.py` importing the removed
  private function. `scripts/toolkit/orchestrator.py` demonstrates the public
  current-task API: `validate_current_task_envelope`.
- `6fd771d` made deprecated `visual_operation` read-only for newly created
  tasks and added `_is_unprovable_legacy_visual_task` ahead of persisted
  envelope validation. Current task fixtures elsewhere use
  `visual_media_operation`, optional `visual_media_context`, and isolated child
  execution; legacy fields are written directly to persisted JSON only.
- `_is_unprovable_legacy_visual_task` currently converts every projection
  `ValueError` into a blocked ambiguous-legacy issue. A missing context is
  ambiguous compatibility state, but an explicitly present `None` context is
  malformed input and the persisted validator already rejects it.
- The unlisted-pack rule itself remains present in
  `validate_declared_image_inputs` (introduced by `222cdb8`). The broad
  `ValidationTests` fixture uses `contracts/S01.json` for Artifact
  `scene-contract-S01-v1`, which violates the exact path-binding invariant and
  masks that permission rule. Focused persisted-visual fixtures use paths bound
  to their Artifact IDs.

### Root-cause hypotheses and minimal tests

1. Voice import: replacing the removed private import/call with the public
   `validate_current_task_envelope` will restore import and retain strict
   current-task semantics. The existing voice module test is the RED test.
2. Current task tests: removing legacy `visual_operation` from new-task cases
   and asserting `visual_media_operation` will exercise the intended current
   contract. These are stale test-call-site repairs, not restored legacy API.
3. Malformed persisted legacy context: treating an explicitly present malformed
   `image_context` as invalid rather than ambiguous will restore
   `invalid-task-envelope` while preserving the missing-context compatibility
   case as `legacy-visual-task-blocked`. Both existing focused tests form the
   RED/regression pair.
4. Unlisted pack: giving the shared scene-contract fixture an exact ID-bound
   path within this test will allow the existing persisted-scope test to reach
   `validate_declared_image_inputs`, which should then emit
   `visual-media-input-forbidden`. The existing test is the RED test; production
   authorization code should not change.

### Phase 4 follow-up RED

After the removed import was repaired, `tests.test_voice_tasks` collected and
ran 20 tests. Nineteen passed; the durable `create_task` case failed at
`validate_declared_visual_media_inputs` with
`task requires a recognized visual_media_operation`. This was previously
hidden by the module import error. The shared voice envelope is a newly minted,
non-visual task but predates the current explicit discriminator. Hypothesis:
adding the literal current discriminator `visual_media_operation: none` to
that current-task fixture will make durable creation valid without granting
visual authority or weakening production validation. The observed failing
module test is the RED test.

The first path-fixture repair changed the shared `ValidationTests` setup and
made the target RED green, but the complete validation module revealed two
tests that intentionally read `contracts/S01.json` directly and one downstream
coverage assertion masked by the missing file. The traceback confirms scope,
not hypothesis, was wrong: the exact-path adjustment belongs only in the
unlisted-pack test's temporary fixture. The shared fixture is restored and the
target test now moves its temporary contract plus updates its temporary
Artifact record before validation.

The subsequent repository discovery run reported 17 installation/retirement
errors with the same prerequisite failure, `invalid:release-fingerprint`, plus
the known `jsonschema` import error. `scripts/validate_package.py` confirmed
the fingerprint failure. `git log` shows release commits `8bdcb66` and
`95bcc78` intentionally fingerprint every required runtime/test file and update
`.codex-plugin/plugin.json` after content changes. Hypothesis: refreshing the
manifest to `_release_fingerprint(.)` after these intentional required-file
changes will remove all 17 derivative errors while preserving integrity checks.
The pre-refresh package validator and full discovery are the RED evidence.

## Phase 4 GREEN and final verification

Status: CODE REGRESSIONS RESOLVED; FULL MATRIX ENVIRONMENT-BLOCKED

| Verification | Result |
|---|---|
| Five original focused reproductions | PASS; voice module 20/20 plus each of the four named tests |
| `tests.test_tasks tests.test_validation tests.test_voice_tasks tests.test_visual_media_context tests.test_image_context` | PASS; 202 tests |
| `tests.test_end_to_end` | PASS; 57 tests, 4 skipped |
| `scripts/validate_package.py` | PASS; `package valid` |
| Full `unittest discover -s tests` | 427 run; only one error, `test_package` import blocked by missing `jsonschema`; 4 skipped |
| `git diff --check` | PASS |

Files changed:

- `.codex-plugin/plugin.json`
- `scripts/toolkit/validation.py`
- `scripts/toolkit/voice_tasks.py`
- `tests/test_tasks.py`
- `tests/test_validation.py`
- `tests/test_voice_tasks.py`

No dependency was installed or vendored. No test was weakened to bypass
`jsonschema`. No media was opened, played, displayed, generated outside test
fixtures, or perceptually inspected. Test-owned temporary artifacts were left
to their test cleanup.

Commit: `4691cc5 fix: resolve visual task validation regressions`

## Round 2: scene.produce schema/runtime parity

### Phase 1–3 evidence and hypothesis

- Both the bundled Python and system `python3` fail to import `jsonschema`; the
  configured Node bundle also contains no AJV/JSON Schema engine. No dependency
  was installed or vendored.
- Read-only inspection shows `task-envelope.schema.json` still unconditionally
  requires deprecated `visual_operation` for `scene.produce`.
- `git blame` traces that scene rule to `d333d6d`; the later current/legacy
  split (`cb2d65a`, `6fd771d`) changed runtime creation semantics but did not
  update this rule. `9fd9c4c` provides the working schema pattern by making
  `structure.validate` a mutually exclusive current/legacy `oneOf`.
- Runtime evidence from round 1 confirms newly created scene tasks reject
  `visual_operation` and use `visual_media_operation` / optional required
  `visual_media_context`; `_validate_persisted_envelope` retains explicit
  read-only legacy authority.

Root-cause hypothesis: replacing the scene rule with an exact current/legacy
`oneOf` will restore schema/runtime parity. The current branch must require a
closed current operation and ban all legacy authority; the persisted branch
must require the closed legacy discriminator, retain the existing generic
legacy image conditionals, and ban current operation/context. An exact package
validator plus mutation and Draft 2020-12 parity tests will prevent regression.

### Round 2 RED/GREEN and verification

- RED: dependency-free focused schema parity test failed because the actual
  scene constraint was `{"required": ["visual_operation"]}` instead of the
  expected mutually exclusive current/legacy `oneOf`.
- Environment RED: the focused Draft 2020-12 test in `tests/test_package.py`
  cannot collect because `jsonschema` is absent. It remains in the suite for
  environments with the declared dependency; no skip or fallback was added.
- GREEN: the dependency-free schema parity test passes after the schema change.
- Exact validator mutation checks pass after fingerprint refresh:
  weakening the current scene branch yields only
  `invalid:scene-visual-authority`; removing the legacy read-only marker yields
  only `invalid:legacy-visual-operation`.
- `tests.test_tasks`: 80 passed.
- `tests.test_validation`: 66 passed.
- `tests.test_voice_tasks`: 20 passed.
- visual/image runtime safety: 37 passed.
- `tests.test_end_to_end`: 57 passed, 4 skipped.
- `scripts/validate_package.py`: `package valid`.
- Full discovery: 428 run; the sole error is the known missing-`jsonschema`
  import, with 4 skipped.

Round 2 files changed:

- `.codex-plugin/plugin.json`
- `references/schemas/task-envelope.schema.json`
- `scripts/validate_package.py`
- `tests/test_package.py`
- `tests/test_tasks.py`

No dependency installation, media operation, media inspection, or test-owned
media handling was performed.

Round 2 commit: `ffe9b61 fix: align scene task schema authority`

## Final pre-install full matrix (2026-08-29)

Status: DONE

Interpreter: `/private/tmp/vptk-verify.l6RoeW/venv/bin/python3`

| Verification | Exit | Structural summary |
|---|---:|---|
| `jsonschema` import/version | 0 | version 4.26.0; version accessor emitted one deprecation warning |
| Full `unittest discover -s tests` | 0 | 453 run; 449 passed; 4 skipped; 0 failures; 0 errors |
| Package validator | 0 | package valid |
| `tests.test_migration_audit` | 0 | 10 run; 10 passed; 0 skipped/failures/errors |
| Specified legacy skill target absence | 0 | target does not exist |
| Placeholder scan | 1 | 0 matches (expected `rg` no-match exit) |
| Visual runtime media-access/probe scan | 1 | 0 matches (expected `rg` no-match exit) |
| Visual runtime process-spawn scan | 1 | 0 matches (expected `rg` no-match exit) |
| Combined policy/skills/runtime scan | 0 | 1 match; audio-only `ffprobe` documentation, not a visual runtime call |
| `git diff --check HEAD` | 0 | no whitespace errors |
| `git diff --cached --check` | 0 | no staged whitespace errors |
| `git diff --stat/name-status HEAD` | 0 | no tracked diff |
| `git status --short --branch` | 0 | branch `codex/visual-media-isolation`; only three pre-existing untracked `__pycache__` directories |
| `git log --oneline --decorate -12` | 0 | HEAD `ffe9b61`; 12 recent commits listed |

The invalid `migration_audit --source` form was not run, and no legacy root
was synthesized. No media was opened, played, displayed, decoded, rendered,
or perceptually inspected. Tests owned creation and cleanup of any synthetic
fixtures. No dependency/plugin installation, code change, commit, push, or
sub-agent dispatch was performed. The only intentional write was this report
append.

## Voice-timing final-review fix wave (2026-08-30)

Status: DONE; all Critical, Important, and Minor findings from the independent
whole-branch review are covered by production checks and regressions.

Corrections completed:

- authoritative timed beats now have exact semantic/voice parents, compare to
  the exact `voice_timing.keyword_anchors`, and must byte-for-byte equal a
  canonical recomputation at Artifact admission, project validation, Scene
  Contract admission, routing, and production readiness;
- timing repair now names the complete authoritative lineage and minimum
  duration, requires a new immutable Scene Timing Contract plus a newly derived
  compact validation, and rejects passed-only output on an unchanged scene;
- the production gate and structural validator derive compact rows from the
  exact scene/timed chain and require the persisted validation result to equal
  the fresh result;
- explicit null is the sole missing-anchor sentinel and emits
  `KEYWORD_ANCHOR_MISSING`; omission and wrong types remain invalid, and one
  end-to-end test builds one bounded repair envelope for the affected Beat ID;
- all applicable upstream invalidation rules now include
  `scene-timing-contracts` and `timing-validation`, with exact table coverage;
- generic semantic admission and schema validation require `user:` approval
  provenance;
- scene admission, compact validation, Scene Contracts, and schemas share one
  closed support-layer registry, including exact secondary/support binding;
- all eight review-listed release files are now fingerprint inputs, with
  membership and content-mutation coverage.

Final verification used the existing offline dependency cache only:
`UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline
--with jsonschema`. No dependency was installed or vendored.

| Verification | Result |
|---|---|
| Full `python -m unittest discover -s tests` | PASS; 589 run, 4 skipped, 0 failures, 0 errors |
| `scripts/validate_package.py` | PASS; `package valid` |
| Repository/local timing smoke | PASS; all 8 checks passed (`installed_module`, `frozen_semantic_beats`, `real_timing_binding`, `storyboard_gate`, `compact_validation`, `stale_timing_recovery`, `v2_compatibility`, `json_metadata_only`) |
| Manifest version | `0.2.0` (unchanged) |
| Declared/recomputed fingerprint | equal; `sha256:e2cbd8ba4577c642c717086051c2f1fca8b830d631e51f5ce06b76a898c24b86` |
| Placeholder scan across timing/isolation runtime, policies, Skills, and tests | 0 matches |
| Visual/runtime media access, probe, and process-spawn scan | 0 matches |
| `git diff --check HEAD` | PASS |

The four skipped tests require the already-absent installed legacy skill and
are unchanged retirement guards. No plugin installation, host-cache mutation,
legacy retirement, media processing/inspection, push, or sub-agent dispatch
was performed in this fix wave.

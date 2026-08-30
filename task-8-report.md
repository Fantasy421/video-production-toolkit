# Task 8 report

Completed release verification Steps 1–4 for the voice-timed semantic-beats
release.

## Release

- Selected `0.2.0` after inspecting the current `0.1.4` manifest. The minor
  bump reflects the public Artifact and workflow-state contract changes.
- Updated the manifest, package validator, README, and installed visual-smoke
  expectations to `0.2.0`.
- Release fingerprint: `sha256:5b4fc51dc4d3dabb01199158ded7ec8bc25807fa096aeacc153c03b30d005e25`.
- Added semantic-beats and timing-validation runtime/test files to the
  distributable fingerprint surface.
- Added refreshed-fingerprint mutation guards for approval freeze, real timing,
  and authoritative voice-timing lineage.

## Installed timing smoke

Added `run_installed_timing_smoke()` and a hidden verifier entrypoint. The
isolated `python -I -B` child confirms installed module identity, untimed
approved semantic beats, real timing binding, storyboard approval gating,
bounded compact validation, stale timing recovery, v2 projection compatibility,
and that no media files are created. The smoke uses metadata-only fixtures and
does not open or play audio or visual payloads.

## Verification

- `python -m unittest discover -s tests -v`: 576 tests passed, 4 documented
  environment skips.
- `UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest discover -s tests -v`: 576 passed, 4 skipped.
- `python scripts/validate_package.py`: `package valid`.
- Installed timing smoke via `python scripts/verify_installation.py --repo . --require-timing-smoke`: passed all 8 checks.
- Forbidden placeholder/media-access scans: clean for the visual-media and
  timing coordinator/runtime modules; `git diff --check` passed.

Installation, host-cache replacement, media operations, and remote push were
not performed, as explicitly out of scope for this task.

## Review fix round 1 (I1/I2)

- Added `references/policies/narration-and-coverage.md` and
  `skills/video-project-manager/SKILL.md` to `REQUIRED_FILES` and release
  fingerprint coverage, with content-mutation assertions.
- Added the fail-closed runtime sentinel for
  `scripts/toolkit/timing_validation.py::_MAX_EXAMPLES = 3` and a
  refreshed-fingerprint mutation test proving `3 -> 4` is rejected.
- Refreshed 0.2.0 fingerprint: `sha256:5b4fc51dc4d3dabb01199158ded7ec8bc25807fa096aeacc153c03b30d005e25`.
- Full offline matrix: 577 passed, 4 documented skips.
- Plain-Python matrix: 577 passed, 4 documented skips.
- Package validation, timing smoke (all 8 checks), forbidden scans, and
  `git diff --check`: passed.

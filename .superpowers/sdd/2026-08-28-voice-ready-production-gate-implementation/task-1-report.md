Status: complete

Commit: recorded with this report (`feat: add recoverable voice-ready phase`)

Implementation: inserted `voice_ready` into the persisted phase order and both phase schemas. New `append_event` calls continue to enforce only the revised order. Replay recognizes the single historical version-one transition difference (`direction_ready` to `storyboard_ready`) while retaining every event-contract, locking, fsync, and symlink safeguard. `project_recovery_view` is read-only: post-direction snapshots without a supplied valid voice-lineage predicate normalize to `direction_ready` with `voice-artifacts-required`, leaving JSONL bytes untouched. Its optional predicate boundary deliberately prevents `project_state` from importing the forthcoming `voice` module.

TDD evidence: added the new phase-order and immutable legacy-recovery tests, then observed RED from the missing `project_recovery_view` import. Added a tampered legacy-event regression, observed RED because the compatibility path accepted an extra event field, then constrained that path to the exact event contract.

Verification: `PYTHONPYCACHEPREFIX=/tmp/voice-ready-task1-green-contract python3 -m unittest tests.test_project_state -v` — 16 passed. `PYTHONPYCACHEPREFIX=/tmp/voice-ready-task1-compile python3 -m py_compile scripts/toolkit/*.py scripts/*.py tests/*.py` — passed. `python3 scripts/validate_package.py` — `package valid`. `git diff --check` — passed.

Full-suite note: `PYTHONPYCACHEPREFIX=/tmp/voice-ready-task1-full python3 -m unittest discover -s tests -v` ran 221 tests and reported four downstream smoke/retirement failures. Each fails because the installed smoke fixture still appends the now-illegal `direction_ready` to `storyboard_ready` transition; this belongs to Task 7's `scripts/verify_installation.py` and `tests/test_end_to_end.py` ownership, so Task 1 did not alter those files.

Concerns: Task 5 must call `project_recovery_view` with Task 2's authoritative lineage predicate when resuming projects; the default is intentionally conservative.

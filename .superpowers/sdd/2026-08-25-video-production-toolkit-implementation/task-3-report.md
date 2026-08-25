Status: complete

Commit: acf70a5980bffe943e271961cb805d92ac113d69 (`feat: add immutable artifact dependency graph`)

Tests: `python3 -m unittest tests.test_artifacts tests.test_invalidation tests.test_project_state tests.test_package -v` — 13 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_pycache python3 -m py_compile scripts/toolkit/artifacts.py scripts/toolkit/invalidation.py` — passed. `git diff --cached --check` — passed before commit.

Concerns: none.

Fix round 1/5 status: complete

Fix commit: 8056f48ae89314b80e452d6d36f21e41bb9dcf96 (`fix: harden artifact publication`)

Root cause: artifact type validation accepted `.` and `..`; JSON was written directly to final paths; artifact-ID uniqueness was checked before a cross-type write without an atomic claim; parent/approval target discovery trusted filenames without parsing metadata.

Fix evidence: artifact IDs and types now require safe single path components, and the resolved destination is checked beneath its storage root. JSON is serialized before any final-file publication, then written to a sibling temporary file and atomically linked into place without overwrite. A per-ID `artifacts/.ids/<artifact_id>.reservation` file provides the cross-type atomic claim and is removed if publishing fails. Parent and approval target discovery parses, validates, and filename-matches stored artifact metadata, excluding corrupt files.

Regression evidence: added coverage for `.`/`..`/nested unsafe types, failed artifact serialization followed by a successful retry, corrupt metadata rejection for approval targets, failed approval serialization with no partial file, and two concurrent same-ID different-type writes yielding exactly one success and one `FileExistsError`.

Verification: `python3 -m unittest tests.test_artifacts tests.test_invalidation tests.test_project_state -v` — 16 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_pycache python3 -m py_compile scripts/toolkit/artifacts.py scripts/toolkit/invalidation.py` — passed. `git diff --check` and pre-commit `git diff --cached --check` — passed.

Fix concerns: none.

Fix round 3/5 status: complete

Fix commit: recorded with this report (`fix: close artifact lock races`)

Root cause: ID discovery occurred before acquisition of the per-ID lock, so a globally duplicate artifact could appear before publication. Dead-lock reclaimers operated on a pathname without owning a stable lock instance, allowing a stale reclaimer to delete a replacement lock in an interleaving.

Fix evidence: `create_artifact` rescans all valid artifact metadata after it owns the artifact-ID lock and before final publication. Artifact lock handles retain an exclusive `flock` descriptor; dead-lock reclamation only unlinks when the pathname and held descriptor still identify the same inode. Lock release performs the same identity check, preserving a replacement lock if the handle was displaced. Locks remain transient JSON records, successful writes remove their own locks, dead PIDs can still be reclaimed, and existing corrupt-metadata and path-validation safeguards are unchanged.

Regression evidence: the post-lock global-ID regression uses events to deterministically hold publication until a competing cross-type record is written; the competing-reclaimer test uses a barrier to ensure only one reclaimer owns the stale lock; the displaced-handle regression proves releasing an old descriptor cannot delete a replacement live lock. The displaced-handle test was observed failing before the release identity check was added, then passing afterward.

Verification: `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_pycache python3 -m unittest discover -s tests -v` — 25 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_pycache python3 -m py_compile scripts/toolkit/artifacts.py scripts/toolkit/invalidation.py` — passed. `git diff --check` — passed.

Fix concerns: none.

Fix round 5/5 status: complete

Fix commit: recorded with this report (`fix: clean interrupted artifact lock acquisition`)

Root cause: after atomically publishing its live-PID JSON lock, the creator retried `BlockingIOError` until it could hold the inode. `KeyboardInterrupt`, `SystemExit`, cancellation, or another `BaseException` escaping anywhere before `_hold_published_lock` returned bypassed both the collision handler and the normal handle-release path, leaving the creator's live lock permanently unreclaimable.

Fix evidence: each acquisition now writes an opaque `owner_token` alongside PID and timestamp. Publication through handle return is covered by `BaseException` cleanup. Cleanup opens the visible lock, verifies the token through that descriptor, then verifies the pathname still identifies the same inode before unlinking; a missing path, replacement inode, malformed record, or another owner's token is preserved. Returned handles retain the prior inode-checked release behavior, and collision-path writers remain fail-fast.

Regression evidence: `test_keyboard_interrupt_during_published_lock_retry_allows_retry` deterministically makes the creator encounter `BlockingIOError`, interrupts the retry sleep, then proves a real second creation succeeds. The regression failed before the fix because the second attempt reported `artifact is locked: style-v1`. `test_interrupted_lock_retry_preserves_replacement_owner` replaces the creator's pathname during that retry and proves interruption cleanup leaves the replacement owner's live lock intact. All earlier publication-gap, competing-reclaimer, and displaced-handle regressions remain green.

Verification: `PYTHONPYCACHEPREFIX=/tmp/video_toolkit_task3_fix5_full_pycache python3 -m unittest discover -s tests -v` — 28 passed. `PYTHONPYCACHEPREFIX=/tmp/video_toolkit_task3_fix5_compile_pycache python3 -m py_compile scripts/toolkit/*.py scripts/*.py tests/*.py` — passed. `git diff --check` — passed.

Fix concerns: none.

Fix round 4/5 status: complete

Fix commit: recorded with this report (`fix: retain published artifact lock ownership`)

Root cause: the lock creator atomically published its live-PID JSON path and only afterward attempted a nonblocking `flock`. A contender could acquire that newly visible inode in the gap; the creator then propagated `BlockingIOError` without receiving a lock handle, so no release path removed its own live-PID record. Failed nonblocking holds also left their opened descriptors unclosed.

Fix evidence: the process that successfully publishes a new lock now treats `BlockingIOError` as temporary ownership handoff contention and retries until it holds that inode. Collision-path writers remain fail-fast. `_hold_lock` closes its descriptor on every failed `flock`, while the existing handle identity checks continue to protect replacement locks during reclaim and release.

Regression evidence: `test_creator_waits_for_contender_in_publish_to_flock_gap` publishes the creator's real JSON lock, makes a contender hold that inode before the creator's first `_hold_lock`, and releases the contender only after the creator encounters contention. The regression failed before the fix with the expected `BlockingIOError`; after the fix, artifact creation completes and removes the transient lock.

Verification: `PYTHONPYCACHEPREFIX=/tmp/video_toolkit_task3_fix4_pycache python3 -m unittest discover -s tests -v` — 26 passed. `PYTHONPYCACHEPREFIX=/tmp/video_toolkit_task3_fix4_pycache python3 -m py_compile scripts/toolkit/*.py` — passed. `git diff --check` and pre-commit `git diff --cached --check` — passed.

Fix concerns: none.

Fix round 2/5 status: complete

Fix commit: 6dfa168857a79fa0ee1bff318449b7ef41f08b90 (`fix: use transient JSON artifact locks`)

Root cause: the round-1 global reservation was a durable plain-text file and was intentionally retained after success; interruption could leave it indefinitely. Its cleanup caught only `Exception`, excluding `KeyboardInterrupt` and other `BaseException` cases.

Fix evidence: reservations are replaced by transient `artifacts/.locks/<artifact_id>.json` acquisition locks. Each atomic lock record contains the current PID and timestamp. Artifact publication always removes its acquired lock in `finally`, so interruption is cleaned up. On a lock collision, valid published metadata is checked first; otherwise a valid dead-PID lock is reclaimed, while live or malformed locks reject the writer. No lock remains after a successful publication.

Regression evidence: added no-lock-after-success, `KeyboardInterrupt` cleanup/retry, dead-PID reclamation, and live-PID lock-refusal tests; the existing concurrent cross-type writer test remains in place.

Verification: `python3 -m unittest tests.test_artifacts tests.test_invalidation tests.test_project_state -v` — 20 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_pycache python3 -m py_compile scripts/toolkit/artifacts.py scripts/toolkit/invalidation.py` — passed. `git diff --check` and pre-commit `git diff --cached --check` — passed.

Fix concerns: none.

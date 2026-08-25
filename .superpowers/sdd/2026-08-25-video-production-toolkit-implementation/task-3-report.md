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

Fix round 2/5 status: complete

Fix commit: 6dfa168857a79fa0ee1bff318449b7ef41f08b90 (`fix: use transient JSON artifact locks`)

Root cause: the round-1 global reservation was a durable plain-text file and was intentionally retained after success; interruption could leave it indefinitely. Its cleanup caught only `Exception`, excluding `KeyboardInterrupt` and other `BaseException` cases.

Fix evidence: reservations are replaced by transient `artifacts/.locks/<artifact_id>.json` acquisition locks. Each atomic lock record contains the current PID and timestamp. Artifact publication always removes its acquired lock in `finally`, so interruption is cleaned up. On a lock collision, valid published metadata is checked first; otherwise a valid dead-PID lock is reclaimed, while live or malformed locks reject the writer. No lock remains after a successful publication.

Regression evidence: added no-lock-after-success, `KeyboardInterrupt` cleanup/retry, dead-PID reclamation, and live-PID lock-refusal tests; the existing concurrent cross-type writer test remains in place.

Verification: `python3 -m unittest tests.test_artifacts tests.test_invalidation tests.test_project_state -v` — 20 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_pycache python3 -m py_compile scripts/toolkit/artifacts.py scripts/toolkit/invalidation.py` — passed. `git diff --check` and pre-commit `git diff --cached --check` — passed.

Fix concerns: none.

Status: complete

Commit: this commit (`feat: add isolated task execution contracts`)

Implementation: added immutable JSON task envelopes, exclusive `tasks/locks/<task_id>.lock` worker claims, result registration, and stale-result quarantine. Completion accepts only results whose declared inputs exactly match the persisted envelope and whose artifact records remain current; stale, superseded, and invalid inputs place the compact result under `tasks/stale-results/` without registering output. Added bounded retry decisions: contract and adapter errors retry twice on one adapter, then switch once to a declared fallback; input and direction errors request user action; all other outcomes block.

Contracts: added JSON Schemas for the compact task envelope and task result, plus the durable retry policy.

Regression evidence: task tests cover immutable envelope persistence, exclusive claims, stale input versions, mismatched result inputs, valid result registration, retry/fallback bounds, and user-action errors.

Verification: `python3 -m unittest tests.test_tasks -v` — 7 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_full_pycache python3 -m unittest discover -s tests -v` — 35 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_pycache python3 -m py_compile scripts/toolkit/tasks.py tests/test_tasks.py` — passed. `git diff --check` — passed.

Concerns: none.

Fix round 1/5 status: complete

Fix commit: this commit (`fix: harden task execution recovery`)

Root cause: worker locks only identified a worker ID, so any caller could complete and release a live task; completion checked claim, task state, and result destination without one ownership-critical lock. Input freshness only considered artifact status and ignored a newer approved version in the same lineage. Retry decisions were an in-memory calculation with caller-supplied adapters, so concurrent or restarted callers could reset the budget and return to a previous adapter. Plain lock files had no recovery metadata, and runtime validators accepted fields that the JSON schemas rejected.

Fix evidence: `claim_task` now returns a worker ID and opaque claim token. Claim records add PID and lease metadata; completion exclusively locks the claim inode, verifies token/worker ownership, validates inputs, publishes the result, and only then removes that same inode. Dead or expired claims are safely reclaimed, while a displaced token cannot complete. Current input comparison requires approved inputs and rejects a task when a newer approved artifact of the same type descends from its contracted version. Retry decisions now read the immutable envelope and atomically persist the current adapter, attempts, fallback state, and history. Envelope and result runtime checks reject unknown properties to match their `additionalProperties: false` schemas.

Regression evidence: deterministic tests cover concurrent claims, owner/token rejection, no re-claim after completion, dead-claim recovery with displaced-worker rejection, newer approved input lineages, concurrent retry-ledger updates, declared-adapter enforcement, strict runtime properties, and retry budget persistence.

Verification: `python3 -m unittest tests.test_tasks -v` — 14 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_fix1_full_pycache python3 -m unittest discover -s tests -v` — 42 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_fix1_pycache python3 -m py_compile scripts/toolkit/tasks.py tests/test_tasks.py` — passed. `git diff --check` — passed.

Fix concerns: none.

Fix round 2/5 status: complete

Fix commit: this commit (`fix: preserve live task claims and retry caps`)

Root cause: a valid claim could be reclaimed solely because its fixed lease elapsed even though its PID was still live. A stale result used one terminal pathname but did not classify that pathname as terminal at claim time, so a recovered worker could acquire a new claim and collide on the immutable stale result. Retry processing incremented the current adapter before checking whether it had already exhausted two attempts.

Fix evidence: valid claims are now reclaimable only when their owner PID is proven dead; lease metadata remains diagnostic and cannot displace a live worker without an authenticated renewal protocol. Stale results are terminal: `claim_task` rejects them, while `complete_task` releases its claim in a `finally` block whenever either terminal output exists, including an interrupt after durable publication. Retry decisions block before mutation when the current adapter has already reached two attempts.

Regression evidence: added live-PID/expired-lease refusal, terminal repeated-stale cleanup, `KeyboardInterrupt` after stale publication cleanup, and duplicate terminal retry-count tests. Existing concurrent claim/retry, ownership, stale-lineage, and dead-PID recovery tests remain green.

Verification: `python3 -m unittest tests.test_tasks -v` — 18 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_fix2_full_pycache python3 -m unittest discover -s tests -v` — 46 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_fix2_pycache python3 -m py_compile scripts/toolkit/tasks.py tests/test_tasks.py` — passed. `git diff --check` — passed.

Fix concerns: none.

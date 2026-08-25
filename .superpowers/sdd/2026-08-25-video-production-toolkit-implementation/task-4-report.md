Status: complete

Commit: this commit (`feat: add isolated task execution contracts`)

Implementation: added immutable JSON task envelopes, exclusive `tasks/locks/<task_id>.lock` worker claims, result registration, and stale-result quarantine. Completion accepts only results whose declared inputs exactly match the persisted envelope and whose artifact records remain current; stale, superseded, and invalid inputs place the compact result under `tasks/stale-results/` without registering output. Added bounded retry decisions: contract and adapter errors retry twice on one adapter, then switch once to a declared fallback; input and direction errors request user action; all other outcomes block.

Contracts: added JSON Schemas for the compact task envelope and task result, plus the durable retry policy.

Regression evidence: task tests cover immutable envelope persistence, exclusive claims, stale input versions, mismatched result inputs, valid result registration, retry/fallback bounds, and user-action errors.

Verification: `python3 -m unittest tests.test_tasks -v` — 7 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_full_pycache python3 -m unittest discover -s tests -v` — 35 passed. `PYTHONPYCACHEPREFIX=/private/tmp/video_toolkit_task4_pycache python3 -m py_compile scripts/toolkit/tasks.py tests/test_tasks.py` — passed. `git diff --check` — passed.

Concerns: none.

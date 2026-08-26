# Task 6 Report: Child Skill Contracts and Progressive Routing

## Delivered

- Added nine bounded child-skill entrypoints with one primary owned capability,
  declared compact inputs, task-result output, stopping conditions, user-gate
  behavior, and schema/policy links.
- Documented the four durable decision gates and one-primary/one-secondary
  visual-carrier grammar.
- Strengthened `video-director` to reconcile summary versus event replay, stop
  on unsafe routing or missing approvals, dispatch exactly one action slice,
  and map each capability to one child skill.
- Kept `motion.preview` as `motion-director`'s owned capability and made
  `motion.produce` an explicit, approval-bound delegated secondary operation.
- Added static contract tests for these boundaries.

## Test-first evidence

`python3 -m unittest tests.test_skill_contracts -v` first failed because the
child Skill and policy files were absent. After implementation, the focused
skill-contract and package tests passed.

## Verification

- `PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-pycache python3 -m py_compile tests/test_skill_contracts.py`
- `PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-pycache python3 -m unittest discover -s tests -v` — 63 tests passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- `git diff --check` — no whitespace errors.

## Self-review

All child entrypoints are below 250 English words (the longest is
`motion-director` at 174 words). The coordinator contains no media-generation
instruction and external providers are explicitly barred from overriding
routing or approval policy.

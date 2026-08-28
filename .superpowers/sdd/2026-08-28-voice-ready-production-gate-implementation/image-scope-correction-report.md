# Image Scope Correction Report

## Outcome

The task runtime now requires exactly one declared scope input for every
image-context task. A `scene-contract` context may contain only its declared
Scene Contract, while a `character-asset-batch` context may contain only its
declared batch or character pack. Ordinary authorized image IDs, the one
continuity exception, historical restrictions, and non-image task behavior
remain unchanged.

## Root Cause and TDD Evidence

`validate_declared_image_inputs` previously proved that `scope_identity`
identified one valid input, but did not reject other inputs of the same scope
family. Real `create_task` regressions were added first and run RED against
`e362395`:

- a `scene-contract` scope accepted both `scene-contract-S03-v4` and
  `scene-contract-S04-v1`;
- a `character-asset-batch` scope accepted a second batch and a second
  `character-pack`.

The minimal runtime change derives the declared inputs whose artifact type is
in the selected scope family and requires that set to equal only
`scope_identity.id`.

The persisted image-context schema was already a closed, bounded `oneOf` of
`{kind, id}` scope objects with safe IDs. The new condition compares that
single declared identity with runtime task inputs, which is a cross-record
relationship JSON Schema cannot express; no distributable schema change was
needed.

## Verification

- RED: `python -m unittest tests.test_tasks.TaskTests.test_image_task_rejects_an_additional_scene_contract_scope_input tests.test_tasks.TaskTests.test_character_batch_image_scope_rejects_other_batch_or_pack_inputs -v` (three expected failures before the runtime change).
- GREEN: the same focused command passed.
- Focused: `python -m unittest tests.test_image_context tests.test_tasks tests.test_package -v` — 83 passed.
- Full suite: `python -m unittest discover -s tests -v` — 369 passed.
- Compilation: `PYTHONPYCACHEPREFIX=/tmp/video-toolkit-image-scope python -m py_compile scripts/toolkit/*.py scripts/*.py tests/*.py` — passed.
- Package: `python scripts/validate_package.py` — `package valid`.
- Migration audit: `python scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .` — valid, 19 legacy files, 0 undisposed executables.
- Installation verifier: `python scripts/verify_installation.py --repo . --require-skill video-director --require-resume-smoke --check-external-skills` — passed, including all resume-smoke checks and available ChatCut Voice capability.
- Diff check: `git diff --check` — passed.

## Scope

Changed files are `scripts/toolkit/image_context.py` and
`tests/test_tasks.py`, plus this report. No image files were opened,
generated, or inspected.

## Correction Round 1

The initial cardinality check treated every `character-pack` input as a
character scope. That conflated explicitly authorized member/reference packs
with an independent character scope. The bounded,
schema-required `allowed_character_pack_ids` list is now used as the declared
member role: a listed approved pack is an authorized member and is excluded
from character scope-candidate counting. An unlisted character pack remains
an independent candidate and is rejected alongside any extra
`character-asset-batch`.

Cardinality is now global across the two families. A scene-contract scope
rejects every declared character-asset-batch, and a character-asset-batch
scope rejects every declared Scene Contract. This preserves one scope even
when there are no duplicate candidates within the selected family.

### TDD Evidence

- RED: a valid character batch with an explicitly allowlisted member pack
  failed as a second scope; scene-plus-batch and batch-plus-scene contexts
  both incorrectly passed real `create_task` authorization.
- GREEN: the five focused runtime regressions passed, including a
  `claim_task` revalidation regression for a persisted envelope that gains a
  second scene scope before claim.
- Focused: `python -m unittest tests.test_image_context tests.test_tasks tests.test_package -v` — 87 passed.

No schema change was needed: the existing closed image-context schema already
defines the member-role field as a unique, safe, maximum-eight list. The
runtime applies its role semantics when relating that context to task inputs.

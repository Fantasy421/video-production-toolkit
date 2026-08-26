# Migration Audit: knowledge-video-visual-director

This report inventories the installed legacy skill without modifying it. The
legacy root is supplied at audit time; no machine-local legacy path is part of
the replacement library.

## Summary

- Legacy files inventoried: 19
- Expected stable legacy files: 19
- Missing expected legacy files: 0
- Executable legacy scripts: 6
- Undisposed executable scripts: 0
- Lifecycle categories: 4 migrated, 14 replaced, 1 retired
- Dispositions: 4 migrated, 12 replaced, 2 externalized, 1 rejected

## File dispositions

| Legacy file | Category | Disposition | New owner paths | Rationale |
|---|---|---|---|---|
| `SKILL.md` | replaced | replaced | `skills/video-director/SKILL.md` | The monolithic entrypoint is split into bounded capability owners. |
| `agents/openai.yaml` | replaced | replaced | `agents/openai.yaml` | Plugin-facing metadata now names the replacement coordinator. |
| `assets/character-model-sheet.png` | retired | rejected | `references/policies/project-assets.md` | A project-specific character baseline must not become a plugin-global asset. |
| `references/audit.md` | migrated | migrated | `references/policies/narration-and-coverage.md`, `references/policies/project-assets.md`, `skills/structural-validator/SKILL.md` | Objective coverage, evidence, and asset rules survive; subjective acceptance remains a user review. |
| `references/plan.md` | migrated | migrated | `references/policies/narration-and-coverage.md`, `references/policies/visual-carriers.md` | Voice timing, semantic coverage, and meaningful holds are retained without universal pacing constants. |
| `references/produce.md` | replaced | replaced | `skills/scene-producer/SKILL.md`, `skills/motion-director/SKILL.md`, `skills/timeline-assembler/SKILL.md` | Production is owned by isolated task capabilities and immutable contracts. |
| `references/scene-patterns.json` | replaced | externalized | `registries/recipes/video-shotcraft-index.json`, `scripts/toolkit/registry.py` | Creative recipes are compact registry metadata loaded through external implementation references. |
| `references/start.md` | replaced | replaced | `skills/video-project-manager/SKILL.md`, `references/policies/project-assets.md` | Project identity and isolation are enforced by project state and artifact policy. |
| `routing-manifest.json` | replaced | replaced | `skills/video-director/SKILL.md`, `skills/video-project-manager/SKILL.md` | Project phase and one ready task now drive routing. |
| `scripts/search_assets.py` | replaced | replaced | `scripts/toolkit/artifacts.py`, `references/policies/project-assets.md` | Machine-local TSV lookup is replaced by project artifacts and explicit promotion policy. |
| `scripts/select_scene_patterns.py` | replaced | externalized | `scripts/toolkit/registry.py`, `scripts/search_registry.py` | Deterministic metadata scoring moved to the versioned registry boundary. |
| `scripts/validate_coverage.py` | migrated | migrated | `scripts/toolkit/coverage.py` | Deterministic semantic coverage becomes a pure structured-issue evaluator. |
| `scripts/validate_library.py` | replaced | replaced | `scripts/toolkit/artifacts.py`, `scripts/toolkit/validation.py`, `references/policies/project-assets.md` | Safe project paths, immutable ownership, and promotion policy replace the narrow global TSV library. |
| `scripts/validate_router.py` | replaced | replaced | `scripts/validate_package.py`, `tests/test_skill_contracts.py` | Package and child-capability contracts replace word-count routing validation. |
| `scripts/validate_state.py` | replaced | replaced | `scripts/toolkit/project_state.py`, `scripts/toolkit/artifacts.py`, `scripts/toolkit/invalidation.py`, `scripts/toolkit/validation.py` | Phase, artifact, invalidation, and structural checks now have separate owners. |
| `tests/test_assets.py` | replaced | replaced | `tests/test_artifacts.py`, `tests/test_validation.py`, `tests/test_migration_audit.py` | Replacement tests exercise immutable project assets and audit completeness. |
| `tests/test_coverage.py` | migrated | migrated | `tests/test_coverage.py` | Coverage regressions are retained at the new pure-library boundary. |
| `tests/test_router.py` | replaced | replaced | `tests/test_package.py`, `tests/test_skill_contracts.py` | Tests target package discovery and exact capability ownership. |
| `tests/test_state.py` | replaced | replaced | `tests/test_project_state.py`, `tests/test_artifacts.py`, `tests/test_invalidation.py`, `tests/test_validation.py` | State behavior is covered through the replacement boundaries. |

## Retained rules

- Confirmed real voice timing, not an estimate, drives production timing.
- Narration and approved semantic intent remain immutable upstream artifacts.
- Every semantic beat needs meaningful visual coverage or stable evidence.
- Important evidence, formulas, numbers, and conclusions require declared readable holds.
- Character action must teach the beat and belong credibly to its environment.
- Real evidence, editable graphics, formulas, and UI are preferred when clearer.
- Required Demos keep an explicit lifecycle.
- Project assets remain isolated unless an explicit, validated promotion creates a new artifact.

## Rejected rules

- A monolithic director owning planning, production, review, and handoff.
- Mandatory serial generation for dependency-independent shots.
- A blanket ban on frame inspection while claiming real-frame verification.
- A single `complete` state that conflates production, audit, and export handoff.
- Universal 0.8–1.2 second state changes or 3–4 second explanation groups.
- A hardcoded machine-local durable library limited to one character-action class.

## Retirement gate

This audit only establishes disposition coverage. It does not authorize removal
or modification of the installed legacy skill. Retirement remains blocked until
the replacement plugin passes the recovery and representative-slice smoke tests
and the user gives execution-time approval for the exact legacy directory.

# Migration Audit: knowledge-video-visual-director

This report inventories the installed legacy skill without modifying it. The
legacy root is supplied at audit time; no machine-local legacy path is part of
the replacement library. Every source hash is compared with the committed
baseline, so a same-path content change blocks this auditable retirement gate.

## Summary

- Legacy files inventoried: 19
- Expected stable legacy files: 19
- Missing expected legacy files: 0
- Baseline manifest: `references/policies/knowledge-video-visual-director-baseline.json`
- Content hash mismatches: 0
- Executable legacy scripts: 6
- Undisposed executable scripts: 0
- Lifecycle categories: 5 migrated, 13 replaced, 1 retired
- Dispositions: 5 migrated, 11 replaced, 2 externalized, 1 rejected

## File dispositions

| Legacy file | Source SHA-256 | Category | Disposition | New owner paths | Rationale |
|---|---|---|---|---|---|
| `SKILL.md` | `e691ae78a9320d14c324f0ecef049a0269a85f5d2960489775db8738ef8dc321` | replaced | replaced | `skills/video-director/SKILL.md` | The monolithic entrypoint is split into bounded capability owners. |
| `agents/openai.yaml` | `24d52b2bf121194813c31e5c098d1fe9f74279babd111f14cb2167ddbd073548` | replaced | replaced | `agents/openai.yaml` | Plugin-facing metadata now names the replacement coordinator. |
| `assets/character-model-sheet.png` | `7aa59331eb620688f50aa5e11a1960521903b0e31a86f01330e7016f6e88b3a6` | retired | rejected | `references/policies/project-assets.md` | A project-specific character baseline must not become a plugin-global asset. |
| `references/audit.md` | `424553ef0d54ea1944932f4ccbf7b2cf06056ce553376ae5dc5e1d43a92c9992` | migrated | migrated | `references/policies/narration-and-coverage.md`, `references/policies/project-assets.md`, `skills/structural-validator/SKILL.md` | Objective coverage, evidence, and asset rules survive; subjective acceptance remains a user review. |
| `references/plan.md` | `a91605cf46633afaf1dbfebd44a4b266f41499756976e704d0c5a21e5ca61b87` | migrated | migrated | `references/policies/narration-and-coverage.md`, `references/policies/visual-carriers.md` | Voice timing, semantic coverage, and meaningful holds are retained without universal pacing constants. |
| `references/produce.md` | `53849f0aa8d48a900149c856d5abbf8d949ff4162ebc91ca220aa6d6d8acecfe` | replaced | replaced | `skills/scene-producer/SKILL.md`, `skills/motion-director/SKILL.md`, `skills/timeline-assembler/SKILL.md` | Production is owned by isolated task capabilities and immutable contracts. |
| `references/scene-patterns.json` | `7c3d317192736f98065ee2b18019b7c90513dff2e0bdc66671dfcc636393254d` | replaced | externalized | `registries/recipes/video-shotcraft-index.json`, `scripts/toolkit/registry.py` | Creative recipes are compact registry metadata loaded through external implementation references. |
| `references/start.md` | `f413902d77efb6d47de4d03eb034d843d6c04ff8e78502e43191ebeb885275b7` | replaced | replaced | `skills/video-project-manager/SKILL.md`, `references/policies/project-assets.md` | Project identity and isolation are enforced by project state and artifact policy. |
| `routing-manifest.json` | `ae2400283db5004ad36eac12d036b2b2969eca4595af2dbd21a20ef4d8d48dab` | replaced | replaced | `skills/video-director/SKILL.md`, `skills/video-project-manager/SKILL.md` | Project phase and one ready task now drive routing. |
| `scripts/search_assets.py` | `0f036c30b74179b34351c79624a786d819287b6514cde6efb9088d18ed79f7e9` | replaced | replaced | `scripts/toolkit/artifacts.py`, `references/policies/project-assets.md` | Machine-local TSV lookup is replaced by project artifacts and explicit promotion policy. |
| `scripts/select_scene_patterns.py` | `c715cc23928c88a77a54c8c03a894cc10ca5d769b445a768a62a00c38773f7e4` | replaced | externalized | `scripts/toolkit/registry.py`, `scripts/search_registry.py` | Deterministic metadata scoring moved to the versioned registry boundary. |
| `scripts/validate_coverage.py` | `b6f2f7f8a09e3de244deb426355e896307c464a53c2ba8f4ed6e4d7e09d27b5b` | migrated | migrated | `scripts/toolkit/coverage.py` | Deterministic semantic coverage becomes a pure structured-issue evaluator. |
| `scripts/validate_library.py` | `d7755e70b07ede8a3707ea60c1d63ef37df2c78f9fd7c0deb80671ed8f7a47bf` | migrated | migrated | `scripts/toolkit/artifacts.py`, `scripts/toolkit/validation.py`, `references/policies/project-assets.md` | Safe paths, exact legacy filename checks, neutral action metadata, provenance, promotion ownership, and compact isolated image-inspection evidence move to metadata-only structural validation. |
| `scripts/validate_router.py` | `d7a2cbad1fb10fbd25ea70d4ce42087a5cda2c67f3758bfdba5bda621f37f992` | replaced | replaced | `scripts/validate_package.py`, `tests/test_skill_contracts.py` | Package and child-capability contracts replace word-count routing validation. |
| `scripts/validate_state.py` | `31dc93e7ee90f4c84612a68150be58120e735c9d910f7f391c98fe44982a918c` | replaced | replaced | `scripts/toolkit/project_state.py`, `scripts/toolkit/artifacts.py`, `scripts/toolkit/invalidation.py`, `scripts/toolkit/validation.py` | Phase, artifact, invalidation, and structural checks now have separate owners. |
| `tests/test_assets.py` | `649f38c735fc1666c571b6b21aa040b79c2a649b350f827c42e8ee6b04ac0a84` | replaced | replaced | `tests/test_artifacts.py`, `tests/test_validation.py`, `tests/test_migration_audit.py` | Replacement tests exercise immutable project assets and audit completeness. |
| `tests/test_coverage.py` | `923cae2e8d4e5ed74477070cea49694757291d52c7991065eca88332c1a156f9` | migrated | migrated | `tests/test_coverage.py` | Coverage regressions are retained at the new pure-library boundary. |
| `tests/test_router.py` | `b39c9091de7e08e9a99259504c33629709d9a83ab7097fba37540832206a8ac2` | replaced | replaced | `tests/test_package.py`, `tests/test_skill_contracts.py` | Tests target package discovery and exact capability ownership. |
| `tests/test_state.py` | `171de88bb420e52616e48ca585e6bf21165a2137707c93bdf9653570749a2622` | replaced | replaced | `tests/test_project_state.py`, `tests/test_artifacts.py`, `tests/test_invalidation.py`, `tests/test_validation.py` | State behavior is covered through the replacement boundaries. |

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
the replacement plugin is host-installed and enabled from its manifest-versioned host cache,
its complete distributable file
inventory and content hashes match the reviewed repository, and required project and
review-pack templates are present. Only generated test/cache and Git scratch are excluded
from that identity check. Its own verifier then runs in an isolated Python subprocess with
external Skill discovery enabled and
must pass the live migration audit, recovery,
four-gate type and lineage counterexamples, a persisted voice-source decision,
current real voice-timing, voice-timing descendant invalidation, and
representative-slice timing-provenance smoke tests before the user gives
execution-time approval for the exact legacy directory. Retirement additionally requires
the ChatCut base Skill plus available `voice.synthesize` and `voice.time` capabilities
owned by ChatCut Voice. Availability alone does not authorize an undeclared provider fallback.

## Retirement events

- 2026-08-28T05:23:34.958074+00:00 — retired exact audited directory `/Users/fantasy/.codex/skills/knowledge-video-visual-director`.

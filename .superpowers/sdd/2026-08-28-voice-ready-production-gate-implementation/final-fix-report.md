# Final Fix Report — Voice-ready Production Gate

Date: 2026-08-28

Branch: `feat/voice-ready-production-gate`

Pre-fix HEAD: `a4f98e5`

Scope: close the nine final-review findings, harden malformed persisted lineage, verify the complete repository result, and create one final commit. Host installation, legacy deletion, merge, and push are intentionally out of scope.

## Finding-to-fix mapping

| # | Review finding | Resolution | Primary regression evidence |
|---|---|---|---|
| 1 | Voice readiness could be inferred from metadata without proving the declared audio file exists and agrees with the Artifact. | Added one canonical project-backed voice validator. It resolves a safe project-contained media path, rejects missing/symlinked/unreadable files, probes real duration, compares it with voiceover and timing metadata, and is used by phase advancement, routing, resume, structural validation, task completion, and installation smoke. | `test_project_voice_verifier_requires_header_duration_agreement`, `test_project_voice_verifier_accepts_a_real_project_wav`, `test_voice_ready_routing_fails_closed_without_project_audio_authority`, and the resume-smoke mismatch regression. |
| 2 | The task-result size/scrubbing boundary applied too narrowly to image results. | Made result sanitation capability-independent and recursive. Forbidden embedded media/prompt-history fields are rejected throughout the persisted result, and the complete serialized envelope—not only one payload field—is capped at 32 KiB. | `test_image_result_budgets_the_full_persisted_envelope` plus task-result payload and nested-media regressions in `tests/test_tasks.py` and `tests/test_image_context.py`. |
| 3 | Image scope was not fully closed or bounded, and continuity access was underspecified. | Closed the image-context schema, required safe unique IDs, bounded every allowlist and the total item count, kept historical access character-only, and allowed at most one exact current-scene continuity exception with `user_requested: true` and a non-empty reason. | `test_current_access_is_exact_allowlist_or_one_user_continuity_exception`, `test_context_is_closed_safe_unique_and_within_its_item_budget`, and compact-result budget tests. |
| 4 | Upgraded v1 projects could retain legacy validation relaxations after migration. | Limited compatibility to recognition/recovery. Once a legacy log is upgraded, canonical v2 file-backed voice authority and Scene Contract timing checks run without an origin-based bypass. | `test_upgraded_legacy_origin_runs_canonical_file_backed_voice_validation` and `test_upgraded_legacy_origin_no_longer_relaxes_scene_timing_authority`. |
| 5 | Retirement/install checks could inspect the wrong cache version and did not prove both ChatCut base and Voice requirements. | Discover the manifest-selected versioned personal-plugin cache, validate critical content in both installed package copies, run smoke in installed isolation, and require ChatCut base plus `voice.synthesize`/`voice.time` skills before retirement can proceed. | Versioned-cache, installed verifier, installed-smoke, fingerprint, template, and retirement regressions in `tests/test_end_to_end.py`. |
| 6 | Caption production and representative-slice assembly were not explicit coordinator routes. | Added phase-specific routing and ownership for `captions.produce` and `representative-slice.produce`, tied both to current voice timing, and prevented full-production expansion before representative-slice approval. | `test_coordinator_routes_captions_and_representative_slice_explicitly`, `test_full_production_captions_route_only_at_production_ready`, and Skill/policy routing tests. |
| 7 | Uploaded-voice review packs assumed a TTS profile. | Resolved uploaded narration from its exact upload lineage and emitted a stable voice review shape with `"profile": null`; no fictional profile is required. | `test_review_pack_resolves_uploaded_voice_without_a_tts_profile`. |
| 8 | Replacing uploaded audio did not invalidate its descendants, and waiting voice tasks could be forced to invent source/profile/upload IDs. | Added exact uploaded-audio descendant invalidation and made voice source, TTS profile, and upload references optional until the corresponding user decision/input exists. Persisted waiting tasks now remain honest and schema-valid. | `test_uploaded_audio_replacement_invalidates_exact_voice_descendants`, `test_create_task_persists_voice_wait_without_optional_artifact_ids`, `test_tts_missing_profile_is_a_persistable_waiting_user_task`, and `test_uploaded_mode_never_requires_a_voice_profile`. |
| 9 | Accepted audio formats, package completeness, and patch-cache invalidation were inconsistent. | Standardized accepted voice media to WAV/MP3/M4A/AAC/FLAC. WAV duration uses bounded standard-library header parsing; compressed formats use bounded `ffprobe` and fail closed. Package validation now requires the final runtime/schema/policy/Skill owners, ChatCut declares the same formats/probe policy, and the plugin version is `0.1.3`. | `test_non_wav_duration_uses_an_available_bounded_probe`, `test_release_runtime_schema_policy_and_skill_files_are_required`, package validation, and manifest checks. |

## RED/GREEN evidence

The review regressions were introduced before their implementations. Recorded RED stages from the final-fix session were:

1. Initial cross-cutting regression batch: **11 failures + 5 errors**.
2. Release/install hardening batch: **7 failures**.
3. Last pre-self-review batch: **1 failure + 1 error**.

The final self-review found two additional malformed-parent crash paths:

- `VoiceBundleTests.test_unhashable_uploaded_audio_parents_return_a_lineage_issue`
- `PrepareVoiceTaskTests.test_tts_mode_treats_unhashable_profile_parents_as_unapproved`

Before the guards, both tests errored at an eager `set(...)` conversion with `TypeError: unhashable type: 'list'`. The fixes validate that parents are lists of safe string IDs before set comparison. GREEN evidence:

- The two new regressions: **2 passed**.
- `tests.test_voice tests.test_voice_tasks`: **48 passed**.
- Focused changed-area suite: **301 passed**.
- Full discovery suite: **367 passed in 11.944s**.

## Fresh final verification matrix

| Check | Result |
|---|---|
| `PYTHONPYCACHEPREFIX=/tmp/video-toolkit-voice-ready-final python3 -m unittest discover -s tests -v` | 367 passed in 11.944s (recorded immediately before the final handoff; the tree was unchanged before the checks below). |
| `PYTHONPYCACHEPREFIX=/tmp/video-toolkit-voice-ready-final python3 -m py_compile scripts/toolkit/*.py scripts/*.py tests/*.py` | Exit 0. |
| `python3 scripts/validate_package.py` | Exit 0: `package valid`. |
| `python3 scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .` | Exit 0: 19 legacy files, 0 undisposed executables. |
| `python3 scripts/verify_installation.py --repo . --require-skill video-director --require-resume-smoke --check-external-skills` | Exit 0 with `ok: true`; repository plugin valid; `voiceover-producer` present; ChatCut base, Voice synthesis, and Voice timing available; all 11 resume-smoke checks passed; representative slice uses `voice-timing-v1`; no warnings or errors. |
| `git diff --check` | Exit 0, no output. |

## Design decisions

- Production readiness is a project-backed fact, not a metadata-only assertion. All downstream gates consume the same authoritative validator.
- Persisted project defects fail closed with stable issue/warning codes; malformed user/project data does not crash recovery or task preparation.
- Uploaded voice and TTS have separate, explicit lineage. Uploaded mode has no TTS profile, while TTS cannot silently switch provider or voice.
- General task-result sanitation is independent of media classification so an unknown/new capability cannot bypass payload and size controls.
- Image authorization is exact-ID and budget based. Historical scene imagery remains forbidden; the only current-scene exception is singular, explicit, and user-requested.
- Legacy v1 recognition enables append-only migration but never weakens validation after the upgraded event exists.
- Installed-cache checks bind to the release manifest version and content fingerprint instead of accepting any plausible cache directory.
- Audio probing has deterministic bounds and fails closed: standard-library parsing for WAV, `ffprobe` for accepted compressed formats.

## Remaining concerns and deferred execution

- Compressed-audio readiness requires a working `ffprobe`; without it, MP3/M4A/AAC/FLAC validation intentionally blocks rather than trusting metadata.
- The external ChatCut provider was capability-checked but no real synthesis/timing job was submitted during this repository-only verification.
- The `0.1.3` plugin was not installed or enabled on the host, and the legacy Skill was not deleted. Those are separate execution-time operations requiring the requested host scope/approval.
- This branch and linked worktree must remain intact after the final commit. No merge or push is part of this run.

# Prerequisite Gate Report: Visual Isolation

## Scope

Close the visual-isolation prerequisite before beginning the voice-timed
semantic-beats implementation. This gate used JSON/dict/string/structural
probes only; no media content was opened, decoded, rendered, extracted,
displayed, or perceptually inspected.

## RED evidence (inherited scoped review)

The prerequisite brief was created from the prior scoped review of `dd12c7b`.
That review recorded accepted counterexamples for:

- `artifact_checksum_backup_base64`
- `artifact_disguised_numeric_samples`
- `artifact_unlisted_remote_scheme`
- `base64url_64`
- `low_entropy_base64_64`
- mixed current and legacy authority accepted by schema
- an audio MIME accepted by schema
- generate/edit/render success without compatible visual output

This report does not claim to have rerun that historical revision or reproduce
its exact output.

## GREEN evidence (fresh)

The current implementation closes Artifact extension fields at runtime and in
the Artifact schema, applies the universal structural scrub on create/read/
completion/validation/recovery paths, and keeps recovery projections compact.
Current visual authority excludes all legacy authority fields in schema and
runtime; persisted legacy remains in its explicit read-only compatibility path.
Handoff MIME metadata is constrained to compatible image/video kinds. Producer
operations require a compatible visual Artifact and non-empty matching
`media.kind`; image/video inspect operations are report-only.

Fresh metadata-only verification in the isolated worktree:

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_validation tests.test_end_to_end.CoordinatorTests tests.test_package tests.test_end_to_end -v
# 326 tests: OK (skipped=4)

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --with jsonschema python -m unittest discover -s tests -v
# 478 tests: OK (skipped=4)

python3 scripts/validate_package.py
# package valid
```

`rg -n "T[B]D|T[O]DO|implement l[a]ter|similar t[o]|read_bytes\\(|Image\\.open|cv2\\.|ffmpeg|ffprobe" scripts/toolkit/visual_media_context.py references/policies/visual-media-isolation.md skills tests/test_visual_media_context.py`
found only the policy/documentation mention of `ffprobe` in
`skills/voiceover-producer/SKILL.md`; it is not an executable visual-media
access call. `git diff --check` completed cleanly.

## Release fingerprint

`tests/test_artifacts.py` and `scripts/migration_audit.py` are required and
fingerprinted. The manifest release fingerprint was refreshed only after the
final code and test changes; release version remains `0.1.4`.

## Initial implementation checkpoint

The initial implementation was committed for independent review. The review
then found follow-up parity gaps, which are documented and closed in the three
fix rounds below. Task 1 was not started.

## Fix round 1: structural boundary follow-up

### Changes

- Replaced the broad key-name URI exemption with a closed, field-specific
  non-media token contract. Only the documented `adapter-selected:<adapter>`
  check and `user:`/`chatcut:` provenance tokens remain eligible; arbitrary
  schemes such as `gopher:` are rejected without decoding.
- Made image/video inspect operations reject a handoff MIME type for the
  opposite visual kind even when `media.kind` is omitted. Empty report-only
  media metadata remains valid.
- Aligned closed promotion metadata in the Artifact schema and runtime:
  promotion text may be bounded-empty for existing semantic validation,
  applicability uses the same type, and validation evidence permits only a
  bounded string or one closed empty-object placeholder with no duplicates.
- Tightened artifact path validation to reject lexical `.` and `..` segments,
  matching the existing Draft 2020-12 path pattern.

### RED evidence

The focused tests were added before the implementation and then failed as
expected: `provenance: gopher:opaque-resource` was accepted through both the
universal result and Artifact paths; MIME-only opposite-kind image/video
inspect handoffs were accepted; schema/runtime promotion fixtures diverged for
empty valid fields, duplicate evidence, and lexical dot paths.

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_visual_media_context.VisualMediaContextTests.test_universal_scrub_rejects_scheme_encoding_and_alias_bypasses tests.test_visual_media_context.VisualMediaContextTests.test_inspect_operations_are_report_only tests.test_artifacts.ArtifactTests.test_artifact_extension_contract_rejects_reviewed_side_channel_probes tests.test_artifacts.ArtifactTests.test_artifact_schema_and_runtime_match_closed_promotion_metadata -v
# Ran 4 tests; FAILED (9 failures)
```

### GREEN evidence

The same four probes passed after the fix:

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_visual_media_context.VisualMediaContextTests.test_universal_scrub_rejects_scheme_encoding_and_alias_bypasses tests.test_visual_media_context.VisualMediaContextTests.test_inspect_operations_are_report_only tests.test_artifacts.ArtifactTests.test_artifact_extension_contract_rejects_reviewed_side_channel_probes tests.test_artifacts.ArtifactTests.test_artifact_schema_and_runtime_match_closed_promotion_metadata -v
# Ran 4 tests in 0.003s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_validation -v
# Ran 208 tests in 3.380s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_validation tests.test_package -v
# Ran 238 tests in 5.140s; OK

python3 scripts/validate_package.py
# package valid

git diff --check
# no output (clean)
```

All work remained JSON/dict/string/schema-only; no media content was decoded,
opened, rendered, played, displayed, extracted, or inspected.

## Fix round 2: colon-free generic identifiers

### Changes

- Made generic Artifact, task, context, scene, voice, and coverage identifiers
  colon-free in their runtime patterns and matching Draft 2020-12 schemas.
  This includes nested `promotion.provenance.artifact_id` and `project_id`.
- Added closed task-envelope and task-result schema contracts for generic task,
  input, and output Artifact IDs; runtime task ID validation now uses the same
  bounded generic-ID pattern.
- Retained colons only for explicit non-media contracts: `user:` and
  `user-upload:` provenance, `chatcut:` provenance/installed skills,
  `adapter-selected:` checks, and
  `isolated-image-inspect:` validation evidence. The adapter token validator
  is intentionally separate because it validates registered skill namespaces,
  not Artifact/task identity.
- Added the observed upload provenance and isolated-alpha inspection evidence
  to their exact field-specific allowlists. Arbitrary schemes remain rejected.

### RED evidence

The focused fixture added actual nested `promotion.provenance` IDs and generic
task/result IDs before implementation. Fresh execution showed the universal
runtime scrub already rejected `gopher:` nested values, while the Artifact
schema and task-envelope schema still accepted colon-bearing generic IDs.

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts.ArtifactTests.test_artifact_schema_and_runtime_match_closed_promotion_metadata tests.test_artifacts.ArtifactTests.test_colon_free_ids_keep_explicit_provenance_namespaces tests.test_package.PackageTests.test_generic_task_and_result_ids_are_colon_free -v
# Ran 3 tests; FAILED (4 failures)
```

### GREEN evidence

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts.ArtifactTests.test_artifact_schema_and_runtime_match_closed_promotion_metadata tests.test_artifacts.ArtifactTests.test_colon_free_ids_keep_explicit_provenance_namespaces tests.test_artifacts.ArtifactTests.test_artifact_keeps_evidence_backed_explicit_scheme_tokens tests.test_package.PackageTests.test_generic_task_and_result_ids_are_colon_free tests.test_voice.VoiceSchemaTests -v
# Ran 7 tests; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_voice_tasks tests.test_voice tests.test_image_context tests.test_validation -v
# Ran 275 tests in 4.164s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_coverage -v
# Ran 12 tests in 0.000s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_package tests.test_voice_tasks tests.test_voice tests.test_image_context tests.test_validation tests.test_coverage -v
# Ran 318 tests; OK

python3 scripts/validate_package.py
# package valid

git diff --check
# no output (clean)
```

All work remained JSON/dict/string/schema-only; no media content was decoded,
opened, rendered, played, displayed, extracted, or inspected.

## Fix round 3: task result worker authority IDs

### Changes

- Aligned `task-result.worker_id` and `claim_token` with the bounded,
  colon-free generic-ID definition in both Draft 2020-12 schema and runtime.
- Applied the same worker-ID validation before `claim_task` creates a claim, so
  an unsafe worker cannot acquire work that its result is unable to complete.
  Generated claim tokens remain 32-character UUID hexadecimal tokens and
  existing `worker-a` identifiers remain valid.
- Corrected the existing resume-smoke provenance fixtures to use their
  documented field-specific `user:` namespace instead of an undeclared
  `smoke:` URI-like prefix, exposed by the lifecycle coverage run.

### RED evidence

The focused schema/runtime cases were added before the implementation. They
proved that colon-bearing, slash-bearing, and oversized values were accepted
by the task-result schema, and that `claim_task` wrote a `gopher:` worker ID
despite the result scrub rejecting scheme-shaped values.

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_package.PackageTests.test_task_result_worker_and_claim_ids_match_safe_id_contract tests.test_tasks.TaskTests.test_claim_rejects_unsafe_worker_id_before_writing_a_claim -v
# Ran 2 tests; FAILED (5 failures)
```

### GREEN evidence

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_package.PackageTests.test_task_result_worker_and_claim_ids_match_safe_id_contract tests.test_tasks.TaskTests.test_claim_rejects_unsafe_worker_id_before_writing_a_claim -v
# Ran 2 tests in 0.028s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_tasks tests.test_package tests.test_visual_media_context tests.test_end_to_end -v
# Ran 210 tests in 6.597s; OK (skipped=4)

python3 scripts/validate_package.py
# package valid

git diff --check
# no output (clean)
```

All work remained JSON/dict/string/schema-only; no media content was decoded,
opened, rendered, played, displayed, extracted, or inspected.

## Final reviewed state

The prerequisite gate is closed at code commit `a85019a` after one task review
and three scoped fix/re-review rounds. The final scoped reviewer reported every
Critical and Important finding addressed, with no new breakage.

Commit chain:

- `fbaa73e` — close the original visual-isolation prerequisite set;
- `fc122e8` — close URI, inspect-MIME, promotion, and lexical-path parity gaps;
- `ab31fb8` — separate colon-free generic identifiers from explicit non-media
  namespaces;
- `a85019a` — align task-result worker and claim identifiers.

Fresh verification at exact code HEAD `a85019a`:

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest discover -s tests -q
# Ran 484 tests in 7.884s; OK (skipped=4)

python3 scripts/validate_package.py
# package valid

python3 -c "... compare manifest release_fingerprint with _release_fingerprint(root) ..."
# sha256:1db956c2c043833f3c7f9a0d5bab8e970afc980cc8c79d214f42fbeff46eea50
# sha256:1db956c2c043833f3c7f9a0d5bab8e970afc980cc8c79d214f42fbeff46eea50
# True

git diff --check 1a4739d..a85019a
# no output (clean)

git status --short --branch
# ## codex/visual-media-isolation
```

The prescribed forbidden-call scan found only the literal `ffprobe` word in
the voiceover-producer documentation; it found no executable visual-media or
Base64-decoder call in the coordinator-safe visual boundary. No install, push,
or Task 1 work was performed.

## Fix round 4: structural encoding and voice/Artifact boundary parity

### Changes

- Extended structural Base64/Base64URL detection across whitespace-separated
  chunks and removed the blanket `path` exemption. Typed safe IDs and explicit
  checksums remain exempt only in their exact fields.
- Rejected untyped numeric arrays under every key while retaining the closed,
  bounded voice timing-segment shape.
- Restricted every task-result handoff MIME to `image/` or `video/`, including
  omitted and generic `visual` kinds, matching runtime acceptance.
- Aligned voice schemas and runtime bounds with persisted Artifact limits for
  IDs, paths, text, speaking rate, durations, and timing segment ceilings.
  Voice bundle screening applies those shared limits without masking semantic
  issue codes such as invalid profile fields or unsafe media paths; full
  Artifact validation remains authoritative at persistence and read boundaries.
- Updated the fixed-length path fixture to use schema-safe punctuation rather
  than a Base64URL-shaped repeated token, and removed an obsolete numeric-key
  heuristic constant.

### RED evidence

The following metadata-only command was run before the round-four production
changes. One Package method name was stale, yielding one loader error; the
remaining focused probes produced the expected 19 failures for path-carried,
whitespace-split, and low-entropy encodings, untyped numeric arrays, MIME
parity, and voice/Artifact bound parity.

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts.ArtifactTests.test_artifact_rejects_structural_encodings_at_create_and_read tests.test_tasks.TaskTests.test_completion_rejects_structural_encodings_in_error_text tests.test_validation.PersistedVisualMediaValidationTests.test_recovery_rejects_structural_encodings_in_persisted_result_text tests.test_visual_media_context.VisualMediaContextTests.test_universal_scrub_rejects_neutral_numeric_arrays_and_encoded_paths tests.test_package.PackageTests.test_task_result_visual_media_handoff_mime_schema_runtime_parity tests.test_voice.VoiceSchemaTests.test_voice_and_artifact_boundaries_share_all_persisted_limits -v
# Ran 6 tests; FAILED (failures=19, errors=1)
```

### GREEN evidence

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts.ArtifactTests.test_artifact_rejects_structural_encodings_at_create_and_read tests.test_tasks.TaskTests.test_completion_rejects_structural_encodings_in_error_text tests.test_validation.PersistedVisualMediaValidationTests.test_recovery_rejects_structural_encodings_in_persisted_result_text tests.test_visual_media_context.VisualMediaContextTests.test_universal_scrub_rejects_neutral_numeric_arrays_and_encoded_paths tests.test_package.PackageTests.test_draft202012_and_runtime_match_handoff_mime_kind_decisions tests.test_voice.VoiceSchemaTests.test_voice_and_artifact_boundaries_share_all_persisted_limits -v
# Ran 6 tests in 0.058s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_voice tests.test_voice_tasks tests.test_visual_media_context -v
# Ran 80 tests in 1.551s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_validation tests.test_end_to_end tests.test_package tests.test_voice tests.test_voice_tasks tests.test_image_context tests.test_coverage -v
# Before the fingerprint refresh: Ran 387 tests; FAILED (failures=2, errors=17, skipped=4).
# One assertion was updated to the new MIME constraint; the other failure and all 17 errors were invalid:release-fingerprint consequences.
```

All probes in this round manipulated only dictionaries, strings, schemas, and
filesystem metadata. No media was opened, decoded, rendered, played,
displayed, extracted, or perceptually inspected.

## Fix round 5: alignment-independent encoding fragments and voice list bounds

### Changes

- Removed the incorrect intermediate-quartet alignment condition from the
  structural Base64/Base64URL scrub. It now joins whitespace-separated
  unpadded fragments at any quantum position and separately recognizes a
  bounded sequence of independently padded canonical fragments without
  decoding either representation.
- Added source-independent coverage for one-, two-, and three-character
  whitespace splits, space/tab/CRLF separators, Base64URL fragments, and
  independently padded fragments. The same encoded values are exercised at
  Artifact create/read, task completion, and persisted-result recovery.
- Applied Artifact's `parents` maximum of 256 to voice runtime identity lists,
  and applied Artifact's pronunciation maximum count and 500-character item
  limit before records can be accepted by voice runtime. Duplicate
  pronunciations remain available to the semantic validator so it can retain
  its stable `invalid-voice-profile` issue code.
- Expanded the voice/Artifact parity matrix with accepted and rejected parent
  counts and pronunciation count/text boundaries in both schema and runtime
  assertions.

### RED evidence

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts.ArtifactTests.test_artifact_rejects_structural_encodings_at_create_and_read tests.test_tasks.TaskTests.test_completion_rejects_structural_encodings_in_error_text tests.test_validation.PersistedVisualMediaValidationTests.test_recovery_rejects_structural_encodings_in_persisted_result_text tests.test_voice.VoiceSchemaTests.test_voice_and_artifact_boundaries_share_all_persisted_limits -v
# Ran 4 tests; FAILED (failures=14, errors=4)
```

The failures captured three-character space/tab/CRLF fragments, Base64URL
fragments, independently padded short fragments, and voice records with 257
parents, 257 pronunciations, or a 501-character pronunciation. Some later
completion subtests reported an inactive claim after an accepted fragment had
incorrectly consumed the one claim; this is expected evidence of the same
completion-boundary bypass.

### GREEN evidence

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts.ArtifactTests.test_artifact_rejects_structural_encodings_at_create_and_read tests.test_tasks.TaskTests.test_completion_rejects_structural_encodings_in_error_text tests.test_validation.PersistedVisualMediaValidationTests.test_recovery_rejects_structural_encodings_in_persisted_result_text tests.test_visual_media_context.VisualMediaContextTests.test_universal_scrub_rejects_neutral_numeric_arrays_and_encoded_paths tests.test_package.PackageTests.test_draft202012_and_runtime_match_handoff_mime_kind_decisions tests.test_voice.VoiceSchemaTests.test_voice_and_artifact_boundaries_share_all_persisted_limits -v
# Ran 6 tests in 0.176s; OK

UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_voice tests.test_voice_tasks tests.test_visual_media_context -v
# Ran 80 tests in 1.017s; OK
```

All round-five probes are metadata-only: strings, dictionaries, JSON schema,
and bounded structural validation. No media was opened, decoded, rendered,
played, displayed, extracted, or perceptually inspected.

### Post-fingerprint covering evidence

```text
UV_CACHE_DIR=/private/tmp/visual-media-isolation-uv-cache uv run --offline --with jsonschema python -m unittest tests.test_artifacts tests.test_visual_media_context tests.test_tasks tests.test_validation tests.test_end_to_end tests.test_package tests.test_voice tests.test_voice_tasks tests.test_image_context tests.test_coverage -v
# Ran 387 tests in 7.831s; OK (skipped=4)

python3 scripts/validate_package.py
# package valid

git diff --check
# no output (clean)
```

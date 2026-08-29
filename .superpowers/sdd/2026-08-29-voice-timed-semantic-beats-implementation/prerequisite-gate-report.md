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

## Conclusion

The prerequisite gate is closed. Task 1 has not been started.

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

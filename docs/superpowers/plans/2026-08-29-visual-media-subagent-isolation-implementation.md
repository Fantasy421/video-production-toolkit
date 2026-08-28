# Visual Media Subagent Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce that every image/video operation runs in one bounded isolated child agent while the primary coordinator sees only compact structural metadata and one unopened preview path.

**Architecture:** Add a closed visual-media context and a focused metadata-only runtime module, then enforce the same classifier and scrubber at task creation, claim, completion, persisted validation, and installed-package smoke tests. Keep `image_context.py` as a compatibility adapter for existing v2 image records; all new task records use `visual_media_operation`, `visual_media_context`, and `visual_media_handoff`.

**Tech Stack:** Python 3 standard library, JSON Schema draft 2020-12, `unittest`, immutable JSON task/artifact records, Codex Skill Markdown contracts.

**Spec:** docs/superpowers/specs/2026-08-29-visual-media-subagent-isolation-design.md

## Global Constraints

- The primary implementation and verification conversation must not generate, edit, open, play, decode, render, screenshot, extract, display, or perceptually inspect image/video payloads.
- Every visual-media operation is executed by exactly one isolated child agent with one scope: `scene-contract`, `character-asset-batch`, or `review-batch`.
- Historical access is `character-only`; one user-requested continuity exception may name one exact current visual Artifact ID and a non-empty reason.
- Paths are metadata, never authority; every returned media path is bound to an allowed returned Artifact ID.
- The coordinator may relay at most one `review_preview_path` and must never dereference it.
- Runtime classification trusts capability, declared operation, input/output Artifact metadata, and returned content rather than worker declarations.
- Every result, including `none` tasks, passes the same recursive leak scrub and the fixed `32768`-byte serialized-result budget.
- Existing v2 image records remain readable; new records use only the visual-media contract, and ambiguous legacy records become blocked without rewriting history.
- Audio is outside this feature; `voiceover-producer` remains responsible for voice preparation, and the coordinator does not play audio.
- Test fixtures use structural metadata and deterministic tiny headers only; tests never open or perceptually inspect media.

---

### Task 1: Closed Visual-Media Schemas and Legacy Projection

**Files:**
- Create: `references/schemas/visual-media-task-context.schema.json`
- Modify: `references/schemas/task-envelope.schema.json`
- Modify: `references/schemas/task-result.schema.json`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: legacy `constraints.image_operation`, `constraints.image_context`, and `result.image_handoff` for read compatibility.
- Produces: closed `constraints.visual_media_operation`, `constraints.visual_media_context`, and `result.visual_media_handoff` schemas used by Tasks 2–8.

- [ ] **Step 1: Add failing schema-contract tests**

Add tests that load all three schemas and assert the exact operation enum, exact scope enum, `historical_access: character-only`, `max_review_previews.maximum == 1`, `context_budget_bytes.maximum == 32768`, and a `visual_media_handoff` with singular `review_preview_path`. Also assert new envelope conditionals require context for every operation except `none` and forbid context for `none`.

```python
def test_visual_media_schema_is_closed_and_bounded(self):
    schema = json.loads((ROOT / "references/schemas/visual-media-task-context.schema.json").read_text())
    self.assertEqual(
        ["scene-contract", "character-asset-batch", "review-batch"],
        schema["properties"]["scope_identity"]["properties"]["kind"]["enum"],
    )
    self.assertEqual("character-only", schema["properties"]["historical_access"]["const"])
    self.assertEqual(1, schema["properties"]["max_review_previews"]["maximum"])
    self.assertEqual(32768, schema["properties"]["context_budget_bytes"]["maximum"])

def test_task_envelope_declares_exact_visual_media_operations(self):
    schema = json.loads((ROOT / "references/schemas/task-envelope.schema.json").read_text())
    operations = schema["properties"]["constraints"]["properties"]["visual_media_operation"]["enum"]
    self.assertEqual([
        "none", "image-generate", "image-edit", "image-inspect",
        "video-generate", "video-edit", "video-render", "video-inspect",
        "frame-extract", "contact-sheet",
    ], operations)
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run: `python -m unittest tests.test_package.PackageTests.test_visual_media_schema_is_closed_and_bounded tests.test_package.PackageTests.test_task_envelope_declares_exact_visual_media_operations -v`

Expected: FAIL because `visual-media-task-context.schema.json` and the new properties do not exist.

- [ ] **Step 3: Implement the closed schemas**

Create a context schema whose required keys are exactly:

```json
[
  "scope_identity",
  "allowed_artifact_ids",
  "historical_access",
  "continuity_exception",
  "max_review_previews",
  "context_budget_bytes"
]
```

Use `additionalProperties: false`; bound `allowed_artifact_ids` to 16 unique safe IDs; define `scope_identity.id` as either one safe ID for scene/character scope or 1–8 unique safe IDs for review scope; define the exception as either `null` or `{artifact_id, user_requested: true, reason}`. Update the envelope conditionals so `none` has no context and every other new operation requires it. Add `visual_media_handoff` to the result with closed fields `artifact_ids`, `paths`, `media`, `checks`, `issues`, `summary`, and singular `review_preview_path`; retain `image_handoff` only as a deprecated compatibility property.

- [ ] **Step 4: Run schema and existing package tests**

Run: `python -m unittest tests.test_package -v`

Expected: PASS, including legacy image-schema assertions.

- [ ] **Step 5: Commit the schema contract**

```bash
git add references/schemas/visual-media-task-context.schema.json references/schemas/task-envelope.schema.json references/schemas/task-result.schema.json tests/test_package.py
git commit -m "feat: define closed visual media task contract"
```

### Task 2: Metadata-Only Visual-Media Runtime

**Files:**
- Create: `scripts/toolkit/visual_media_context.py`
- Modify: `scripts/toolkit/image_context.py`
- Create: `tests/test_visual_media_context.py`
- Test: `tests/test_image_context.py`

**Interfaces:**
- Consumes: `Mapping[str, Any]` envelopes/artifacts/results and legacy image helpers.
- Produces: `validate_visual_media_context(context) -> dict[str, Any]`, `project_legacy_image_context(envelope) -> dict[str, Any] | None`, `classify_visual_media_artifact(artifact) -> str`, `classify_visual_media_task(envelope, artifacts, produced_artifacts=()) -> str`, `validate_declared_visual_media_inputs(envelope, artifacts) -> None`, `compact_visual_media_result(context, result) -> dict[str, Any]`, `validate_visual_media_result_envelope(context, result) -> None`, and `validate_result_envelope(result) -> None`.

- [ ] **Step 1: Write focused RED tests for scope, classification, and compatibility**

Cover all ten operations, the three mutually exclusive scope shapes, review-batch maximum 8, exact continuity exception, character-only historical access, visual classification from `kind`, MIME type, suffix, capability, output contract, and returned Artifact metadata. Include harmless audio/data/document cases and projection of legacy `generate`/`image-inspect` records.

```python
def test_visual_artifacts_and_operations_cannot_classify_as_none(self):
    envelope = self.envelope(operation="none", inputs=["clip-v1"])
    artifacts = {"clip-v1": {"artifact_id": "clip-v1", "type": "scene-video", "media_kind": "video", "path": "media/clip-v1.mp4"}}
    with self.assertRaisesRegex(ValueError, "visual media.*none"):
        validate_declared_visual_media_inputs(envelope, artifacts)

def test_review_scope_is_exact_and_bounded(self):
    context = self.context(scope={"kind": "review-batch", "id": [f"asset-{i}" for i in range(9)]})
    with self.assertRaisesRegex(ValueError, "review-batch"):
        validate_visual_media_context(context)
```

- [ ] **Step 2: Run the new runtime tests and verify RED**

Run: `python -m unittest tests.test_visual_media_context -v`

Expected: FAIL with `ModuleNotFoundError: scripts.toolkit.visual_media_context`.

- [ ] **Step 3: Implement normalization and deterministic classification**

Define immutable sets for operations, visual capabilities, visual artifact types, image/video suffixes, and MIME prefixes. Classification must use metadata only and must never call `Path.read_bytes`, PIL, ffmpeg, ffprobe, browser tools, or media decoders. Reject conflicts such as `media_kind: data` with `.mp4`, unknown context fields, duplicate IDs, neighboring scope IDs, and paths whose Artifact ID is not authorized.

```python
VISUAL_MEDIA_OPERATIONS = frozenset({
    "image-generate", "image-edit", "image-inspect", "video-generate",
    "video-edit", "video-render", "video-inspect", "frame-extract", "contact-sheet",
})
VISUAL_RESULT_BUDGET_BYTES = 32_768

def classify_visual_media_artifact(artifact: Mapping[str, Any]) -> str:
    validate_media_artifact_metadata(artifact)
    kind = artifact.get("media_kind")
    if kind in {"image", "video"}:
        return kind
    if artifact.get("type") in VISUAL_ARTIFACT_TYPES:
        return "visual"
    return "non-visual"
```

- [ ] **Step 4: Implement universal recursive scrub and compact handoff**

Reject bytes, bytearray, memoryview, data URLs, HTTP(S) media URLs, binary magic encoded as Base64, pixel/frame arrays, thumbnails/screenshots/contact sheets, HTML media embedding, prompt-history keys/text, more than one preview path, unsafe paths, unknown fields, and serialized JSON over 32768 bytes. Accept IDs, checksums, bounded prose, dimensions, FPS, duration, format, readiness, issue/check codes, and one project-contained preview path.

- [ ] **Step 5: Turn legacy image runtime into a compatibility surface**

Keep its public names import-compatible, but make the shared `validate_result_envelope` delegate to the visual-media scrubber. Project legacy image constraints into the new normalized context without changing persisted records.

- [ ] **Step 6: Run runtime regression tests**

Run: `python -m unittest tests.test_visual_media_context tests.test_image_context -v`

Expected: PASS with no media files opened or generated.

- [ ] **Step 7: Commit the runtime boundary**

```bash
git add scripts/toolkit/visual_media_context.py scripts/toolkit/image_context.py tests/test_visual_media_context.py tests/test_image_context.py
git commit -m "feat: enforce metadata-only visual media boundary"
```

### Task 3: Creation, Claim, and Completion Enforcement

**Files:**
- Modify: `scripts/toolkit/tasks.py`
- Modify: `tests/test_tasks.py`

**Interfaces:**
- Consumes: all Task 2 classifier/validator functions and Task 1 envelope/result fields.
- Produces: lifecycle enforcement in `create_task`, `claim_task`, and `complete_task`; successful new visual tasks persist only `visual_media_handoff`.

- [ ] **Step 1: Add lifecycle RED tests**

Add table-driven tests proving each visual operation requires a context and `constraints.execution_context == "isolated-child-agent"`; visual capability/input/output cannot hide behind `none`; claim revalidates a mutated/legacy persisted envelope; returned visual artifacts from a declared non-visual task are rejected; every result is scrubbed; missing/multiple previews and undeclared paths/IDs fail.

```python
def test_every_visual_operation_requires_isolated_child_at_create_and_claim(self):
    for operation in sorted(VISUAL_MEDIA_OPERATIONS):
        envelope = self.visual_envelope(operation=operation)
        envelope["constraints"]["execution_context"] = "primary-coordinator"
        with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "isolated child"):
            create_task(self.root, envelope)

def test_none_task_cannot_return_visual_artifact(self):
    envelope = self.non_visual_envelope()
    create_task(self.root, envelope)
    claim = claim_task(self.root, envelope["task_id"], "worker-a")
    self.create_artifact("hidden-video-v1", "scene-video", 1, media_kind="video", path="media/hidden-video-v1.mp4")
    with self.assertRaisesRegex(ValueError, "visual media"):
        complete_task(self.root, self.result_for(claim, artifacts=["hidden-video-v1"]))
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `python -m unittest tests.test_tasks.TaskTests.test_every_visual_operation_requires_isolated_child_at_create_and_claim tests.test_tasks.TaskTests.test_none_task_cannot_return_visual_artifact -v`

Expected: FAIL because task lifecycle still enforces image-only fields.

- [ ] **Step 3: Replace image-only lifecycle hooks with visual-media hooks**

In `create_task`, validate classification and exact declared inputs before persistence. In `claim_task`, re-read the immutable envelope and re-run the same validation before returning claim authority. In `complete_task`, run the universal scrub before reading conditional fields, classify produced Artifacts, validate the handoff, compare exact Artifact IDs/status/paths, then publish. Add `visual_media_handoff` to `RESULT_KEYS`; accept `image_handoff` only for a projected legacy envelope and reject both fields appearing together.

- [ ] **Step 4: Run the complete task suite**

Run: `python -m unittest tests.test_tasks -v`

Expected: PASS for new and legacy task records, including retry and concurrency tests.

- [ ] **Step 5: Commit lifecycle enforcement**

```bash
git add scripts/toolkit/tasks.py tests/test_tasks.py
git commit -m "feat: enforce visual isolation through task lifecycle"
```

### Task 4: Persisted Validation and Safe Recovery

**Files:**
- Modify: `scripts/toolkit/validation.py`
- Modify: `tests/test_validation.py`
- Modify: `scripts/verify_installation.py`
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: Task 2 classifiers and Task 3 persisted task/result shapes.
- Produces: stable issue codes `visual-media-context-invalid`, `visual-media-isolation-required`, `visual-media-input-forbidden`, `visual-media-result-invalid`, and `legacy-visual-task-blocked`.

- [ ] **Step 1: Write persisted-project RED tests**

Create structural JSON records for malformed scopes, historical scene/video input, neighboring scene access, `none` laundering, undeclared returned media, leaked result payloads, and ambiguous legacy visual tasks. Assert the exact issue codes and that immutable task/event files are byte-for-byte unchanged.

```python
def test_ambiguous_legacy_visual_task_is_blocked_without_history_rewrite(self):
    path = self.write_task(self.legacy_video_task_without_scope())
    before = path.read_bytes()
    result = validate_project(self.root)
    self.assertIn("legacy-visual-task-blocked", {issue["code"] for issue in result["errors"]})
    self.assertEqual(before, path.read_bytes())
```

- [ ] **Step 2: Run persisted validation tests and verify RED**

Run: `python -m unittest tests.test_validation.ValidationTests.test_ambiguous_legacy_visual_task_is_blocked_without_history_rewrite -v`

Expected: FAIL because persisted validation currently calls image-only rules.

- [ ] **Step 3: Apply identical validation rules to persisted records**

Replace image-only checks in `_check_tasks` with the shared visual-media validators. Convert exceptions to the stable issue codes above. Never broaden, rewrite, or auto-migrate an ambiguous record. Update installed smoke fixture construction to declare `visual_media_operation: none` only for structurally non-visual tasks and use isolated-child metadata for synthetic visual tasks.

- [ ] **Step 4: Run validation and end-to-end suites**

Run: `python -m unittest tests.test_validation tests.test_end_to_end -v`

Expected: PASS, with recovery reporting compact errors and preserving immutable history.

- [ ] **Step 5: Commit persisted enforcement**

```bash
git add scripts/toolkit/validation.py scripts/verify_installation.py tests/test_validation.py tests/test_end_to_end.py
git commit -m "feat: revalidate visual isolation during recovery"
```

### Task 5: Highest-Priority Coordinator and Worker Skill Contracts

**Files:**
- Create: `references/policies/visual-media-isolation.md`
- Modify: `skills/video-director/SKILL.md`
- Modify: `skills/visual-system-designer/SKILL.md`
- Modify: `skills/storyboard-director/SKILL.md`
- Modify: `skills/scene-producer/SKILL.md`
- Modify: `skills/motion-director/SKILL.md`
- Modify: `skills/structural-validator/SKILL.md`
- Modify: `skills/timeline-assembler/SKILL.md`
- Modify: `skills/video-review-packager/SKILL.md`
- Modify: `tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: runtime field names and scope semantics from Tasks 1–4.
- Produces: human/agent-visible routing rules aligned with runtime enforcement.

- [ ] **Step 1: Add RED contract tests for coordinator and every visual worker**

Assert that `video-director` places a `Highest-priority visual-media isolation` section before routing, names image and video prohibitions, forbids preview dereference, requires one isolated child agent, and permits only compact metadata relay. Assert all seven visual workers state `isolated child agent only`, one bounded scope, no project crawl/neighbor discovery, and `visual_media_handoff`. Assert external adapter names appear only under the child-only boundary.

```python
def test_all_visual_workers_require_isolated_child_execution(self):
    workers = (
        "visual-system-designer", "storyboard-director", "scene-producer",
        "motion-director", "structural-validator", "timeline-assembler",
        "video-review-packager",
    )
    for worker in workers:
        text = (ROOT / "skills" / worker / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("isolated child agent only", text, worker)
        self.assertIn("visual_media_handoff", text, worker)
```

- [ ] **Step 2: Run Skill contract tests and verify RED**

Run: `python -m unittest tests.test_skill_contracts -v`

Expected: FAIL because the current wording is image-only and inconsistent across workers.

- [ ] **Step 3: Write the global policy and update coordinator**

The policy must enumerate every prohibited primary-context action, coordinator-safe metadata, exact scopes, historical rule, continuity exception, result scrub, user-review boundary, audio exclusion, and child-only adapters: HyperFrames, VideoShotCraft, Remotion, ChatCut, plus future visual adapters. Put a concise mandatory version at the beginning of `video-director`, before phase routing.

- [ ] **Step 4: Update each worker at its visual execution boundary**

Mark structure-only modes as non-visual but still scrubbed. Mark pixel inspection, previews, rendering, screenshots, frame extraction, contact sheets, and media QA as child-only. Require the claimed immutable envelope and exact Artifact allowlist, and prohibit neighboring scene discovery or project-wide media enumeration.

- [ ] **Step 5: Run Skill and package tests**

Run: `python -m unittest tests.test_skill_contracts tests.test_package -v`

Expected: PASS with all wording matching the new field names.

- [ ] **Step 6: Commit policy and Skill contracts**

```bash
git add references/policies/visual-media-isolation.md skills/video-director/SKILL.md skills/visual-system-designer/SKILL.md skills/storyboard-director/SKILL.md skills/scene-producer/SKILL.md skills/motion-director/SKILL.md skills/structural-validator/SKILL.md skills/timeline-assembler/SKILL.md skills/video-review-packager/SKILL.md tests/test_skill_contracts.py
git commit -m "docs: make visual media isolation the top routing rule"
```

### Task 6: Compact User Review Relay

**Files:**
- Modify: `scripts/build_review_pack.py`
- Modify: `tests/test_review_pack.py`
- Modify: `skills/video-review-packager/SKILL.md`

**Interfaces:**
- Consumes: validated `visual_media_handoff` from Task 3.
- Produces: a compact review manifest containing structural metadata, issue/check codes, and zero or one relayed `review_preview_path` without media dereference.

- [ ] **Step 1: Add RED review-pack tests**

Assert the builder copies one path string without opening it (patch `Path.open`, `Path.read_bytes`, and `Path.read_text` for the preview target to raise), rejects two preview candidates, omits prompts/payloads, and keeps the user as the subjective decision authority.

```python
def test_review_pack_relays_preview_path_without_dereferencing_it(self):
    handoff = self.visual_handoff(review_preview_path="previews/S03-v4-low.mp4")
    with patch("pathlib.Path.read_bytes", side_effect=AssertionError("media dereferenced")):
        pack = build_review_pack(self.root, handoff)
    self.assertEqual("previews/S03-v4-low.mp4", pack["review_preview_path"])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_review_pack -v`

Expected: FAIL because review packaging still consumes the prior image-oriented shape.

- [ ] **Step 3: Implement structural-only packaging**

Accept only the already validated compact handoff fields. Copy strings/scalars into the manifest, cap checks/issues to fixed small lists, and never resolve/open/probe the preview path. The Skill must instruct the coordinator to relay the path and stop for user approval/rejection/revision.

- [ ] **Step 4: Run review-pack tests**

Run: `python -m unittest tests.test_review_pack tests.test_skill_contracts -v`

Expected: PASS.

- [ ] **Step 5: Commit review relay**

```bash
git add scripts/build_review_pack.py tests/test_review_pack.py skills/video-review-packager/SKILL.md
git commit -m "feat: relay compact visual review handoffs"
```

### Task 7: Package Version, Fingerprint, and Installed-Cache Smoke

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `scripts/validate_package.py`
- Modify: `scripts/install_personal_plugin.py`
- Modify: `scripts/verify_installation.py`
- Modify: `tests/test_package.py`
- Modify: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: all new files and runtime behavior from Tasks 1–6.
- Produces: plugin version `0.1.4`, complete release fingerprint, and a host-installed structural smoke that performs no visual operation in the primary context.

- [ ] **Step 1: Add RED release-surface tests**

Assert version `0.1.4`; require the new schema, policy, runtime, every modified visual Skill, and tests in `REQUIRED_FILES`; copy the package to a temporary directory and prove deleting or modifying each required file fails validation. Add installed-cache smoke cases for isolated visual routing, `none` laundering rejection, universal scrub, exact scope, and one-preview relay using metadata-only records.

- [ ] **Step 2: Run package tests and verify RED**

Run: `python -m unittest tests.test_package -v`

Expected: FAIL because the manifest and validator still declare `0.1.3` and omit new files.

- [ ] **Step 3: Bump version and strengthen fingerprint validation**

Set the manifest and `PLUGIN_VERSION` to `0.1.4`. Extend `REQUIRED_FILES` with `visual-media-task-context.schema.json`, `visual-media-isolation.md`, `visual_media_context.py`, and all affected Skill paths. Validate the exact operation/scope enums and fixed budgets rather than only file presence.

- [ ] **Step 4: Add metadata-only installed smoke**

Build temporary task/artifact JSON through public runtime functions. Do not create, open, render, inspect, play, or probe image/video files. Verify the installed cache module path belongs to version `0.1.4` and that malformed visual records fail with the same stable errors as the repository runtime.

- [ ] **Step 5: Run packaging and installation-unit suites**

Run: `python -m unittest tests.test_package tests.test_end_to_end -v`

Expected: PASS without changing the currently installed `0.1.3` cache.

- [ ] **Step 6: Commit release metadata**

```bash
git add .codex-plugin/plugin.json scripts/validate_package.py scripts/install_personal_plugin.py scripts/verify_installation.py tests/test_package.py tests/test_end_to_end.py
git commit -m "chore: prepare visual isolation plugin release"
```

### Task 8: Full Verification, Independent Review, Install, and Remote Delivery

**Files:**
- Verify only: entire repository
- Install target after review: personal plugin cache version `0.1.4`

**Interfaces:**
- Consumes: completed commits from Tasks 1–7.
- Produces: reviewed branch, verified installed cache, and remote branch update; preserves installed `0.1.3` until `0.1.4` passes host smoke.

- [ ] **Step 1: Run the full repository test matrix**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 2: Run package and project validators**

Run: `python scripts/validate_package.py`

Expected: exit 0 with no missing file, schema, version, or contract errors.

Run: `python scripts/migration_audit.py --source .`

Expected: exit 0 and no retired-skill conflict.

- [ ] **Step 3: Verify no placeholder language or accidental media access exists**

Run: `rg -n "T[B]D|T[O]DO|implement l[a]ter|similar t[o]|read_bytes\(|Image\.open|cv2\.|ffmpeg|ffprobe" scripts/toolkit/visual_media_context.py references/policies/visual-media-isolation.md skills tests/test_visual_media_context.py`

Expected: no placeholders; any existing ffmpeg/ffprobe mentions are explicit prohibitions or audio-only code, not calls from the visual-media coordinator/runtime.

- [ ] **Step 4: Request independent whole-branch review**

Use `superpowers:requesting-code-review` against the merge base and ask the reviewer to verify all 15 spec verification points, schema/runtime parity, legacy compatibility, false-positive resistance, and absence of primary-context visual operations. Resolve every blocking finding with a focused failing test, fix, passing test, and commit.

- [ ] **Step 5: Re-run full verification after review fixes**

Run: `python -m unittest discover -s tests -v && python scripts/validate_package.py`

Expected: all tests PASS and package validation exits 0.

- [ ] **Step 6: Install version 0.1.4 without deleting 0.1.3**

Run: `python scripts/install_personal_plugin.py --source .`

Expected: a fresh personal plugin cache for `0.1.4`; existing `0.1.3` remains present until host verification succeeds.

- [ ] **Step 7: Verify the installed cache, not the repository**

Run: `python scripts/verify_installation.py --source .`

Expected: PASS for discoverability, fingerprint, child-only visual routing, universal scrub, exact scope, legacy projection, and one-preview relay without opening or generating media.

- [ ] **Step 8: Commit review-only adjustments and push the feature branch**

```bash
git status --short
git log --oneline --decorate -12
git push -u origin codex/visual-media-isolation
```

Expected: only intentional files are changed, commits are reviewable, and the remote branch points at the verified HEAD.

# Voice-Timed Semantic Beats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make approved semantic beats, real narration timing, formal scene timing, and motion windows one immutable lineage while keeping validation compact and bounded.

**Architecture:** Split the current timing-linked `semantic-beats` concept into user-approved untimed `semantic-beats` and voice-derived `timed-semantic-beats`. Generate formal `scene-timing-contracts` only after real timing exists, then enforce the lineage in task dispatch, state recovery, storyboarding, motion, assembly, and compact validation.

**Tech Stack:** Python 3 standard library, JSON Schema draft 2020-12, immutable Artifact JSON, append-only project events, `unittest`, Codex Skill Markdown contracts.

**Spec:** docs/superpowers/specs/2026-08-29-voice-timing-semantic-beats-design.md

## Global Constraints

- Formal storyboards, motion, representative scenes, and production scenes require current real `voice-timing` and current `timed-semantic-beats`.
- Text-duration estimates may produce only explicitly untimed visual-direction previews and never formal Scene Contracts.
- Full narration uses segment timing; only user-approved keywords receive word-level timing anchors.
- Keywords, intent, priority, and preferred carrier are frozen by user approval before voice binding.
- Every semantic beat has exactly one primary carrier and at most one lightweight support layer.
- Every formal visual event stays inside both its keyword window and Scene Contract.
- Timing validation reads compact structural rows only; it never reads or plays audio, images, video, motion source, full transcripts, or prompt history.
- Validation returns at most three Beat IDs per issue code and aggregates all remaining occurrences by count.
- Existing timing-linked `semantic-beats` records remain readable through a non-mutating compatibility projection; new records use the split contracts.
- Execution is gated on resolving the current branch's known visual-isolation release blockers recorded in the existing SDD ledger; this feature must not be installed on a runtime with a known media-payload bypass.

---

### Task 1: Split Artifact Schemas and Legacy Projection

**Files:**
- Create: `references/schemas/semantic-beats.schema.json`
- Create: `references/schemas/timed-semantic-beats.schema.json`
- Create: `references/schemas/scene-timing-contracts.schema.json`
- Create: `references/schemas/timing-validation.schema.json`
- Modify: `references/schemas/artifact.schema.json`
- Modify: `scripts/validate_package.py`
- Modify: `tests/test_package.py`

**Interfaces:**
- Produces: `semantic-beats` with approved untimed anchors; `timed-semantic-beats` with real timing lineage; `scene-timing-contracts`; compact `timing-validation`.
- Compatibility: legacy records containing `type: semantic-beats` plus `voice_timing_id` are read as legacy timed beats but cannot be authored by new workers.

- [ ] **Step 1: Write schema RED tests**

```python
def test_split_timing_schemas_are_closed_and_bounded(self):
    semantic = self.schema("semantic-beats.schema.json")
    timed = self.schema("timed-semantic-beats.schema.json")
    scenes = self.schema("scene-timing-contracts.schema.json")
    validation = self.schema("timing-validation.schema.json")
    self.assertFalse(semantic["additionalProperties"])
    self.assertEqual("real", timed["properties"]["timing_kind"]["const"])
    self.assertEqual(1, scenes["$defs"]["scene"]["properties"]["primary_carrier"]["minLength"])
    self.assertEqual(3, validation["$defs"]["examples"]["additionalProperties"]["maxItems"])
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_package.PackageTests.test_split_timing_schemas_are_closed_and_bounded -v`

Expected: FAIL because the four schemas do not exist.

- [ ] **Step 3: Implement exact closed schemas**

Require safe IDs, unique bounded Beat IDs, project-contained paths, approval provenance, closed priority/carrier strings, non-negative millisecond integers, ordered two-item windows, one primary carrier, nullable single support layer, and a maximum of three example IDs per issue code. Add the files to package fingerprints and exact schema validation.

- [ ] **Step 4: Add compatibility and mutation tests**

Validate one new untimed record, one new timed record, one legacy timing-linked record, and failures for estimated timing, missing approval provenance, duplicated Beat IDs, more than one support layer, and four returned examples. Refresh the release fingerprint before each schema-mutation assertion.

- [ ] **Step 5: Run package tests and commit**

Run: `python -m unittest tests.test_package -v`

```bash
git add references/schemas scripts/validate_package.py tests/test_package.py
git commit -m "feat: define split semantic timing contracts"
```

### Task 2: Approved Semantic Beat Planning

**Files:**
- Create: `scripts/toolkit/semantic_beats.py`
- Create: `tests/test_semantic_beats.py`
- Modify: `skills/narration-planner/SKILL.md`
- Modify: `tests/test_skill_contracts.py`

**Interfaces:**
- Produces: `validate_semantic_beats(record) -> dict[str, Any]`, `freeze_semantic_beats(narration_id, candidates, approval) -> dict[str, Any]`, and `project_legacy_timed_beats(record) -> dict[str, Any] | None`.
- Consumes: confirmed narration ID, compact text references, candidate anchors, and explicit user approval provenance.

- [ ] **Step 1: Write behavioral RED tests**

```python
def test_freeze_requires_user_approved_keywords_without_timing(self):
    with self.assertRaisesRegex(ValueError, "approval"):
        freeze_semantic_beats("narration-v3", self.candidates(), None)
    frozen = freeze_semantic_beats("narration-v3", self.candidates(), self.approval())
    self.assertNotIn("voice_timing_id", frozen)
    self.assertNotIn("keyword_start_ms", frozen["beats"][0])
```

Cover duplicate keywords only when Beat IDs differ intentionally, missing text references, unknown priorities/carriers, timing fields leaking into Stage A, and downstream attempts to rewrite frozen anchors.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_semantic_beats -v`

Expected: FAIL with missing module.

- [ ] **Step 3: Implement immutable planning helpers**

Normalize no narration text into the Artifact; preserve only `text_ref`, keyword, intent, priority, preferred carrier, and approval provenance. Return fresh dictionaries and reject unknown fields.

- [ ] **Step 4: Update narration-planner contract**

State that it extracts candidates, asks the user alongside script approval, freezes Stage A beats, never fabricates final milliseconds, and never publishes formal storyboard timing.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_semantic_beats tests.test_skill_contracts -v`

```bash
git add scripts/toolkit/semantic_beats.py tests/test_semantic_beats.py skills/narration-planner/SKILL.md tests/test_skill_contracts.py
git commit -m "feat: freeze approved semantic beat anchors"
```

### Task 3: Bind Approved Anchors to Real Voice Timing

**Files:**
- Create: `scripts/toolkit/timed_semantic_beats.py`
- Create: `tests/test_timed_semantic_beats.py`
- Modify: `scripts/toolkit/voice_tasks.py`
- Modify: `tests/test_voice_tasks.py`
- Modify: `skills/voiceover-producer/SKILL.md`

**Interfaces:**
- Produces: `bind_semantic_beats(semantic_beats, voice_timing, keyword_anchors) -> dict[str, Any]` and `validate_timed_semantic_beats(record, semantic_beats, voice_timing) -> dict[str, Any]`.
- Consumes: frozen `semantic-beats`, current real `voice-timing`, and word-level anchors for only the approved keyword set.

- [ ] **Step 1: Write binding RED tests**

```python
def test_binding_uses_real_timing_and_only_approved_keywords(self):
    timed = bind_semantic_beats(self.semantic(), self.real_timing(), self.keyword_anchors())
    self.assertEqual("real", timed["timing_kind"])
    self.assertEqual(["B07"], [beat["beat_id"] for beat in timed["beats"]])
    self.assertNotIn("unapproved-word", json.dumps(timed))
```

Cover estimated timing rejection, missing keyword anchor, anchor outside its spoken segment, mismatched narration lineage, stale timing, extra word-level timestamps, and default 120–250 ms entry plus 200–500 ms exit bounds.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_timed_semantic_beats -v`

Expected: FAIL with missing module.

- [ ] **Step 3: Implement deterministic binding**

Require millisecond ordering and lineage. Store full narration timing only by `voice_timing_id`; copy only per-beat segment bounds and approved keyword anchors. Calculate explicit `visual_window_ms` without copying the transcript.

- [ ] **Step 4: Update voice task completion**

Change the current voice preparation output contract from timing-linked legacy `semantic-beats` to `timed-semantic-beats`, requiring the pre-existing approved `semantic_beats_id` as an immutable input. Legacy three-output results remain readable but new jobs must publish voiceover, voice-timing, and timed-semantic-beats.

- [ ] **Step 5: Run voice regressions and commit**

Run: `python -m unittest tests.test_timed_semantic_beats tests.test_voice_tasks tests.test_voice -v`

```bash
git add scripts/toolkit/timed_semantic_beats.py scripts/toolkit/voice_tasks.py tests/test_timed_semantic_beats.py tests/test_voice_tasks.py skills/voiceover-producer/SKILL.md
git commit -m "feat: bind approved beats to real narration timing"
```

### Task 4: Formal Scene Timing Contracts

**Files:**
- Create: `scripts/toolkit/scene_timing.py`
- Create: `tests/test_scene_timing.py`
- Modify: `references/schemas/scene-contract.schema.json`
- Modify: `scripts/toolkit/contracts.py`
- Modify: `tests/test_representative_slice.py`
- Modify: `skills/storyboard-director/SKILL.md`

**Interfaces:**
- Produces: `build_scene_timing_contracts(timed_beats, assignments) -> dict[str, Any]` and `validate_scene_timing_contracts(record, timed_beats) -> dict[str, Any]`.
- Consumes: current timed beats and assignments containing exactly one primary carrier plus zero or one support layer.

- [ ] **Step 1: Write scene-contract RED tests**

Cover valid consecutive beats, one Beat ID assigned twice, a scene outside spoken boundaries, two primary carriers, two support layers, keyword windows crossing scene bounds, adjacent keywords requiring merge/omission, and an estimated-time storyboard attempt.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_scene_timing -v`

Expected: FAIL with missing module.

- [ ] **Step 3: Implement scene timing construction**

Require every timed Beat ID exactly once, ordered consecutive membership inside each scene, contracted window containment, and project registry carrier IDs. Return structural JSON only.

- [ ] **Step 4: Bind existing Scene Contracts and representative slices**

Add required `timed_semantic_beats_id`, `scene_timing_contracts_id`, and exact `beat_ids` to new Scene Contracts. Preserve legacy recovery through existing compatibility flags, but reject new Scene Contracts that name only `voice_timing_id`.

- [ ] **Step 5: Update storyboard Skill, run tests, and commit**

Run: `python -m unittest tests.test_scene_timing tests.test_representative_slice tests.test_skill_contracts -v`

```bash
git add scripts/toolkit/scene_timing.py scripts/toolkit/contracts.py references/schemas/scene-contract.schema.json tests/test_scene_timing.py tests/test_representative_slice.py skills/storyboard-director/SKILL.md
git commit -m "feat: contract formal scenes to timed semantic beats"
```

### Task 5: Compact Deterministic Timing Validator

**Files:**
- Create: `scripts/toolkit/timing_validation.py`
- Create: `tests/test_timing_validation.py`
- Modify: `skills/structural-validator/SKILL.md`
- Modify: `skills/motion-director/SKILL.md`
- Modify: `skills/timeline-assembler/SKILL.md`

**Interfaces:**
- Produces: `validate_timing_rows(rows, *, minimum_readable_duration_ms) -> dict[str, Any]` with `status`, `checks_run`, `issue_counts`, and at most three Beat IDs per issue code.
- Consumes: compact rows only; never Artifact payloads or media paths.

- [ ] **Step 1: Write the six-case minimal RED matrix**

```python
CASES = (
    ("valid", valid_rows(), "passed"),
    ("missing-real-timing", missing_timing_rows(), "VOICE_TIMING_REQUIRED"),
    ("keyword-window", keyword_outside_rows(), "VISUAL_BEFORE_ALLOWED_WINDOW"),
    ("scene-window", scene_outside_rows(), "BEAT_OUTSIDE_SCENE"),
    ("multiple-primary", multiple_primary_rows(), "MULTIPLE_PRIMARY_CARRIERS"),
    ("recovery-stale", stale_rows(), "STALE_VOICE_TIMING"),
)
```

Add one aggregation test with seven failures and assert count 7 but examples exactly the first three deterministic Beat IDs.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_timing_validation -v`

Expected: FAIL with missing module.

- [ ] **Step 3: Implement table-driven validation**

Use a closed rule table and bounded accumulators. Do not accept narration text, transcript arrays, audio paths, visual paths, prompt history, or motion code fields in a row.

- [ ] **Step 4: Update worker contracts**

Motion consumes only assigned Beat IDs/windows; assembler reports codes instead of retiming; structural validator reads compact rows and never detailed diagnostics.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_timing_validation tests.test_skill_contracts -v`

```bash
git add scripts/toolkit/timing_validation.py tests/test_timing_validation.py skills/structural-validator/SKILL.md skills/motion-director/SKILL.md skills/timeline-assembler/SKILL.md
git commit -m "feat: validate timing with bounded issue summaries"
```

### Task 6: Workflow State, Task Gates, and Invalidation

**Files:**
- Modify: `references/schemas/project.schema.json`
- Modify: `references/schemas/event.schema.json`
- Modify: `references/policies/decision-gates.md`
- Modify: `references/policies/invalidation.json`
- Modify: `scripts/toolkit/project_state.py`
- Modify: `scripts/toolkit/tasks.py`
- Modify: `scripts/toolkit/orchestrator.py`
- Modify: `scripts/toolkit/validation.py`
- Modify: `tests/test_project_state.py`
- Modify: `tests/test_tasks.py`
- Modify: `tests/test_validation.py`

**Interfaces:**
- Produces: version-three phase order `script_confirmed -> semantic_beats_confirmed -> visual_direction_previewed? -> voiceover_ready -> timing_bound -> storyboard_timed -> representative_scene_ready -> production_ready` plus read-only v1/v2 recovery.
- Consumes: current Artifact lineage and `timing-validation.status`.

- [ ] **Step 1: Write phase/gate RED tests**

Prove formal storyboard creation fails before real timing, `visual_direction_previewed` cannot skip timing, representative production requires current scene timing, production readiness requires passed timing validation, and legacy v2 projects recover without history rewriting.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_project_state tests.test_tasks tests.test_validation -v`

Expected: FAIL on missing v3 phases and timing gates.

- [ ] **Step 3: Implement v3 replay and compatibility projection**

Add exact phase-event legality, optional preview transition, and a non-mutating recovery projection for old projects. Never rewrite old event logs.

- [ ] **Step 4: Enforce dispatch, claim, completion, and recovery gates**

Storyboard/motion/scene/timeline tasks require current timed beats and scene timing as appropriate. Recheck lineage at claim and completion. Recovery blocks stale or missing timing and returns compact issue codes.

- [ ] **Step 5: Update invalidation edges**

Split the old `semantic-beats` timing edge into `semantic-beats -> timed-semantic-beats -> scene-timing-contracts -> storyboard/scene/motion/timeline`. Preserve visual-style independence from voice timing.

- [ ] **Step 6: Run state/lifecycle tests and commit**

Run: `python -m unittest tests.test_project_state tests.test_tasks tests.test_validation tests.test_invalidation -v`

```bash
git add references/schemas/project.schema.json references/schemas/event.schema.json references/policies/decision-gates.md references/policies/invalidation.json scripts/toolkit/project_state.py scripts/toolkit/tasks.py scripts/toolkit/orchestrator.py scripts/toolkit/validation.py tests/test_project_state.py tests/test_tasks.py tests/test_validation.py tests/test_invalidation.py
git commit -m "feat: gate production on bound narration timing"
```

### Task 7: Coordinator Contract and Compact Review Surface

**Files:**
- Modify: `skills/video-director/SKILL.md`
- Modify: `skills/video-project-manager/SKILL.md`
- Modify: `references/policies/narration-and-coverage.md`
- Modify: `tests/test_skill_contracts.py`
- Modify: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: v3 states and compact timing validation result.
- Produces: one-action routing that never loads detailed timing diagnostics and returns at most three Beat IDs per issue code.

- [ ] **Step 1: Write contract RED tests**

Assert the director blocks formal storyboard before `timing_bound`, allows only untimed visual-direction preview earlier, never loads `timing-validation` detail paths, returns bounded examples, and routes one timing-repair task for affected Beat IDs.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_skill_contracts tests.test_end_to_end -v`

Expected: FAIL because the current director routes storyboard directly from `voice_ready`.

- [ ] **Step 3: Update policy and Skill wording**

Use canonical v3 Artifact names and states. Prohibit downstream workers from estimating timing, changing keywords, reading full narration for timing validation, or expanding detailed diagnostics into the coordinator context.

- [ ] **Step 4: Add end-to-end structural workflow**

Create a metadata-only project from script confirmation through production readiness. Assert an estimated timing branch blocks, a real timing branch succeeds, a changed voice timing invalidates downstream contracts, and every issue category exposes at most three Beat IDs.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_skill_contracts tests.test_end_to_end -v`

```bash
git add skills/video-director/SKILL.md skills/video-project-manager/SKILL.md references/policies/narration-and-coverage.md tests/test_skill_contracts.py tests/test_end_to_end.py
git commit -m "docs: route production through voice-timed beats"
```

### Task 8: Release Verification and Installed Smoke

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `scripts/validate_package.py`
- Modify: `scripts/verify_installation.py`
- Modify: `tests/test_package.py`
- Modify: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: Tasks 1–7 and a visual-isolation runtime with no known release blocker.
- Produces: next plugin release, complete fingerprint, metadata-only installed-cache timing smoke, reviewed remote branch.

- [ ] **Step 1: Add release RED tests**

Require all new schemas, modules, policies, Skills, and tests in the fingerprint. Mutation tests must prove removal or weakening of the real-timing gate, three-example bound, approval freeze, or lineage constraints fails even after fingerprint refresh.

- [ ] **Step 2: Choose and apply the next version**

Read the installed/published version at execution time. Increment the minor version because this changes public Artifact and workflow-state contracts; do not hard-code a version in advance if another release has landed.

- [ ] **Step 3: Add metadata-only installed smoke**

Verify the installed module path/version, frozen semantic beats, real timing binding, storyboard gate, compact validation aggregation, stale timing recovery, and v2 compatibility without playing audio or opening visual media.

- [ ] **Step 4: Run the full matrix in an isolated verification child**

Run: `python -m unittest discover -s tests -v`

Run: `python scripts/validate_package.py`

Expected: all tests pass except documented environment skips; package valid; forbidden audio/visual access scans clean in coordinator-safe timing modules.

- [ ] **Step 5: Request independent whole-branch review**

Review every success criterion, schema/runtime parity, v1/v2 recovery, invalidation, token bounds, and absence of media/full-transcript access in timing validation. Fix all Critical/Important findings before installation.

- [ ] **Step 6: Install, verify host cache, and push**

Keep the previous installed version until the new cache passes. Run the installer and installed-cache verifier, then push the verified feature branch requested by the user.

```bash
git push -u origin codex/visual-media-isolation
```

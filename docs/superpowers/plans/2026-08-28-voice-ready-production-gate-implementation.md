# Voice-ready Production Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a produced narration track and confirmed real voice timing before storyboard, representative-slice, or full video production can begin.

**Architecture:** Insert an explicit `voice_ready` phase between visual direction and storyboard readiness. A bounded `voiceover-producer` owns `voice.prepare`, supports user-uploaded narration and approved ChatCut TTS, and publishes immutable voice artifacts. Coordinator routing, phase replay, validation, invalidation, review packs, and recovery all consume the same voice lineage contract.

**Tech Stack:** Codex Plugin Skills, Python 3 standard library, JSON/JSONL, JSON Schema, `unittest`, existing ChatCut Voice external Skill adapter.

**Spec:** `docs/superpowers/specs/2026-08-28-voice-ready-production-gate-design.md`

## Global Constraints

- The coordinator routes exactly one action and never generates, imports, or analyzes media itself.
- The user chooses `uploaded-voice` or `tts`; silence is not approval.
- TTS requires an approved voice profile and may use only its declared provider and voice.
- Real voice timing, never estimated timing, is required for `voice_ready` and every downstream timing consumer.
- Artifact versions remain immutable and project-contained; revisions use DAG invalidation.
- Existing pre-voice event logs are not rewritten.
- External providers cannot change the approved script, voice profile, routing, or decision gates.
- No automatic voice cloning, undeclared fallback, script rewriting, or final audio mastering is added.

---

## File Map

- `scripts/toolkit/project_state.py`: revised phase order and compatibility projection.
- `references/schemas/project.schema.json`, `references/schemas/event.schema.json`: persisted phase contracts.
- `references/schemas/voice-source-decision.schema.json`: selected source mode.
- `references/schemas/voice-profile.schema.json`: approved TTS/upload profile.
- `references/schemas/voiceover.schema.json`: produced or uploaded audio metadata.
- `references/schemas/voice-timing.schema.json`: real segment timing tied to one voiceover.
- `scripts/toolkit/voice.py`: voice artifact validation and readiness calculation.
- `skills/voiceover-producer/SKILL.md`: bounded `voice.prepare` worker contract.
- `scripts/toolkit/orchestrator.py`: voice capability routing and downstream readiness.
- `registries/adapters/chatcut.json`: ChatCut voice capability declaration.
- `scripts/toolkit/adapters.py`: voice adapter selection through existing compatibility rules.
- `references/policies/decision-gates.md`: source/profile decisions and revised phase routing.
- `references/policies/invalidation.json`: voice descendant invalidation.
- `scripts/toolkit/validation.py`: project-wide voice lineage and timing checks.
- `scripts/build_review_pack.py`: current voice review links and blockers.
- `scripts/verify_installation.py`: end-to-end voice-ready recovery smoke.

---

### Task 1: Persist the `voice_ready` Phase and Compatibility Projection

**Files:**
- Modify: `scripts/toolkit/project_state.py`
- Modify: `references/schemas/project.schema.json`
- Modify: `references/schemas/event.schema.json`
- Modify: `tests/test_project_state.py`

**Interfaces:**
- Consumes: `append_event(root: Path, event: dict) -> None`; `replay_events(root: Path) -> dict`.
- Produces: `PHASES` containing `voice_ready`; `project_recovery_view(root: Path, artifacts: Iterable[dict]) -> dict` for non-mutating legacy normalization.

- [ ] **Step 1: Add failing phase-order and legacy-recovery tests**

```python
def test_direction_advances_to_voice_before_storyboard(self):
    self.advance_to("direction_ready")
    append_event(self.root, {"event": "project.phase_changed", "phase": "voice_ready"})
    self.assertEqual("voice_ready", replay_events(self.root)["phase"])

def test_direction_cannot_skip_voice_ready(self):
    self.advance_to("direction_ready")
    with self.assertRaisesRegex(ValueError, "illegal project phase transition"):
        append_event(self.root, {"event": "project.phase_changed", "phase": "storyboard_ready"})

def test_legacy_production_snapshot_without_voice_projects_to_direction_ready(self):
    self.write_pre_voice_event_log(final_phase="production_ready")
    view = project_recovery_view(self.root, artifacts=[])
    self.assertEqual("direction_ready", view["phase"])
    self.assertEqual("voice-artifacts-required", view["migration_requirement"]["code"])
    self.assertEqual(self.original_events, self.event_log.read_bytes())
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python3 -m unittest tests.test_project_state -v`

Expected: failures because `voice_ready` and `project_recovery_view` do not exist and the old phase order permits the prior transition.

- [ ] **Step 3: Implement the revised phase order and read-only compatibility view**

```python
PHASES = (
    "initialized", "content_ready", "direction_ready", "voice_ready",
    "storyboard_ready", "production_ready", "assembled", "review_ready",
    "handoff_ready",
)

def project_recovery_view(root: Path, artifacts: Iterable[dict]) -> dict:
    state = replay_events(root)
    if state["phase"] in {"storyboard_ready", "production_ready", "assembled", "review_ready", "handoff_ready"}:
        if not has_current_voice_lineage(artifacts):
            return {**state, "phase": "direction_ready", "migration_requirement": {
                "code": "voice-artifacts-required",
                "recorded_phase": state["phase"],
            }}
    return state
```

Keep the event log immutable. Detect legacy phase sequences by schema/versioned replay compatibility, not by weakening legal transitions for new events.

- [ ] **Step 4: Update both schemas with the exact phase enum**

Add `voice_ready` between `direction_ready` and `storyboard_ready`. Keep current schema versions readable and document the compatibility projection in schema descriptions.

- [ ] **Step 5: Run targeted and full state tests**

Run: `python3 -m unittest tests.test_project_state -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/toolkit/project_state.py references/schemas/project.schema.json references/schemas/event.schema.json tests/test_project_state.py
git commit -m "feat: add recoverable voice-ready phase"
```

---

### Task 2: Define and Validate Immutable Voice Artifacts

**Files:**
- Create: `references/schemas/voice-source-decision.schema.json`
- Create: `references/schemas/voice-profile.schema.json`
- Create: `references/schemas/voiceover.schema.json`
- Create: `references/schemas/voice-timing.schema.json`
- Create: `scripts/toolkit/voice.py`
- Create: `tests/test_voice.py`
- Modify: `scripts/validate_package.py`

**Interfaces:**
- Produces: `validate_voice_bundle(artifacts: Iterable[Mapping], narration_id: str) -> dict`; `has_current_voice_lineage(artifacts: Iterable[Mapping], narration_id: str | None = None) -> bool`.
- Result shape: `{"ok": bool, "voiceover_id": str | None, "voice_timing_id": str | None, "issues": list[dict]}`.

- [ ] **Step 1: Write failing schema and lineage tests**

```python
def test_voice_bundle_requires_exact_voiceover_parent(self):
    result = validate_voice_bundle(self.bundle(timing_parents=["other-audio"]), "narration-v2")
    self.assertFalse(result["ok"])
    self.assertIn("voice-timing-lineage-mismatch", self.codes(result))

def test_timing_must_be_ordered_and_bounded_by_real_duration(self):
    result = validate_voice_bundle(self.bundle(duration_ms=1000, segments=[
        {"start_ms": 0, "end_ms": 700, "text": "A"},
        {"start_ms": 650, "end_ms": 1100, "text": "B"},
    ]), "narration-v2")
    self.assertEqual({"voice-timing-overlap", "voice-timing-out-of-bounds"}, self.codes(result))

def test_estimated_timing_never_satisfies_voice_readiness(self):
    result = validate_voice_bundle(self.bundle(timing_kind="estimated"), "narration-v2")
    self.assertIn("real-voice-timing-required", self.codes(result))
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_voice -v`

Expected: import failure for `scripts.toolkit.voice`.

- [ ] **Step 3: Add closed JSON schemas**

Use `additionalProperties: false`. Required fields:

```json
{"voice-source-decision": ["artifact_id", "narration_id", "mode", "decision"],
 "voice-profile": ["artifact_id", "mode", "language", "provider", "voice_id", "speaking_rate", "emotion", "pronunciations", "approved"],
 "voiceover": ["artifact_id", "narration_id", "profile_id", "media_path", "duration_ms", "provenance", "parents"],
 "voice-timing": ["artifact_id", "voiceover_id", "timing_kind", "duration_ms", "segments", "parents"]}
```

`mode` is `uploaded-voice` or `tts`; `timing_kind` must be `real`; segment times are integer milliseconds.

- [ ] **Step 4: Implement compact validation**

Validate exact current IDs, approved status, parent lineage, safe project-relative media paths, positive duration, ordered non-overlapping segments, segment bounds, and text coverage. Return issue codes rather than raising for project-content defects; raise only for programmer-invalid input types.

- [ ] **Step 5: Add schemas to package validation and run tests**

Run: `python3 -m unittest tests.test_voice tests.test_package -v`

Expected: PASS and all new schemas parse.

- [ ] **Step 6: Commit**

```bash
git add references/schemas/voice-*.schema.json scripts/toolkit/voice.py scripts/validate_package.py tests/test_voice.py tests/test_package.py
git commit -m "feat: add immutable voice artifact contracts"
```

---

### Task 3: Add the Bounded Voiceover Producer Skill and Decision Policy

**Files:**
- Create: `skills/voiceover-producer/SKILL.md`
- Modify: `skills/video-director/SKILL.md`
- Modify: `references/policies/decision-gates.md`
- Modify: `tests/test_skill_contracts.py`
- Modify: `scripts/validate_package.py`

**Interfaces:**
- Produces: child Skill owner `voice.prepare`; routing `voice.prepare → voiceover-producer`.
- Consumes: task/result schemas and Task 2 voice schemas.

- [ ] **Step 1: Write failing static contract tests**

```python
def test_voiceover_producer_owns_only_voice_prepare(self):
    text = self.skill("voiceover-producer")
    self.assertIn("Owned capability: `voice.prepare`", text)
    self.assertIn("uploaded-voice", text)
    self.assertIn("tts", text)
    self.assertIn("waiting_user", text)
    self.assertIn("waiting_external", text)

def test_video_director_routes_voice_prepare_once(self):
    text = self.skill("video-director")
    self.assertEqual(1, text.count("`voice.prepare` → `voiceover-producer`"))
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_skill_contracts -v`

Expected: missing Skill and route failures.

- [ ] **Step 3: Write the Skill contract**

The Skill must state:

```markdown
Owned capability: `voice.prepare`
Allowed inputs: one claimed envelope with approved narration, style decision,
voice-source decision, and either an approved TTS profile or uploaded audio.
Success: publish voiceover, real voice-timing, and timing-linked semantic-beats.
Stop: waiting_user for choice/profile/upload; waiting_external for the declared
provider; never rewrite narration or silently change voice/profile/provider.
```

- [ ] **Step 4: Update decision and phase policy**

Add durable voice-source and TTS-profile decisions under the confirmed content lineage. Add `direction_ready → voice.prepare` and `voice_ready → storyboard.plan`; remove `direction_ready → storyboard.plan`.

- [ ] **Step 5: Run skill/package tests and commit**

Run: `python3 -m unittest tests.test_skill_contracts tests.test_package -v`

```bash
git add skills/voiceover-producer skills/video-director/SKILL.md references/policies/decision-gates.md scripts/validate_package.py tests/test_skill_contracts.py tests/test_package.py
git commit -m "feat: add voiceover producer skill"
```

---

### Task 4: Route Uploaded Voice and Approved ChatCut TTS

**Files:**
- Modify: `registries/adapters/chatcut.json`
- Modify: `scripts/toolkit/adapters.py`
- Create: `scripts/toolkit/voice_tasks.py`
- Modify: `tests/test_adapters.py`
- Create: `tests/test_voice_tasks.py`

**Interfaces:**
- Produces: `prepare_voice_task(root: Path, envelope: Mapping, artifacts: Iterable[Mapping], installed_skills: Iterable[str]) -> dict`.
- Returns a task-result payload with status `waiting_user`, `waiting_external`, or `succeeded`.
- ChatCut manifest capabilities: `voice.synthesize`, `voice.time`; accepts `voice-profile`/`narration`; outputs `voiceover`/`voice-timing`.

- [ ] **Step 1: Write failing source-mode tests**

```python
def test_uploaded_mode_waits_for_declared_audio(self):
    result = prepare_voice_task(self.root, self.upload_envelope(), self.artifacts_without_audio(), [])
    self.assertEqual("waiting_user", result["status"])
    self.assertEqual("voice-upload-required", result["warnings"][0]["code"])

def test_tts_mode_requires_approved_profile(self):
    result = prepare_voice_task(self.root, self.tts_envelope(), self.unapproved_profile(), ["chatcut:voice"])
    self.assertEqual("waiting_user", result["status"])

def test_tts_selects_only_declared_chatcut_voice_adapter(self):
    result = prepare_voice_task(self.root, self.tts_envelope(adapter_preferences=["chatcut"]), self.approved_profile(), ["chatcut:voice"])
    self.assertEqual("waiting_external", result["status"])
    self.assertEqual("chatcut", result["adapter"])
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_voice_tasks tests.test_adapters -v`

Expected: missing module/capability failures.

- [ ] **Step 3: Extend the ChatCut manifest**

Declare voice capabilities without removing timeline and Motion Graphics capabilities. Use `installed_skill: chatcut:voice`, external-reference implementation, explicit accepted contracts and outputs, and no undeclared voice fallback.

- [ ] **Step 4: Implement task preparation**

Uploaded mode checks the declared audio Artifact and returns `waiting_user` until present. TTS mode checks profile approval and calls existing adapter selection with exact requirements. It prepares an external job contract; it does not fake output or mark success before the external result publishes valid Artifacts.

- [ ] **Step 5: Verify tests and commit**

Run: `python3 -m unittest tests.test_voice_tasks tests.test_adapters tests.test_tasks -v`

```bash
git add registries/adapters/chatcut.json scripts/toolkit/adapters.py scripts/toolkit/voice_tasks.py tests/test_adapters.py tests/test_voice_tasks.py
git commit -m "feat: route uploaded and ChatCut narration"
```

---

### Task 5: Enforce Voice Readiness in Routing and Production Inputs

**Files:**
- Modify: `scripts/toolkit/orchestrator.py`
- Modify: `scripts/toolkit/tasks.py`
- Modify: `scripts/toolkit/contracts.py`
- Modify: `tests/test_end_to_end.py`
- Modify: `tests/test_tasks.py`
- Modify: `tests/test_representative_slice.py`

**Interfaces:**
- Consumes: `validate_voice_bundle`; `project_recovery_view`.
- Produces: ready-task gating for `voice.prepare` and current `voice-timing` input enforcement.

- [ ] **Step 1: Write failing routing regressions**

```python
def test_direction_ready_routes_voice_not_storyboard_without_real_timing(self):
    state = self.state(phase="direction_ready", candidates=[self.voice_task(), self.storyboard_task()])
    self.assertEqual(["voice.prepare"], calculate_ready_tasks(state, self.artifacts_without_voice(), self.approvals()))

def test_voice_ready_rejects_storyboard_with_stale_timing_input(self):
    state = self.state(phase="voice_ready", candidates=[self.storyboard_task(inputs=["voice-timing-v1"])])
    artifacts = self.voice_bundle(timing_status="stale")
    self.assertEqual([], calculate_ready_tasks(state, artifacts, self.approvals()))

def test_production_ready_without_voice_bundle_is_invalid(self):
    resumed = resume_project(self.project_without_voice_at("production_ready"))
    self.assertEqual("direction_ready", resumed["phase"])
    self.assertEqual([], resumed["ready_tasks"])
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_end_to_end tests.test_tasks tests.test_representative_slice -v`

Expected: storyboard/production currently route without voice artifacts.

- [ ] **Step 3: Implement routing requirements**

Add `voice.prepare` to capability phases and gate mapping. Require current `voice-timing` for storyboard, scene, motion, timeline, captions, and representative-slice task envelopes. The required timing ID must be in the declared input set and share narration/voiceover lineage.

- [ ] **Step 4: Enforce Scene Contract timing provenance**

Scene Contract validation must require `voice_timing_id`; its start/end interval must fall within the declared real timing and correspond to covered semantic segments. Do not copy timing estimates into the field.

- [ ] **Step 5: Run targeted tests and commit**

Run: `python3 -m unittest tests.test_end_to_end tests.test_tasks tests.test_representative_slice -v`

```bash
git add scripts/toolkit/orchestrator.py scripts/toolkit/tasks.py scripts/toolkit/contracts.py tests/test_end_to_end.py tests/test_tasks.py tests/test_representative_slice.py
git commit -m "feat: gate production on real narration timing"
```

---

### Task 6: Invalidate, Validate, and Review Voice Lineage

**Files:**
- Modify: `references/policies/invalidation.json`
- Modify: `scripts/toolkit/validation.py`
- Modify: `scripts/build_review_pack.py`
- Modify: `tests/test_invalidation.py`
- Modify: `tests/test_validation.py`
- Modify: `tests/test_review_pack.py`

**Interfaces:**
- Produces: shipped invalidation rules for voice descendants; structural issue codes; link-only current voice review data.

- [ ] **Step 1: Write failing invalidation tests**

```python
def test_voice_profile_change_invalidates_audio_and_timing_consumers(self):
    stale = invalidate_descendants(self.graph, "voice-profile-v1", self.rules)
    self.assertEqual({"voiceover-v1", "voice-timing-v1", "beats-v1", "storyboard-v1", "timeline-v1", "review-v1"}, stale)

def test_style_change_does_not_invalidate_unchanged_voiceover(self):
    stale = invalidate_descendants(self.graph, "style-v1", self.rules)
    self.assertNotIn("voiceover-v1", stale)
```

- [ ] **Step 2: Write failing validation/review tests**

```python
def test_voice_timing_beyond_audio_duration_is_structural_error(self):
    self.assertIn("voice-timing-out-of-bounds", self.codes(validate_project(self.root)))

def test_review_pack_links_only_current_voiceover(self):
    pack = build_review_pack(self.root, self.output)
    self.assertEqual("voiceover-v2", pack["voice"]["voiceover_id"])
    self.assertNotIn("voiceover-v1", json.dumps(pack))
```

- [ ] **Step 3: Run and verify RED**

Run: `python3 -m unittest tests.test_invalidation tests.test_validation tests.test_review_pack -v`

- [ ] **Step 4: Update shipped rules and structural checks**

Add exact descendant types for narration, source decision, profile, voiceover, and voice timing. Validation consumes the same Task 2 validator and emits stable issue codes. Review packs resolve effective event-backed status and link current audio without embedding it.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m unittest tests.test_invalidation tests.test_validation tests.test_review_pack -v`

```bash
git add references/policies/invalidation.json scripts/toolkit/validation.py scripts/build_review_pack.py tests/test_invalidation.py tests/test_validation.py tests/test_review_pack.py
git commit -m "feat: validate and review voice lineage"
```

---

### Task 7: Verify End-to-End Recovery and Installed Plugin Behavior

**Files:**
- Modify: `scripts/verify_installation.py`
- Modify: `scripts/retire_legacy_skill.py`
- Modify: `tests/test_end_to_end.py`
- Modify: `.codex-plugin/plugin.json`
- Modify: `docs/migration/knowledge-video-visual-director.md`

**Interfaces:**
- Produces: voice-aware `run_smoke(root, legacy_root=None) -> dict`; installed-package fingerprint including the new Skill, schemas, and policies.

- [ ] **Step 1: Add a failing voice-aware smoke test**

```python
def test_resume_smoke_requires_voice_before_representative_slice(self):
    result = run_smoke(ROOT, legacy_root=LEGACY)
    self.assertEqual("passed", result["checks"]["voice_source_decision"])
    self.assertEqual("passed", result["checks"]["real_voice_timing"])
    self.assertEqual("voice-timing-v1", result["representative_slice"]["voice_timing_id"])
```

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_end_to_end -v`

Expected: smoke result lacks voice checks and timing provenance.

- [ ] **Step 3: Extend the recovery smoke**

The smoke must demonstrate both blocked and ready paths:

1. At `direction_ready`, storyboard and scene production are blocked.
2. A declared upload or TTS decision is persisted.
3. Valid voiceover and real voice timing are published.
4. The project advances to `voice_ready`.
5. Storyboard and a 10–20 second representative slice reference that timing.
6. A voice timing revision invalidates only declared descendants.

- [ ] **Step 4: Update retirement fingerprint and plugin version**

Ensure the installed distributable fingerprint includes the new Skill, schemas,
module, and policy. Increment the plugin patch version so Codex creates a fresh
personal-plugin cache rather than reusing `0.1.1`.

- [ ] **Step 5: Run the full verification matrix**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/video-toolkit-voice-ready python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/video-toolkit-voice-ready python3 -m py_compile scripts/toolkit/*.py scripts/*.py tests/*.py
python3 scripts/validate_package.py
python3 scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .
python3 scripts/verify_installation.py --repo . --require-skill video-director --require-resume-smoke --check-external-skills
```

Expected: all tests and compilation pass; package/audit/smoke are valid; external adapter status includes ChatCut Voice capability.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_installation.py scripts/retire_legacy_skill.py tests/test_end_to_end.py .codex-plugin/plugin.json docs/migration/knowledge-video-visual-director.md
git commit -m "feat: verify voice-ready production workflow"
```

---

## Completion Gate

Before installing the new patch version or retiring the old Skill:

1. Run the full verification matrix from Task 7 on the final commit.
2. Perform a whole-branch review against the voice-ready design spec.
3. Install and enable the new personal plugin version.
4. Run the verifier against the host-installed cache, not the repository.
5. Confirm `video-director`, `voiceover-producer`, ChatCut Voice, real timing,
   recovery smoke, and representative-slice timing provenance.
6. Request explicit execution-time approval before deleting
   `/Users/fantasy/.codex/skills/knowledge-video-visual-director`.

# Video Production Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable personal Codex plugin that coordinates recoverable, user-directed Chinese knowledge-video production through small skills, immutable artifacts, registries, and external rendering/editing adapters.

**Architecture:** The repository itself is the plugin package. A small `video-director` reads a compact JSON project summary and dispatches one typed task at a time; Python standard-library scripts own deterministic state, DAG invalidation, event replay, registry search, locking, and validation. External Hyperframes, Remotion, VideoShotCraft, and ChatCut capabilities are referenced through adapter manifests and loaded only by the isolated worker that needs them.

**Tech Stack:** Codex Plugin manifest, Markdown Agent Skills, Python 3 standard library, JSON/JSONL, `unittest`, JSON Schema documents, HTML preview artifacts, existing installed external Skills.

**Spec:** `docs/superpowers/specs/2026-08-25-video-production-toolkit-design.md`

## Global Constraints

- MVP workflows are Chinese knowledge, talking-head, and tutorial videos; general long-form editing is excluded.
- Runtime state uses JSON/JSONL files; do not add a database dependency.
- `video-director` dispatches one action slice and never generates media itself.
- Every semantic beat has exactly one primary carrier and at most one secondary layer.
- Child tasks communicate with artifact IDs, paths, summaries, and contract results; never embed media or bulk logs.
- User approvals are durable artifacts at four decision gates.
- Machine review is structural; subjective aesthetics are packaged for user review.
- ChatCut is the default editable timeline backend.
- External skills remain capability providers and cannot override toolkit routing or approval policy.
- Do not delete `/Users/fantasy/.codex/skills/knowledge-video-visual-director` until the replacement plugin passes the end-to-end recovery and representative-slice smoke tests.
- Preserve Apache-2.0 and MIT attribution for vendored material; do not vendor AGPL Hyperframes skill content.

---

## Planned File Map

```text
.codex-plugin/plugin.json                       Plugin identity and packaged skills
agents/openai.yaml                              Plugin-facing display metadata
skills/video-director/SKILL.md                  Small routing entrypoint
skills/video-project-manager/SKILL.md           State and recovery workflow
skills/narration-planner/SKILL.md                Voice timing and semantic planning
skills/visual-system-designer/SKILL.md           Style/Layout and H5 preview workflow
skills/storyboard-director/SKILL.md              Visual-carrier and scene contracts
skills/scene-producer/SKILL.md                   One-scene production contract
skills/motion-director/SKILL.md                  MG selection and adapter routing
skills/timeline-assembler/SKILL.md               Editable timeline assembly
skills/structural-validator/SKILL.md             Objective validation workflow
skills/video-review-packager/SKILL.md            Concentrated user review artifacts
references/schemas/*.schema.json                Stable persisted interfaces
references/policies/*.md                        Approval, visual, retry, migration policies
references/adapters/*.json                      External capability manifests
registries/{styles,layouts,recipes,adapters,lessons}/
scripts/toolkit/*.py                            Focused state and registry modules
scripts/*.py                                    Stable CLI entrypoints
assets/project-template/                        New runtime-project template
tests/*.py                                      Unit, contract, and scenario tests
```

---

### Task 1: Installable Plugin Skeleton and Package Validation

**Files:**
- Create: `.codex-plugin/plugin.json`
- Create: `agents/openai.yaml`
- Create: `skills/video-director/SKILL.md`
- Create: `scripts/validate_package.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: repository root.
- Produces: `validate_package(root: Path) -> list[str]`; plugin ID `video-production-toolkit`; top-level skill name `video-director`.

- [ ] **Step 1: Write the failing package test**

```python
# tests/test_package.py
import unittest
from pathlib import Path

from scripts.validate_package import validate_package

ROOT = Path(__file__).parents[1]

class PackageTests(unittest.TestCase):
    def test_required_plugin_entrypoints_exist(self):
        self.assertEqual([], validate_package(ROOT))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing-module failure**

Run: `python3 -m unittest tests.test_package -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.validate_package'`.

- [ ] **Step 3: Add the minimal plugin manifest and entry skill**

```json
{
  "id": "video-production-toolkit",
  "name": "Video Production Toolkit",
  "version": "0.1.0",
  "description": "Recoverable, user-directed knowledge-video production workflows"
}
```

`skills/video-director/SKILL.md` must declare `name: video-director`, describe topic/script/voice/A-roll knowledge-video requests, and instruct the agent to read only `project.json`, choose one ready task, and load the single matching child skill.

- [ ] **Step 4: Implement deterministic package validation**

```python
# scripts/validate_package.py
import json
from pathlib import Path

REQUIRED = (
    ".codex-plugin/plugin.json",
    "agents/openai.yaml",
    "skills/video-director/SKILL.md",
)

def validate_package(root: Path) -> list[str]:
    errors = [f"missing:{path}" for path in REQUIRED if not (root / path).is_file()]
    manifest_path = root / ".codex-plugin/plugin.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("id") != "video-production-toolkit":
            errors.append("invalid:plugin-id")
    return errors

if __name__ == "__main__":
    import sys
    issues = validate_package(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())
    print("\n".join(issues) if issues else "package valid")
    raise SystemExit(bool(issues))
```

- [ ] **Step 5: Run the package test and validator**

Run: `python3 -m unittest tests.test_package -v`

Expected: PASS.

Run: `python3 scripts/validate_package.py .`

Expected: `package valid`.

- [ ] **Step 6: Commit the plugin skeleton**

```bash
git add .codex-plugin agents skills/video-director scripts/validate_package.py tests/test_package.py
git commit -m "feat: scaffold video production toolkit plugin"
```

---

### Task 2: Runtime Project Initialization, Events, and Replay

**Files:**
- Create: `assets/project-template/project.json`
- Create: `references/schemas/project.schema.json`
- Create: `references/schemas/event.schema.json`
- Create: `scripts/toolkit/__init__.py`
- Create: `scripts/toolkit/project_state.py`
- Create: `scripts/init_project.py`
- Test: `tests/test_project_state.py`

**Interfaces:**
- Consumes: `project_id: str`, `workflow: str`, `target: Path`.
- Produces: `initialize_project(target, project_id, workflow) -> dict`; `append_event(root, event) -> None`; `replay_events(root) -> dict`.

- [ ] **Step 1: Write failing initialization and replay tests**

```python
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from scripts.toolkit.project_state import initialize_project, append_event, replay_events

class ProjectStateTests(unittest.TestCase):
    def test_initialize_creates_compact_project_and_event_log(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            state = initialize_project(root, "kv-001", "knowledge-video")
            self.assertEqual("initialized", state["phase"])
            self.assertTrue((root / "events/events.jsonl").is_file())

    def test_replay_restores_phase_from_events(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_project(root, "kv-001", "knowledge-video")
            append_event(root, {"event": "project.phase_changed", "phase": "content_ready"})
            self.assertEqual("content_ready", replay_events(root)["phase"])
```

- [ ] **Step 2: Run tests and verify missing implementation**

Run: `python3 -m unittest tests.test_project_state -v`

Expected: FAIL importing `scripts.toolkit.project_state`.

- [ ] **Step 3: Implement atomic initialization and append-only events**

Use `tempfile.NamedTemporaryFile(dir=root, delete=False)` followed by `Path.replace()` for `project.json`. Create only these runtime directories: `artifacts`, `tasks`, `events`, `approvals`, `previews`, `media`, and `timeline`. The initial event is `project.initialized` and contains `schema_version`, `project_id`, and `workflow`.

```python
PHASES = (
    "initialized", "content_ready", "direction_ready", "storyboard_ready",
    "production_ready", "assembled", "review_ready", "handoff_ready",
)
```

- [ ] **Step 4: Implement `init_project.py` CLI**

```python
parser.add_argument("target", type=Path)
parser.add_argument("--project-id", required=True)
parser.add_argument("--workflow", default="knowledge-video")
```

The command prints only the absolute `project.json` path and project ID.

- [ ] **Step 5: Run tests and a CLI smoke test**

Run: `python3 -m unittest tests.test_project_state -v`

Expected: PASS.

Run: `python3 scripts/init_project.py /tmp/video-toolkit-smoke --project-id kv-smoke`

Expected: creates a valid project whose event replay returns phase `initialized`.

- [ ] **Step 6: Commit project state initialization**

```bash
git add assets/project-template references/schemas scripts/toolkit scripts/init_project.py tests/test_project_state.py
git commit -m "feat: add recoverable project state"
```

---

### Task 3: Immutable Artifacts, DAG Invalidation, and Approvals

**Files:**
- Create: `references/schemas/artifact.schema.json`
- Create: `references/schemas/approval.schema.json`
- Create: `scripts/toolkit/artifacts.py`
- Create: `scripts/toolkit/invalidation.py`
- Test: `tests/test_artifacts.py`
- Test: `tests/test_invalidation.py`

**Interfaces:**
- Produces: `create_artifact(root, artifact: dict) -> Path`; `approve_artifact(root, target_id, scope, notes) -> str`; `invalidate_descendants(artifacts, changed_id, rules) -> set[str]`.
- Artifact required keys: `artifact_id`, `type`, `version`, `status`, `parents`, `path`.

- [ ] **Step 1: Write failing immutable-artifact tests**

```python
def test_existing_artifact_id_cannot_be_overwritten(self):
    create_artifact(self.root, self.artifact)
    with self.assertRaises(FileExistsError):
        create_artifact(self.root, self.artifact)

def test_approval_is_persisted_as_artifact(self):
    create_artifact(self.root, self.artifact)
    approval_id = approve_artifact(self.root, "style-v1", "whole-project", "approved")
    self.assertTrue((self.root / "approvals" / f"{approval_id}.json").is_file())
```

- [ ] **Step 2: Write failing targeted invalidation tests**

```python
def test_style_change_does_not_invalidate_narration(self):
    stale = invalidate_descendants(self.artifacts, "style-v1", self.rules)
    self.assertEqual({"scene-S01-v1", "timeline-v1"}, stale)

def test_voice_change_invalidates_timing_descendants(self):
    stale = invalidate_descendants(self.artifacts, "voice-v1", self.rules)
    self.assertIn("storyboard-v1", stale)
    self.assertIn("timeline-v1", stale)
```

- [ ] **Step 3: Run tests and verify failures**

Run: `python3 -m unittest tests.test_artifacts tests.test_invalidation -v`

Expected: FAIL importing both new modules.

- [ ] **Step 4: Implement immutable writes and graph traversal**

Store one metadata JSON file per artifact under `artifacts/<type>/<artifact_id>.json`. Validate all parents exist. Build reverse edges once per invalidation call. Apply explicit type-to-type invalidation rules from `references/policies/invalidation.json`; never infer rules from artifact names.

- [ ] **Step 5: Add explicit MVP invalidation rules**

```json
{
  "narration": ["semantic-beats", "storyboard", "scene-contract", "media", "timeline", "review-pack"],
  "voice-timing": ["semantic-beats", "storyboard", "scene-contract", "timeline", "review-pack"],
  "style-pack": ["visual-preview", "media", "motion-graphic", "timeline", "review-pack"],
  "layout-pack": ["visual-preview", "scene-contract", "media", "motion-graphic", "timeline", "review-pack"],
  "scene-media": ["timeline", "review-pack"],
  "caption-style": ["captions", "timeline", "review-pack"]
}
```

- [ ] **Step 6: Run artifact and invalidation tests**

Run: `python3 -m unittest tests.test_artifacts tests.test_invalidation -v`

Expected: PASS.

- [ ] **Step 7: Commit artifact DAG behavior**

```bash
git add references/schemas references/policies/invalidation.json scripts/toolkit tests/test_artifacts.py tests/test_invalidation.py
git commit -m "feat: add immutable artifact dependency graph"
```

---

### Task 4: Task Envelopes, Locks, Stale Results, and Retry Policy

**Files:**
- Create: `references/schemas/task-envelope.schema.json`
- Create: `references/schemas/task-result.schema.json`
- Create: `references/policies/retry.md`
- Create: `scripts/toolkit/tasks.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Produces: `create_task(root, envelope) -> Path`; `claim_task(root, task_id, worker_id) -> None`; `complete_task(root, result) -> str`; `retry_decision(task, result, adapters) -> dict`.
- Result status is one of `blocked`, `waiting_external`, `waiting_user`, `succeeded`, `failed`, `cancelled`.

- [ ] **Step 1: Write failing task safety tests**

```python
def test_second_worker_cannot_claim_same_task(self):
    create_task(self.root, self.envelope)
    claim_task(self.root, "preview-S03-v2", "worker-a")
    with self.assertRaises(RuntimeError):
        claim_task(self.root, "preview-S03-v2", "worker-b")

def test_late_result_cannot_supersede_new_input_version(self):
    create_task(self.root, self.envelope)
    self.set_active_input("scene-contract-S03-v5")
    status = complete_task(self.root, self.result_for_v4)
    self.assertEqual("stale-result", status)

def test_retry_stops_after_two_attempts_and_one_fallback(self):
    decision = retry_decision({"attempt": 2, "adapter": "hyperframes"}, {"error": "adapter_error"}, ["hyperframes", "remotion"])
    self.assertEqual("switch-adapter", decision["action"])
    blocked = retry_decision({"attempt": 2, "fallback_used": True}, {"error": "adapter_error"}, ["hyperframes", "remotion"])
    self.assertEqual("block", blocked["action"])
```

- [ ] **Step 2: Run and verify missing implementation**

Run: `python3 -m unittest tests.test_tasks -v`

Expected: FAIL importing `scripts.toolkit.tasks`.

- [ ] **Step 3: Implement lock files and stale-input comparison**

Create locks with exclusive mode `"x"` at `tasks/locks/<task_id>.lock`. A result is current only when every input artifact ID still matches the task envelope and remains non-stale. Persist stale results under `tasks/stale-results/` for diagnosis without registering their outputs.

- [ ] **Step 4: Implement bounded retry policy**

Only `contract_error` and `adapter_error` are retryable. `input_error` and `direction_error` immediately request user action. No task gets more than two same-adapter attempts and one declared adapter fallback.

- [ ] **Step 5: Run task tests**

Run: `python3 -m unittest tests.test_tasks -v`

Expected: PASS.

- [ ] **Step 6: Commit task execution safety**

```bash
git add references/schemas references/policies/retry.md scripts/toolkit/tasks.py tests/test_tasks.py
git commit -m "feat: add isolated task execution contracts"
```

---

### Task 5: Versioned Registries and Compact Candidate Search

**Files:**
- Create: `references/schemas/registry-entry.schema.json`
- Create: `scripts/toolkit/registry.py`
- Create: `scripts/search_registry.py`
- Create: `registries/styles/editorial-clean/v1/manifest.json`
- Create: `registries/layouts/talking-head-left-explainer-right/v1/manifest.json`
- Create: `registries/recipes/video-shotcraft-index.json`
- Create: `registries/adapters/*.json`
- Create: `registries/lessons/.gitkeep`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `search_registry(root, kind, query, limit=3) -> list[dict]`; `promote_lesson(lesson, evidence) -> dict`.
- Query keys: `mechanism`, `participants`, `duration`, `canvas`, `preferred_renderer`, `recent_ids`.

- [ ] **Step 1: Write failing search and lesson-promotion tests**

```python
def test_search_returns_three_compact_ranked_candidates(self):
    results = search_registry(ROOT, "recipes", self.query, limit=3)
    self.assertLessEqual(len(results), 3)
    self.assertNotIn("implementation_source", results[0])
    self.assertIn("implementation_ref", results[0])

def test_one_project_observation_cannot_become_global(self):
    promoted = promote_lesson(self.lesson, {"scenes": 2, "projects": 1})
    self.assertEqual("candidate", promoted["status"])
```

- [ ] **Step 2: Run and verify failures**

Run: `python3 -m unittest tests.test_registry -v`

Expected: FAIL importing `scripts.toolkit.registry`.

- [ ] **Step 3: Implement deterministic metadata scoring**

Score exact mechanism `+40`, compatible participant shape `+20`, duration in range `+15`, preferred renderer `+10`, recent recipe `-25`, and recent carrier `-12`. Sort by descending score then stable ID. Return compact fields only: `id`, `version`, `score`, `job`, `preview`, `renderer`, `implementation_ref`, `license`.

- [ ] **Step 4: Add external adapter manifests**

Create manifests for `hyperframes`, `remotion`, `video-shotcraft`, and `chatcut`. Each declares `capabilities`, `accepts`, `outputs`, `editable`, `installed_skill`, `fallback`, and `license_mode`. Hyperframes uses `license_mode: external-reference`; do not copy its skill content.

- [ ] **Step 5: Build VideoShotCraft metadata indexing without loading recipe bodies**

Add `scripts/index_video_shotcraft.py` that reads the installed skill's gallery index path passed through `--source`, extracts recipe metadata and source references, and writes `registries/recipes/video-shotcraft-index.json`. The script must fail clearly when the source is absent and must not copy demo source code.

- [ ] **Step 6: Run registry tests and index smoke test**

Run: `python3 -m unittest tests.test_registry -v`

Expected: PASS.

Run: `python3 scripts/index_video_shotcraft.py --source /Users/fantasy/.codex/skills/video-shotcraft --check-only`

Expected: reports a non-zero recipe count and writes nothing in check-only mode.

- [ ] **Step 7: Commit registry support**

```bash
git add references/schemas registries scripts/toolkit/registry.py scripts/search_registry.py scripts/index_video_shotcraft.py tests/test_registry.py
git commit -m "feat: add extensible creative registries"
```

---

### Task 6: Child Skill Contracts and Progressive Routing

**Files:**
- Create: `skills/video-project-manager/SKILL.md`
- Create: `skills/narration-planner/SKILL.md`
- Create: `skills/visual-system-designer/SKILL.md`
- Create: `skills/storyboard-director/SKILL.md`
- Create: `skills/scene-producer/SKILL.md`
- Create: `skills/motion-director/SKILL.md`
- Create: `skills/timeline-assembler/SKILL.md`
- Create: `skills/structural-validator/SKILL.md`
- Create: `skills/video-review-packager/SKILL.md`
- Create: `references/policies/decision-gates.md`
- Create: `references/policies/visual-carriers.md`
- Test: `tests/test_skill_contracts.py`

**Interfaces:**
- Each skill consumes exactly one declared task-envelope capability and produces one task-result envelope.
- Capability names: `project.manage`, `narration.plan`, `visual.preview`, `storyboard.plan`, `scene.produce`, `motion.preview`, `motion.produce`, `timeline.assemble`, `structure.validate`, `review.package`.

- [ ] **Step 1: Write failing static contract tests**

```python
EXPECTED = {
    "video-project-manager": "project.manage",
    "narration-planner": "narration.plan",
    "visual-system-designer": "visual.preview",
    "storyboard-director": "storyboard.plan",
    "scene-producer": "scene.produce",
    "motion-director": "motion.preview",
    "timeline-assembler": "timeline.assemble",
    "structural-validator": "structure.validate",
    "video-review-packager": "review.package",
}

def test_each_child_skill_has_one_owned_capability(self):
    for skill, capability in EXPECTED.items():
        text = (ROOT / "skills" / skill / "SKILL.md").read_text()
        self.assertIn(f"Owned capability: `{capability}`", text)
        self.assertIn("Return a task-result envelope", text)
```

- [ ] **Step 2: Run and verify missing skill failures**

Run: `python3 -m unittest tests.test_skill_contracts -v`

Expected: FAIL because child skill files do not exist.

- [ ] **Step 3: Write small child skill entrypoints**

Each `SKILL.md` must contain only purpose, owned capability, allowed inputs, required output, stopping conditions, user-gate behavior, and links to the relevant schema/policy. Move format-specific detail into references. Keep each entrypoint below 250 English-equivalent words where practical.

- [ ] **Step 4: Encode decision gates and visual-carrier grammar**

`decision-gates.md` defines content, visual direction, storyboard/cost, and representative-slice/final-draft approvals. `visual-carriers.md` defines A-roll, B-roll, Scene, Demo, Motion Graphics, and Evidence, plus the one-primary/one-secondary invariant.

- [ ] **Step 5: Strengthen `video-director` routing**

The top-level skill must map project phase and ready-task capability to exactly one child skill. It must instruct the agent to stop if more than one contradictory task is marked ready, if an approval is missing, or if the state summary does not match event replay.

- [ ] **Step 6: Run skill contract and package tests**

Run: `python3 -m unittest tests.test_skill_contracts tests.test_package -v`

Expected: PASS.

- [ ] **Step 7: Commit child skills**

```bash
git add skills references/policies tests/test_skill_contracts.py
git commit -m "feat: add bounded video production skills"
```

---

### Task 7: Structural Validator and User Review Packager

**Files:**
- Create: `scripts/toolkit/validation.py`
- Create: `scripts/validate_project.py`
- Create: `scripts/build_review_pack.py`
- Create: `assets/project-template/review-pack/index.html`
- Test: `tests/test_validation.py`
- Test: `tests/test_review_pack.py`

**Interfaces:**
- Produces: `validate_project(root) -> {"errors": list, "warnings": list}`; `build_review_pack(root, output) -> Path`.

- [ ] **Step 1: Write failing objective-validation tests**

```python
def test_stale_artifact_on_active_timeline_is_error(self):
    result = validate_project(self.fixture("stale-timeline"))
    self.assertIn("stale-active-artifact", {item["code"] for item in result["errors"]})

def test_subjective_aesthetic_language_is_not_emitted(self):
    result = validate_project(self.fixture("valid-project"))
    rendered = json.dumps(result, ensure_ascii=False)
    self.assertNotIn("不高级", rendered)
    self.assertNotIn("不好看", rendered)
```

- [ ] **Step 2: Write failing review-pack test**

```python
def test_review_pack_links_previews_and_decisions_without_embedding_media(self):
    path = build_review_pack(self.root, self.root / "review")
    html = path.read_text(encoding="utf-8")
    self.assertIn("data-scene-id=\"S01\"", html)
    self.assertNotIn("data:image/", html)
```

- [ ] **Step 3: Run and verify missing implementation**

Run: `python3 -m unittest tests.test_validation tests.test_review_pack -v`

Expected: FAIL importing validator and packager modules.

- [ ] **Step 4: Implement structural checks**

Validate artifact existence/status, DAG parent existence, active-version freshness, timeline duration/gaps/overlaps, caption safe-region records, required Demo lifecycle, approval presence, saved-project reference, and task-envelope completeness. Return stable error codes with artifact or task IDs.

- [ ] **Step 5: Implement a file-link review pack**

Generate a static `index.html` and `review.json` containing relative links to low-resolution previews, contact sheets, keyframes, comparisons, timecoded warnings, and decision requests. Do not embed base64 media or ask the model to author subjective critiques.

- [ ] **Step 6: Run validation and review tests**

Run: `python3 -m unittest tests.test_validation tests.test_review_pack -v`

Expected: PASS.

- [ ] **Step 7: Commit validation and review packaging**

```bash
git add scripts assets/project-template/review-pack tests/test_validation.py tests/test_review_pack.py
git commit -m "feat: add structural validation and review packs"
```

---

### Task 8: External Adapter Contract Tests and Representative-Slice Planner

**Files:**
- Create: `references/schemas/motion-contract.schema.json`
- Create: `references/schemas/scene-contract.schema.json`
- Create: `scripts/toolkit/adapters.py`
- Create: `scripts/plan_representative_slice.py`
- Test: `tests/test_adapters.py`
- Test: `tests/test_representative_slice.py`

**Interfaces:**
- Produces: `select_adapter(capability, requirements, manifests) -> dict`; `select_representative_slice(scene_contracts) -> list[str]`.

- [ ] **Step 1: Write failing adapter selection tests**

```python
def test_h5_preview_prefers_hyperframes(self):
    selected = select_adapter("motion.preview", {"format": "html"}, self.manifests)
    self.assertEqual("hyperframes", selected["id"])

def test_editable_overlay_prefers_chatcut_motion_graphics(self):
    selected = select_adapter("motion.produce", {"editable": True, "overlay": True}, self.manifests)
    self.assertEqual("chatcut", selected["id"])
```

- [ ] **Step 2: Write failing representative-slice risk test**

```python
def test_slice_covers_highest_risk_carriers(self):
    selected = select_representative_slice(self.contracts)
    carriers = {self.by_id[item]["primary_carrier"] for item in selected}
    self.assertIn("scene", carriers)
    self.assertIn("motion-graphics", carriers)
```

- [ ] **Step 3: Run and verify missing implementation**

Run: `python3 -m unittest tests.test_adapters tests.test_representative_slice -v`

Expected: FAIL importing new modules.

- [ ] **Step 4: Implement capability-first adapter selection**

Filter by capability, installed skill, accepted contract, required output, and editability. Rank explicit user preference first, then local/no-credit execution, then declared primary order. Return a single backend and one fallback; never fan out the same shot to several engines.

- [ ] **Step 5: Implement risk-based representative-slice selection**

Assign risk weights: new character baseline `5`, scene-image generation `4`, Motion Graphics `4`, Demo `4`, generated video `3`, B-roll placement `2`, captions `1`. Choose the shortest adjacent range between 10 and 20 seconds that covers the maximum distinct high-risk carriers. If no range covers both scene and motion risks, select two explicit non-adjacent sample ranges and mark the slice as composite.

- [ ] **Step 6: Run adapter and slice tests**

Run: `python3 -m unittest tests.test_adapters tests.test_representative_slice -v`

Expected: PASS.

- [ ] **Step 7: Commit adapter routing and slice planning**

```bash
git add references/schemas scripts/toolkit/adapters.py scripts/plan_representative_slice.py tests/test_adapters.py tests/test_representative_slice.py
git commit -m "feat: route adapters and plan representative slices"
```

---

### Task 9: Migrate Validated Legacy Rules and Validators

**Files:**
- Create: `references/policies/narration-and-coverage.md`
- Create: `references/policies/project-assets.md`
- Create: `scripts/toolkit/coverage.py`
- Create: `scripts/migration_audit.py`
- Create: `docs/migration/knowledge-video-visual-director.md`
- Test: `tests/test_coverage.py`
- Test: `tests/test_migration_audit.py`

**Interfaces:**
- Consumes legacy path supplied by CLI, never hardcoded by library code.
- Produces: `evaluate_coverage(shots) -> dict`; `audit_legacy(legacy_root, new_root) -> dict`.

- [ ] **Step 1: Write coverage regression tests before moving code**

```python
def test_decorative_motion_does_not_cover_semantic_beat(self):
    result = evaluate_coverage([{
        "shot_id": "S1", "duration_ms": 6000,
        "semantic_beats": ["premise", "result"],
        "visual_states": [{"kind": "floating", "start_ms": 0, "end_ms": 6000}],
    }])
    self.assertIn("decorative-only", {item["code"] for item in result["issues"]})

def test_meaningful_states_cover_matching_beats(self):
    result = evaluate_coverage([self.meaningful_shot])
    self.assertEqual([], result["issues"])
```

- [ ] **Step 2: Run and verify missing coverage module**

Run: `python3 -m unittest tests.test_coverage -v`

Expected: FAIL importing `scripts.toolkit.coverage`.

- [ ] **Step 3: Port only deterministic coverage behavior**

Port meaningful/decorative state classification, beat coverage, readable holds, and uncovered intervals. Generalize pacing: do not retain a universal 0.8–1.2 second rule. Place policy prose under `narration-and-coverage.md` and keep the validator data-driven.

- [ ] **Step 4: Write a migration audit with explicit retained and rejected inventory**

The audit must report legacy files as `migrated`, `replaced`, `externalized`, or `rejected`, with new owner paths. It must fail when any executable legacy validator lacks a disposition.

- [ ] **Step 5: Run legacy audit against the installed old skill**

Run: `python3 scripts/migration_audit.py --legacy /Users/fantasy/.codex/skills/knowledge-video-visual-director --new .`

Expected: zero undisposed executable files; a report is written to `docs/migration/knowledge-video-visual-director.md`.

- [ ] **Step 6: Run coverage and migration tests**

Run: `python3 -m unittest tests.test_coverage tests.test_migration_audit -v`

Expected: PASS.

- [ ] **Step 7: Commit migrated policies and validators**

```bash
git add references/policies scripts/toolkit/coverage.py scripts/migration_audit.py docs/migration tests/test_coverage.py tests/test_migration_audit.py
git commit -m "refactor: migrate validated knowledge video rules"
```

---

### Task 10: End-to-End Recovery Scenario, Plugin Installation, and Legacy Retirement

**Files:**
- Create: `tests/fixtures/knowledge-video-minimal/`
- Create: `tests/test_end_to_end.py`
- Create: `scripts/install_personal_plugin.py`
- Create: `scripts/verify_installation.py`

**Interfaces:**
- Produces: `run_smoke(root) -> dict`; installer copies or links the repository plugin to the supported personal plugin location discovered at execution time; verifier reports skill discovery and external adapter availability.

- [ ] **Step 1: Write the failing recovery and invalidation scenario**

```python
def test_project_can_resume_and_rebuild_only_changed_scene(self):
    project = self.initialize_fixture()
    self.advance_to_storyboard_ready(project)
    self.complete_scene(project, "S01")
    self.complete_scene(project, "S02")
    self.change_scene_contract(project, "S02")
    resumed = replay_events(project)
    self.assertEqual("approved", self.artifact(project, "scene-S01-v1")["status"])
    self.assertEqual("stale", self.artifact(project, "scene-S02-v1")["status"])
    self.assertEqual(["scene.produce:S02"], resumed["ready_tasks"])

def test_representative_slice_requires_user_approval_before_expansion(self):
    project = self.initialize_fixture()
    self.prepare_slice_without_approval(project)
    self.assertNotIn("full-production", replay_events(project)["ready_tasks"])
```

- [ ] **Step 2: Run the complete suite and verify the scenario fails**

Run: `python3 -m unittest discover -s tests -v`

Expected: all earlier tests PASS and `tests.test_end_to_end` FAIL at the missing orchestration behavior.

- [ ] **Step 3: Implement the minimal coordinator transition calculator**

Add `scripts/toolkit/orchestrator.py` with `calculate_ready_tasks(state, artifacts, approvals) -> list[str]`. It may emit only tasks whose parents are approved/non-stale, whose lock is free, and whose required decision gate has an approval artifact.

- [ ] **Step 4: Run full tests, package validation, and representative smoke**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS.

Run: `python3 scripts/validate_package.py .`

Expected: `package valid`.

Run: `python3 scripts/verify_installation.py --repo . --check-external-skills`

Expected: plugin valid; Hyperframes, Remotion, VideoShotCraft, and ChatCut capability statuses reported individually; optional absence is a warning, not a package failure.

- [ ] **Step 5: Install the personal plugin using the supported discovered location**

Run: `python3 scripts/install_personal_plugin.py --source . --mode link`

Expected: prints the exact installed plugin path and does not overwrite an unrelated existing plugin. If a same-ID plugin exists, require `--replace` and preserve a recoverable backup.

- [ ] **Step 6: Verify the new entrypoint before touching the old skill**

Run: `python3 scripts/verify_installation.py --require-skill video-director --require-resume-smoke`

Expected: PASS and confirms the new plugin can initialize, replay, approve, invalidate one scene, and plan a representative slice.

- [ ] **Step 7: Retire the old skill after explicit execution-time approval**

Resolve and print the exact target first:

```bash
python3 -c 'from pathlib import Path; p=Path("/Users/fantasy/.codex/skills/knowledge-video-visual-director").resolve(); assert p.name=="knowledge-video-visual-director"; print(p)'
```

After approval, remove only that exact directory using a small retirement script that verifies the basename, writes a retirement event into the repository migration report, and refuses symlinks or broader paths. Do not use a recursive shell glob.

- [ ] **Step 8: Verify retirement and run the suite again**

Run: `python3 scripts/verify_installation.py --require-skill video-director --forbid-skill knowledge-video-visual-director`

Expected: PASS.

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 9: Commit the end-to-end slice and retirement tooling**

```bash
git add scripts tests skills/video-director docs/migration
git commit -m "feat: complete recoverable video toolkit foundation"
```

- [ ] **Step 10: Push the verified implementation branch**

Run: `git status --short --branch`

Expected: clean working tree on the implementation branch.

Run: `git push -u origin HEAD`

Expected: the verified branch is available in `Fantasy421/video-production-toolkit` without force-pushing.

---

## Final Verification Matrix

Run all commands before claiming completion:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py .
python3 scripts/verify_installation.py --require-skill video-director --forbid-skill knowledge-video-visual-director --check-external-skills
git status --short --branch
```

Required observable outcomes:

- All tests pass.
- Package validator reports `package valid`.
- `video-director` is discoverable from the installed plugin.
- Legacy `knowledge-video-visual-director` is absent only after migration and resume-smoke verification.
- External adapter capability status is reported without loading their full instructions into the coordinator.
- Working tree is clean and no force push was used.

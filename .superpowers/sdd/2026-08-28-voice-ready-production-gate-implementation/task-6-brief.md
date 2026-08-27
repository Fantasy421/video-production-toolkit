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

- [x] **Step 1: Write failing invalidation tests**

```python
def test_voice_profile_change_invalidates_audio_and_timing_consumers(self):
    stale = invalidate_descendants(self.graph, "voice-profile-v1", self.rules)
    self.assertEqual({"voiceover-v1", "voice-timing-v1", "beats-v1", "storyboard-v1", "timeline-v1", "review-v1"}, stale)

def test_style_change_does_not_invalidate_unchanged_voiceover(self):
    stale = invalidate_descendants(self.graph, "style-v1", self.rules)
    self.assertNotIn("voiceover-v1", stale)
```

- [x] **Step 2: Write failing validation/review tests**

```python
def test_voice_timing_beyond_audio_duration_is_structural_error(self):
    self.assertIn("voice-timing-out-of-bounds", self.codes(validate_project(self.root)))

def test_review_pack_links_only_current_voiceover(self):
    pack = build_review_pack(self.root, self.output)
    self.assertEqual("voiceover-v2", pack["voice"]["voiceover_id"])
    self.assertNotIn("voiceover-v1", json.dumps(pack))
```

- [x] **Step 3: Run and verify RED**

Run: `python3 -m unittest tests.test_invalidation tests.test_validation tests.test_review_pack -v`

- [x] **Step 4: Update shipped rules and structural checks**

Add exact descendant types for narration, source decision, profile, voiceover, and voice timing. Validation consumes the same Task 2 validator and emits stable issue codes. Review packs resolve effective event-backed status and link current audio without embedding it.

- [x] **Step 5: Run tests and commit**

Run: `python3 -m unittest tests.test_invalidation tests.test_validation tests.test_review_pack -v`

```bash
git add references/policies/invalidation.json scripts/toolkit/validation.py scripts/build_review_pack.py tests/test_invalidation.py tests/test_validation.py tests/test_review_pack.py
git commit -m "feat: validate and review voice lineage"
```

---

# Task 6 Report: Voice Lineage Invalidation, Validation, and Review

Status: complete

Invalidation: the shipped policy now precisely carries narration,
voice-source-decision, voice-profile, voiceover, and voice-timing revisions
through their declared descendants. It includes captions, media, Motion
Graphics, timelines, and review packs where appropriate. Visual style changes
remain isolated from an unchanged voiceover.

Validation: current version-two projects at `voice_ready` or later reuse the
authoritative effective voice-bundle validator. Its stable lineage issues are
reported unchanged. The structural layer then confirms the selected voiceover
media exists and reads WAV container metadata only; it never decodes or loads
audio payloads. It emits stable media-missing, unreadable-duration,
duration-mismatch, and timing-out-of-bounds issues as applicable.

Review: review packs now resolve effective (event-overlay) artifacts, expose
only the current voiceover's relative link and compact source/profile/timing
summary, and never embed audio. Invalid or stale voice lineages have no voice
link; their structural blockers remain in the existing error list. Publication
continues to use the pre-existing atomic bundle pointer.

TDD evidence: the initial targeted RED run failed because the policy lacked
voice profile descendants, structural validation trusted voice metadata, and
the review data had no `voice` section. After the minimal implementation, the
same targeted suite passed.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task6-green python3 -m unittest tests.test_invalidation tests.test_validation tests.test_review_pack -v` — 56 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task6-full python3 -m unittest discover -s tests -v` — 291 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task6-compile python3 -m py_compile scripts/toolkit/*.py scripts/*.py tests/*.py` — passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- `git diff --check` — passed.

Concerns: duration verification presently supports the deterministic WAV
container used by the voice workflow; other audio formats are reported as
`voiceover-media-duration-unverifiable` rather than being decoded or loaded.

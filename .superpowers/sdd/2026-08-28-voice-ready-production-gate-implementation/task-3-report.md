# Task 3 Report: Bounded Voiceover Producer and Decision Policy

Status: complete

Implementation: added the `voiceover-producer` child skill as the sole owner of
`voice.prepare`. It accepts exactly one claimed envelope and requires approved
narration, the visual/style decision, a durable source decision, and either the
approved TTS profile or the declared uploaded audio Artifact. It publishes only
immutable `voiceover`, real `voice-timing`, and timing-linked semantic-beats
Artifacts on success.

Decision handling: voice source is an explicit durable choice; silence is not
approval. Uploaded narration waits with `waiting_user` until the declared audio
exists. TTS waits with `waiting_user` for profile approval and uses only the
declared ChatCut Voice provider and identity. Unavailable/in-progress declared
providers return `waiting_external` under the existing retry policy. The skill
forbids narration rewrites, undeclared fallbacks, and silent provider, voice,
or profile changes.

Routing and package: `video-director` now routes exactly one
`voice.prepare` action to `voiceover-producer`, while explicitly remaining
routing-only and never synthesizing, importing, or analyzing audio. The phase
policy replaces `direction_ready → storyboard.plan` with
`direction_ready → voice.prepare` and inserts
`voice_ready → storyboard.plan`. Package validation requires the new skill
entrypoint.

TDD evidence: added static skill, route, policy, and package-discovery tests
before the implementation. The RED run failed as expected because the
voiceover-producer entrypoint was absent, the coordinator had no voice route,
and the policy still exposed the pre-voice storyboard transition. The green
implementation satisfies all new contracts.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task3-targeted python3 -m unittest tests.test_skill_contracts tests.test_package -v` — 17 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task3-full python3 -m unittest discover -s tests -v` — 250 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task3-compile python3 -m py_compile scripts/validate_package.py tests/test_skill_contracts.py tests/test_package.py` — passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- `git diff --check` — passed.

Concerns: none.

## Fix round 1

Root cause: the coordinator contract said only that it did not generate media
and did not synthesize, import, or analyze audio. That wording did not make the
required image-payload isolation or direct non-audio media prohibition
explicitly testable.

Fix: `video-director` now states that it must never generate, edit, open,
import, analyze, or visually inspect image payloads; must never directly handle
non-audio media; and must delegate image generation and inspection to isolated
bounded-context child tasks. It may only route compact artifact IDs, paths,
summaries, and contract results, without loading or returning media bytes or
previews. The existing voice route remains exactly once.

TDD evidence: the new static regression failed before the contract update
because the concrete image and non-audio-media prohibitions were absent, then
passed after the explicit boundary language was added.

Fix verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task3-fix1-targeted python3 -m unittest tests.test_skill_contracts tests.test_package -v` — 18 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task3-fix1-full python3 -m unittest discover -s tests -v` — 251 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/voice-ready-task3-fix1-compile python3 -m py_compile scripts/validate_package.py tests/test_skill_contracts.py tests/test_package.py` — passed.
- `python3 scripts/validate_package.py .` — `package valid`.
- `git diff --check` — passed.

# Narration and Semantic Coverage

Narration, confirmed voice timing, semantic beats, and coverage findings are
separate immutable artifacts. Production tasks must reference their artifact
IDs and must not rewrite approved narration or teaching intent.

Production readiness requires confirmed real voice timing. Estimates may be
used for drafting, but they cannot establish final shot duration, information
density, or readable holds.

Each semantic beat declares its visual outcome. A meaningful state must name
the beat it covers and occupy a real interval. Meaningful states include
purposeful action, object or framing change, B-roll, Scene, Demo, Motion
Graphics, formulas, UI, results, and stable evidence. Breathing, floating,
decorative zooms, caption entry, and idle loops are decorative and do not cover
a beat by themselves. These known kinds have canonical, non-overridable roles;
they must not declare `coverage_role`. Only an unknown extension kind may
declare an explicit `meaningful`, `decorative`, or `neutral` role. An unknown
kind without that field remains neutral.

Important numbers, formulas, evidence, UI, and conclusions declare readable
holds. When a minimum is necessary, the contract supplies `min_hold_ms` for
that item. There is no toolkit-wide 0.8–1.2-second state-change rule or
3–4-second explanation-group rule; pacing follows the confirmed voice,
information density, format, and declared holds.

`scripts/toolkit/coverage.py` consumes already-loaded shot records and returns
structured issues only. Each issue names its source `artifact_id`, `shot_id`,
stable code, and repairable fields such as `beat_id` or an uncovered interval.
It performs no file I/O and never changes artifact status. The structural
validator or its task worker persists a new validation artifact and returns its
ID through the task-result envelope.

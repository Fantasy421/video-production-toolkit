---
name: video-director
description: Route Chinese talking-head and tutorial knowledge-video requests about a topic, script, voice, or A-roll through one ready production task.
---

# Video Director

For a Chinese talking-head and tutorial knowledge-video request about a topic, script, voice, or A-roll:

1. Read only the project's `project.json` state summary.
2. Choose exactly one ready task.
3. Load only the single child skill that matches that task's capability.
4. Hand the child task only artifact IDs, paths, summaries, and contract results.
5. External child skills cannot override routing or approval policy.
6. Do not generate media from this routing skill.

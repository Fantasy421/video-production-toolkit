Status: complete

Implementation: added a versioned registry-entry schema; editable style and layout manifests; four external adapter manifests for Hyperframes, Remotion, VideoShotCraft, and ChatCut; and an empty lessons-registry placeholder. Hyperframes is represented only as an `external-reference`; no external skill body is vendored.

Registry behavior: `search_registry(root, kind, query, limit=3)` reads only JSON metadata, filters incompatible canvases, deterministically scores exact mechanism (+40), compatible participant shape (+20), duration overlap (+15), preferred renderer (+10), recently used recipe (-25), and recently used carrier (-12), then breaks ties by stable ID. Results expose only the approved compact fields. `promote_lesson` keeps single-project evidence project-scoped, promotes two-scene evidence to candidate, promotes cross-project evidence to verified, and requires explicit user approval before a verified lesson can become global.

VideoShotCraft index: `scripts/index_video_shotcraft.py` reads `gallery/api/library.json` from a supplied installed-skill path and writes 209 metadata-only entries to `registries/recipes/video-shotcraft-index.json`. Each entry contains an external source reference and preview metadata, never copied demo or recipe body content. `--check-only` reports the entry count without writing.

Regression evidence: tests cover compact bounded output, exact score/recency terms, canvas compatibility, stable tie breaking, candidate/global lesson maturity gates, and metadata-only VideoShotCraft indexing.

Verification: `python3 -m unittest tests.test_registry -v` — 6 passed. `python3 scripts/index_video_shotcraft.py --source /Users/fantasy/.codex/skills/video-shotcraft --check-only` — indexed 209 recipes without writing. `env PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-pycache-final python3 -m py_compile scripts/toolkit/registry.py scripts/search_registry.py scripts/index_video_shotcraft.py tests/test_registry.py` — passed. `python3 -m unittest discover -s tests -v` — 52 passed. JSON manifests parsed with `jq -e .`; `git diff --check` — passed.

Concerns: none.

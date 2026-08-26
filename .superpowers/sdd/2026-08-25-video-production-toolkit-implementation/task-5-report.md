Status: complete

Implementation: added a versioned registry-entry schema; editable style and layout manifests; four external adapter manifests for Hyperframes, Remotion, VideoShotCraft, and ChatCut; and an empty lessons-registry placeholder. Hyperframes is represented only as an `external-reference`; no external skill body is vendored.

Registry behavior: `search_registry(root, kind, query, limit=3)` reads only JSON metadata, filters incompatible canvases, deterministically scores exact mechanism (+40), compatible participant shape (+20), duration overlap (+15), preferred renderer (+10), recently used recipe (-25), and recently used carrier (-12), then breaks ties by stable ID. Results expose only the approved compact fields. `promote_lesson` keeps single-project evidence project-scoped, promotes two-scene evidence to candidate, promotes cross-project evidence to verified, and requires explicit user approval before a verified lesson can become global.

VideoShotCraft index: `scripts/index_video_shotcraft.py` reads `gallery/api/library.json` from a supplied installed-skill path and writes 209 metadata-only entries to `registries/recipes/video-shotcraft-index.json`. Each entry contains an external source reference and preview metadata, never copied demo or recipe body content. `--check-only` reports the entry count without writing.

Regression evidence: tests cover compact bounded output, exact score/recency terms, canvas compatibility, stable tie breaking, candidate/global lesson maturity gates, and metadata-only VideoShotCraft indexing.

Verification: `python3 -m unittest tests.test_registry -v` — 6 passed. `python3 scripts/index_video_shotcraft.py --source /Users/fantasy/.codex/skills/video-shotcraft --check-only` — indexed 209 recipes without writing. `env PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-pycache-final python3 -m py_compile scripts/toolkit/registry.py scripts/search_registry.py scripts/index_video_shotcraft.py tests/test_registry.py` — passed. `python3 -m unittest discover -s tests -v` — 52 passed. JSON manifests parsed with `jq -e .`; `git diff --check` — passed.

Concerns: none.

Fix round 1 status: complete

Root causes: registry callers could raise their result limit above the coordinator-safe compact set; adapter manifests used local shorthand capability names that Task 8's canonical router cannot select; gallery source strings were placed into external references without path validation; cross-project evidence could skip maturity stages; and runtime entry checks covered only required strings while the schema allowed underspecified optional values and unknown properties.

Fix evidence: the search API now clamps every request, including CLI `--limit`, to three candidates. Adapter manifests declare only the relevant canonical `motion.preview` and `motion.produce` capabilities, while their accepted contract names are distinct `*-contract-v1` values. VideoShotCraft validates each emitted source as a non-empty relative POSIX path with no absolute, dot, traversal, empty, backslash, or control-character segments. Lesson promotion is strictly one stage per call: observed → candidate → verified → global, with global still requiring cross-project evidence and explicit user approval. The schema and runtime now share a closed optional-field contract, type-check non-empty string arrays and adapter fields, validate duration ranges, reject unknown fields, and exercise every packaged registry kind through runtime validation.

Regression evidence: added tests for API/CLI top-three enforcement, canonical adapter capabilities, all maturity transitions and global gates, unsafe gallery source variants, optional field array/mapping/type/value rejection, and packaged manifest alignment.

Verification: `python3 -m unittest tests.test_registry -v` — 12 passed. `python3 scripts/index_video_shotcraft.py --source /Users/fantasy/.codex/skills/video-shotcraft --check-only` — indexed 209 recipes without writing. `env PYTHONPYCACHEPREFIX=/private/tmp/video-toolkit-task5-fix1-pycache python3 -m py_compile scripts/toolkit/registry.py scripts/search_registry.py scripts/index_video_shotcraft.py tests/test_registry.py` — passed. `python3 -m unittest discover -s tests -v` — 58 passed. JSON manifests parsed with `jq -e .`; `git diff --check` — passed.

Fix concerns: none.

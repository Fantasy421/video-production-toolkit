import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.index_video_shotcraft import index_video_shotcraft
from scripts.toolkit.registry import promote_lesson, search_registry


ROOT = Path(__file__).parents[1]


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.query = {
            "mechanism": "explainer-overlay",
            "participants": ["host", "diagram"],
            "duration": 6,
            "canvas": "16:9",
            "preferred_renderer": "remotion",
            "recent_ids": ["vs-shot-explainer-overlay", "a-roll"],
        }
        self.lesson = {
            "id": "lesson-readable-overlays",
            "status": "observed",
            "applicability": {"workflow": "knowledge-video"},
        }

    def test_search_returns_three_compact_ranked_candidates(self):
        """Catches verbose recipe bodies or unbounded, non-deterministic candidate output."""
        results = search_registry(ROOT, "recipes", self.query, limit=3)

        self.assertLessEqual(len(results), 3)
        self.assertEqual(
            {
                "id",
                "version",
                "score",
                "job",
                "preview",
                "renderer",
                "implementation_ref",
                "license",
            },
            set(results[0]),
        )
        self.assertNotIn("implementation_source", results[0])
        self.assertIn("implementation_ref", results[0])

    def test_search_scores_metadata_terms_and_recency_penalties(self):
        """Catches ranking that omits a required score, penalty, or stable tie-break."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            recipe_dir = root / "registries" / "recipes"
            recipe_dir.mkdir(parents=True)
            (recipe_dir / "entries.json").write_text(
                json.dumps(
                    {
                        "recipes": [
                            self.recipe("vs-shot-host-diagram", "16:9"),
                            self.recipe("vs-shot-explainer-overlay", "16:9"),
                            self.recipe("vs-shot-diagram-build", "16:9", duration={"min": 12, "max": 16}),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            results = search_registry(root, "recipes", self.query, limit=3)

        self.assertEqual(
            ["vs-shot-host-diagram", "vs-shot-diagram-build", "vs-shot-explainer-overlay"],
            [result["id"] for result in results],
        )
        self.assertEqual([85, 70, 60], [result["score"] for result in results])

    def test_search_applies_canvas_filter_and_stable_id_tie_break(self):
        """Catches candidate search recommending an incompatible canvas or unstable tied order."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            recipe_dir = root / "registries" / "recipes"
            recipe_dir.mkdir(parents=True)
            (recipe_dir / "entries.json").write_text(
                json.dumps(
                    {
                        "recipes": [
                            self.recipe("z-compatible", "16:9"),
                            self.recipe("a-compatible", "16:9"),
                            self.recipe("wrong-canvas", "9:16"),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            results = search_registry(root, "recipes", {"canvas": "16:9"})

        self.assertEqual(["a-compatible", "z-compatible"], [result["id"] for result in results])

    def test_one_project_observation_cannot_become_global(self):
        """Catches a single project observation being promoted beyond candidate maturity."""
        promoted = promote_lesson(self.lesson, {"scenes": 2, "projects": 1})

        self.assertEqual("candidate", promoted["status"])

    def test_global_lesson_requires_cross_project_evidence_and_user_approval(self):
        """Catches automatic global rules without explicit approval after cross-project validation."""
        verified = promote_lesson(self.lesson, {"scenes": 4, "projects": 2})
        global_lesson = promote_lesson(
            {**verified, "status": "verified"},
            {"scenes": 4, "projects": 2, "user_approved": True},
        )

        self.assertEqual("verified", verified["status"])
        self.assertEqual("global", global_lesson["status"])

    def test_video_shotcraft_index_keeps_metadata_and_external_source_reference_only(self):
        """Catches indexing that embeds external recipe bodies instead of a source reference."""
        with TemporaryDirectory() as folder:
            source = Path(folder)
            gallery = source / "gallery" / "api"
            gallery.mkdir(parents=True)
            (gallery / "library.json").write_text(
                json.dumps(
                    {
                        "revision": "fixture-revision",
                        "cards": [
                            {
                                "name": "diagram-build",
                                "use": "build a concept diagram",
                                "category": "interaction",
                                "tags": ["diagram"],
                                "duration": "约 4–5s",
                                "source": "references/shots/interaction/diagram-build.md",
                                "styles": [
                                    {
                                        "key": "diagram-build-v1",
                                        "media": {"url": "./media/diagram-build.mp4"},
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            index = index_video_shotcraft(source)

        recipe = index["recipes"][0]
        self.assertEqual("video-shotcraft:references/shots/interaction/diagram-build.md", recipe["implementation_ref"])
        self.assertEqual({"min": 4, "max": 5}, recipe["duration"])
        self.assertNotIn("implementation_source", recipe)

    @staticmethod
    def recipe(recipe_id, canvas, duration=None):
        return {
            "id": recipe_id,
            "version": "v1",
            "job": "explain",
            "preview": "preview.mp4",
            "renderer": "remotion",
            "implementation_ref": "external/reference",
            "license": "Apache-2.0",
            "mechanism": "explainer-overlay",
            "participants": ["host", "diagram"],
            "duration": duration or {"min": 4, "max": 8},
            "canvas": [canvas],
            "carriers": ["diagram"],
        }


if __name__ == "__main__":
    unittest.main()

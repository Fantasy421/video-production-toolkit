import json
from pathlib import Path
import unittest

from scripts.toolkit.adapters import select_adapter


ROOT = Path(__file__).parents[1]


class AdapterSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifests = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((ROOT / "registries" / "adapters").glob("*.json"))
        ]

    def test_h5_preview_prefers_hyperframes(self):
        selected = select_adapter("motion.preview", {"format": "html"}, self.manifests)
        self.assertEqual("hyperframes", selected["id"])
        self.assertEqual("remotion", selected["fallback"]["id"])

    def test_editable_overlay_prefers_chatcut_motion_graphics(self):
        selected = select_adapter(
            "motion.produce", {"editable": True, "overlay": True}, self.manifests
        )
        self.assertEqual("chatcut", selected["id"])

    def test_selection_honors_contract_output_and_explicit_preference(self):
        selected = select_adapter(
            "motion.produce",
            {
                "contract": "scene-contract-v1",
                "output": "rendered-video",
                "adapter_preferences": ["remotion", "chatcut"],
            },
            self.manifests,
        )
        self.assertEqual("remotion", selected["id"])
        self.assertEqual("chatcut", selected["fallback"]["id"])

    def test_rejects_missing_or_undeclared_installed_skill(self):
        selected = select_adapter(
            "motion.preview",
            {"installed_skills": ["remotion-best-practices"]},
            self.manifests,
        )
        self.assertEqual("remotion", selected["id"])
        with self.assertRaises(ValueError):
            select_adapter(
                "motion.preview", {"adapter_preferences": ["untrusted"]}, self.manifests
            )

    def test_manifest_cannot_supply_routing_or_gate_override(self):
        unsafe = {
            **self.manifests[0],
            "routing_override": "video-director",
        }
        with self.assertRaises(ValueError):
            select_adapter("motion.preview", {}, [unsafe])


if __name__ == "__main__":
    unittest.main()

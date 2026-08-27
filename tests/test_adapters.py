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
        selected = select_adapter("motion.preview", self.requirements(format="html"), self.manifests)
        self.assertEqual("hyperframes", selected["id"])
        self.assertEqual("remotion", selected["fallback"]["id"])

    def test_visual_direction_preview_is_a_declared_adapter_capability(self):
        """Catches visual.preview routing to no provider despite the H5 workflow."""
        selected = select_adapter(
            "visual.preview", self.requirements(format="html"), self.manifests
        )

        self.assertEqual("hyperframes", selected["id"])
        self.assertEqual("remotion", selected["fallback"]["id"])

    def test_chatcut_declares_editable_timeline_assembly(self):
        """Catches the default final timeline backend lacking its coordinator capability."""
        selected = select_adapter(
            "timeline.assemble",
            self.requirements(
                contract="timeline-contract-v1",
                output="chatcut-project",
                editable=True,
            ),
            self.manifests,
        )

        self.assertEqual("chatcut", selected["id"])
        self.assertIsNone(selected["fallback"])
        self.assertEqual("external:chatcut-plugin-basics", selected["implementation_ref"])

    def test_chatcut_adds_voice_capabilities_without_losing_editable_capabilities(self):
        """Catches a voice manifest replacement that drops established ChatCut routes."""
        selected = select_adapter(
            "voice.synthesize",
            {
                "contract": "voice-profile",
                "output": "voiceover",
                "adapter_preferences": ["chatcut"],
                "installed_skills": ["chatcut:voice"],
            },
            self.manifests,
        )

        self.assertEqual("chatcut", selected["id"])
        self.assertEqual("chatcut:voice", selected["installed_skill"])
        self.assertEqual("external:chatcut-voice", selected["implementation_ref"])
        self.assertIn("voice.time", selected["capabilities"])
        self.assertIn("timeline.assemble", selected["capabilities"])
        self.assertIn("motion.produce", selected["capabilities"])
        self.assertIn("voice-timing", selected["outputs"])

    def test_editable_overlay_prefers_chatcut_motion_graphics(self):
        selected = select_adapter(
            "motion.produce", self.requirements(editable=True, overlay=True), self.manifests
        )
        self.assertEqual("chatcut", selected["id"])

    def test_selection_honors_contract_output_and_explicit_preference(self):
        selected = select_adapter(
            "motion.produce",
            {
                "contract": "scene-contract-v1",
                "output": "rendered-video",
                "adapter_preferences": ["remotion", "chatcut"],
                "installed_skills": ["remotion-best-practices", "chatcut:chatcut-plugin-basics"],
            },
            self.manifests,
        )
        self.assertEqual("remotion", selected["id"])
        self.assertIsNone(selected["fallback"])

    def test_rejects_missing_or_undeclared_installed_skill(self):
        with self.assertRaises(ValueError):
            select_adapter("motion.preview", {"adapter_preferences": ["remotion"]}, self.manifests)
        selected = select_adapter(
            "motion.preview",
            {"adapter_preferences": ["remotion"], "installed_skills": ["remotion-best-practices"]},
            self.manifests,
        )
        self.assertEqual("remotion", selected["id"])
        with self.assertRaises(ValueError):
            select_adapter(
                "motion.preview", {"adapter_preferences": ["untrusted"], "installed_skills": []}, self.manifests
            )

    def test_manifest_cannot_supply_routing_or_gate_override(self):
        unsafe = {
            **self.manifests[0],
            "routing_override": "video-director",
        }
        with self.assertRaises(ValueError):
            select_adapter("motion.preview", self.requirements(), [unsafe])

    def test_fallback_never_substitutes_an_adapter_absent_from_task_preferences(self):
        selected = select_adapter(
            "motion.produce",
            {
                "adapter_preferences": ["remotion"],
                "installed_skills": ["remotion-best-practices"],
            },
            self.manifests,
        )
        self.assertEqual("remotion", selected["id"])
        self.assertIsNone(selected["fallback"])

    def test_fallback_must_satisfy_the_same_immutable_contract_and_output(self):
        selected = select_adapter(
            "motion.preview",
            self.requirements(format="html"),
            self.manifests,
        )
        self.assertEqual("hyperframes", selected["id"])
        self.assertEqual("remotion", selected["fallback"]["id"])

    def test_explicit_primary_preference_retains_only_its_declared_authorized_fallback(self):
        selected = select_adapter(
            "motion.preview",
            self.requirements(
                adapter_preferences=["hyperframes", "remotion"],
                installed_skills=["hyperframes-motion-director", "remotion-best-practices"],
                preferred_adapter="hyperframes",
            ),
            self.manifests,
        )
        self.assertEqual("hyperframes", selected["id"])
        self.assertEqual("remotion", selected["fallback"]["id"])

    def test_rejects_unsafe_external_implementation_references(self):
        for reference in ("external:unsafe\nname", "external:../escape", "external:folder/name", "external:bad\x7f"):
            with self.subTest(reference=reference):
                manifest = {**self.manifests[0], "implementation_ref": reference}
                with self.assertRaises(ValueError):
                    select_adapter("motion.preview", self.requirements(), [manifest])

    @staticmethod
    def requirements(**updates):
        return {
            "adapter_preferences": ["hyperframes", "remotion", "video-shotcraft", "chatcut"],
            "installed_skills": [
                "hyperframes-motion-director",
                "remotion-best-practices",
                "video-shotcraft:video-shotcraft",
                "chatcut:chatcut-plugin-basics",
            ],
            **updates,
        }


if __name__ == "__main__":
    unittest.main()

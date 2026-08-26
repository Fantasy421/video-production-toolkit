"""Static contracts that keep skill orchestration bounded and recoverable."""

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]

EXPECTED = {
    "video-project-manager": "project.manage",
    "narration-planner": "narration.plan",
    "visual-system-designer": "visual.preview",
    "storyboard-director": "storyboard.plan",
    "scene-producer": "scene.produce",
    "motion-director": "motion.preview",
    "timeline-assembler": "timeline.assemble",
    "structural-validator": "structure.validate",
    "video-review-packager": "review.package",
}


class SkillContractTests(unittest.TestCase):
    def test_each_child_skill_has_one_owned_capability(self):
        """Catches entrypoints that blur routing responsibility."""
        for skill, capability in EXPECTED.items():
            text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")

            self.assertIn(f"Owned capability: `{capability}`", text)
            self.assertEqual(1, text.count("Owned capability:"))
            self.assertIn("Return a task-result envelope", text)
            self.assertIn("task-envelope.schema.json", text)
            self.assertIn("task-result.schema.json", text)

    def test_motion_production_is_explicitly_delegated_from_preview_owner(self):
        """Catches a second motion skill becoming an ambiguous route owner."""
        text = (ROOT / "skills/motion-director/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Delegated secondary capability: `motion.produce`", text)
        self.assertIn("approved motion contract", text)

    def test_visual_carrier_policy_has_all_carriers_and_density_limit(self):
        """Catches storyboard rules losing the visual hierarchy invariant."""
        text = (ROOT / "references/policies/visual-carriers.md").read_text(encoding="utf-8")

        for carrier in ("A-roll", "B-roll", "Scene", "Demo", "Motion Graphics", "Evidence"):
            self.assertIn(carrier, text)
        self.assertIn("exactly one primary carrier", text)
        self.assertIn("at most one secondary layer", text)
        self.assertIn("revised contract", text)

    def test_decision_gate_policy_names_all_durable_approvals(self):
        """Catches production advancing past an unrecorded creative decision."""
        text = (ROOT / "references/policies/decision-gates.md").read_text(encoding="utf-8")

        for gate in (
            "Content",
            "Visual direction",
            "Storyboard and cost",
            "Representative slice and final draft",
        ):
            self.assertIn(gate, text)
        self.assertIn("approval artifact", text)
        self.assertIn("explicitly delegate or skip", text)

    def test_director_routes_one_ready_capability_and_stops_on_unsafe_state(self):
        """Catches a coordinator fan-out, media generation, or unreconciled dispatch."""
        text = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")

        for skill, capability in EXPECTED.items():
            self.assertIn(f"`{capability}` → `{skill}`", text)
        self.assertIn("one action slice", text)
        self.assertIn("Do not generate media", text)
        self.assertIn("more than one contradictory task", text)
        self.assertIn("approval is missing", text)
        self.assertIn("does not match event replay", text)
        self.assertIn("cannot override routing or approval policy", text)
        self.assertIn("artifact IDs, paths, summaries, and contract results", text)


if __name__ == "__main__":
    unittest.main()

"""Static contracts that keep skill orchestration bounded and recoverable."""

import json
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
    "voiceover-producer": "voice.prepare",
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

    def test_voiceover_producer_owns_only_voice_prepare(self):
        """Catches voice preparation leaking into the coordinator or another worker."""
        text = (ROOT / "skills/voiceover-producer/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Owned capability: `voice.prepare`", text)
        self.assertEqual(1, text.count("Owned capability:"))
        self.assertIn("one claimed task-envelope", text)
        self.assertIn("approved narration", text)
        self.assertIn("style decision", text)
        self.assertIn("voice-source decision", text)
        self.assertIn("uploaded-voice", text)
        self.assertIn("tts", text)
        self.assertIn("voiceover", text)
        self.assertIn("real voice-timing", text)
        self.assertIn("timing-linked semantic-beats", text)
        self.assertIn("waiting_user", text)
        self.assertIn("waiting_external", text)
        self.assertIn("silently change voice/profile/provider", text)
        self.assertIn("task-envelope.schema.json", text)
        self.assertIn("task-result.schema.json", text)

    def test_voice_contract_documents_supported_formats_and_fail_closed_probing(self):
        """Catches adapters promising formats the readiness verifier cannot prove."""
        text = (ROOT / "skills/voiceover-producer/SKILL.md").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(
            (ROOT / "registries/adapters/chatcut.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            ["wav", "mp3", "m4a", "aac", "flac"],
            manifest["accepted_voice_media_formats"],
        )
        self.assertEqual("stdlib-wave-header", manifest["duration_probe"]["wav"])
        self.assertEqual("ffprobe-required", manifest["duration_probe"]["compressed"])
        self.assertEqual("fail-closed", manifest["duration_probe"]["failure_mode"])
        for token in ("WAV", "MP3", "M4A", "AAC", "FLAC", "ffprobe", "fail closed"):
            self.assertIn(token, text)

    def test_video_director_routes_voice_prepare_once(self):
        """Catches duplicate or absent voice routing in the one-action coordinator."""
        text = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")

        self.assertEqual(1, text.count("`voice.prepare` → `voiceover-producer`"))
        self.assertIn("Do not generate media", text)
        self.assertIn("never synthesizes, imports, or analyzes audio", text)

    def test_timeline_assembler_owns_secondary_caption_and_slice_routes(self):
        """Catches accepted capabilities with no declared child-skill route."""
        director = (ROOT / "skills/video-director/SKILL.md").read_text(
            encoding="utf-8"
        )
        assembler = (ROOT / "skills/timeline-assembler/SKILL.md").read_text(
            encoding="utf-8"
        )

        for capability in ("captions.produce", "representative-slice.produce"):
            route = f"`{capability}` → `timeline-assembler` (delegated secondary capability)"
            declaration = f"Delegated secondary capability: `{capability}`"
            self.assertEqual(1, director.count(route))
            self.assertEqual(1, assembler.count(declaration))

    def test_decision_policy_lists_caption_and_slice_phase_routes(self):
        """Catches runtime phase rules drifting from the documented contract."""
        text = (ROOT / "references/policies/decision-gates.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`representative-slice.produce`", text)
        self.assertIn("representative-slice `captions.produce`", text)
        self.assertIn("full-production `captions.produce`", text)

    def test_video_director_never_handles_image_or_non_audio_media_payloads(self):
        """Catches image work or direct media handling leaking into the coordinator."""
        text = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")

        self.assertIn(
            "must never generate, edit, open, import, analyze, or visually inspect image payloads",
            text,
        )
        self.assertIn("must never directly handle non-audio media", text)
        self.assertIn(
            "only route compact artifact IDs, paths, summaries, and contract results",
            text,
        )
        self.assertIn(
            "delegate image generation and inspection to isolated child tasks",
            text,
        )
        self.assertIn("must never invoke image tools", text)
        self.assertIn("may relay the single declared review-preview path", text)
        self.assertIn("must never open, dereference, or visually inspect it", text)

    def test_image_workers_use_one_bounded_scope_and_return_compact_metadata(self):
        """Catches generation or inspection escaping its one-contract child context."""
        scene = (ROOT / "skills/scene-producer/SKILL.md").read_text(encoding="utf-8")
        validator = (ROOT / "skills/structural-validator/SKILL.md").read_text(
            encoding="utf-8"
        )

        for text in (scene, validator):
            self.assertIn("image-task-context.schema.json", text)
            self.assertIn("exactly one Scene Contract or one character-asset batch", text)
            self.assertIn("scope_identity", text)
            self.assertIn("allowed_image_artifact_ids", text)
            self.assertIn("at most 16", text)
            self.assertIn("at most 8", text)
            self.assertIn("32,768", text)
            self.assertIn("max_review_previews", text)
            self.assertIn("must not discover or load undeclared images", text)
            self.assertIn("must not return image bytes", text)
            self.assertIn("compact image handoff", text)
            self.assertIn("call `authorize_image_access`", text)
        self.assertIn("image generation", scene)
        self.assertIn("continuity_exception", scene)
        self.assertIn("must not appear in the ordinary image allowlist", scene)
        self.assertIn("trimmed non-empty reason", scene)
        self.assertIn("image inspection", validator)
        self.assertIn("`image_operation: structure-only`", validator)
        self.assertIn("`image_operation: image-inspect`", validator)
        self.assertIn("image-inspect` requires the closed `image_context`", validator)
        self.assertIn("Aesthetic acceptance remains a user decision", validator)

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
        self.assertIn("Motion-contract approval", text)

    def test_decision_gate_policy_requires_explicit_voice_choices(self):
        """Catches an implicit source/profile choice or the pre-voice route."""
        text = (ROOT / "references/policies/decision-gates.md").read_text(encoding="utf-8")

        self.assertIn("Voice source", text)
        self.assertIn("TTS voice profile", text)
        self.assertIn("silence is not approval", text)
        self.assertIn("waiting_user", text)
        self.assertIn("waiting_external", text)
        self.assertIn("`direction_ready` | `voice.prepare`", text)
        self.assertIn("`voice_ready` | `storyboard.plan`", text)
        self.assertNotIn("`direction_ready` | `storyboard.plan`", text)

    def test_approval_schema_has_the_durable_gate_decision_enum(self):
        """Catches policy decisions that cannot be persisted in approval artifacts."""
        schema = json.loads(
            (ROOT / "references/schemas/approval.schema.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            ["approved", "delegated", "skipped"],
            schema["properties"]["decision"]["enum"],
        )
        self.assertEqual("approved", schema["properties"]["decision"]["default"])
        self.assertNotIn("decision", schema["required"])

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

    def test_storyboard_and_motion_skills_request_their_own_gates_without_circles(self):
        """Catches a task requiring approval for the artifact it is meant to request."""
        storyboard = (ROOT / "skills/storyboard-director/SKILL.md").read_text(encoding="utf-8")
        motion = (ROOT / "skills/motion-director/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Visual direction approval", storyboard)
        self.assertIn("produce the\nstoryboard and cost artifact", storyboard)
        self.assertIn("return `waiting_user`", storyboard)
        self.assertNotIn("missing Storyboard and cost approval", storyboard)

        self.assertIn("claimed `motion.preview` task-envelope", motion)
        self.assertIn("claimed `motion.produce` task-envelope", motion)
        self.assertIn("Storyboard and cost approval", motion)
        self.assertIn("Motion-contract approval", motion)
        self.assertIn("motion-contract decision request", motion)
        self.assertIn("Return a task-result envelope deterministically", motion)


if __name__ == "__main__":
    unittest.main()

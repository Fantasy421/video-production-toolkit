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

    def test_video_director_never_handles_visual_media_payloads(self):
        """Catches visual-media work or direct payload handling leaking into routing."""
        text = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        self.assertIn("must never directly handle image or video payloads", normalized)
        self.assertIn(
            "only route compact artifact IDs, paths, summaries, and contract results",
            normalized,
        )
        self.assertIn(
            "delegate visual-media execution to one isolated child agent",
            normalized,
        )
        self.assertIn("must never invoke visual-media tools", normalized)
        self.assertIn("may relay the single declared review-preview path", normalized)
        self.assertIn("must never dereference it", normalized)

    def test_video_director_makes_visual_media_isolation_its_highest_priority_rule(self):
        """Catches routing or adapter use preceding coordinator visual-media isolation."""
        text = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        isolation = text.index("## Highest-priority visual-media isolation")
        routing = text.index("## Routing")
        self.assertLess(isolation, routing)
        for prohibition in (
            "must never generate, edit, open, play, decode, render, screenshot",
            "frame-extract, display, or perceptually inspect image or video",
            "must never dereference a preview path",
            "exactly one isolated child agent",
            "compact metadata relay",
        ):
            with self.subTest(prohibition=prohibition):
                self.assertIn(prohibition, normalized)

    def test_all_visual_workers_require_isolated_child_execution(self):
        """Catches a visual worker escaping its one immutable media scope."""
        workers = (
            "visual-system-designer",
            "storyboard-director",
            "scene-producer",
            "motion-director",
            "structural-validator",
            "timeline-assembler",
            "video-review-packager",
        )
        for worker in workers:
            text = (ROOT / "skills" / worker / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(worker=worker):
                self.assertIn("isolated child agent only", text)
                self.assertIn("one exact `scope_identity`", text)
                self.assertIn("must not crawl the project", text)
                self.assertRegex(
                    text, r"must not crawl the project or discover neighboring\s+scenes"
                )
                self.assertIn("visual_media_handoff", text)
                self.assertIn("visual-media-task-context.schema.json", text)

    def test_visual_adapters_are_limited_to_the_isolated_child_boundary(self):
        """Catches primary-context routing gaining a visual adapter execution path."""
        policy = (ROOT / "references/policies/visual-media-isolation.md").read_text(
            encoding="utf-8"
        )
        boundary = policy.index("## Child-only visual adapters")
        self.assertIn("Only the isolated child agent may route to or invoke", policy[boundary:])
        for adapter in ("HyperFrames", "VideoShotCraft", "Remotion", "ChatCut"):
            with self.subTest(adapter=adapter):
                self.assertIn(adapter, policy[boundary:])

    def test_policy_preserves_audio_exclusion_user_authority_and_recursive_scrub(self):
        """Catches isolation leaking into audio or trusting an automated visual judgment."""
        text = (ROOT / "references/policies/visual-media-isolation.md").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(text.split())

        for contract in (
            "Audio-only preparation is outside this policy",
            "Recursively scrub",
            "every result field",
            "subjective acceptance remains the user's decision",
            "structure-only",
            "same output scrub",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized)

    def test_canonical_visual_workers_relegate_legacy_image_fields_to_persisted_compatibility(self):
        """Catches new scene or validation tasks authoring deprecated image-only fields."""
        scene = (ROOT / "skills/scene-producer/SKILL.md").read_text(encoding="utf-8")
        validator = (ROOT / "skills/structural-validator/SKILL.md").read_text(
            encoding="utf-8"
        )

        for text in (scene, validator):
            normalized = " ".join(text.split())
            self.assertIn("visual_media_operation", normalized)
            self.assertIn("visual_media_context", normalized)
            self.assertIn("allowed_artifact_ids", normalized)
            self.assertIn("visual_media_handoff", normalized)
            self.assertIn("must not return image or video payloads", normalized)
            self.assertIn(
                "persisted legacy runtime compatibility; workers MUST NOT author/use for new tasks",
                normalized,
            )
            for legacy_field in (
                "image_operation",
                "image_context",
                "allowed_image_artifact_ids",
                "allowed_character_pack_ids",
            ):
                with self.subTest(legacy_field=legacy_field):
                    self.assertEqual(1, text.count(legacy_field))

    def test_motion_and_review_delegate_visual_execution_to_isolated_children(self):
        """Catches a worker directly invoking a visual adapter or building a review preview."""
        motion = (ROOT / "skills/motion-director/SKILL.md").read_text(encoding="utf-8")
        review = (ROOT / "skills/video-review-packager/SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "isolated child agent must route to and invoke the selected adapter",
            " ".join(motion.split()),
        )
        self.assertIn("through an isolated child agent", " ".join(review.split()))

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

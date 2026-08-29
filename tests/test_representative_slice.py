import unittest

from scripts.plan_representative_slice import select_representative_slice
from scripts.toolkit.contracts import validate_scene_contract


class RepresentativeSliceTests(unittest.TestCase):
    @staticmethod
    def voice_artifacts(
        *,
        narration_id="narration-v1",
        voiceover_id="voiceover-v1",
        timing_id="voice-timing-v1",
        duration_ms=60_000,
        segments=None,
        timing_kind="real",
    ):
        return [
            {
                "artifact_id": narration_id,
                "type": "narration",
                "version": 1,
                "status": "approved",
                "parents": [],
                "path": f"metadata/{narration_id}.json",
            },
            {
                "artifact_id": "voice-source-v1",
                "type": "voice-source-decision",
                "version": 1,
                "status": "approved",
                "parents": [narration_id],
                "path": "metadata/voice-source-v1.json",
                "narration_id": narration_id,
                "mode": "tts",
                "decision": "approved",
                "decision_provenance": "user:source-v1",
            },
            {
                "artifact_id": "voice-profile-v1",
                "type": "voice-profile",
                "version": 1,
                "status": "approved",
                "parents": [narration_id, "voice-source-v1"],
                "path": "metadata/voice-profile-v1.json",
                "narration_id": narration_id,
                "source_decision_id": "voice-source-v1",
                "mode": "tts",
                "language": "zh-CN",
                "provider": "chatcut",
                "voice_id": "narrator-1",
                "speaking_rate": 1.0,
                "emotion": "calm",
                "pronunciations": [],
                "approved": True,
                "consent_provenance": "user:consent-v1",
                "profile_provenance": "user:profile-v1",
            },
            {
                "artifact_id": voiceover_id,
                "type": "voiceover",
                "version": 1,
                "status": "approved",
                "parents": [narration_id, "voice-source-v1", "voice-profile-v1"],
                "path": f"media/{voiceover_id}.wav",
                "narration_id": narration_id,
                "source_decision_id": "voice-source-v1",
                "mode": "tts",
                "profile_id": "voice-profile-v1",
                "media_path": f"media/{voiceover_id}.wav",
                "media_format": "wav",
                "duration_ms": duration_ms,
                "provenance": "test-fixture",
            },
            {
                "artifact_id": timing_id,
                "type": "voice-timing",
                "version": 1,
                "status": "approved",
                "parents": [voiceover_id],
                "path": f"metadata/{timing_id}.json",
                "voiceover_id": voiceover_id,
                "timing_kind": timing_kind,
                "duration_ms": duration_ms,
                "segments": segments
                if segments is not None
                else [
                    {
                        "start_ms": 0,
                        "end_ms": duration_ms,
                        "text": "fixture narration",
                    }
                ],
                "keyword_anchors": [],
            },
        ]

    def setUp(self):
        self.contracts = [
            {
                "scene_id": "S01",
                "start_ms": 0,
                "end_ms": 6000,
                "primary_carrier": "scene",
                "scene_image_generation": True,
                "new_character_baseline": True,
                "purpose": "show character action",
            },
            {
                "scene_id": "S02",
                "start_ms": 6000,
                "end_ms": 12000,
                "primary_carrier": "motion-graphics",
                "purpose": "explain relationship",
            },
            {
                "scene_id": "S03",
                "start_ms": 12000,
                "end_ms": 18000,
                "primary_carrier": "evidence",
                "generated_video": True,
                "captions": True,
                "purpose": "show supporting evidence",
            },
        ]
        self.by_id = {item["scene_id"]: item for item in self.contracts}
        self.artifacts = self.voice_artifacts()
        self.voice_timing = self.artifacts[-1]

    def select(self, contracts):
        if any(
            not isinstance(contract, dict)
            or not {"scene_id", "start_ms", "end_ms", "primary_carrier", "purpose"}.issubset(contract)
            for contract in contracts
        ):
            raise ValueError("scene contract does not match scene-contract-v1")
        current_contracts, artifacts = self.currentize(contracts, self.artifacts)
        return select_representative_slice(current_contracts, artifacts)

    @staticmethod
    def currentize(contracts, artifacts):
        """Attach exact scene-timing lineage to representative-slice fixtures."""
        timing_id = artifacts[-1]["artifact_id"]
        timed_id = "timed-semantic-beats-v1"
        scene_timing_id = "scene-timing-contracts-v1"
        beat_ids = [f"B{index:02d}" for index in range(1, len(contracts) + 1)]
        timed = {
            "artifact_id": timed_id,
            "type": "timed-semantic-beats",
            "version": 1,
            "status": "approved",
            "parents": ["semantic-beats-v1", timing_id],
            "path": "metadata/timed-semantic-beats-v1.json",
            "semantic_beats_id": "semantic-beats-v1",
            "voice_timing_id": timing_id,
            "timing_kind": "real",
            "beats": [
                {
                    "beat_id": beat_id,
                    "speech_start_ms": contract["start_ms"],
                    "speech_end_ms": contract["end_ms"],
                    "keyword_start_ms": contract["start_ms"] + 1,
                    "keyword_end_ms": contract["end_ms"] - 1,
                    "emphasis_ms": (contract["start_ms"] + contract["end_ms"]) // 2,
                    "visual_window_ms": [contract["start_ms"], contract["end_ms"]],
                    "approved_anchor_commitment": "sha256:" + "0" * 64,
                }
                for beat_id, contract in zip(beat_ids, contracts)
            ],
        }
        current_contracts = [
            {
                **contract,
                "voice_timing_id": timing_id,
                "timed_semantic_beats_id": timed_id,
                "scene_timing_contracts_id": scene_timing_id,
                "beat_ids": [beat_id],
            }
            for beat_id, contract in zip(beat_ids, contracts)
        ]
        scene_timing = {
            "artifact_id": scene_timing_id,
            "type": "scene-timing-contracts",
            "version": 1,
            "status": "approved",
            "parents": [timed_id],
            "path": "metadata/scene-timing-contracts-v1.json",
            "timed_semantic_beats_id": timed_id,
            "scenes": [
                {
                    "scene_id": contract["scene_id"],
                    "scene_window_ms": [contract["start_ms"], contract["end_ms"]],
                    "beat_ids": [beat_id],
                    "primary_carrier": contract["primary_carrier"],
                    "support_layer": None,
                    "visual_window_ms": [contract["start_ms"], contract["end_ms"]],
                }
                for beat_id, contract in zip(beat_ids, contracts)
            ],
        }
        return current_contracts, [*artifacts, timed, scene_timing]

    def test_scene_contract_uses_exact_real_timing_and_spoken_boundaries(self):
        """Catches estimates, a wrong timing ID, and silence-bound intervals."""
        artifacts = self.voice_artifacts(
            narration_id="narration-v2",
            voiceover_id="voiceover-v2",
            timing_id="voice-timing-v2",
            duration_ms=12_000,
            segments=[
                {"start_ms": 0, "end_ms": 5000, "text": "first"},
                {"start_ms": 6000, "end_ms": 12000, "text": "second"},
            ],
        )
        timing = artifacts[-1]
        contract = {
            "scene_id": "S01",
            "voice_timing_id": "voice-timing-v2",
            "start_ms": 0,
            "end_ms": 5000,
            "primary_carrier": "scene",
            "purpose": "show the first semantic segment",
        }

        with self.assertRaisesRegex(ValueError, "timed semantic beats"):
            validate_scene_contract(contract, timing)
        with self.assertRaisesRegex(ValueError, "artifacts"):
            select_representative_slice([contract], timing)
        self.assertEqual(
            contract,
            validate_scene_contract(
                contract,
                timing,
                allow_legacy_unresolved_timing=True,
            ),
        )
        with self.assertRaisesRegex(ValueError, "timed semantic beats"):
            validate_scene_contract(contract, artifacts=artifacts)
        current_contracts, current_artifacts = self.currentize([contract], artifacts)
        with self.assertRaisesRegex(ValueError, "full artifact"):
            validate_scene_contract(current_contracts[0], timing)
        self.assertEqual(
            current_contracts[0],
            validate_scene_contract(current_contracts[0], artifacts=current_artifacts),
        )
        with self.assertRaisesRegex(ValueError, "authoritative voice timing"):
            validate_scene_contract(
                {**current_contracts[0], "voice_timing_id": "voice-timing-v1"},
                artifacts=current_artifacts,
            )
        estimated = self.voice_artifacts(
            narration_id="narration-v2",
            voiceover_id="voiceover-v2",
            timing_id="voice-timing-v2",
            duration_ms=12_000,
            segments=timing["segments"],
            timing_kind="estimated",
        )
        estimated_contracts, estimated_artifacts = self.currentize([contract], estimated)
        with self.assertRaisesRegex(ValueError, "authoritative voice timing"):
            validate_scene_contract(estimated_contracts[0], artifacts=estimated_artifacts)
        silent_contracts, silent_artifacts = self.currentize(
            [{**contract, "start_ms": 5000, "end_ms": 7000}], artifacts
        )
        with self.assertRaisesRegex(ValueError, "spoken timing segment"):
            validate_scene_contract(
                silent_contracts[0], artifacts=silent_artifacts
            )

        current_contracts, current_artifacts = self.currentize(
            [contract, {**contract, "scene_id": "S02", "start_ms": 6000, "end_ms": 12000}],
            artifacts,
        )
        selected = select_representative_slice(current_contracts, current_artifacts)
        self.assertEqual("voice-timing-v2", selected.voice_timing_id)

    def test_slice_covers_highest_risk_carriers(self):
        selected = self.select(self.contracts)
        carriers = {self.by_id[item]["primary_carrier"] for item in selected}
        self.assertIn("scene", carriers)
        self.assertIn("motion-graphics", carriers)
        self.assertFalse(selected.composite)
        self.assertGreaterEqual(selected.duration_ms, 10000)
        self.assertLessEqual(selected.duration_ms, 20000)

    def test_prefers_shorter_equal_coverage_adjacent_range(self):
        contracts = [
            self.contracts[0],
            self.contracts[1],
            {
                "scene_id": "S03",
                "start_ms": 12000,
                "end_ms": 18000,
                "primary_carrier": "motion-graphics",
                "purpose": "hold supporting texture",
            },
            {
                "scene_id": "S04",
                "start_ms": 18000,
                "end_ms": 28000,
                "primary_carrier": "motion-graphics",
                "purpose": "explain another relationship",
            },
        ]
        selected = self.select(contracts)
        self.assertEqual(["S01", "S02"], selected)

    def test_marks_composite_when_scene_and_motion_cannot_share_a_valid_range(self):
        contracts = [
            {
                "scene_id": "S01",
                "start_ms": 0,
                "end_ms": 10000,
                "primary_carrier": "scene",
                "scene_image_generation": True,
                "purpose": "show a scene",
            },
            {
                "scene_id": "S02",
                "start_ms": 30000,
                "end_ms": 40000,
                "primary_carrier": "motion-graphics",
                "purpose": "show a diagram",
            },
        ]
        selected = self.select(contracts)
        self.assertEqual(["S01", "S02"], selected)
        self.assertTrue(selected.composite)
        self.assertEqual(((0, 10000), (30000, 40000)), selected.ranges)

    def test_rejects_contracts_that_do_not_match_the_canonical_scene_schema(self):
        with self.assertRaises(ValueError):
            self.select([
                {"scene_id": "../escape", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "unsafe"}
            ])
        for contract in (
            {"scene_id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene"},
            {"id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "alias id"},
            {"scene_id": "S01..v1", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "dot segment"},
            {"scene_id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "alias", "caption_required": True},
        ):
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                self.select([contract])
        with self.assertRaises(ValueError):
            self.select([
                {"scene_id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "one"},
                {"scene_id": "S02", "start_ms": 9000, "end_ms": 15000, "primary_carrier": "b-roll", "purpose": "two"},
            ])

    def test_composite_optimizes_two_ranges_not_two_single_risk_objects(self):
        contracts = [
            {"scene_id": "S01", "start_ms": 0, "end_ms": 5000, "primary_carrier": "scene", "new_character_baseline": True, "purpose": "character action"},
            {"scene_id": "S02", "start_ms": 5000, "end_ms": 10000, "primary_carrier": "demo", "purpose": "demonstrate the action"},
            {"scene_id": "S03", "start_ms": 30000, "end_ms": 40000, "primary_carrier": "motion-graphics", "purpose": "explain the abstraction"},
        ]
        selected = self.select(contracts)
        self.assertEqual(["S01", "S02", "S03"], selected)
        self.assertEqual(((0, 10000), (30000, 40000)), selected.ranges)
        self.assertTrue(selected.composite)

    def test_high_risk_carrier_coverage_beats_lower_risk_extras(self):
        contracts = [
            {"scene_id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "show causality"},
            {"scene_id": "S02", "start_ms": 10000, "end_ms": 20000, "primary_carrier": "b-roll", "generated_video": True, "captions": True, "purpose": "add texture"},
            {"scene_id": "S03", "start_ms": 30000, "end_ms": 40000, "primary_carrier": "motion-graphics", "purpose": "explain abstraction"},
        ]
        selected = self.select(contracts)
        self.assertEqual(["S01", "S03"], selected)
        self.assertEqual(((0, 10000), (30000, 40000)), selected.ranges)
        self.assertTrue(selected.composite)

    def test_shorter_valid_range_beats_low_risk_extras_with_equal_high_risk_coverage(self):
        contracts = [
            {"scene_id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene", "purpose": "show causality"},
            {"scene_id": "S02", "start_ms": 10000, "end_ms": 20000, "primary_carrier": "b-roll", "generated_video": True, "captions": True, "purpose": "add texture"},
        ]
        selected = self.select(contracts)
        self.assertEqual(["S01"], selected)
        self.assertEqual(((0, 10000),), selected.ranges)
        self.assertFalse(selected.composite)

    def test_distant_short_scene_and_motion_ranges_form_a_ten_second_composite(self):
        contracts = [
            {"scene_id": "S01", "start_ms": 0, "end_ms": 5000, "primary_carrier": "scene", "purpose": "show causality"},
            {"scene_id": "S02", "start_ms": 30000, "end_ms": 35000, "primary_carrier": "motion-graphics", "purpose": "explain abstraction"},
        ]
        selected = self.select(contracts)
        self.assertEqual(["S01", "S02"], selected)
        self.assertEqual(((0, 5000), (30000, 35000)), selected.ranges)
        self.assertEqual(10000, selected.duration_ms)
        self.assertTrue(selected.composite)

    def test_returns_structured_blocker_when_no_valid_duration_can_cover_risk(self):
        selected = self.select([
            {"scene_id": "S01", "start_ms": 0, "end_ms": 5000, "primary_carrier": "scene", "purpose": "show causality"},
        ])
        self.assertEqual([], selected)
        self.assertTrue(selected.blocked)
        self.assertEqual("representative-slice-duration-unavailable", selected.blocker["code"])
        self.assertEqual(["scene"], selected.blocker["required_high_risk_carriers"])


if __name__ == "__main__":
    unittest.main()

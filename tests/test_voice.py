import json
import unittest
from pathlib import Path

from scripts.toolkit.voice import has_current_voice_lineage, validate_voice_bundle


ROOT = Path(__file__).parents[1]


class VoiceBundleTests(unittest.TestCase):
    def bundle(
        self,
        *,
        duration_ms=1_000,
        timing_parents=None,
        segments=None,
        timing_kind="real",
    ):
        return [
            {
                "artifact_id": "source-v2",
                "type": "voice-source-decision",
                "version": 2,
                "status": "approved",
                "narration_id": "narration-v2",
                "mode": "tts",
                "decision": "approved",
            },
            {
                "artifact_id": "profile-v2",
                "type": "voice-profile",
                "version": 2,
                "status": "approved",
                "mode": "tts",
                "language": "zh-CN",
                "provider": "chatcut",
                "voice_id": "narrator-1",
                "speaking_rate": 1.0,
                "emotion": "calm",
                "pronunciations": [],
                "approved": True,
            },
            {
                "artifact_id": "voiceover-v2",
                "type": "voiceover",
                "version": 2,
                "status": "approved",
                "narration_id": "narration-v2",
                "profile_id": "profile-v2",
                "media_path": "media/voiceover-v2.wav",
                "duration_ms": duration_ms,
                "provenance": "chatcut:voice",
                "parents": ["narration-v2", "profile-v2"],
            },
            {
                "artifact_id": "voice-timing-v2",
                "type": "voice-timing",
                "version": 2,
                "status": "approved",
                "voiceover_id": "voiceover-v2",
                "timing_kind": timing_kind,
                "duration_ms": duration_ms,
                "segments": segments
                if segments is not None
                else [{"start_ms": 0, "end_ms": duration_ms, "text": "旁白"}],
                "parents": timing_parents
                if timing_parents is not None
                else ["voiceover-v2"],
            },
        ]

    @staticmethod
    def codes(result):
        return {issue["code"] for issue in result["issues"]}

    def test_voice_bundle_requires_exact_voiceover_parent(self):
        result = validate_voice_bundle(
            self.bundle(timing_parents=["other-audio"]), "narration-v2"
        )

        self.assertFalse(result["ok"])
        self.assertIn("voice-timing-lineage-mismatch", self.codes(result))

    def test_timing_must_be_ordered_and_bounded_by_real_duration(self):
        result = validate_voice_bundle(
            self.bundle(
                duration_ms=1_000,
                segments=[
                    {"start_ms": 0, "end_ms": 700, "text": "A"},
                    {"start_ms": 650, "end_ms": 1_100, "text": "B"},
                ],
            ),
            "narration-v2",
        )

        self.assertEqual(
            {"voice-timing-overlap", "voice-timing-out-of-bounds"},
            self.codes(result),
        )

    def test_estimated_timing_never_satisfies_voice_readiness(self):
        result = validate_voice_bundle(
            self.bundle(timing_kind="estimated"), "narration-v2"
        )

        self.assertIn("real-voice-timing-required", self.codes(result))

    def test_safe_current_lineage_returns_the_exact_current_artifact_ids(self):
        result = validate_voice_bundle(self.bundle(), "narration-v2")

        self.assertEqual(
            {
                "ok": True,
                "voiceover_id": "voiceover-v2",
                "voice_timing_id": "voice-timing-v2",
                "issues": [],
            },
            result,
        )
        self.assertTrue(has_current_voice_lineage(self.bundle(), "narration-v2"))

    def test_project_defects_return_issue_codes_instead_of_raising(self):
        artifacts = self.bundle()
        artifacts[1]["approved"] = False
        artifacts[2]["media_path"] = "../outside.wav"
        artifacts[3]["segments"] = []

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertTrue(
            {
                "voice-profile-unapproved",
                "unsafe-voiceover-media-path",
                "voice-timing-text-coverage",
            }
            <= self.codes(result)
        )

    def test_programmer_invalid_input_shapes_raise_value_error(self):
        with self.assertRaisesRegex(ValueError, "artifacts"):
            validate_voice_bundle({"not": "an iterable of artifacts"}, "narration-v2")
        with self.assertRaisesRegex(ValueError, "narration_id"):
            validate_voice_bundle(self.bundle(), "")


class VoiceSchemaTests(unittest.TestCase):
    REQUIRED = {
        "voice-source-decision": ["artifact_id", "narration_id", "mode", "decision"],
        "voice-profile": [
            "artifact_id",
            "mode",
            "language",
            "provider",
            "voice_id",
            "speaking_rate",
            "emotion",
            "pronunciations",
            "approved",
        ],
        "voiceover": [
            "artifact_id",
            "narration_id",
            "profile_id",
            "media_path",
            "duration_ms",
            "provenance",
            "parents",
        ],
        "voice-timing": [
            "artifact_id",
            "voiceover_id",
            "timing_kind",
            "duration_ms",
            "segments",
            "parents",
        ],
    }

    def test_voice_artifact_schemas_are_closed_and_parseable(self):
        for artifact_type, required in self.REQUIRED.items():
            with self.subTest(artifact_type=artifact_type):
                schema = json.loads(
                    (ROOT / "references/schemas" / f"{artifact_type}.schema.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(required, schema["required"])
                self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()

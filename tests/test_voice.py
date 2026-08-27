import json
import unittest
from pathlib import Path

from scripts.toolkit import voice
from scripts.toolkit.voice import (
    has_current_voice_lineage,
    validate_authoritative_voice_bundle,
    validate_voice_bundle,
)


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
                "parents": [],
                "path": "metadata/source-v2.json",
                "narration_id": "narration-v2",
                "mode": "tts",
                "decision": "approved",
            },
            {
                "artifact_id": "profile-v2",
                "type": "voice-profile",
                "version": 2,
                "status": "approved",
                "parents": [],
                "path": "metadata/profile-v2.json",
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
                "path": "media/voiceover-v2.wav",
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
                "path": "metadata/voice-timing-v2.json",
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

    def test_authoritative_narration_walks_intermediate_artifact_types(self):
        """Catches narration supersession traversal discarding non-narration nodes."""
        artifacts = [
            {
                "artifact_id": "narration-v1",
                "type": "narration",
                "version": 1,
                "status": "approved",
                "parents": [],
                "path": "metadata/narration-v1.json",
            },
            {
                "artifact_id": "revision-bridge",
                "type": "decision-pack",
                "version": 1,
                "status": "approved",
                "parents": ["cycle-node"],
                "path": "metadata/revision-bridge.json",
            },
            {
                "artifact_id": "cycle-node",
                "type": "semantic-beats",
                "version": 1,
                "status": "approved",
                "parents": ["revision-bridge", "narration-v1"],
                "path": "metadata/cycle-node.json",
            },
            {
                "artifact_id": "narration-v2",
                "type": "narration",
                "version": 2,
                "status": "approved",
                "parents": ["revision-bridge"],
                "path": "metadata/narration-v2.json",
            },
            *self.bundle(),
        ]

        result = validate_authoritative_voice_bundle(artifacts)

        self.assertTrue(result["ok"], result)
        self.assertEqual("narration-v2", result["narration_id"])

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

    def test_unhashable_parent_metadata_returns_a_project_issue(self):
        artifacts = self.bundle()
        artifacts[2]["parents"] = [["narration-v2"]]

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_malformed_scalar_metadata_returns_a_project_issue(self):
        artifacts = self.bundle()
        artifacts[0]["status"] = []
        artifacts[1]["mode"] = []

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_missing_artifact_identity_cannot_satisfy_current_lineage(self):
        artifacts = self.bundle()
        artifacts[0].pop("artifact_id")

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(has_current_voice_lineage(artifacts, "narration-v2"))
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_unsafe_linkage_identity_cannot_satisfy_current_lineage(self):
        artifacts = self.bundle()
        artifacts[1]["artifact_id"] = "profile v2"
        artifacts[2]["profile_id"] = "profile v2"
        artifacts[2]["parents"] = ["narration-v2", "profile v2"]

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(has_current_voice_lineage(artifacts, "narration-v2"))
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_duplicate_pronunciations_are_not_a_current_profile(self):
        artifacts = self.bundle()
        artifacts[1]["pronunciations"] = ["OpenAI", "OpenAI"]

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("invalid-voice-profile", self.codes(result))

    def test_unknown_artifact_metadata_cannot_satisfy_a_closed_contract(self):
        artifacts = self.bundle()
        artifacts[1]["unexpected"] = True

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_unknown_timing_segment_metadata_cannot_satisfy_a_closed_contract(self):
        artifacts = self.bundle()
        artifacts[3]["segments"][0]["unexpected"] = True

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("invalid-voice-timing-segment", self.codes(result))

    def test_schema_optional_output_contract_is_checked_at_runtime(self):
        artifacts = self.bundle()
        artifacts[2]["output_contract"] = ""

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_schema_safe_voice_id_is_checked_at_runtime(self):
        artifacts = self.bundle()
        artifacts[1]["voice_id"] = "voice id"

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("invalid-voice-profile", self.codes(result))

    def test_schema_rejected_ids_never_satisfy_current_lineage(self):
        for invalid_id in ("profile@v2", "声音-v2", ".profile-v2", "profile-v2.", "profile..v2"):
            with self.subTest(invalid_id=invalid_id):
                artifacts = self.bundle()
                artifacts[1]["artifact_id"] = invalid_id
                artifacts[2]["profile_id"] = invalid_id
                artifacts[2]["parents"] = ["narration-v2", invalid_id]

                result = validate_voice_bundle(artifacts, "narration-v2")

                self.assertFalse(result["ok"])
                self.assertFalse(has_current_voice_lineage(artifacts, "narration-v2"))
                self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_schema_rejected_dot_path_is_not_a_persisted_artifact_path(self):
        artifacts = self.bundle()
        artifacts[2]["path"] = "./media/voiceover-v2.wav"

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("malformed-voice-artifact", self.codes(result))

    def test_schema_rejected_dot_path_is_not_a_voiceover_media_path(self):
        artifacts = self.bundle()
        artifacts[2]["media_path"] = "./media/voiceover-v2.wav"

        result = validate_voice_bundle(artifacts, "narration-v2")

        self.assertFalse(result["ok"])
        self.assertIn("unsafe-voiceover-media-path", self.codes(result))


class VoiceSchemaTests(unittest.TestCase):
    REQUIRED = {
        "voice-source-decision": [
            "artifact_id",
            "type",
            "version",
            "status",
            "parents",
            "path",
            "narration_id",
            "mode",
            "decision",
        ],
        "voice-profile": [
            "artifact_id",
            "type",
            "version",
            "status",
            "parents",
            "path",
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
            "type",
            "version",
            "status",
            "parents",
            "path",
            "narration_id",
            "profile_id",
            "media_path",
            "duration_ms",
            "provenance",
        ],
        "voice-timing": [
            "artifact_id",
            "type",
            "version",
            "status",
            "parents",
            "path",
            "voiceover_id",
            "timing_kind",
            "duration_ms",
            "segments",
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

    def test_voice_schemas_cover_the_persisted_artifact_envelopes(self):
        """Catches a closed schema that rejects the Artifact Manager records."""
        fixture = VoiceBundleTests().bundle()
        for artifact in fixture:
            schema = json.loads(
                (ROOT / "references/schemas" / f"{artifact['type']}.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(artifact_type=artifact["type"]):
                self.assertTrue(set(schema["required"]).issubset(artifact))
                self.assertTrue(set(artifact).issubset(schema["properties"]))
                self.assertEqual(artifact["type"], schema["properties"]["type"]["const"])

    def test_runtime_patterns_are_the_schema_patterns(self):
        for artifact_type in self.REQUIRED:
            schema = json.loads(
                (ROOT / "references/schemas" / f"{artifact_type}.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(artifact_type=artifact_type):
                self.assertEqual(voice.SAFE_ID_PATTERN, schema["$defs"]["safeId"]["pattern"])
                self.assertEqual(
                    voice.PROJECT_PATH_PATTERN,
                    schema["$defs"]["projectPath"]["pattern"],
                )


if __name__ == "__main__":
    unittest.main()

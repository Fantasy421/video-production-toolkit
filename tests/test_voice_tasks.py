import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.toolkit import tasks
from scripts.toolkit.voice_tasks import prepare_voice_task


ROOT = Path(__file__).parents[1]


class PrepareVoiceTaskTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def envelope(self, *, adapter_preferences=None):
        return {
            "task_id": "voice-prepare-v2",
            "capability": "voice.prepare",
            "inputs": ["narration-v2", "style-v2", "source-v2", "profile-v2"],
            "adapter_preferences": adapter_preferences or ["chatcut"],
            "output_contract": "voiceover-v1",
            "constraints": {
                "worker_id": "voiceover-producer",
                "claim_token": "claim-v2",
                "voice_source_id": "source-v2",
                "voice_profile_id": "profile-v2",
                "output_artifact_ids": ["voiceover-v2", "voice-timing-v2", "beats-v2"],
            },
        }

    def artifacts(self, *, mode="tts", profile_approved=True, include_upload=False):
        records = [
            self.artifact("narration-v2", "narration"),
            self.artifact("style-v2", "style-pack"),
            self.artifact(
                "source-v2",
                "voice-source-decision",
                narration_id="narration-v2",
                mode=mode,
                decision="approved",
            ),
            self.artifact(
                "profile-v2",
                "voice-profile",
                mode=mode,
                language="zh-CN",
                provider="chatcut",
                voice_id="narrator-1",
                speaking_rate=1.0,
                emotion="calm",
                pronunciations=[],
                approved=profile_approved,
            ),
        ]
        if include_upload:
            audio_path = self.root / "media" / "upload-v2.wav"
            audio_path.parent.mkdir()
            audio_path.write_bytes(b"RIFF")
            records.append(
                self.artifact(
                    "upload-v2",
                    "uploaded-audio",
                    media_path="media/upload-v2.wav",
                )
            )
        return records

    @staticmethod
    def artifact(artifact_id, artifact_type, **metadata):
        return {
            "artifact_id": artifact_id,
            "type": artifact_type,
            "version": 2,
            "status": "approved",
            "parents": [],
            "path": f"metadata/{artifact_id}.json",
            **metadata,
        }

    def test_uploaded_mode_waits_for_a_safe_declared_audio_artifact(self):
        """Catches accepting a source decision as though it were an uploaded recording."""
        envelope = self.envelope()
        result = prepare_voice_task(
            self.root,
            envelope,
            self.artifacts(mode="uploaded-voice"),
            ["chatcut:voice"],
        )

        self.assertEqual("waiting_user", result["status"])
        self.assertEqual(["voice-upload-required"], result["warnings"])
        self.assertEqual(envelope["inputs"], result["inputs"])
        tasks._validate_result(result)

    def test_uploaded_mode_submits_only_the_declared_safe_audio_for_timing(self):
        """Catches external timing work starting before its immutable upload input exists."""
        envelope = self.envelope()
        envelope["inputs"].append("upload-v2")
        result = prepare_voice_task(
            self.root,
            envelope,
            self.artifacts(mode="uploaded-voice", include_upload=True),
            ["chatcut:voice"],
        )

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["adapter-selected:chatcut", "voice-timing-job-prepared"], result["checks"])
        self.assertEqual([], result["artifacts"])
        tasks._validate_result(result)

    def test_tts_mode_requires_an_approved_profile(self):
        """Catches synthesis with an unapproved profile despite a declared source decision."""
        result = prepare_voice_task(
            self.root,
            self.envelope(),
            self.artifacts(profile_approved=False),
            ["chatcut:voice"],
        )

        self.assertEqual("waiting_user", result["status"])
        self.assertEqual(["voice-profile-approval-required"], result["warnings"])
        tasks._validate_result(result)

    def test_tts_prepares_only_the_declared_chatcut_voice_adapter(self):
        """Catches a compatible but undeclared provider being selected for an approved profile."""
        result = prepare_voice_task(
            self.root,
            self.envelope(adapter_preferences=["chatcut"]),
            self.artifacts(),
            ["chatcut:voice"],
        )

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["adapter-selected:chatcut", "voice-synthesis-job-prepared"], result["checks"])
        self.assertEqual([], result["artifacts"])
        self.assertNotIn("adapter", result)
        tasks._validate_result(result)

    def test_tts_never_falls_back_when_chatcut_voice_is_unavailable(self):
        """Catches missing ChatCut Voice silently routing approved narration elsewhere."""
        result = prepare_voice_task(
            self.root,
            self.envelope(),
            self.artifacts(),
            [],
        )

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["chatcut-voice-unavailable"], result["warnings"])
        self.assertEqual([], result["artifacts"])
        tasks._validate_result(result)

    def test_succeeds_only_for_a_published_valid_voice_and_timing_bundle(self):
        """Catches a preparatory external job being reported as produced narration."""
        artifacts = self.artifacts()
        artifacts.extend(
            [
                self.artifact(
                    "voiceover-v2",
                    "voiceover",
                    parents=["narration-v2", "profile-v2"],
                    narration_id="narration-v2",
                    profile_id="profile-v2",
                    media_path="media/voiceover-v2.wav",
                    duration_ms=1000,
                    provenance="chatcut:voice",
                    output_contract="voiceover-v1",
                ),
                self.artifact(
                    "voice-timing-v2",
                    "voice-timing",
                    parents=["voiceover-v2"],
                    voiceover_id="voiceover-v2",
                    timing_kind="real",
                    duration_ms=1000,
                    segments=[{"start_ms": 0, "end_ms": 1000, "text": "旁白"}],
                    output_contract="voiceover-v1",
                ),
                self.artifact(
                    "beats-v2",
                    "semantic-beats",
                    parents=["voice-timing-v2"],
                    voice_timing_id="voice-timing-v2",
                    output_contract="voiceover-v1",
                ),
            ]
        )
        self.write_audio("media/voiceover-v2.wav")

        result = prepare_voice_task(self.root, self.envelope(), artifacts, ["chatcut:voice"])

        self.assertEqual("succeeded", result["status"])
        self.assertEqual(["voiceover-v2", "voice-timing-v2", "beats-v2"], result["artifacts"])
        tasks._validate_result(result)

    def test_published_bundle_requires_a_readable_project_contained_voiceover_file(self):
        """Catches metadata-only, redirected, or missing media being reported as produced audio."""
        for media_path, make_fixture in (
            ("media/voiceover-v2.wav", False),
            ("../voiceover-v2.wav", True),
        ):
            with self.subTest(media_path=media_path):
                artifacts = self.published_bundle(media_path=media_path)
                if make_fixture:
                    self.write_audio("media/voiceover-v2.wav")

                result = prepare_voice_task(
                    self.root, self.envelope(), artifacts, ["chatcut:voice"]
                )

                self.assertEqual("waiting_external", result["status"])
                self.assertEqual(["voiceover-media-unavailable"], result["warnings"])

    def test_tts_does_not_succeed_before_declared_chatcut_voice_is_available(self):
        """Catches published-looking audio bypassing the declared provider availability gate."""
        artifacts = self.published_bundle()
        self.write_audio("media/voiceover-v2.wav")

        result = prepare_voice_task(self.root, self.envelope(), artifacts, [])

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["chatcut-voice-unavailable"], result["warnings"])

    def test_symlinked_voiceover_media_cannot_satisfy_success(self):
        """Catches an artifact path following a project-local link to non-immutable audio."""
        artifacts = self.published_bundle()
        outside = self.root / "outside.wav"
        outside.write_bytes(b"RIFF")
        media = self.root / "media" / "voiceover-v2.wav"
        media.parent.mkdir(exist_ok=True)
        media.symlink_to(outside)

        result = prepare_voice_task(
            self.root, self.envelope(), artifacts, ["chatcut:voice"]
        )

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["voiceover-media-unavailable"], result["warnings"])

    def test_mismatched_declared_timing_duration_cannot_satisfy_success(self):
        """Catches a real file overriding inconsistent immutable duration metadata."""
        artifacts = self.published_bundle()
        artifacts[-2]["duration_ms"] = 999
        self.write_audio("media/voiceover-v2.wav")

        result = prepare_voice_task(
            self.root, self.envelope(), artifacts, ["chatcut:voice"]
        )

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["voice-artifacts-pending"], result["warnings"])

    def test_undeclared_higher_version_bundle_cannot_satisfy_this_task(self):
        """Catches scanning arbitrary project artifacts and silently substituting profile/provider lineage."""
        artifacts = self.artifacts()
        artifacts.extend(
            [
                self.artifact(
                    "profile-v3",
                    "voice-profile",
                    version=3,
                    mode="tts",
                    language="zh-CN",
                    provider="unapproved-provider",
                    voice_id="other-voice",
                    speaking_rate=1.0,
                    emotion="calm",
                    pronunciations=[],
                    approved=True,
                ),
                self.artifact(
                    "voiceover-v3",
                    "voiceover",
                    version=3,
                    parents=["narration-v2", "profile-v3"],
                    narration_id="narration-v2",
                    profile_id="profile-v3",
                    media_path="media/voiceover-v3.wav",
                    duration_ms=1000,
                    provenance="unapproved:voice",
                    output_contract="voiceover-v1",
                ),
                self.artifact(
                    "voice-timing-v3",
                    "voice-timing",
                    version=3,
                    parents=["voiceover-v3"],
                    voiceover_id="voiceover-v3",
                    timing_kind="real",
                    duration_ms=1000,
                    segments=[{"start_ms": 0, "end_ms": 1000, "text": "旁白"}],
                    output_contract="voiceover-v1",
                ),
                self.artifact(
                    "beats-v3",
                    "semantic-beats",
                    version=3,
                    parents=["voice-timing-v3"],
                    voice_timing_id="voice-timing-v3",
                    output_contract="voiceover-v1",
                ),
            ]
        )
        self.write_audio("media/voiceover-v3.wav")

        result = prepare_voice_task(self.root, self.envelope(), artifacts, ["chatcut:voice"])

        self.assertEqual("waiting_external", result["status"])
        self.assertEqual(["voice-artifacts-pending"], result["warnings"])

    def test_result_uses_only_the_persisted_task_result_schema_keys(self):
        """Catches provider bookkeeping leaking into the closed result envelope."""
        schema = json.loads(
            (ROOT / "references/schemas/task-result.schema.json").read_text(encoding="utf-8")
        )
        result = prepare_voice_task(
            self.root, self.envelope(), self.artifacts(), ["chatcut:voice"]
        )

        self.assertTrue(set(result).issubset(schema["properties"]))
        self.assertTrue(set(schema["required"]).issubset(result))

    def test_rejects_an_envelope_the_task_runtime_cannot_complete(self):
        """Catches a preparer returning schema-looking results for unsafe task identities."""
        envelope = self.envelope()
        envelope["task_id"] = "../voice-prepare-v2"

        with self.assertRaisesRegex(ValueError, "safe"):
            prepare_voice_task(self.root, envelope, self.artifacts(), ["chatcut:voice"])

    def published_bundle(self, *, media_path="media/voiceover-v2.wav"):
        artifacts = self.artifacts()
        artifacts.extend(
            [
                self.artifact(
                    "voiceover-v2",
                    "voiceover",
                    parents=["narration-v2", "profile-v2"],
                    narration_id="narration-v2",
                    profile_id="profile-v2",
                    media_path=media_path,
                    duration_ms=1000,
                    provenance="chatcut:voice",
                    output_contract="voiceover-v1",
                ),
                self.artifact(
                    "voice-timing-v2",
                    "voice-timing",
                    parents=["voiceover-v2"],
                    voiceover_id="voiceover-v2",
                    timing_kind="real",
                    duration_ms=1000,
                    segments=[{"start_ms": 0, "end_ms": 1000, "text": "旁白"}],
                    output_contract="voiceover-v1",
                ),
                self.artifact(
                    "beats-v2",
                    "semantic-beats",
                    parents=["voice-timing-v2"],
                    voice_timing_id="voice-timing-v2",
                    output_contract="voiceover-v1",
                ),
            ]
        )
        return artifacts

    def write_audio(self, relative_path):
        path = self.root / relative_path
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"RIFF")


if __name__ == "__main__":
    unittest.main()

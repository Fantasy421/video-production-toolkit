"""Behavioral tests for deterministic worker-facing task packets."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.toolkit.task_packets import (
    build_task_packet,
    validate_task_packet,
    validate_task_result_summary,
)


class TaskPacketTests(unittest.TestCase):
    @staticmethod
    def envelope(**constraints):
        return {
            "task_id": "scene-batch-01",
            "capability": "scene.produce",
            "inputs": [
                "scene-contract-S01",
                "scene-contract-S02",
                "voice-timing-v1",
                "timed-beats-v1",
                "scene-timing-v1",
            ],
            "adapter_preferences": ["chatcut"],
            "output_contract": "scene-batch-v1",
            "constraints": {
                "visual_media_operation": "none",
                "time_window_ms": [0, 12_000],
                "contract_summary": {
                    "chapter_id": "chapter-01",
                    "scene_ids": ["S01", "S02"],
                    "scene_contract_ids": [
                        "scene-contract-S01",
                        "scene-contract-S02",
                    ],
                    "production_scope": "representative-slice",
                },
                **constraints,
            },
        }

    def test_projection_excludes_unrelated_constraints_and_keeps_authority(self):
        envelope = self.envelope(
            full_transcript="must never enter the worker packet" * 500,
        )

        packet = build_task_packet(envelope)

        self.assertEqual(1, packet["packet_version"])
        self.assertEqual("scene.produce", packet["capability"])
        self.assertEqual(envelope["inputs"], packet["artifact_ids"])
        self.assertEqual([0, 12_000], packet["time_window_ms"])
        self.assertEqual(
            envelope["constraints"]["contract_summary"],
            packet["contract_summary"],
        )
        self.assertEqual(
            {"max_checks": 8, "max_warnings": 8, "max_item_chars": 64},
            packet["result_limits"],
        )
        self.assertNotIn("full_transcript", repr(packet))
        self.assertLessEqual(validate_task_packet(packet), 8_192)

    def test_active_visual_authority_survives_compaction_exactly(self):
        context = {
            "scope_identity": {
                "kind": "scene-batch",
                "id": ["scene-contract-S01", "scene-contract-S02"],
            },
            "allowed_artifact_ids": ["style-v1"],
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 1,
            "context_budget_bytes": 8_192,
        }
        envelope = self.envelope(
            visual_media_operation="video-render",
            visual_media_context=context,
            execution_context="isolated-child-agent",
        )

        packet = build_task_packet(envelope)

        self.assertEqual(
            {"operation": "video-render", **context},
            packet["visual_media_authority"],
        )

    def test_result_summary_rejects_unbounded_model_output(self):
        valid = {
            "checks": [f"check-{index}" for index in range(8)],
            "warnings": [f"warning-{index}" for index in range(8)],
        }
        self.assertEqual(valid, validate_task_result_summary(valid))

        for invalid in (
            {**valid, "checks": [f"check-{index}" for index in range(9)]},
            {**valid, "warnings": ["x" * 65]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_task_result_summary(invalid)

    def test_capability_summary_rejects_unknown_fields(self):
        envelope = self.envelope()
        envelope["constraints"]["contract_summary"]["full_storyboard"] = {}

        with self.assertRaisesRegex(ValueError, "contract summary field"):
            build_task_packet(envelope)

    def test_standalone_validation_rejects_tampered_authority_and_ids(self):
        packet = build_task_packet(self.envelope())
        invalid_packets = []

        invalid_id = json.loads(json.dumps(packet))
        invalid_id["artifact_ids"].append("../secret")
        invalid_packets.append(invalid_id)

        oversized_batch = json.loads(json.dumps(packet))
        oversized_batch["contract_summary"]["scene_ids"] = [
            f"S{index:02d}" for index in range(1, 8)
        ]
        oversized_batch["contract_summary"]["scene_contract_ids"] = [
            f"scene-contract-S{index:02d}" for index in range(1, 8)
        ]
        invalid_packets.append(oversized_batch)

        for invalid in invalid_packets:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_task_packet(invalid)

        visual = build_task_packet(
            self.envelope(
                visual_media_operation="video-render",
                visual_media_context={
                    "scope_identity": {
                        "kind": "scene-batch",
                        "id": ["scene-contract-S01", "scene-contract-S02"],
                    },
                    "allowed_artifact_ids": [],
                    "historical_access": "character-only",
                    "continuity_exception": None,
                    "max_review_previews": 1,
                    "context_budget_bytes": 8_192,
                },
                execution_context="isolated-child-agent",
            )
        )
        visual["visual_media_authority"]["operation"] = "read-whole-project"
        with self.assertRaises(ValueError):
            validate_task_packet(visual)

    def test_cli_builds_packet_without_schema_text(self):
        with TemporaryDirectory() as folder:
            envelope_path = Path(folder) / "envelope.json"
            envelope_path.write_text(json.dumps(self.envelope()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "scripts/validate_task_packet.py",
                    "build",
                    str(envelope_path),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        packet = json.loads(completed.stdout)
        self.assertEqual("scene.produce", packet["capability"])
        self.assertNotIn("$schema", completed.stdout)


if __name__ == "__main__":
    unittest.main()

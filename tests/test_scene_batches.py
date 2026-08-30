"""Tests for clean, timing-frozen scene production batches."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.toolkit.scene_batches import plan_scene_batches


class SceneBatchTests(unittest.TestCase):
    @staticmethod
    def contracts(count, *, chapter_id="chapter-01", start_index=1, start_ms=0):
        return [
            {
                "contract_id": f"scene-contract-S{index:02d}",
                "chapter_id": chapter_id,
                "scene_id": f"S{index:02d}",
                "start_ms": start_ms + offset * 2_000,
                "end_ms": start_ms + (offset + 1) * 2_000,
            }
            for offset, index in enumerate(range(start_index, start_index + count))
        ]

    @staticmethod
    def frozen(contracts):
        return {
            "timing_kind": "real",
            "keywords_frozen": True,
            "timing_validation_status": "passed",
            "voice_timing_id": "voice-timing-v1",
            "timed_semantic_beats_id": "timed-beats-v1",
            "scene_timing_contracts_id": "scene-timing-v1",
            "timing_validation_id": "timing-validation-v1",
            "frozen_scene_contract_ids": [
                item["contract_id"] for item in contracts
            ],
        }

    def test_thirty_four_scenes_become_six_fresh_bounded_batches(self):
        contracts = self.contracts(34)

        batches = plan_scene_batches(contracts, self.frozen(contracts))

        self.assertEqual([6, 6, 6, 6, 5, 5], [len(item["scene_ids"]) for item in batches])
        self.assertEqual(6, len({item["batch_id"] for item in batches}))
        self.assertTrue(all(item["context_policy"] == "fresh" for item in batches))
        self.assertEqual(
            [item["scene_id"] for item in contracts],
            [scene_id for batch in batches for scene_id in batch["scene_ids"]],
        )

    def test_batches_never_cross_chapter_or_time_window(self):
        first = self.contracts(5, chapter_id="chapter-01")
        second = self.contracts(
            5,
            chapter_id="chapter-02",
            start_index=6,
            start_ms=10_000,
        )
        contracts = [*first, *second]

        batches = plan_scene_batches(contracts, self.frozen(contracts))

        self.assertEqual(2, len(batches))
        self.assertEqual(
            [
                ("chapter-01", [0, 10_000]),
                ("chapter-02", [10_000, 20_000]),
            ],
            [(item["chapter_id"], item["time_window_ms"]) for item in batches],
        )

    def test_short_chapter_is_one_bounded_exception(self):
        contracts = self.contracts(3)

        batches = plan_scene_batches(contracts, self.frozen(contracts))

        self.assertEqual([3], [len(item["scene_ids"]) for item in batches])

    def test_production_is_blocked_until_full_timing_is_frozen(self):
        contracts = self.contracts(6)
        valid = self.frozen(contracts)
        invalid_states = [
            {**valid, "timing_kind": "estimated"},
            {**valid, "keywords_frozen": False},
            {**valid, "timing_validation_status": "blocked"},
            {**valid, "frozen_scene_contract_ids": valid["frozen_scene_contract_ids"][:-1]},
        ]

        for timing in invalid_states:
            with self.subTest(timing=timing), self.assertRaisesRegex(
                ValueError, "frozen"
            ):
                plan_scene_batches(contracts, timing)

    def test_cli_emits_compact_batches_for_skill_execution(self):
        contracts = self.contracts(8)
        with TemporaryDirectory() as folder:
            contracts_path = Path(folder) / "contracts.json"
            timing_path = Path(folder) / "timing.json"
            contracts_path.write_text(json.dumps(contracts), encoding="utf-8")
            timing_path.write_text(
                json.dumps(self.frozen(contracts)), encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "scripts/plan_scene_batches.py",
                    str(contracts_path),
                    str(timing_path),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        batches = json.loads(completed.stdout)
        self.assertEqual([4, 4], [len(item["scene_ids"]) for item in batches])
        self.assertTrue(all(item["context_policy"] == "fresh" for item in batches))


if __name__ == "__main__":
    unittest.main()

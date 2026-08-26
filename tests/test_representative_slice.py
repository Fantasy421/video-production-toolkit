import unittest

from scripts.plan_representative_slice import select_representative_slice


class RepresentativeSliceTests(unittest.TestCase):
    def setUp(self):
        self.contracts = [
            {
                "scene_id": "S01",
                "start_ms": 0,
                "end_ms": 6000,
                "primary_carrier": "scene",
                "scene_image_generation": True,
                "new_character_baseline": True,
            },
            {
                "scene_id": "S02",
                "start_ms": 6000,
                "end_ms": 12000,
                "primary_carrier": "motion-graphics",
            },
            {
                "scene_id": "S03",
                "start_ms": 12000,
                "end_ms": 18000,
                "primary_carrier": "b-roll",
                "generated_video": True,
                "captions": True,
            },
        ]
        self.by_id = {item["scene_id"]: item for item in self.contracts}

    def test_slice_covers_highest_risk_carriers(self):
        selected = select_representative_slice(self.contracts)
        carriers = {self.by_id[item]["primary_carrier"] for item in selected}
        self.assertIn("scene", carriers)
        self.assertIn("motion-graphics", carriers)
        self.assertFalse(selected.composite)
        self.assertGreaterEqual(selected.duration_ms, 10000)
        self.assertLessEqual(selected.duration_ms, 20000)

    def test_prefers_shorter_equal_coverage_adjacent_range(self):
        contracts = [
            *self.contracts,
            {
                "scene_id": "S04",
                "start_ms": 18000,
                "end_ms": 28000,
                "primary_carrier": "motion-graphics",
            },
        ]
        selected = select_representative_slice(contracts)
        self.assertEqual(["S01", "S02"], selected)

    def test_marks_composite_when_scene_and_motion_cannot_share_a_valid_range(self):
        contracts = [
            {
                "scene_id": "S01",
                "start_ms": 0,
                "end_ms": 10000,
                "primary_carrier": "scene",
                "scene_image_generation": True,
            },
            {
                "scene_id": "S02",
                "start_ms": 30000,
                "end_ms": 40000,
                "primary_carrier": "motion-graphics",
            },
        ]
        selected = select_representative_slice(contracts)
        self.assertEqual(["S01", "S02"], selected)
        self.assertTrue(selected.composite)
        self.assertEqual(((0, 10000), (30000, 40000)), selected.ranges)

    def test_rejects_unsafe_or_overlapping_contracts(self):
        with self.assertRaises(ValueError):
            select_representative_slice([
                {"scene_id": "../escape", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene"}
            ])
        with self.assertRaises(ValueError):
            select_representative_slice([
                {"scene_id": "S01", "start_ms": 0, "end_ms": 10000, "primary_carrier": "scene"},
                {"scene_id": "S02", "start_ms": 9000, "end_ms": 15000, "primary_carrier": "b-roll"},
            ])


if __name__ == "__main__":
    unittest.main()

"""Focused tests for compact, metadata-only timing validation."""

import copy
import unittest

from scripts.toolkit.timing_validation import validate_timing_rows


def _row(beat_id="B01", *, timing_kind="real"):
    row = {
        "beat_id": beat_id,
        "scene_id": "S01",
        "keyword_anchor_ms": [1_000, 1_200],
        "visual_window_ms": [880, 1_400],
        "scene_window_ms": [0, 2_000],
        "primary_carrier": "motion-graphics",
        "support_layer": "caption-emphasis",
    }
    if timing_kind is not None:
        row["timing_kind"] = timing_kind
    return row


def valid_rows():
    return [_row()]


def missing_timing_rows():
    return [_row(timing_kind="estimated")]


def keyword_outside_rows():
    row = _row()
    row["visual_window_ms"] = [1_050, 1_400]
    return [row]


def scene_outside_rows():
    row = _row()
    row["scene_window_ms"] = [900, 1_300]
    return [row]


def multiple_primary_rows():
    row = _row()
    row["primary_carrier"] = ["motion-graphics", "scene"]
    return [row]


def stale_rows():
    row = _row()
    row["voice_timing_status"] = "stale"
    return [row]


class TimingValidationTests(unittest.TestCase):
    CASES = (
        ("valid", valid_rows, "passed"),
        ("missing-real-timing", missing_timing_rows, "VOICE_TIMING_REQUIRED"),
        ("keyword-window", keyword_outside_rows, "VISUAL_BEFORE_ALLOWED_WINDOW"),
        ("scene-window", scene_outside_rows, "BEAT_OUTSIDE_SCENE"),
        ("multiple-primary", multiple_primary_rows, "MULTIPLE_PRIMARY_CARRIERS"),
        ("recovery-stale", stale_rows, "STALE_VOICE_TIMING"),
    )

    def test_minimal_matrix_returns_compact_status_and_issue_code(self):
        for name, factory, expected in self.CASES:
            with self.subTest(case=name):
                result = validate_timing_rows(
                    factory(), minimum_readable_duration_ms=500
                )
                if expected == "passed":
                    self.assertEqual({"status", "checks_run"}, set(result))
                    self.assertEqual("passed", result["status"])
                else:
                    self.assertEqual("blocked", result["status"])
                    self.assertEqual(1, result["issue_counts"][expected])
                    self.assertEqual([factory()[0]["beat_id"]], result["examples"][expected])

    def test_issue_examples_are_bounded_but_counts_are_aggregated(self):
        rows = []
        for index in range(7):
            row = _row(f"B{index + 1:02d}")
            row["visual_window_ms"] = [1_050, 1_400]
            rows.append(row)

        result = validate_timing_rows(rows, minimum_readable_duration_ms=500)

        self.assertEqual(7, result["issue_counts"]["VISUAL_BEFORE_ALLOWED_WINDOW"])
        self.assertEqual(
            ["B01", "B02", "B03"],
            result["examples"]["VISUAL_BEFORE_ALLOWED_WINDOW"],
        )

    def test_rows_are_closed_compact_metadata_only_records(self):
        row = _row()
        row["narration_text"] = "must not be accepted"
        with self.assertRaisesRegex(ValueError, "closed|compact"):
            validate_timing_rows([row], minimum_readable_duration_ms=500)

    def test_input_rows_are_not_mutated(self):
        rows = valid_rows()
        original = copy.deepcopy(rows)
        validate_timing_rows(rows, minimum_readable_duration_ms=500)
        self.assertEqual(original, rows)

    def test_malformed_structural_rows_are_rejected_before_rules(self):
        cases = (
            ("missing scene", "scene_id", None),
            ("missing visual", "visual_window_ms", None),
            ("missing scene window", "scene_window_ms", None),
            ("reversed visual", "visual_window_ms", [1_400, 880]),
            ("wrong-type scene", "scene_window_ms", "0..2000"),
            ("out-of-range keyword", "keyword_anchor_ms", [-1, 1_200]),
        )
        for name, field, value in cases:
            with self.subTest(case=name):
                row = _row()
                row.pop(field, None) if value is None else row.__setitem__(field, value)
                with self.assertRaisesRegex(ValueError, "compact|timing row"):
                    validate_timing_rows([row], minimum_readable_duration_ms=500)

    def test_explicit_null_keyword_anchor_returns_the_closed_missing_issue(self):
        """Catches nullable missing-anchor state raising before bounded repair routing."""
        row = _row()
        row["keyword_anchor_ms"] = None

        result = validate_timing_rows([row], minimum_readable_duration_ms=500)

        self.assertEqual("blocked", result["status"])
        self.assertEqual(1, result["issue_counts"]["KEYWORD_ANCHOR_MISSING"])
        self.assertEqual(["B01"], result["examples"]["KEYWORD_ANCHOR_MISSING"])

    def test_missing_or_wrong_typed_keyword_anchor_is_not_nullable(self):
        """Catches the missing sentinel broadening into omitted or malformed payloads."""
        cases = (
            ("omitted", object()),
            ("string", "1000..1200"),
            ("mapping", {"start_ms": 1000, "end_ms": 1200}),
            ("wrong-list", [1000]),
        )
        for name, value in cases:
            with self.subTest(name=name):
                row = _row()
                if name == "omitted":
                    row.pop("keyword_anchor_ms")
                else:
                    row["keyword_anchor_ms"] = value
                with self.assertRaisesRegex(ValueError, "compact|keyword_anchor"):
                    validate_timing_rows([row], minimum_readable_duration_ms=500)

    def test_carrier_and_support_are_canonical_scalars(self):
        cases = (
            ("one primary", "primary_carrier", ["motion-graphics"]),
            ("unknown primary", "primary_carrier", "not-registered"),
            ("one support", "support_layer", ["caption-emphasis"]),
            ("empty support", "support_layer", ""),
            ("unknown support", "support_layer", "not-registered"),
        )
        for name, field, value in cases:
            with self.subTest(case=name):
                row = _row()
                row[field] = value
                with self.assertRaisesRegex(ValueError, "compact|carrier|support"):
                    validate_timing_rows([row], minimum_readable_duration_ms=500)

    def test_lineage_ids_are_safe_and_timed_lineage_mismatch_is_stale(self):
        invalid = _row()
        invalid["voice_timing_id"] = "audio:/secret.wav"
        with self.assertRaisesRegex(ValueError, "lineage|safe"):
            validate_timing_rows([invalid], minimum_readable_duration_ms=500)

        stale = _row()
        stale.update(
            timed_semantic_beats_id="timed-v1",
            current_timed_semantic_beats_id="timed-v2",
        )
        result = validate_timing_rows([stale], minimum_readable_duration_ms=500)
        self.assertEqual(1, result["issue_counts"]["STALE_VOICE_TIMING"])

        for empty_field in ("voice_timing_id", "current_voice_timing_id", "timed_semantic_beats_id", "current_timed_semantic_beats_id"):
            with self.subTest(empty_field=empty_field):
                row = _row()
                row[empty_field] = None
                result = validate_timing_rows([row], minimum_readable_duration_ms=500)
                self.assertIn("STALE_VOICE_TIMING", result["issue_counts"])


if __name__ == "__main__":
    unittest.main()

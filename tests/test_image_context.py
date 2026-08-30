"""Closed metadata-only contracts for isolated image work."""

import json
import unittest
from pathlib import Path

from scripts.toolkit.image_context import (
    authorize_image_access,
    compact_image_result,
    validate_result_envelope,
)
from tests.encoding_boundary_cases import HARMLESS_PROSE_CONTROL


ROOT = Path(__file__).parents[1]


class ImageContextTests(unittest.TestCase):
    def context(
        self,
        *,
        allowed=None,
        packs=None,
        max_previews=1,
        budget=4096,
        scope=None,
        **extra,
    ):
        return {
            "scope_identity": scope
            or {"kind": "scene-contract", "id": "contract-S01-v1"},
            "allowed_image_artifact_ids": list(allowed or []),
            "allowed_character_pack_ids": list(packs or []),
            "forbidden_scene_image_access": True,
            "max_review_previews": max_previews,
            "context_budget": budget,
            **extra,
        }

    def artifact(self, artifact_type, *, artifact_id=None, status="approved", **extra):
        return {
            "artifact_id": artifact_id or f"host-{artifact_type}-v1",
            "type": artifact_type,
            "status": status,
            **extra,
        }

    def test_historical_approved_independent_character_classes_are_allowed(self):
        """Catches an allowlist that blocks approved project-independent identity assets."""
        for artifact_type in (
            "character-model-sheet",
            "character-turnaround",
            "character-clothing-reference",
            "character-expression-reference",
            "character-pose-reference",
            "transparent-character-action",
            "character-identity-metadata",
        ):
            with self.subTest(artifact_type=artifact_type):
                artifact = self.artifact(artifact_type)
                authorize_image_access(
                    self.context(allowed=[artifact["artifact_id"]]),
                    artifact,
                    historical=True,
                )

    def test_historical_scene_classes_are_forbidden_even_for_the_same_character(self):
        """Catches character identity metadata laundering historical scene imagery."""
        for artifact_type in (
            "scene",
            "scene-image",
            "storyboard",
            "storyboard-image",
            "b-roll",
            "b-roll-image",
            "motion-graphics",
            "motion-graphic-screenshot",
            "motion-graphics-screenshot",
            "motion-preview",
            "scene-preview",
        ):
            with self.subTest(artifact_type=artifact_type):
                artifact = self.artifact(
                    artifact_type,
                    character_ids=["host-v1"],
                )
                with self.assertRaisesRegex(PermissionError, "historical scene image"):
                    authorize_image_access(
                        self.context(allowed=[artifact["artifact_id"]]),
                        artifact,
                        historical=True,
                    )

    def test_historical_access_requires_declaration_approval_and_hard_ban(self):
        """Catches discovery, draft reuse, or a disabled scene ban broadening history."""
        artifact = self.artifact("character-model-sheet")
        with self.assertRaisesRegex(PermissionError, "undeclared image"):
            authorize_image_access(self.context(), artifact, historical=True)
        with self.assertRaisesRegex(PermissionError, "approved character asset"):
            authorize_image_access(
                self.context(allowed=[artifact["artifact_id"]]),
                {**artifact, "status": "draft"},
                historical=True,
            )

    def test_character_pack_never_replaces_the_exact_image_allowlist(self):
        """Catches pack membership implicitly authorizing an undeclared image."""
        artifact = self.artifact(
            "character-model-sheet", character_pack_id="host-pack-v1"
        )
        with self.assertRaisesRegex(PermissionError, "undeclared image"):
            authorize_image_access(
                self.context(packs=["host-pack-v1"]),
                artifact,
                historical=True,
            )
        authorize_image_access(
            self.context(
                allowed=[artifact["artifact_id"]], packs=["host-pack-v1"]
            ),
            artifact,
            historical=True,
        )
        with self.assertRaisesRegex(PermissionError, "historical scene ban"):
            authorize_image_access(
                {
                    **self.context(allowed=[artifact["artifact_id"]]),
                    "forbidden_scene_image_access": False,
                },
                artifact,
                historical=True,
            )

    def test_current_access_is_exact_allowlist_or_one_user_continuity_exception(self):
        """Catches neighboring scene discovery or an implied continuity exception."""
        allowed = self.artifact("scene-image", artifact_id="S02-image-v3")
        with self.assertRaisesRegex(PermissionError, "continuity exception"):
            authorize_image_access(
                self.context(allowed=[allowed["artifact_id"]]),
                allowed,
                historical=False,
            )

        exception = self.artifact("scene-image", artifact_id="S01-image-v2")
        authorize_image_access(
            self.context(
                continuity_exception={
                    "artifact_id": exception["artifact_id"],
                    "user_requested": True,
                    "reason": "Match the explicitly named eyeline.",
                }
            ),
            exception,
            historical=False,
        )

        neighbor = self.artifact("scene-image", artifact_id="S03-image-v1")
        with self.assertRaisesRegex(PermissionError, "continuity exception"):
            authorize_image_access(
                self.context(
                    continuity_exception={
                        "artifact_id": exception["artifact_id"],
                        "user_requested": True,
                        "reason": "Match the explicitly named eyeline.",
                    }
                ),
                neighbor,
                historical=False,
            )

        non_scene = self.artifact(
            "character-model-sheet", artifact_id=exception["artifact_id"]
        )
        with self.assertRaisesRegex(PermissionError, "continuity.*scene image"):
            authorize_image_access(
                self.context(
                    continuity_exception={
                        "artifact_id": exception["artifact_id"],
                        "user_requested": True,
                        "reason": "Match the explicitly named eyeline.",
                    }
                ),
                non_scene,
                historical=False,
            )

    def test_context_is_closed_safe_unique_and_within_its_item_budget(self):
        """Catches malformed or oversized context being treated as authority."""
        cases = (
            ({**self.context(), "surprise": True}, "unknown"),
            (self.context(allowed=["../outside"]), "safe"),
            (self.context(allowed=["same", "same"]), "duplicates"),
            (self.context(max_previews=2), "max_review_previews"),
            (self.context(budget=0), "positive integer"),
            (self.context(budget=32_769), "context_budget"),
            (self.context(allowed=[f"image-{index}" for index in range(17)]), "allowed_image"),
            (self.context(packs=[f"pack-{index}" for index in range(9)]), "allowed_character"),
            (
                self.context(scope={"kind": "scene-contract", "id": "one", "extra": True}),
                "scope_identity",
            ),
            (
                self.context(scope={"kind": "unknown", "id": "one"}),
                "scope_identity",
            ),
            (
                self.context(
                    continuity_exception={
                        "artifact_id": "S01-image-v2",
                        "user_requested": False,
                        "reason": "No explicit request.",
                    }
                ),
                "user_requested",
            ),
            (
                self.context(
                    continuity_exception={
                        "artifact_id": "S01-image-v2",
                        "user_requested": True,
                        "reason": " trailing whitespace ",
                    }
                ),
                "trimmed",
            ),
        )
        artifact = self.artifact("scene-image", artifact_id="asset-a")
        for context, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                authorize_image_access(context, artifact, historical=False)

    def test_general_result_validator_scrubs_nested_leaks_and_bounds_json(self):
        """Catches non-image result envelopes bypassing the shared payload scrub."""
        with self.assertRaisesRegex(ValueError, "image payload"):
            validate_result_envelope(
                {"checks": [{"detail": "payload=data:image/png;base64,AAEC"}]}
            )
        with self.assertRaisesRegex(ValueError, "prompt history"):
            validate_result_envelope(
                {"warnings": [{"prompt_iteration_history": ["first", "second"]}]}
            )
        with self.assertRaisesRegex(ValueError, "result budget"):
            validate_result_envelope({"checks": ["x" * 33_000]})

        harmless = {
            "checks": ["sha512=" + "0123456789abcdef" * 8],
            "warnings": [HARMLESS_PROSE_CONTROL],
        }
        validate_result_envelope(harmless)

    def test_compact_result_rejects_payloads_data_urls_and_prompt_histories(self):
        """Catches image or generation transcript content escaping into the parent task."""
        cases = (
            ({"image_bytes": b"binary", "review_previews": []}, "image payload"),
            ({"base64": "AAEC", "review_previews": []}, "image payload"),
            ({"images": ["data:image/png;base64,AAEC"], "review_previews": []}, "image payload"),
            ({"prompt_history": ["first", "second"], "review_previews": []}, "prompt history"),
            ({"metadata": {"image_url": "https://example.invalid/x.png"}}, "image payload"),
            ({"summary": "leak https://example.invalid/x.png"}, "image payload"),
            ({"summary": "prompt history: first, second"}, "prompt history"),
            ({"summary": "x " * 50_000}, "compact text"),
            ({"metadata": {"digest": "x " * 2048}}, "compact scalar"),
        )
        for result, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                compact_image_result(self.context(), result)

    def test_compact_result_normalizes_urls_data_urls_and_wrapped_base64(self):
        """Catches payload scanners that depend on leading text or uninterrupted base64."""
        png_payload = (
            "iVBORw0KGgoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        )
        self.assertEqual(128, len(png_payload))
        cases = (
            {"summary": "preview=(https://example.invalid/review.png)"},
            {"summary": "preview=https://example.invalid/review.png"},
            {"summary": "note[payload=data:image/png;base64,\nAAEC]"},
            {"metadata": {"digest": png_payload[:65] + "\n" + png_payload[65:]}},
            {
                "summary": " ".join(
                    png_payload[index : index + 10]
                    for index in range(0, len(png_payload), 10)
                )
            },
            {"summary": f'image_bytes="{png_payload}"'},
            {"summary": f"```\n{png_payload}\n```"},
        )
        for result in cases:
            with self.subTest(result=result), self.assertRaisesRegex(
                ValueError, "image payload"
            ):
                compact_image_result(self.context(), result)

    def test_compact_result_does_not_treat_repeated_prose_as_base64(self):
        """Catches an equal-length prose heuristic rejecting an ordinary summary."""
        raw = {"summary": "normal " * 22}

        self.assertEqual(raw, compact_image_result(self.context(), raw))

    def test_compact_result_rejects_media_base64_at_any_wrap_width(self):
        """Catches base64 detection depending on whitespace-delimited chunk width."""
        png_payload = (
            "iVBORw0KGgoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        )
        self.assertEqual(128, len(png_payload))
        for width in (1, 2, 3, 5):
            wrapped = " \n".join(
                png_payload[index : index + width]
                for index in range(0, len(png_payload), width)
            )
            with self.subTest(width=width), self.assertRaisesRegex(
                ValueError, "image payload"
            ):
                compact_image_result(self.context(), {"metadata": {"digest": wrapped}})

    def test_compact_result_requires_media_evidence_before_rejecting_base64_text(self):
        """Catches hashes or harmless base64 prose being treated as media payloads."""
        cases = (
            {"metadata": {"sha512": "0123456789abcdef" * 8}},
            {"summary": HARMLESS_PROSE_CONTROL},
            {"metadata": {"digest": "QUJD" * 32}},
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(raw, compact_image_result(self.context(), raw))

    def test_compact_result_rejects_unsafe_undeclared_paths_and_preview_overflow(self):
        """Catches path smuggling and multiple review renders in a compact handoff."""
        with self.assertRaisesRegex(ValueError, "undeclared path"):
            compact_image_result(
                self.context(),
                {"artifact_ids": [], "paths": ["artifacts/unbound.json"]},
            )
        with self.assertRaisesRegex(ValueError, "project-contained path"):
            compact_image_result(
                self.context(),
                {"artifact_ids": ["asset-a"], "paths": ["private/unbound.txt"]},
            )
        with self.assertRaisesRegex(ValueError, "project-contained path"):
            compact_image_result(
                self.context(),
                {"artifact_ids": ["asset-a"], "paths": ["private/asset-a.json"]},
            )
        for unsafe_path in (
            "../outside.png",
            "/outside.png",
            "https://example.invalid/outside.png",
            "file:///outside.png",
            "data:image/png;base64,AAEC",
        ):
            with self.subTest(path=unsafe_path), self.assertRaisesRegex(
                ValueError, "project-contained path|image payload"
            ):
                compact_image_result(
                    self.context(),
                    {"artifact_ids": ["asset-a"], "paths": [unsafe_path]},
                )
        with self.assertRaisesRegex(ValueError, "preview budget"):
            compact_image_result(
                self.context(max_previews=1),
                {"review_previews": ["previews/a.jpg", "previews/b.jpg"]},
            )

    def test_compact_result_keeps_only_the_closed_artifact_handoff(self):
        """Catches compact structural metadata being dropped or expanded on return."""
        raw = {
            "artifact_ids": ["scene-S02-v3"],
            "paths": ["artifacts/media/scene-S02-v3.json"],
            "summary": "角色一致；等待用户审美确认",
            "metadata": {"width": 1920, "height": 1080},
            "issues": [{"code": "needs-user-aesthetic-review"}],
            "status": "waiting_user",
            "user_decision_request": "请审美确认唯一预览。",
            "review_previews": ["previews/scene-S02-v3.jpg"],
        }

        result = compact_image_result(self.context(max_previews=1), raw)

        self.assertEqual(raw, result)
        self.assertNotIn("images", result)

    def test_compact_result_enforces_declared_context_budget(self):
        """Catches serialized handoff content overflowing its declared byte budget."""
        with self.assertRaisesRegex(ValueError, "context budget"):
            compact_image_result(
                self.context(budget=256),
                {
                    "artifact_ids": ["asset-a"],
                    "paths": ["artifacts/asset-a.json"],
                    "summary": "summary " * 30,
                    "metadata": {"width": 1920},
                },
            )


class ImageSchemaTests(unittest.TestCase):
    def test_image_context_schema_is_closed_and_task_context_is_conditional(self):
        """Catches generic non-image tasks being forced to carry image authority."""
        context = json.loads(
            (ROOT / "references/schemas/image-task-context.schema.json").read_text(
                encoding="utf-8"
            )
        )
        envelope = json.loads(
            (ROOT / "references/schemas/task-envelope.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            {
                "project.manage",
                "narration.plan",
                "visual.preview",
                "voice.prepare",
                "storyboard.plan",
                "scene.produce",
                "motion.preview",
                "motion.produce",
                "timeline.assemble",
                "structure.validate",
                "review.package",
                "captions.produce",
                "representative-slice.produce",
                "timing-repair",
            },
            set(envelope["properties"]["capability"]["enum"]),
        )

        self.assertFalse(context["additionalProperties"])
        self.assertEqual(
            {
                "scope_identity",
                "allowed_image_artifact_ids",
                "allowed_character_pack_ids",
                "forbidden_scene_image_access",
                "max_review_previews",
                "context_budget",
            },
            set(context["required"]),
        )
        constraints = envelope["properties"]["constraints"]
        self.assertEqual(
            "image-task-context.schema.json",
            constraints["properties"]["image_context"]["$ref"],
        )
        self.assertNotIn("image_context", constraints.get("required", []))
        self.assertIn("allOf", constraints)
        self.assertEqual(
            {"generate", "structure-only", "image-inspect"},
            set(constraints["properties"]["image_operation"]["enum"]),
        )
        structure_rule = next(
            rule
            for rule in envelope["allOf"]
            if rule["if"]["properties"]["capability"].get("const")
            == "structure.validate"
        )
        structure_branches = structure_rule["then"]["properties"]["constraints"][
            "oneOf"
        ]
        self.assertEqual(
            {"none", "image-inspect"},
            set(structure_branches[0]["properties"]["visual_media_operation"]["enum"]),
        )
        self.assertEqual(
            {"structure-only", "image-inspect"},
            set(structure_branches[1]["properties"]["image_operation"]["enum"]),
        )
        structure_only_rule = next(
            rule
            for rule in constraints["allOf"]
            if rule["if"].get("properties", {})
            .get("image_operation", {})
            .get("const")
            == "structure-only"
        )
        self.assertEqual(
            ["image_context"],
            structure_only_rule["then"]["not"]["required"],
        )

    def test_image_result_contract_is_optional_for_non_image_results(self):
        """Catches the compact image handoff breaking existing task-result records."""
        result = json.loads(
            (ROOT / "references/schemas/task-result.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn("image_handoff", result["required"])
        handoff = result["properties"]["image_handoff"]
        self.assertFalse(handoff["additionalProperties"])
        self.assertIn("allOf", result)


if __name__ == "__main__":
    unittest.main()

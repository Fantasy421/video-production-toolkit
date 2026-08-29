import base64
import unittest
from unittest.mock import patch

from scripts.toolkit.visual_media_context import (
    classify_visual_media_artifact,
    classify_visual_media_task,
    compact_visual_media_result,
    project_legacy_image_context,
    validate_compact_visual_media_handoff,
    validate_declared_visual_media_inputs,
    validate_result_envelope,
    validate_visual_media_context,
    validate_visual_media_operation_outputs,
    validate_visual_media_result_envelope,
)


class VisualMediaContextTests(unittest.TestCase):
    def context(self, *, scope=None, allowed=None, **extra):
        return {
            "scope_identity": scope
            or {"kind": "scene-contract", "id": "scene-contract-S03-v2"},
            "allowed_artifact_ids": list(allowed or []),
            "historical_access": "character-only",
            "continuity_exception": None,
            "max_review_previews": 1,
            "context_budget_bytes": 32_768,
            **extra,
        }

    def envelope(
        self,
        *,
        operation="image-generate",
        inputs=None,
        context=None,
        capability="scene.produce",
        output_contract="visual-result-v1",
    ):
        constraints = {"visual_media_operation": operation}
        if operation != "none":
            constraints["visual_media_context"] = context or self.context()
        return {
            "task_id": "visual-task-1",
            "capability": capability,
            "inputs": list(inputs or ["scene-contract-S03-v2"]),
            "adapter_preferences": ["local"],
            "output_contract": output_contract,
            "constraints": constraints,
        }

    def artifact(self, artifact_id, artifact_type, **extra):
        return {"artifact_id": artifact_id, "type": artifact_type, **extra}

    def handoff(self, **extra):
        return {
            "artifact_ids": ["media-S03-v4"],
            "paths": ["artifacts/media/media-S03-v4.json"],
            "media": {
                "kind": "video",
                "format": "mp4",
                "width": 1080,
                "height": 1920,
                "duration_ms": 12_400,
                "fps": 25,
                "readiness": "review-ready",
            },
            "checks": ["render-complete", "safe-region-valid"],
            "issues": [],
            "summary": "Scene S03 render is ready for review.",
            "review_preview_path": "previews/media-S03-v4/low.mp4",
            **extra,
        }

    def test_context_accepts_exact_operations_and_three_scope_shapes(self):
        """Catches a visual operation or one of the three exact scopes being dropped."""
        operations = (
            "none",
            "image-generate",
            "image-edit",
            "image-inspect",
            "video-generate",
            "video-edit",
            "video-render",
            "video-inspect",
            "frame-extract",
            "contact-sheet",
        )
        for operation in operations:
            task_kwargs = {"operation": operation}
            if operation == "none":
                task_kwargs.update(
                    capability="project.manage", output_contract="project-state-v1"
                )
            envelope = self.envelope(**task_kwargs)
            artifacts = {
                "scene-contract-S03-v2": self.artifact(
                    "scene-contract-S03-v2", "scene-contract"
                )
            }
            expected = "non-visual" if operation == "none" else "visual"
            with self.subTest(operation=operation):
                self.assertEqual(
                    expected,
                    classify_visual_media_task(envelope, artifacts),
                )

        scopes = (
            {"kind": "scene-contract", "id": "scene-contract-S03-v2"},
            {"kind": "character-asset-batch", "id": "characters-main-v2"},
            {"kind": "review-batch", "id": ["asset-1", "asset-2"]},
        )
        for scope in scopes:
            with self.subTest(scope=scope):
                self.assertEqual(
                    scope,
                    validate_visual_media_context(self.context(scope=scope))[
                        "scope_identity"
                    ],
                )

    def test_context_is_closed_unique_and_bounded(self):
        """Catches context authority expanding through unknown, duplicate, or oversized data."""
        cases = (
            ({**self.context(), "neighbor_scene_ids": ["S02"]}, "unknown"),
            (self.context(allowed=["asset-1", "asset-1"]), "duplicates"),
            (
                self.context(allowed=[f"asset-{index}" for index in range(17)]),
                "16-item",
            ),
            (
                self.context(
                    scope={"kind": "review-batch", "id": []},
                ),
                "review-batch",
            ),
            (
                self.context(
                    scope={
                        "kind": "review-batch",
                        "id": [f"asset-{index}" for index in range(9)],
                    }
                ),
                "review-batch",
            ),
            (self.context(historical_access="all"), "character-only"),
            (self.context(max_review_previews=2), "max_review_previews"),
            (self.context(context_budget_bytes=32_769), "context_budget_bytes"),
        )
        for context, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, message
            ):
                validate_visual_media_context(context)

    def test_continuity_exception_is_one_exact_user_requested_current_artifact(self):
        """Catches implicit or neighboring continuity authority."""
        exact = self.context(
            continuity_exception={
                "artifact_id": "scene-S02-v3",
                "user_requested": True,
                "reason": "Match the specifically requested eyeline.",
            }
        )
        normalized = validate_visual_media_context(exact)
        self.assertEqual(
            "scene-S02-v3", normalized["continuity_exception"]["artifact_id"]
        )
        for exception in (
            {
                "artifact_id": "scene-S02-v3",
                "user_requested": False,
                "reason": "No request.",
            },
            {
                "artifact_id": "scene-S02-v3",
                "user_requested": True,
                "reason": " trailing ",
            },
            {
                "artifact_id": "scene-S02-v3",
                "user_requested": True,
                "reason": "Exact.",
                "neighbor": "scene-S04-v1",
            },
        ):
            with self.subTest(exception=exception), self.assertRaises(ValueError):
                validate_visual_media_context(
                    self.context(continuity_exception=exception)
                )

    def test_artifact_classification_uses_only_declared_metadata(self):
        """Catches kind, MIME, suffix, or visual type evidence being ignored."""
        cases = (
            (
                self.artifact(
                    "still-v1",
                    "media",
                    media_kind="image",
                    path="media/still-v1.png",
                ),
                "image",
            ),
            (
                self.artifact(
                    "clip-v1",
                    "media",
                    mime_type="video/mp4",
                    path="media/clip-v1.mp4",
                ),
                "video",
            ),
            (self.artifact("board-v1", "storyboard-image"), "visual"),
            (self.artifact("clip-v2", "asset", path="media/clip-v2.mov"), "video"),
            (
                self.artifact(
                    "audio-v1",
                    "media",
                    media_kind="audio",
                    mime_type="audio/wav",
                    path="media/audio-v1.wav",
                ),
                "non-visual",
            ),
            (
                self.artifact(
                    "data-v1",
                    "media",
                    media_kind="data",
                    mime_type="application/json",
                    path="artifacts/data-v1.json",
                ),
                "non-visual",
            ),
            (self.artifact("notes-v1", "document", path="artifacts/notes-v1.md"), "non-visual"),
        )
        for artifact, expected in cases:
            with self.subTest(artifact=artifact):
                self.assertEqual(expected, classify_visual_media_artifact(artifact))

    def test_artifact_classification_rejects_conflicting_metadata(self):
        """Catches a false non-visual label laundering a visual suffix or MIME."""
        cases = (
            self.artifact(
                "clip-v1", "media", media_kind="data", path="media/clip-v1.mp4"
            ),
            self.artifact(
                "clip-v2",
                "media",
                media_kind="video",
                mime_type="image/png",
                path="media/clip-v2.mp4",
            ),
            self.artifact(
                "clip-v3", "scene-video", media_kind="audio", path="media/clip-v3.wav"
            ),
            self.artifact(
                "clip-v4",
                "media",
                media_kind="video",
                mime_type="video/mp4",
                path="media/clip-v4.mov",
            ),
        )
        for artifact in cases:
            with self.subTest(artifact=artifact), self.assertRaisesRegex(
                ValueError, "conflict|does not match"
            ):
                classify_visual_media_artifact(artifact)

    def test_artifact_and_handoff_paths_are_safe_and_exactly_id_bound(self):
        """Catches path traversal and prefix/sub-string Artifact authority confusion."""
        invalid_artifacts = (
            self.artifact(
                "asset-1",
                "scene-video",
                media_kind="video",
                path="../media/asset-1.mp4",
            ),
            self.artifact(
                "asset-1",
                "scene-video",
                media_kind="video",
                path="media/neighbor-asset-1.mp4",
            ),
            self.artifact(
                "asset-1",
                "scene-video",
                media_kind="video",
                path="media/asset-10.mp4",
            ),
            self.artifact(
                "asset-1",
                "scene-video",
                media_kind="video",
                path="media/asset-1-neighbor.mp4",
            ),
        )
        for artifact in invalid_artifacts:
            with self.subTest(artifact=artifact), self.assertRaisesRegex(
                ValueError, "project-contained|Artifact ID"
            ):
                classify_visual_media_artifact(artifact)

        self.assertEqual(
            "video",
            classify_visual_media_artifact(
                self.artifact(
                    "asset-1",
                    "scene-video",
                    media_kind="video",
                    path="media/asset-1.mp4",
                )
            ),
        )
        self.assertEqual(
            "video",
            classify_visual_media_artifact(
                self.artifact(
                    "asset-1",
                    "scene-video",
                    media_kind="video",
                    path="media/asset-1/output.mp4",
                )
            ),
        )

        with self.assertRaisesRegex(ValueError, "undeclared path"):
            compact_visual_media_result(
                self.context(),
                self.handoff(
                    artifact_ids=["asset-1"],
                    paths=["artifacts/media/neighbor-asset-10.json"],
                    review_preview_path="previews/asset-1-low.mp4",
                ),
            )
        exact = self.handoff(
            artifact_ids=["asset-1"],
            paths=["artifacts/media/asset-1.json"],
            review_preview_path="previews/asset-1/low.mp4",
        )
        self.assertEqual(exact, compact_visual_media_result(self.context(), exact))

        with self.assertRaisesRegex(ValueError, "Artifact ID|authority|bound"):
            classify_visual_media_artifact(
                self.artifact(
                    "media",
                    "scene-video",
                    media_kind="video",
                    path="media/unrelated.mp4",
                )
            )

        self.assertEqual(
            "non-visual",
            classify_visual_media_artifact(
                self.artifact(
                    "license-v1",
                    "license-document",
                    path="artifacts/licenses/source.txt",
                )
            ),
        )

    def test_task_classification_uses_capability_output_and_returned_artifacts(self):
        """Catches any runtime classification signal being treated as worker-controlled."""
        non_visual = self.envelope(
            operation="none",
            inputs=["notes-v1"],
            capability="project.manage",
            output_contract="project-state-v1",
        )
        artifacts = {"notes-v1": self.artifact("notes-v1", "document")}
        self.assertEqual("non-visual", classify_visual_media_task(non_visual, artifacts))

        for envelope, produced in (
            ({**non_visual, "capability": "motion.preview"}, ()),
            ({**non_visual, "output_contract": "rendered-video-v1"}, ()),
            ({**non_visual, "output_contract": "review-preview-v1"}, ()),
            (
                non_visual,
                (self.artifact("returned-v1", "scene-video", path="media/returned-v1.mp4"),),
            ),
        ):
            with self.subTest(envelope=envelope, produced=produced):
                self.assertEqual(
                    "visual",
                    classify_visual_media_task(
                        envelope, artifacts, produced_artifacts=produced
                    ),
                )

        with self.assertRaisesRegex(ValueError, "conflict"):
            classify_visual_media_task(
                self.envelope(),
                {
                    "scene-contract-S03-v2": self.artifact(
                        "scene-contract-S03-v2", "scene-contract"
                    )
                },
                produced_artifacts=(
                    self.artifact(
                        "bad-v1",
                        "scene-video",
                        media_kind="data",
                        path="media/bad-v1.mp4",
                    ),
                ),
            )

    def test_visual_artifacts_and_operations_cannot_classify_as_none(self):
        """Catches a none declaration bypassing a visual input."""
        envelope = self.envelope(
            operation="none",
            inputs=["clip-v1"],
            capability="project.manage",
            output_contract="project-state-v1",
        )
        artifacts = {
            "clip-v1": self.artifact(
                "clip-v1",
                "scene-video",
                media_kind="video",
                path="media/clip-v1.mp4",
            )
        }
        with self.assertRaisesRegex(ValueError, "visual media.*none"):
            validate_declared_visual_media_inputs(envelope, artifacts)

    def test_scope_and_visual_input_authority_are_exact(self):
        """Catches neighboring scopes, undeclared visuals, or missing scope artifacts."""
        context = self.context(allowed=["character-lin-v3"])
        envelope = self.envelope(
            inputs=["scene-contract-S03-v2", "character-lin-v3"], context=context
        )
        artifacts = {
            "scene-contract-S03-v2": self.artifact(
                "scene-contract-S03-v2", "scene-contract"
            ),
            "character-lin-v3": self.artifact(
                "character-lin-v3",
                "character-model-sheet",
                status="approved",
                historical=True,
            ),
        }
        validate_declared_visual_media_inputs(envelope, artifacts)

        neighbor = {
            **artifacts,
            "scene-contract-S04-v1": self.artifact(
                "scene-contract-S04-v1", "scene-contract"
            ),
        }
        with self.assertRaisesRegex(PermissionError, "exactly one|neighbor"):
            validate_declared_visual_media_inputs(
                {**envelope, "inputs": [*envelope["inputs"], "scene-contract-S04-v1"]},
                neighbor,
            )

        undeclared = {
            **artifacts,
            "scene-S04-v1": self.artifact(
                "scene-S04-v1", "scene-video", path="media/scene-S04-v1.mp4"
            ),
        }
        with self.assertRaisesRegex(PermissionError, "undeclared visual"):
            validate_declared_visual_media_inputs(
                {**envelope, "inputs": [*envelope["inputs"], "scene-S04-v1"]},
                undeclared,
            )

    def test_review_scope_is_the_exact_bounded_visual_input_set(self):
        """Catches review scope quietly discovering another current visual Artifact."""
        context = self.context(
            scope={"kind": "review-batch", "id": ["asset-1", "asset-2"]},
            allowed=[],
        )
        envelope = self.envelope(
            operation="video-inspect",
            inputs=["asset-1", "asset-2"],
            context=context,
            capability="review.package",
            output_contract="review-package-v1",
        )
        artifacts = {
            "asset-1": self.artifact(
                "asset-1",
                "scene-video",
                path="media/asset-1.mp4",
                historical=False,
            ),
            "asset-2": self.artifact(
                "asset-2",
                "scene-image",
                path="media/asset-2.png",
                historical=False,
            ),
        }
        validate_declared_visual_media_inputs(envelope, artifacts)
        with self.assertRaisesRegex(PermissionError, "review-batch"):
            validate_declared_visual_media_inputs(
                {**envelope, "inputs": ["asset-1"]}, artifacts
            )

        artifacts["notes-v1"] = self.artifact("notes-v1", "document")
        with self.assertRaisesRegex(PermissionError, "review-batch.*exact"):
            validate_declared_visual_media_inputs(
                {**envelope, "inputs": ["asset-1", "asset-2", "notes-v1"]},
                artifacts,
            )

    def test_character_batch_scope_requires_approved_provenance(self):
        """Catches draft character batches granting visual-media scope authority."""
        context = self.context(
            scope={"kind": "character-asset-batch", "id": "characters-main-v2"}
        )
        envelope = self.envelope(
            inputs=["characters-main-v2"],
            context=context,
            capability="visual.preview",
            output_contract="character-preview-v1",
        )
        with self.assertRaisesRegex(PermissionError, "approved"):
            validate_declared_visual_media_inputs(
                envelope,
                {
                    "characters-main-v2": self.artifact(
                        "characters-main-v2",
                        "character-asset-batch",
                        status="draft",
                    )
                },
            )
        validate_declared_visual_media_inputs(
            envelope,
            {
                "characters-main-v2": self.artifact(
                    "characters-main-v2",
                    "character-asset-batch",
                    status="approved",
                )
            },
        )

    def test_visual_history_requires_explicit_origin_and_continuity_is_current_visual(self):
        """Catches missing origin metadata or a non-visual continuity exception."""
        context = self.context(
            continuity_exception={
                "artifact_id": "scene-S02-v3",
                "user_requested": True,
                "reason": "Use this exact current reference.",
            }
        )
        envelope = self.envelope(
            inputs=["scene-contract-S03-v2", "scene-S02-v3"], context=context
        )
        scope = self.artifact("scene-contract-S03-v2", "scene-contract")
        with self.assertRaisesRegex(ValueError, "historical.*explicit|origin"):
            validate_declared_visual_media_inputs(
                envelope,
                {
                    "scene-contract-S03-v2": scope,
                    "scene-S02-v3": self.artifact(
                        "scene-S02-v3",
                        "scene-image",
                        path="media/scene-S02-v3.png",
                    ),
                },
            )

        continuity_context = self.context(
            continuity_exception={
                "artifact_id": "continuity-v1",
                "user_requested": True,
                "reason": "Use this exact current reference.",
            }
        )
        continuity_envelope = self.envelope(
            inputs=["scene-contract-S03-v2", "continuity-v1"],
            context=continuity_context,
        )
        with self.assertRaisesRegex(PermissionError, "continuity.*visual"):
            validate_declared_visual_media_inputs(
                continuity_envelope,
                {
                    "scene-contract-S03-v2": scope,
                    "continuity-v1": self.artifact(
                        "continuity-v1",
                        "document",
                        path="artifacts/continuity-v1.md",
                        historical=False,
                    ),
                },
            )

        validate_declared_visual_media_inputs(
            continuity_envelope,
            {
                "scene-contract-S03-v2": scope,
                "continuity-v1": self.artifact(
                    "continuity-v1",
                    "scene-image",
                    path="media/continuity-v1.png",
                    historical=False,
                ),
            },
        )

    def test_historical_access_is_character_only(self):
        """Catches historical scene media being authorized by an ordinary allowlist."""
        context = self.context(allowed=["history-v1"])
        envelope = self.envelope(
            inputs=["scene-contract-S03-v2", "history-v1"], context=context
        )
        base = {
            "scene-contract-S03-v2": self.artifact(
                "scene-contract-S03-v2", "scene-contract"
            )
        }
        allowed = {
            **base,
            "history-v1": self.artifact(
                "history-v1",
                "character-turnaround",
                historical=True,
                status="approved",
            ),
        }
        validate_declared_visual_media_inputs(envelope, allowed)

        identity_context = self.context(allowed=["identity-v1"])
        identity_envelope = self.envelope(
            inputs=["scene-contract-S03-v2", "identity-v1"],
            context=identity_context,
        )
        validate_declared_visual_media_inputs(
            identity_envelope,
            {
                **base,
                "identity-v1": self.artifact(
                    "identity-v1",
                    "character-identity-metadata",
                    historical=True,
                    status="approved",
                ),
            },
        )

        forbidden = {
            **base,
            "history-v1": self.artifact(
                "history-v1", "storyboard-image", historical=True, status="approved"
            ),
        }
        with self.assertRaisesRegex(PermissionError, "historical.*character"):
            validate_declared_visual_media_inputs(envelope, forbidden)

    def test_plain_allowlist_only_authorizes_independently_approved_character_assets(self):
        """Catches current scene-bound media bypassing an exact continuity exception."""
        scope = self.artifact("scene-contract-S03-v2", "scene-contract")
        for artifact_type, suffix in (("scene-image", "png"), ("scene-video", "mp4")):
            context = self.context(allowed=["scene-S04-v1"])
            envelope = self.envelope(
                inputs=["scene-contract-S03-v2", "scene-S04-v1"],
                context=context,
            )
            artifacts = {
                "scene-contract-S03-v2": scope,
                "scene-S04-v1": self.artifact(
                    "scene-S04-v1",
                    artifact_type,
                    status="approved",
                    historical=False,
                    path=f"media/scene-S04-v1.{suffix}",
                ),
            }
            with self.subTest(artifact_type=artifact_type), self.assertRaisesRegex(
                PermissionError, "continuity exception|character asset"
            ):
                validate_declared_visual_media_inputs(envelope, artifacts)

        character_context = self.context(allowed=["character-lin-v4"])
        validate_declared_visual_media_inputs(
            self.envelope(
                inputs=["scene-contract-S03-v2", "character-lin-v4"],
                context=character_context,
            ),
            {
                "scene-contract-S03-v2": scope,
                "character-lin-v4": self.artifact(
                    "character-lin-v4",
                    "character-model-sheet",
                    status="approved",
                    historical=False,
                    path="media/character-lin-v4.png",
                ),
            },
        )

    def test_one_continuity_exception_cannot_authorize_a_neighbor_through_allowlist(self):
        """Catches one exact exception silently broadening to a second scene asset."""
        context = self.context(
            allowed=["scene-S04-v1"],
            continuity_exception={
                "artifact_id": "scene-S02-v1",
                "user_requested": True,
                "reason": "Use this exact current eyeline reference.",
            },
        )
        envelope = self.envelope(
            inputs=[
                "scene-contract-S03-v2",
                "scene-S02-v1",
                "scene-S04-v1",
            ],
            context=context,
        )
        artifacts = {
            "scene-contract-S03-v2": self.artifact(
                "scene-contract-S03-v2", "scene-contract"
            ),
            "scene-S02-v1": self.artifact(
                "scene-S02-v1",
                "scene-image",
                status="approved",
                historical=False,
                path="media/scene-S02-v1.png",
            ),
            "scene-S04-v1": self.artifact(
                "scene-S04-v1",
                "scene-video",
                status="approved",
                historical=False,
                path="media/scene-S04-v1.mp4",
            ),
        }
        with self.assertRaisesRegex(PermissionError, "continuity exception|character asset"):
            validate_declared_visual_media_inputs(envelope, artifacts)

    def test_classifier_fails_closed_for_named_capture_forms_and_unknown_signals(self):
        """Catches screenshots/captures and future adapters laundering through none."""
        named_types = (
            "screenshot",
            "thumbnail",
            "keyframe",
            "browser-screenshot",
            "browser-capture",
            "app-capture",
            "evidence-capture",
        )
        for artifact_type in named_types:
            artifact_id = f"{artifact_type}-v1"
            with self.subTest(artifact_type=artifact_type):
                self.assertNotEqual(
                    "non-visual",
                    classify_visual_media_artifact(
                        self.artifact(
                            artifact_id,
                            artifact_type,
                            path=f"media/{artifact_id}.png",
                        )
                    ),
                )

        ordinary = (
            self.artifact(
                "license-v1", "document", path="artifacts/licenses/source.txt"
            ),
            self.artifact("table-v1", "data", path="artifacts/tables/source.csv"),
        )
        for artifact in ordinary:
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    "non-visual", classify_visual_media_artifact(artifact)
                )

        ambiguous_artifacts = (
            self.artifact("capture-v1", "capture"),
            self.artifact("future-v1", "future-artifact", media_kind=None),
        )
        for artifact in ambiguous_artifacts:
            with self.subTest(artifact=artifact), self.assertRaisesRegex(
                ValueError, "ambiguous|cannot classify"
            ):
                classify_visual_media_artifact(artifact)

        non_visual = self.envelope(
            operation="none",
            inputs=[],
            capability="project.manage",
            output_contract="project-state-v1",
        )
        for mutation in (
            {**non_visual, "capability": "browser.capture"},
            {**non_visual, "capability": "future.adapter"},
            {**non_visual, "output_contract": "browser-screenshot-v1"},
            {**non_visual, "output_contract": "binary-output-v1"},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(
                (PermissionError, ValueError)
            ):
                validate_declared_visual_media_inputs(mutation, {})

    def test_legacy_generate_and_inspect_records_project_without_mutation(self):
        """Catches legacy v2 records becoming unreadable or being rewritten in place."""
        old_context = {
            "scope_identity": {"kind": "scene-contract", "id": "contract-S01-v1"},
            "allowed_image_artifact_ids": ["character-lin-v2"],
            "allowed_character_pack_ids": ["pack-main-v1"],
            "forbidden_scene_image_access": True,
            "max_review_previews": 1,
            "context_budget": 4096,
        }
        for old_operation in ("generate", "image-inspect"):
            envelope = {
                "constraints": {
                    "image_operation": old_operation,
                    "image_context": old_context,
                }
            }
            before = {**envelope, "constraints": dict(envelope["constraints"])}
            projected = project_legacy_image_context(envelope)
            self.assertEqual(
                ["character-lin-v2"],
                projected["allowed_artifact_ids"],
            )
            self.assertEqual("character-only", projected["historical_access"])
            self.assertEqual(
                "visual", classify_visual_media_task(envelope, artifacts={})
            )
            self.assertEqual(before, envelope)

    def test_compact_handoff_is_closed_bound_and_metadata_only(self):
        """Catches unknown fields, unbound paths, or preview fan-out in a handoff."""
        handoff = self.handoff()
        self.assertEqual(handoff, compact_visual_media_result(self.context(), handoff))

        cases = (
            ({**handoff, "thumbnail": "previews/thumb.png"}, "payload|unknown"),
            ({**handoff, "paths": ["artifacts/media/other.json"]}, "undeclared path"),
            (
                {
                    **handoff,
                    "review_preview_path": ["previews/a.mp4", "previews/b.mp4"],
                },
                "preview",
            ),
            ({**handoff, "paths": ["../outside.mp4"]}, "project-contained"),
        )
        for result, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, message
            ):
                compact_visual_media_result(self.context(), result)

    def test_intrinsic_handoff_validation_is_closed_before_scope_binding(self):
        """Catches callers accepting malformed metadata before scope-specific checks."""
        handoff = self.handoff(
            media={
                "kind": "video",
                "format": "mp4",
                "mime_type": "video/mp4",
                "width": 1080,
                "height": 1920,
                "duration_ms": 12_400,
                "fps": 25,
                "readiness": "review-ready",
                "checksum": "a1b2c3d4",
            }
        )
        self.assertEqual(handoff, validate_compact_visual_media_handoff(handoff))

        cases = (
            ({**handoff, "unknown": "field"}, "unknown top-level field"),
            ({**handoff, "media": {**handoff["media"], "sha256": "a1b2c3d4"}}, "unsupported media field"),
            ({**handoff, "issues": [{"code": "issue-1", "extra": "field"}]}, "unknown issue field"),
            ({**handoff, "checks": ["same", "same"]}, "duplicate checks"),
            ({**handoff, "paths": ["../outside.mp4"]}, "malformed path"),
            ({**handoff, "review_preview_path": ["previews/a.mp4", "previews/b.mp4"]}, "multiple previews"),
            ({**handoff, "media": {**handoff["media"], "checksum": "not hex"}}, "malformed checksum"),
            ({**handoff, "media": {**handoff["media"], "kind": None}}, "null media scalar"),
            ({**handoff, "media": {**handoff["media"], "duration_ms": 12.5}}, "fractional duration"),
            ({**handoff, "paths": ["media/" + "a" * 251]}, "oversized path"),
            ({**handoff, "review_preview_path": "previews/" + "a" * 248}, "oversized preview path"),
        )
        for result, name in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_compact_visual_media_handoff(result)

    def test_intrinsic_handoff_matches_schema_path_and_issue_id_bounds(self):
        """Catches runtime strings accepted outside the handoff schema's ASCII bounds."""
        exact_id = "a" * 128
        exact_path = "media/" + "a" * 250
        exact_preview = "previews/" + "a" * 247
        accepted = self.handoff(
            artifact_ids=[exact_id],
            paths=[exact_path],
            issues=[{"code": exact_id, "artifact_id": exact_id}],
            review_preview_path=exact_preview,
        )
        self.assertEqual(accepted, validate_compact_visual_media_handoff(accepted))

        string_cases = (
            ({"paths": ["media/scene one.mp4"]}, "space artifact path"),
            ({"paths": ["media/场景.mp4"]}, "unicode artifact path"),
            ({"review_preview_path": "previews/scene one.mp4"}, "space preview path"),
            ({"review_preview_path": "previews/场景.mp4"}, "unicode preview path"),
        )
        dict_cases = (
            ({"issues": [{"code": "a" * 129}]}, "oversized issue code"),
            (
                {"issues": [{"code": "issue-1", "artifact_id": "a" * 129}]},
                "oversized issue artifact ID",
            ),
        )
        for overrides, name in string_cases + dict_cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_compact_visual_media_handoff({**self.handoff(), **overrides})

    def test_universal_scrub_rejects_recursive_visual_payload_forms(self):
        """Catches non-visual task results relaying visual payloads or inspection history."""
        png_header = b"\x89PNG\r\n\x1a\n" + b"0" * 88
        encoded = base64.b64encode(png_header).decode("ascii")
        wav_header = b"RIFF" + b"0" * 4 + b"WAVE" + b"0" * 84
        encoded_wav = base64.b64encode(wav_header).decode("ascii")
        cases = (
            ({"checks": [b"raw"]}, "payload"),
            ({"checks": [{"payload": "data:image/png;base64,AAEC"}]}, "payload"),
            ({"warnings": [{"preview_url": "https://example.invalid/a.mp4"}]}, "URL|payload"),
            ({"checks": [{"frames": [[0, 1, 2]]}]}, "frame|payload"),
            ({"checks": [{"thumbnail": "inline"}]}, "thumbnail|payload"),
            ({"checks": ["<video src='data:video/mp4;base64,AAEC'>"]}, "HTML|payload"),
            ({"warnings": [{"prompt_iteration_history": ["one", "two"]}]}, "prompt history"),
            ({"checks": [encoded]}, "Base64|payload"),
            ({"checks": [encoded_wav]}, "Base64|payload"),
            ({"checks": ["x" * 33_000]}, "bounded compact prose|result budget"),
        )
        for result, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, message
            ):
                validate_result_envelope(result)

        validate_result_envelope(
            {
                "checks": ["sha512=" + "0123456789abcdef" * 8],
                "warnings": ["Audio loudness metadata is ready."],
            }
        )

    def test_universal_scrub_uses_token_and_field_semantics_for_ambiguous_text(self):
        """Catches Metadata false positives and context-free short-token decoding."""
        cases = (
            {"checks": ["data:text/plain,hidden"]},
            {"checks": ["<svg viewBox='0 0 1 1'></svg>"]},
            {"checks": ["<object data='asset'></object>"]},
            {"checks": ["<embed src='asset'>"]},
            {"checks": [{"payload": "SUQz"}]},
        )
        for result in cases:
            with self.subTest(result=result), self.assertRaisesRegex(
                ValueError, "data URL|HTML|Base64|payload"
            ):
                validate_result_envelope(result)

        validate_result_envelope(
            {
                "artifact_ids": ["SUQz"],
                "checks": ["SUQz"],
                "issues": [{"code": "SUQz"}],
                "summary": "SUQz",
                "warnings": ["Metadata: value, next item."],
            }
        )

    def test_universal_scrub_rejects_all_remote_schemes_without_decoding_base64(self):
        """Catches non-HTTP URLs and structural Base64 bypassing the common scrub."""
        for remote in (
            "ftp://example.invalid/asset.bin",
            "s3://bucket/asset.png",
            "file://host/share/asset.mov",
            "//cdn.example.invalid/asset.webp",
        ):
            with self.subTest(remote=remote), self.assertRaisesRegex(
                ValueError, "URL|scheme"
            ):
                validate_result_envelope({"warnings": [remote]})

        canonical_binary_like = (
            "AAECAwQFBgcICQoLDA0ODxAREhMUFRYX"
            "GBkaGxwdHh8gISIjJCUmJygpKissLS4v"
        )
        with patch(
            "base64.b64decode",
            side_effect=AssertionError("scrubber must never decode Base64"),
        ):
            with self.assertRaisesRegex(ValueError, "Base64|binary"):
                validate_result_envelope({"checks": [canonical_binary_like]})

        validate_result_envelope(
            {
                "artifact_ids": ["asset-SUQz-v1"],
                "checks": ["sha256=" + "0123456789abcdef" * 4],
                "summary": "Local project metadata is ready.",
            }
        )

    def test_universal_scrub_does_not_exempt_arbitrary_id_fields_from_base64(self):
        """Catches payload-shaped data escaping through a generic ID field name."""
        canonical_binary_like = (
            "AAECAwQFBgcICQoLDA0ODxAREhMUFRYX"
            "GBkaGxwdHh8gISIjJCUmJygpKissLS4v"
        )

        for key in ("opaque_id", "opaque_ids"):
            with self.subTest(key=key), self.assertRaisesRegex(
                ValueError, "Base64|binary"
            ):
                validate_result_envelope({key: canonical_binary_like})

        validate_result_envelope({"artifact_id": canonical_binary_like})

    def test_universal_scrub_rejects_scheme_encoding_and_alias_bypasses(self):
        """Catches reviewed URI, Base64URL, repeated-token, and alias bypasses."""
        cases = (
            {"source_ref": "gopher:opaque-resource"},
            {"source_ref": "mailto:owner@example.invalid"},
            {"source_ref": "urn:example:asset"},
            {"provenance": "gopher:opaque-resource"},
            {
                "opaque": (
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "abcdefghijklmnopqrstuvwxyz0123456789-_"
                )
            },
            {"opaque": "A" * 64},
            {"checksum_backup": "A" * 64},
            {"sample_values": [0, 1, 2, 3]},
            {"pixel_cache": [[0, 1], [2, 3]]},
            {"frame_backup": [0, 1, 2]},
            {"prompt_records": ["secret instruction"]},
            {"assistant_messages": ["secret response"]},
            {"generation_trace": ["internal iteration"]},
        )
        with patch(
            "base64.b64decode",
            side_effect=AssertionError("scrubber must never decode Base64"),
        ):
            for result in cases:
                with self.subTest(result=result), self.assertRaises(ValueError):
                    validate_result_envelope(result)

        validate_result_envelope(
            {
                "artifact_ids": ["asset-SUQz-v1"],
                "checks": ["adapter-selected:chatcut"],
                "checksum": "0123456789abcdef",
            }
        )

    def test_handoff_mime_type_matches_its_declared_media_kind(self):
        """Catches schema-compatible MIME metadata contradicting runtime media kind."""
        for kind, mime_type in (("image", "image/png"), ("video", "video/mp4")):
            handoff = self.handoff(media={"kind": kind, "mime_type": mime_type})
            with self.subTest(kind=kind, accepted=True):
                self.assertEqual(handoff, validate_compact_visual_media_handoff(handoff))

            mismatched = self.handoff(
                media={
                    "kind": kind,
                    "mime_type": "video/mp4" if kind == "image" else "image/png",
                }
            )
            with self.subTest(kind=kind, accepted=False), self.assertRaisesRegex(
                ValueError, "mime_type|kind"
            ):
                validate_compact_visual_media_handoff(mismatched)

    def test_output_operations_require_visual_artifact_and_exact_handoff_kind(self):
        """Catches successful producers returning only reports or an untyped handoff."""
        report = {
            "artifact_id": "report-v1",
            "type": "report",
            "path": "artifacts/report-v1.json",
        }
        image = {
            "artifact_id": "image-v1",
            "type": "image",
            "media_kind": "image",
            "path": "media/image-v1.png",
        }
        with self.assertRaisesRegex(ValueError, "at least one|visual output"):
            validate_visual_media_operation_outputs(
                "image-generate", [report], {"media": {"kind": "image"}}, status="succeeded"
            )
        with self.assertRaisesRegex(ValueError, "media.kind|handoff"):
            validate_visual_media_operation_outputs(
                "image-generate", [image], {"media": {}}, status="succeeded"
            )

        validate_visual_media_operation_outputs(
            "image-generate",
            [image],
            {"media": {"kind": "image"}},
            status="succeeded",
        )

    def test_inspect_operations_are_report_only(self):
        """Catches inspection silently minting new visual output artifacts."""
        report = {
            "artifact_id": "report-v1",
            "type": "report",
            "path": "artifacts/report-v1.json",
        }
        image = {
            "artifact_id": "image-v1",
            "type": "image",
            "media_kind": "image",
            "path": "media/image-v1.png",
        }
        validate_visual_media_operation_outputs(
            "image-inspect", [report], {"media": {}}, status="succeeded"
        )
        for operation, incompatible_mime in (
            ("image-inspect", "video/mp4"),
            ("video-inspect", "image/png"),
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                ValueError, "mime_type|handoff"
            ):
                validate_visual_media_operation_outputs(
                    operation,
                    [report],
                    {"media": {"mime_type": incompatible_mime}},
                    status="succeeded",
                )
        with self.assertRaisesRegex(ValueError, "report-only"):
            validate_visual_media_operation_outputs(
                "image-inspect",
                [image],
                {"media": {"kind": "image"}},
                status="succeeded",
            )

    def test_operation_and_output_contract_kinds_are_compatible(self):
        """Catches image/video operations declaring an output of the opposite kind."""
        artifacts = {
            "scene-contract-S03-v2": self.artifact(
                "scene-contract-S03-v2", "scene-contract"
            )
        }
        incompatible = (
            ("image-generate", "rendered-video-v1"),
            ("image-edit", "scene-video-v1"),
            ("image-inspect", "video-report-v1"),
            ("video-generate", "scene-image-v1"),
            ("video-edit", "image-preview-v1"),
            ("video-render", "thumbnail-image-v1"),
            ("video-inspect", "image-report-v1"),
            ("frame-extract", "scene-video-v1"),
            ("contact-sheet", "rendered-video-v1"),
        )
        for operation, output_contract in incompatible:
            with self.subTest(operation=operation), self.assertRaisesRegex(
                ValueError, "operation|output.*kind|compatible"
            ):
                validate_declared_visual_media_inputs(
                    self.envelope(
                        operation=operation, output_contract=output_contract
                    ),
                    artifacts,
                )

        for operation in ("frame-extract", "contact-sheet"):
            with self.subTest(operation=operation):
                validate_declared_visual_media_inputs(
                    self.envelope(operation=operation, output_contract="scene-image-v1"),
                    artifacts,
                )

    def test_visual_result_envelope_applies_context_budget_and_closed_handoff(self):
        """Catches a valid-looking handoff bypassing recursive or declared-budget checks."""
        result = {
            "task_id": "visual-task-1",
            "status": "waiting_user",
            "inputs": ["scene-contract-S03-v2"],
            "artifacts": ["media-S03-v4"],
            "checks": ["render-complete"],
            "warnings": [],
            "worker_id": "worker-1",
            "claim_token": "claim-1",
            "visual_media_handoff": self.handoff(),
        }
        validate_visual_media_result_envelope(self.context(), result)

        with self.assertRaisesRegex(ValueError, "context budget"):
            validate_visual_media_result_envelope(
                self.context(context_budget_bytes=300), result
            )
        with self.assertRaisesRegex(ValueError, "visual_media_handoff"):
            validate_visual_media_result_envelope(
                self.context(),
                {
                    **result,
                    "visual_media_handoff": {**self.handoff(), "extra": True},
                },
            )


if __name__ == "__main__":
    unittest.main()

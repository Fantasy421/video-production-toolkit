import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.validate_package import validate_package


ROOT = Path(__file__).parents[1]


class PackageTests(unittest.TestCase):
    def test_required_plugin_entrypoints_exist(self):
        self.assertEqual([], validate_package(ROOT))

    def test_video_director_declares_required_routing_constraints(self):
        skill = (ROOT / "skills/video-director/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Chinese talking-head and tutorial", skill)
        self.assertIn("artifact IDs, paths, summaries, and contract results", skill)
        self.assertIn("cannot override routing or approval policy", skill)

    def test_voiceover_producer_entrypoint_is_required(self):
        """Catches an installable package that omits the voice-ready child skill."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            (package / "skills/voiceover-producer/SKILL.md").unlink()

            self.assertIn(
                "missing:skills/voiceover-producer/SKILL.md",
                validate_package(package),
            )

    def test_image_context_schema_is_required(self):
        """Catches a package whose image workers reference a missing contract."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            (package / "references/schemas/image-task-context.schema.json").unlink()

            self.assertIn(
                "missing:references/schemas/image-task-context.schema.json",
                validate_package(package),
            )

    def test_manifest_declares_the_host_plugin_name_and_skill_directory(self):
        """Catches a marketplace entry whose manifest cannot expose bundled skills."""
        with TemporaryDirectory() as folder:
            package = Path(folder)
            shutil.copytree(
                ROOT,
                package,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
            manifest_path = package / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["name"] = "Video Production Toolkit"
            manifest.pop("skills", None)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual(
                ["invalid:plugin-name", "invalid:skills-path"],
                validate_package(package),
            )

    def test_manifest_requires_the_voice_ready_patch_release(self):
        """Catches host cache reuse under the pre-fix package version."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            manifest_path = package / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = "0.1.2"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertIn("invalid:plugin-version", validate_package(package))

    def test_release_runtime_schema_policy_and_skill_files_are_required(self):
        """Catches a valid-looking archive that omits a final-fix contract owner."""
        required = (
            "scripts/build_review_pack.py",
            "scripts/toolkit/adapters.py",
            "scripts/toolkit/image_context.py",
            "scripts/toolkit/orchestrator.py",
            "scripts/toolkit/project_state.py",
            "scripts/toolkit/tasks.py",
            "scripts/toolkit/validation.py",
            "scripts/toolkit/voice.py",
            "scripts/toolkit/voice_tasks.py",
            "references/policies/decision-gates.md",
            "references/policies/invalidation.json",
            "references/policies/project-assets.md",
            "references/schemas/event.schema.json",
            "references/schemas/project.schema.json",
            "references/schemas/task-envelope.schema.json",
            "references/schemas/task-result.schema.json",
            "registries/adapters/chatcut.json",
            "skills/scene-producer/SKILL.md",
            "skills/structural-validator/SKILL.md",
            "skills/timeline-assembler/SKILL.md",
        )
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            for relative in required:
                (package / relative).unlink()

            errors = validate_package(package)

            for relative in required:
                self.assertIn(f"missing:{relative}", errors)

    def test_chatcut_voice_media_and_probe_contract_is_exact(self):
        """Catches packaged formats drifting beyond the verifier's real probes."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            manifest_path = package / "registries/adapters/chatcut.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["accepted_voice_media_formats"] = ["wav", "ogg"]
            manifest["duration_probe"] = {"wav": "metadata-only"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:chatcut-voice-formats", errors)
            self.assertIn("invalid:chatcut-duration-probe", errors)

    def test_image_context_release_bounds_and_scope_are_exact(self):
        """Catches a shipped schema broadening one isolated image task."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            schema_path = package / "references/schemas/image-task-context.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["required"].remove("scope_identity")
            schema["$defs"]["uniqueSafeImageIds"]["maxItems"] = 17
            schema["$defs"]["uniqueSafePackIds"]["maxItems"] = 9
            schema["properties"]["context_budget"]["maximum"] = 65536
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:image-scope-identity", errors)
            self.assertIn("invalid:image-artifact-limit", errors)
            self.assertIn("invalid:image-pack-limit", errors)
            self.assertIn("invalid:image-context-budget", errors)

    def test_voice_schemas_keep_provenance_and_mode_specific_lineage(self):
        """Catches a distributable schema accepting anonymous or ambiguous audio."""
        with TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
            source_path = package / "references/schemas/voice-source-decision.schema.json"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["required"].remove("decision_provenance")
            source_path.write_text(json.dumps(source), encoding="utf-8")
            profile_path = package / "references/schemas/voice-profile.schema.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["required"].remove("consent_provenance")
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            voiceover_path = package / "references/schemas/voiceover.schema.json"
            voiceover = json.loads(voiceover_path.read_text(encoding="utf-8"))
            voiceover["required"].remove("provenance")
            voiceover["allOf"] = []
            voiceover_path.write_text(json.dumps(voiceover), encoding="utf-8")

            errors = validate_package(package)

            self.assertIn("invalid:voice-source-provenance", errors)
            self.assertIn("invalid:voice-profile-provenance", errors)
            self.assertIn("invalid:voiceover-provenance", errors)
            self.assertIn("invalid:voiceover-mode-lineage", errors)

    def test_runtime_project_and_review_pack_templates_are_required(self):
        """Catches a plugin package that cannot initialize or review a project."""
        for relative in (
            "assets/project-template/project.json",
            "assets/project-template/review-pack/index.html",
        ):
            with self.subTest(relative=relative), TemporaryDirectory() as folder:
                package = Path(folder) / "package"
                shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
                (package / relative).unlink()

                self.assertIn(f"missing:{relative}", validate_package(package))

    def test_project_template_uses_the_current_project_schema_version(self):
        """Catches new projects starting from the legacy pre-voice contract."""
        template = json.loads(
            (ROOT / "assets/project-template/project.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            {
                "schema_version": 2,
                "project_id": "<project-id>",
                "workflow": "knowledge-video",
                "phase": "initialized",
            },
            template,
        )

    def test_style_and_layout_pack_assets_are_required(self):
        """Catches installation omitting schemas, manifests, or human previews."""
        required_pack_assets = (
            "references/schemas/style-pack.schema.json",
            "references/schemas/layout-pack.schema.json",
            "registries/styles/editorial-clean/v1/manifest.json",
            "registries/layouts/talking-head-left-explainer-right/v1/manifest.json",
            "previews/styles/editorial-clean-v1.html",
            "previews/layouts/talking-head-left-explainer-right-v1.html",
        )
        for relative in required_pack_assets:
            with self.subTest(relative=relative), TemporaryDirectory() as folder:
                package = Path(folder) / "package"
                shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns(".git"))
                (package / relative).unlink()

                self.assertIn(f"missing:{relative}", validate_package(package))


if __name__ == "__main__":
    unittest.main()

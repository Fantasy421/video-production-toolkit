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

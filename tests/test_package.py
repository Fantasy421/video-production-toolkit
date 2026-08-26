import json
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

    def test_manifest_declares_the_host_plugin_name_and_skill_directory(self):
        """Catches a marketplace entry whose manifest cannot expose bundled skills."""
        with TemporaryDirectory() as folder:
            package = Path(folder)
            for relative in (
                ".codex-plugin/plugin.json",
                "agents/openai.yaml",
                "skills/video-director/SKILL.md",
            ):
                destination = package / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            manifest_path = package / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["name"] = "Video Production Toolkit"
            manifest.pop("skills", None)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual(
                ["invalid:plugin-name", "invalid:skills-path"],
                validate_package(package),
            )


if __name__ == "__main__":
    unittest.main()

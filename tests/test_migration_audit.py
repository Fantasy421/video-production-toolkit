import json
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.migration_audit import DISPOSITIONS, audit_legacy, write_migration_report


class MigrationAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.legacy = self.root / "arbitrary-old-skill"
        self.new = self.root / "replacement-plugin"
        (self.legacy / "scripts").mkdir(parents=True)
        self.new.mkdir()

    def tearDown(self):
        self.folder.cleanup()

    def create(self, root, relative, contents="fixture"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def populate_complete_inventory(self):
        entries = []
        for relative, disposition in DISPOSITIONS.items():
            contents = "#!/usr/bin/env python3\n" if relative.startswith("scripts/") else "fixture"
            legacy_path = self.create(self.legacy, relative, contents)
            entries.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(legacy_path.read_bytes()).hexdigest(),
                }
            )
            for owner in disposition["owners"]:
                self.create(self.new, owner)
        self.create(
            self.new,
            "references/policies/knowledge-video-visual-director-baseline.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "legacy_skill": "knowledge-video-visual-director",
                    "files": sorted(entries, key=lambda item: item["path"]),
                }
            ),
        )

    def test_known_validator_has_disposition_and_existing_owner(self):
        """Catches a migrated executable disappearing from the explicit inventory."""
        self.populate_complete_inventory()

        result = audit_legacy(self.legacy, self.new)
        item = next(
            item
            for item in result["inventory"]
            if item["legacy_path"] == "scripts/validate_coverage.py"
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["schema_version"])
        self.assertEqual([], result["undisposed_executables"])
        self.assertEqual("migrated", item["category"])
        self.assertEqual("migrated", item["disposition"])
        self.assertEqual(["scripts/toolkit/coverage.py"], item["owners"])
        self.assertEqual(item["expected_sha256"], item["sha256"])
        self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")

    def test_missing_expected_legacy_file_blocks_audit(self):
        """Catches a partial or already-damaged legacy tree satisfying the retirement gate."""
        self.populate_complete_inventory()
        missing = self.legacy / "scripts/validate_coverage.py"
        missing.unlink()

        result = audit_legacy(self.legacy, self.new)

        self.assertFalse(result["ok"])
        self.assertEqual(
            ["scripts/validate_coverage.py"], result["missing_legacy_files"]
        )

    def test_same_legacy_path_with_changed_content_blocks_audit(self):
        """Catches filename-only disposition checks accepting unreviewed source changes."""
        self.populate_complete_inventory()
        changed = self.legacy / "scripts/validate_coverage.py"
        changed.write_text("#!/usr/bin/env python3\n# changed after audit\n", encoding="utf-8")

        result = audit_legacy(self.legacy, self.new)

        self.assertFalse(result["ok"])
        self.assertEqual(
            ["scripts/validate_coverage.py"],
            [item["legacy_path"] for item in result["content_mismatches"]],
        )

    def test_rejected_legacy_asset_is_explicitly_categorized_as_retired(self):
        """Catches intentionally discarded material disappearing into a generic disposition."""
        self.populate_complete_inventory()

        result = audit_legacy(self.legacy, self.new)
        item = next(
            item
            for item in result["inventory"]
            if item["legacy_path"] == "assets/character-model-sheet.png"
        )

        self.assertEqual("retired", item["category"])
        self.assertEqual(1, result["summary"]["categories"]["retired"])

    def test_unknown_executable_validator_blocks_audit(self):
        """Catches a newly added legacy validator being silently omitted."""
        self.populate_complete_inventory()
        self.create(self.legacy, "scripts/validate_future.py", "#!/usr/bin/env python3\n")

        result = audit_legacy(self.legacy, self.new)

        self.assertFalse(result["ok"])
        self.assertEqual(["scripts/validate_future.py"], result["undisposed_executables"])
        self.assertEqual(["scripts/validate_future.py"], result["undisposed_files"])

    def test_missing_new_owner_blocks_audit(self):
        """Catches paper migrations whose declared replacement does not exist."""
        self.populate_complete_inventory()
        (self.new / "scripts/toolkit/coverage.py").unlink()

        result = audit_legacy(self.legacy, self.new)

        self.assertFalse(result["ok"])
        self.assertEqual(
            [
                {
                    "legacy_path": "scripts/validate_coverage.py",
                    "owner": "scripts/toolkit/coverage.py",
                }
            ],
            result["missing_owners"],
        )

    def test_runtime_cache_files_do_not_change_the_inventory(self):
        """Catches py_compile side effects making a verified audit non-repeatable."""
        self.populate_complete_inventory()
        self.create(self.legacy, "scripts/__pycache__/validate_coverage.cpython-39.pyc")

        result = audit_legacy(self.legacy, self.new)

        self.assertEqual(len(DISPOSITIONS), result["summary"]["legacy_files"])
        self.assertTrue(result["ok"])

    def test_report_is_published_below_new_root(self):
        """Catches reporting to a process-relative or legacy-owned path."""
        self.populate_complete_inventory()
        result = audit_legacy(self.legacy, self.new)

        path = write_migration_report(self.new, result)

        self.assertEqual(
            self.new.resolve() / "docs/migration/knowledge-video-visual-director.md", path
        )
        report = path.read_text(encoding="utf-8")
        self.assertIn("Undisposed executable scripts: 0", report)
        self.assertIn("Content hash mismatches: 0", report)
        self.assertIn("Source SHA-256", report)
        self.assertIn("manifest-versioned host cache", report)
        self.assertIn("external Skill discovery", report)
        self.assertIn("ChatCut base Skill", report)
        self.assertIn("voice.synthesize", report)
        self.assertIn("voice.time", report)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_report_refuses_a_symlinked_output_directory(self):
        """Catches an apparently local report path escaping through a symlink."""
        self.populate_complete_inventory()
        external = self.root / "external"
        external.mkdir()
        (self.new / "docs").mkdir()
        os.symlink(external, self.new / "docs/migration")

        with self.assertRaisesRegex(ValueError, "inside the new root"):
            write_migration_report(self.new, audit_legacy(self.legacy, self.new))

        self.assertEqual([], list(external.iterdir()))

    def test_audit_result_is_json_serializable(self):
        """Catches Path objects leaking across the CLI result boundary."""
        self.populate_complete_inventory()

        rendered = json.dumps(audit_legacy(self.legacy, self.new), ensure_ascii=False)

        self.assertIn('"ok": true', rendered)


if __name__ == "__main__":
    unittest.main()

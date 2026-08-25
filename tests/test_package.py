import unittest
from pathlib import Path

from scripts.validate_package import validate_package


ROOT = Path(__file__).parents[1]


class PackageTests(unittest.TestCase):
    def test_required_plugin_entrypoints_exist(self):
        self.assertEqual([], validate_package(ROOT))


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the tracked environment-file guard (stdlib only)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_tracked_env_files import find_disallowed_paths, is_disallowed_environment_file


class TrackedEnvironmentFileGuardTests(unittest.TestCase):
    def test_rejects_tracked_local_env_files(self):
        paths = [
            ".env",
            ".env.local",
            ".env.production",
            ".env.windows",
            "backend/.env.test",
            "nested/config/.env.staging",
        ]
        self.assertEqual(find_disallowed_paths(paths), sorted(paths))

    def test_allows_documented_example_templates(self):
        paths = [
            ".env.example",
            ".env.windows.example",
            ".env.production.example",
            "backend/config/.env.test.example",
            "README.md",
            "config.env",
        ]
        self.assertEqual(find_disallowed_paths(paths), [])

    def test_handles_paths_with_newlines(self):
        path = "nested/.env.production\nother-file"
        self.assertTrue(is_disallowed_environment_file(path))

    def test_ignores_empty_entries_from_nul_delimited_path_lists(self):
        self.assertEqual(find_disallowed_paths(["", ".env.example", "main.py"]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

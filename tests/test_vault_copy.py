import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/vault-copy.py"
spec = importlib.util.spec_from_file_location("vault_copy", SCRIPT)
vault_copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vault_copy)


class VaultCopyTest(unittest.TestCase):
    def test_migrates_links_and_preserves_both_sides(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "project"
            vault = Path(temporary) / "vault"
            (source / "docs").mkdir(parents=True)
            vault.mkdir()
            original = source / "docs/plan.md"
            original.write_text("first")
            (vault / "docs").symlink_to(source / "docs", target_is_directory=True)

            vault_copy.sync(source, vault)
            copy = vault / "docs/plan.md"
            self.assertFalse((vault / "docs").is_symlink())
            self.assertEqual(copy.read_text(), "first")
            original.write_text("second")
            vault_copy.sync(source, vault)
            self.assertEqual(copy.read_text(), "second")

            copy.write_text("vault edit")
            vault_copy.sync(source, vault)
            self.assertEqual(copy.read_text(), "vault edit")
            self.assertEqual(original.read_text(), "second")
            original.write_text("third")
            vault_copy.sync(source, vault)
            self.assertEqual(copy.read_text(), "vault edit")
            self.assertEqual(len(list((vault / "docs").glob("plan.incoming-*.md"))), 1)
            self.assertEqual(original.read_text(), "third")
            original.unlink()
            vault_copy.sync(source, vault)
            self.assertEqual(copy.read_text(), "vault edit")


if __name__ == "__main__":
    unittest.main()

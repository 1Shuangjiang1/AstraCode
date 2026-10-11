import tempfile
import unittest
from pathlib import Path

from agent_harness.change_tracking import RunTransaction


class ChangeTrackingTests(unittest.TestCase):
    def test_diff_tracks_create_modify_delete_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; root.mkdir()
            storage = Path(temp) / "state"
            (root / "modify.py").write_text("a = 1\n", encoding="utf-8")
            (root / "delete.md").write_text("old\n", encoding="utf-8")
            tx = RunTransaction(storage, "run-1")
            tx.begin(root)
            (root / "modify.py").write_text("a = 2\nprint(a)\n", encoding="utf-8")
            (root / "delete.md").unlink()
            (root / "new.txt").write_text("new\n", encoding="utf-8")
            result = tx.finish()
            self.assertEqual({item["status"] for item in result["files"]}, {"created", "modified", "deleted"})
            self.assertGreater(result["totals"]["additions"], 0)
            rolled = tx.rollback()
            self.assertTrue(rolled["ok"])
            self.assertEqual((root / "modify.py").read_text(encoding="utf-8"), "a = 1\n")
            self.assertTrue((root / "delete.md").exists())
            self.assertFalse((root / "new.txt").exists())

    def test_rollback_refuses_to_overwrite_external_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; root.mkdir()
            target = root / "a.txt"; target.write_text("before", encoding="utf-8")
            tx = RunTransaction(Path(temp) / "state", "run-2"); tx.begin(root)
            target.write_text("agent", encoding="utf-8"); tx.finish()
            target.write_text("external", encoding="utf-8")
            result = tx.rollback()
            self.assertFalse(result["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "external")


if __name__ == "__main__":
    unittest.main()

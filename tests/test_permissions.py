import tempfile
import unittest
from pathlib import Path

from agent_harness.permissions import PermissionEngine, Risk


class PermissionEngineTests(unittest.TestCase):
    def test_safe_mode_blocks_high_risk_but_allows_normal_read(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = PermissionEngine(Path(temp), "safe")
            self.assertTrue(engine.authorize("read_file", {"path": "notes.md"}).allowed)
            decision = engine.authorize("bash", {"command": "rm notes.md"})
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.risk, Risk.HIGH)

    def test_approval_mode_can_cache_similar_approval(self):
        prompts = []
        def approve(tool, args, decision, actor):
            prompts.append((tool, actor))
            return "a"
        with tempfile.TemporaryDirectory() as temp:
            engine = PermissionEngine(Path(temp), "approval", prompt=approve)
            self.assertTrue(engine.authorize("bash", {"command": "rm one.txt"}).allowed)
            second = engine.authorize("bash", {"command": "rm two.txt"})
            self.assertTrue(second.allowed)
            self.assertTrue(second.cached)
            self.assertEqual(len(prompts), 1)

    def test_single_file_delete_is_smartly_scoped_by_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            args = {"path": "generated.py"}
            self.assertFalse(PermissionEngine(Path(temp), "safe").authorize("delete_file", args).allowed)
            decision = PermissionEngine(Path(temp), "approval").authorize("delete_file", args)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.risk, Risk.MEDIUM)

    def test_chat_directory_change_requires_approval_then_becomes_boundary(self):
        with tempfile.TemporaryDirectory() as initial, tempfile.TemporaryDirectory() as target:
            prompts = []
            engine = PermissionEngine(
                Path(initial), "approval", prompt=lambda *args: prompts.append(args) or "y",
                dynamic_workspace=True,
            )
            decision = engine.authorize("set_working_directory", {"path": target})
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.risk, Risk.HIGH)
            self.assertEqual(len(prompts), 1)
            engine.set_workdir(Path(target))
            self.assertEqual(engine.assess("write_file", {"path": "inside.txt"}).risk, Risk.MEDIUM)

    def test_full_access_skips_high_risk_prompt_but_not_critical_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = PermissionEngine(Path(temp), "full_access")
            self.assertTrue(engine.authorize("bash", {"command": "rm one.txt"}).allowed)
            critical = engine.authorize("bash", {"command": "shutdown /s"})
            self.assertFalse(critical.allowed)
            self.assertEqual(critical.risk, Risk.CRITICAL)

    def test_mode_can_be_changed_at_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = PermissionEngine(Path(temp), "approval")
            engine.set_mode("full")
            self.assertEqual(engine.mode, "full_access")
            with self.assertRaises(ValueError):
                engine.set_mode("unknown")


if __name__ == "__main__":
    unittest.main()

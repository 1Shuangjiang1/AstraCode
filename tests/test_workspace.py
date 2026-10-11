import tempfile
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_harness.concurrency import WorkspaceCoordinator
from agent_harness.workspace import WorkspaceTools


class WorkspaceToolsTests(unittest.TestCase):
    def test_bash_tolerates_none_stdout_or_stderr(self):
        class FakeProcess:
            returncode = 0
            pid = 999999

            def communicate(self, timeout=None):
                return None, None

            def poll(self):
                return 0

        with tempfile.TemporaryDirectory() as temp, patch("subprocess.Popen", return_value=FakeProcess()) as popen:
            tools = WorkspaceTools(Path(temp), WorkspaceCoordinator())
            self.assertEqual(tools.bash("anything"), "(no output)")
            self.assertIs(popen.call_args.kwargs["stdin"], __import__("subprocess").DEVNULL)

    def test_running_command_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as temp:
            cancelled = threading.Event()
            tools = WorkspaceTools(Path(temp), WorkspaceCoordinator(), cancelled)
            result = []
            command = f'"{sys.executable}" -c "import time; time.sleep(20)"'
            worker = threading.Thread(target=lambda: result.append(tools.bash(command, timeout=30)))
            started = time.monotonic()
            worker.start()
            time.sleep(0.25)
            cancelled.set()
            tools.cancel_active()
            worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - started, 4)
            self.assertTrue(result and result[0].startswith("Error: Cancelled"))

    def test_nonzero_exit_is_reported_as_error(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = WorkspaceTools(Path(temp), WorkspaceCoordinator())
            result = tools.bash(f'"{sys.executable}" -c "raise SystemExit(7)"')
            self.assertTrue(result.startswith("Error: Command exited with code 7"))

    def test_edit_requires_unique_match(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.txt"
            path.write_text("same same", encoding="utf-8")
            tools = WorkspaceTools(Path(temp), WorkspaceCoordinator())
            result = tools.edit("sample.txt", "same", "new")
            self.assertIn("appears 2 times", result)
            self.assertEqual(path.read_text(encoding="utf-8"), "same same")

    def test_workspace_escape_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = WorkspaceTools(Path(temp), WorkspaceCoordinator())
            self.assertTrue(tools.read("../outside.txt").startswith("Error:"))

    def test_dedicated_crud_helpers_treat_absence_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = WorkspaceTools(Path(temp), WorkspaceCoordinator())
            self.assertEqual(tools.list_directory(), "(empty directory)")
            self.assertTrue(tools.write("nested/sample.txt", "hello").startswith("Wrote"))
            self.assertEqual(tools.path_exists("nested/sample.txt"), "exists (file): nested/sample.txt")
            self.assertIn("sample.txt", tools.list_directory("nested"))
            self.assertEqual(tools.delete_file("nested/sample.txt"), "Deleted file: nested/sample.txt")
            self.assertEqual(tools.path_exists("nested/sample.txt"), "absent: nested/sample.txt")
            self.assertEqual(tools.delete_file("nested/sample.txt"), "Already absent: nested/sample.txt")

    def test_chat_workspace_requires_directory_selection(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as target:
            tools = WorkspaceTools(
                Path(temp), WorkspaceCoordinator(), unrestricted=True,
                require_directory_selection=True,
            )
            self.assertIn("no active directory", tools.bash("python -c \"print(1)\""))
            self.assertTrue(tools.read("anything.txt").startswith("Error:"))
            self.assertEqual(tools.set_working_directory(target), f"Working directory: {Path(target).resolve()}")
            self.assertEqual(tools.write("ready.txt", "ok"), "Wrote 2 bytes to ready.txt")
            self.assertEqual(Path(target, "ready.txt").read_text(encoding="utf-8"), "ok")


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_harness.settings import Settings, user_config_path
from tests.helpers import make_settings


class SettingsTests(unittest.TestCase):
    def test_installed_app_config_path_is_user_local_and_persistent(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}, clear=False):
            self.assertEqual(user_config_path(), Path(temp).resolve() / "AstraCode" / "config.env")

    def test_optional_state_root_keeps_runtime_metadata_out_of_project(self):
        with tempfile.TemporaryDirectory() as temp:
            # Windows CI may provide a short 8.3 temp path; compare canonical paths.
            root = Path(temp).resolve()
            settings = make_settings(root / "project", state_root=root / "app-data")
            self.assertEqual(settings.task_dir, root / "app-data" / ".tasks")
            self.assertEqual(settings.team_dir, root / "app-data" / ".team")
            self.assertEqual(settings.transcript_dir, root / "app-data" / ".transcripts")
            self.assertEqual(settings.memory_dir, root / "app-data" / ".memory")
            self.assertEqual(settings.skill_dir, root / "project" / "skills")
            self.assertEqual(settings.skill_dirs[-1], root / "project" / "skills")
            self.assertTrue((settings.skill_dirs[0] / "code-review" / "SKILL.md").is_file())

    def test_explicit_process_flags_override_dotenv(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            (workdir / ".env").write_text(
                "S_FULL_FAKE_CLIENT=0\nS_FULL_PERMISSION_MODE=approval\nS_FULL_MODEL=from-file\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "S_FULL_FAKE_CLIENT": "1",
                "S_FULL_PERMISSION_MODE": "safe",
                "S_FULL_MODEL": "deepseek-v4-flash",
            }, clear=False):
                settings = Settings.from_env(workdir)
            self.assertTrue(settings.fake_client)
            self.assertEqual(settings.permission_mode, "safe")
            self.assertEqual(settings.model, "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()

import importlib.util
import tempfile
import unittest
from pathlib import Path


_path = Path(__file__).resolve().parent.parent / "packaging" / "export_public.py"
_spec = importlib.util.spec_from_file_location("public_export", _path)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


class PublicExportTests(unittest.TestCase):
    def test_runtime_credentials_and_builds_excluded(self):
        for name in (".env", ".env.local", ".memory/user.md", "bubble_sort.py",
                     "desktop/node_modules/pkg/index.js", "desktop/src-tauri/target/test.exe",
                     "docs/project_docs/career/INTERVIEW_GUIDE_0.8.1.md"):
            with self.subTest(name=name):
                self.assertFalse(export.permitted(Path(name)))

    def test_application_and_build_inputs_preserved(self):
        for name in (".env.example", "LICENSE", "agent_harness/memory.py",
                     "desktop/package-lock.json", "desktop/src-tauri/Cargo.lock",
                     "desktop/src/App.tsx", "skills/code-review/SKILL.md",
                     "packaging/build_windows.ps1", ".github/workflows/ci.yml"):
            with self.subTest(name=name):
                self.assertTrue(export.permitted(Path(name)))

    def test_scan_rejects_credential_without_printing_value(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("sk-" + "a" * 32, encoding="utf-8")
            issues = export.scan(root)
            self.assertEqual(issues, ["possible credential: README.md"])

    def test_scan_checks_json_and_document_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("[missing](missing.md)", encoding="utf-8")
            (root / "broken.json").write_text("{bad}", encoding="utf-8")
            self.assertEqual(len(export.scan(root)), 2)

    def test_redaction_does_not_change_executable_code(self):
        text = r"C:\Users\example\project"
        self.assertEqual(export.public_text(Path("tests/example.py"), text), text)
        self.assertNotIn("example", export.public_text(Path("docs/project_docs/example.md"), text))

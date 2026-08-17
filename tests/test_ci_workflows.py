import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TESTS_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
DEV_REQUIREMENTS = REPOSITORY_ROOT / "requirements-dev.txt"


class CIWorkflowTests(unittest.TestCase):
    def test_tests_workflow_covers_push_pull_request_and_reuse(self):
        workflow = TESTS_WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^  workflow_call:$")
        self.assertRegex(workflow, r"(?m)^  push:$")
        self.assertRegex(workflow, r"(?m)^  pull_request:$")

    def test_unit_tests_run_on_supported_python_versions_without_display(self):
        workflow = TESTS_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('- "3.11"', workflow)
        self.assertIn('- "3.12"', workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("MPLBACKEND: Agg", workflow)
        self.assertNotRegex(workflow, r"(?i)\b(?:DISPLAY|xvfb)\b")

    def test_ruff_is_pinned_and_checks_initial_critical_rules(self):
        requirements = DEV_REQUIREMENTS.read_text(encoding="utf-8")
        workflow = TESTS_WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(requirements, r"(?m)^ruff==\d+\.\d+\.\d+$")
        self.assertIn("python-version: \"3.11\"", workflow)
        self.assertIn("python -m pip install -r requirements-dev.txt", workflow)
        self.assertIn("ruff check --select E9,F63,F7,F82 .", workflow)

    def test_release_build_waits_for_reusable_tests_workflow(self):
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(
            workflow,
            re.compile(
                r"^  quality:\n"
                r"    uses: \./\.github/workflows/tests\.yml\n"
                r"\n?"
                r"  build:\n"
                r"    needs: quality$",
                re.MULTILINE,
            ),
        )
        self.assertRegex(workflow, r"(?m)^  release:\n    needs: build$")


if __name__ == "__main__":
    unittest.main()

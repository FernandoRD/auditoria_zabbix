from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def test_python_311_is_the_minimum_runtime(self):
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("Python 3.11+", readme)
        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("ENV PYPANDOC_PANDOC=/opt/pandoc/pandoc", dockerfile)

    def test_requirements_are_the_only_dependency_source(self):
        requirements = (REPOSITORY_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertFalse((REPOSITORY_ROOT / "whl").exists())
        self.assertIn("pypandoc==1.17", requirements)
        self.assertNotIn("pypandoc[tinytex]", requirements)

    def test_spec_requires_and_bundles_prepared_pandoc(self):
        spec = (REPOSITORY_ROOT / "pyinstaller.spec").read_text(encoding="utf-8")

        self.assertIn('os.path.join("build", "pandoc", pandoc_name)', spec)
        self.assertIn('binaries=[(pandoc_binary, "pandoc")]', spec)
        self.assertIn("if not os.path.isfile(pandoc_binary):", spec)
        self.assertIn("pathex=[SPECPATH]", spec)

    def test_release_prepares_builds_and_smoke_tests_before_packaging(self):
        workflow = (REPOSITORY_ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )

        prepare = workflow.index("python tools/prepare_pandoc.py --output-dir build/pandoc")
        build = workflow.index("pyinstaller pyinstaller.spec --noconfirm")
        windows_smoke = workflow.index(
            'AuditoriaZabbix.exe" --packaging-smoke-test'
        )
        linux_smoke = workflow.index(
            "dist/AuditoriaZabbix/AuditoriaZabbix --packaging-smoke-test"
        )
        windows_package = workflow.index("Compress-Archive")
        linux_package = workflow.index("tar -czf")

        self.assertLess(prepare, build)
        self.assertLess(build, windows_smoke)
        self.assertLess(build, linux_smoke)
        self.assertLess(windows_smoke, windows_package)
        self.assertLess(linux_smoke, linux_package)
        self.assertEqual(2, workflow.count("HTTP_PROXY: http://127.0.0.1:9"))


if __name__ == "__main__":
    unittest.main()

"""Static safety checks for the Docker build context and publication script."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class TestPackagingSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")
        cls.dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
        cls.build_script = (REPOSITORY_ROOT / "build_image.fish").read_text(encoding="utf-8")

    def test_dockerignore_excludes_env_files_but_keeps_example(self):
        ignored = {
            line.strip()
            for line in self.dockerignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn(".env", ignored)
        self.assertIn(".env.*", ignored)
        self.assertIn("!.env.example", ignored)

    def test_dockerignore_excludes_local_development_and_generated_files(self):
        for pattern in ("venv/", ".venv/", "whl/", "wheelhouse/", "tests/", "docs/", "build/", "dist/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, self.dockerignore)

    def test_dockerfile_copies_only_runtime_assets(self):
        self.assertNotIn("COPY . .", self.dockerfile)
        for source in ("api", "core", "gui", "prompts", "templates", "main.py", "__init__.py"):
            with self.subTest(source=source):
                self.assertIn(source, self.dockerfile)

    def test_dockerfile_uses_non_root_runtime_user(self):
        self.assertIn("useradd --system", self.dockerfile)
        self.assertIn("USER app", self.dockerfile)

    def test_build_script_push_requires_an_explicit_flag_and_confirmation(self):
        self.assertIn("'p/push'", self.build_script)
        self.assertIn("if not set -q _flag_push", self.build_script)
        self.assertIn("Digite PUSH para confirmar", self.build_script)

        push_position = self.build_script.index("docker push")
        flag_position = self.build_script.index("if not set -q _flag_push")
        confirmation_position = self.build_script.index("Digite PUSH para confirmar")
        self.assertGreater(push_position, flag_position)
        self.assertGreater(push_position, confirmation_position)


if __name__ == "__main__":
    unittest.main()

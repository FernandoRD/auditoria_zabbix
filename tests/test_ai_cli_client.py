import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from api.ai_cli_client import (
    CLI_BINARIES,
    CLI_SYSTEM_PROMPT,
    cli_binary_status,
    build_cli_command,
    build_cli_input_text,
    extract_cli_json_text,
    generate_via_cli,
)


class TestCliBinaryStatus(unittest.TestCase):
    def test_binary_found(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"):
            binary, path = cli_binary_status("Anthropic")
        self.assertEqual(binary, "claude")
        self.assertEqual(path, "/usr/bin/claude")

    def test_binary_not_found(self):
        with patch("api.ai_cli_client.shutil.which", return_value=None):
            binary, path = cli_binary_status("OpenAI")
        self.assertEqual(binary, "codex")
        self.assertIsNone(path)

    def test_provider_without_cli_support(self):
        binary, path = cli_binary_status("Ollama")
        self.assertIsNone(binary)
        self.assertIsNone(path)


class TestBuildCliCommand(unittest.TestCase):
    def test_anthropic_without_override(self):
        cmd = build_cli_command("Anthropic")
        self.assertEqual(cmd, [
            "claude", "-p", "--allowedTools", "", "--output-format", "json",
            "--system-prompt", CLI_SYSTEM_PROMPT,
        ])

    def test_anthropic_with_override(self):
        cmd = build_cli_command("Anthropic", model_override="opus")
        self.assertEqual(cmd[-2:], ["--model", "opus"])

    def test_openai_without_override(self):
        cmd = build_cli_command("OpenAI", codex_output_file="/tmp/x/out.txt")
        self.assertEqual(cmd, [
            "codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check",
            "-o", "/tmp/x/out.txt",
        ])

    def test_openai_with_override(self):
        cmd = build_cli_command("OpenAI", model_override="o3", codex_output_file="/tmp/x/out.txt")
        self.assertEqual(cmd[-2:], ["-m", "o3"])

    def test_openai_missing_output_file_raises(self):
        with self.assertRaises(ValueError):
            build_cli_command("OpenAI")

    def test_gemini_without_override(self):
        cmd = build_cli_command("Google Gemini")
        self.assertEqual(cmd[0], "gemini")
        self.assertIn("--approval-mode", cmd)
        self.assertIn("plan", cmd)
        self.assertEqual(cmd[-2], "-p")

    def test_gemini_with_override(self):
        cmd = build_cli_command("Google Gemini", model_override="gemini-2.5-pro")
        self.assertIn("--model", cmd)
        self.assertIn("gemini-2.5-pro", cmd)

    def test_unsupported_provider_raises(self):
        with self.assertRaises(ValueError):
            build_cli_command("Ollama")


class TestBuildCliInputText(unittest.TestCase):
    def test_anthropic_uses_system_prompt_flag_so_input_is_unchanged(self):
        self.assertEqual(build_cli_input_text("Anthropic", "PROMPT"), "PROMPT")

    def test_openai_prepends_persona(self):
        result = build_cli_input_text("OpenAI", "PROMPT")
        self.assertEqual(result, f"{CLI_SYSTEM_PROMPT}\n\nPROMPT")

    def test_gemini_prepends_persona(self):
        result = build_cli_input_text("Google Gemini", "PROMPT")
        self.assertEqual(result, f"{CLI_SYSTEM_PROMPT}\n\nPROMPT")


class TestExtractCliJsonText(unittest.TestCase):
    def test_extracts_result_key(self):
        raw = '{"result": "Relatório gerado", "is_error": false}'
        self.assertEqual(extract_cli_json_text(raw), "Relatório gerado")

    def test_falls_back_to_response_key_when_no_result(self):
        raw = '{"response": "Texto via response"}'
        self.assertEqual(extract_cli_json_text(raw), "Texto via response")

    def test_falls_back_to_raw_text_on_invalid_json(self):
        raw = "isto não é json"
        self.assertEqual(extract_cli_json_text(raw), "isto não é json")

    def test_falls_back_to_raw_text_when_no_known_key(self):
        raw = '{"foo": "bar"}'
        self.assertEqual(extract_cli_json_text(raw), raw)


class TestGenerateViaCliAnthropic(unittest.TestCase):
    def test_yields_extracted_text(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0,
                stdout='{"result": "Relatório gerado"}', stderr="",
            )
            chunks = list(generate_via_cli("Anthropic", "PROMPT", None))

        self.assertEqual(chunks, ["Relatório gerado"])
        called_cmd = mock_run.call_args.args[0]
        self.assertEqual(called_cmd[0], "claude")
        self.assertEqual(mock_run.call_args.kwargs["input"], "PROMPT")

    def test_missing_binary_raises_before_running(self):
        with patch("api.ai_cli_client.shutil.which", return_value=None), \
             patch("api.ai_cli_client.subprocess.run") as mock_run:
            with self.assertRaises(RuntimeError):
                list(generate_via_cli("Anthropic", "PROMPT", None))
        mock_run.assert_not_called()

    def test_nonzero_exit_raises_with_stderr(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=1, stdout="", stderr="sessão expirada",
            )
            with self.assertRaisesRegex(RuntimeError, "sessão expirada"):
                list(generate_via_cli("Anthropic", "PROMPT", None))

    def test_timeout_raises_runtime_error(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600)):
            with self.assertRaisesRegex(RuntimeError, "600"):
                list(generate_via_cli("Anthropic", "PROMPT", None))

    def test_scratch_dir_is_removed_after_call(self):
        created_dirs = []
        real_mkdtemp = tempfile.mkdtemp

        def spy_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created_dirs.append(d)
            return d

        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.tempfile.mkdtemp", side_effect=spy_mkdtemp), \
             patch("api.ai_cli_client.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout='{"result": "ok"}', stderr="",
            )
            list(generate_via_cli("Anthropic", "PROMPT", None))

        self.assertEqual(len(created_dirs), 1)
        self.assertFalse(os.path.exists(created_dirs[0]))


class TestGenerateViaCliOpenAI(unittest.TestCase):
    def test_reads_output_file_written_by_codex(self):
        def fake_run(cmd, input, cwd, timeout):
            idx = cmd.index("-o")
            with open(cmd[idx + 1], "w", encoding="utf-8") as f:
                f.write("Relatório via Codex")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/codex"), \
             patch("api.ai_cli_client.subprocess.run", side_effect=fake_run):
            chunks = list(generate_via_cli("OpenAI", "PROMPT", None))

        self.assertEqual(chunks, ["Relatório via Codex"])


if __name__ == "__main__":
    unittest.main()

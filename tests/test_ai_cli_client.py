import unittest
from unittest.mock import patch

from api.ai_cli_client import (
    CLI_BINARIES,
    CLI_SYSTEM_PROMPT,
    cli_binary_status,
    build_cli_command,
    build_cli_input_text,
    extract_cli_json_text,
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


if __name__ == "__main__":
    unittest.main()

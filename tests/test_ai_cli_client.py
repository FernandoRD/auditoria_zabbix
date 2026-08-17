import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from api.ai_cli_client import (
    CLI_SYSTEM_PROMPT,
    CLI_BINARIES,
    CLICapabilities,
    ClaudeCLIAdapter,
    CodexCLIAdapter,
    GeminiCLIAdapter,
    cli_binary_status,
    build_cli_command,
    build_cli_input_text,
    CLIBinaryNotFoundError,
    CLIProcessError,
    CLITimeoutError,
    _run_cli_subprocess,
    _run_cli_streaming_subprocess,
    probe_cli_capabilities,
    _terminate_process_tree,
    extract_cli_json_text,
    generate_via_cli,
)
from api.ai_prompts import AIStreamEvent
from core.operation import OperationCancelled


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
        self.assertNotIn("--output-format", cmd)
        self.assertEqual(cmd[:4], ["claude", "-p", "--allowedTools", ""])

    def test_anthropic_only_adds_json_after_capability_confirmation(self):
        cmd = build_cli_command("Anthropic", capabilities=CLICapabilities(json_fallback=True))
        self.assertIn("--output-format", cmd)
        self.assertIn("json", cmd)

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
    def test_system_prompt_marks_prompt_content_as_untrusted(self):
        self.assertIn("dados não confiáveis", CLI_SYSTEM_PROMPT)

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


class TestCLIStreamingCapabilities(unittest.TestCase):
    fixtures_dir = Path(__file__).with_name("fixtures")

    def test_claude_help_enables_stream_json_only_when_all_required_flags_exist(self):
        help_text = "--output-format <format>  json, stream-json\n--verbose\n--include-partial-messages"
        capabilities = ClaudeCLIAdapter().detect_capabilities(help_text)
        self.assertEqual("claude-stream-json", capabilities.stream_format)
        self.assertTrue(capabilities.partial_messages)
        cmd = build_cli_command("Anthropic", capabilities=capabilities)
        self.assertIn("stream-json", cmd)
        self.assertIn("--include-partial-messages", cmd)

    def test_stream_json_without_partial_messages_does_not_enable_streaming(self):
        capabilities = ClaudeCLIAdapter().detect_capabilities(
            "--output-format <format> stream-json\n--verbose"
        )
        self.assertFalse(capabilities.supports_streaming)
        self.assertFalse(capabilities.json_fallback)

    def test_claude_parser_accepts_only_the_fixture_text_deltas(self):
        adapter = ClaudeCLIAdapter()
        lines = (self.fixtures_dir / "claude_stream_jsonl.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            [adapter.parse_stream_line(line) for line in lines if adapter.parse_stream_line(line)],
            ["Relatório ", "incremental"],
        )

    def test_codex_help_is_probed_on_exec_subcommand_and_parser_has_fixture(self):
        adapter = CodexCLIAdapter()
        self.assertEqual(adapter.help_command(), ["codex", "exec", "--help"])
        capabilities = adapter.detect_capabilities("Usage: codex exec [OPTIONS]\n  --json")
        self.assertEqual("codex-jsonl", capabilities.stream_format)
        lines = (self.fixtures_dir / "codex_jsonl.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            [adapter.parse_stream_line(line) for line in lines if adapter.parse_stream_line(line)],
            ["Relatório via Codex"],
        )

    def test_gemini_documents_json_as_final_response_not_streaming(self):
        capabilities = GeminiCLIAdapter().detect_capabilities("--output-format <format> json")
        self.assertFalse(capabilities.supports_streaming)
        self.assertTrue(capabilities.json_fallback)

    def test_failed_help_probe_disables_structured_formats(self):
        with patch("api.ai_cli_client._run_cli_subprocess", side_effect=CLIProcessError("erro")):
            capabilities = probe_cli_capabilities("Anthropic", tempfile.gettempdir())
        self.assertEqual(CLICapabilities(), capabilities)


class TestGenerateViaCliAnthropic(unittest.TestCase):
    def test_yields_extracted_text(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.probe_cli_capabilities", return_value=CLICapabilities(json_fallback=True)), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.communicate.return_value = ('{"result": "Relatório gerado"}', "")
            process.returncode = 0
            chunks = list(generate_via_cli("Anthropic", "PROMPT", None))

        self.assertEqual(
            chunks,
            [AIStreamEvent.text_chunk("Relatório gerado"), AIStreamEvent.final("stop")],
        )
        called_cmd = mock_popen.call_args.args[0]
        self.assertEqual(called_cmd[0], "claude")
        self.assertTrue(mock_popen.call_args.kwargs["start_new_session"])
        self.assertEqual(process.communicate.call_args.kwargs["input"], "PROMPT")

    def test_missing_binary_emits_terminal_error_before_running(self):
        with patch("api.ai_cli_client.shutil.which", return_value=None), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            events = list(generate_via_cli("Anthropic", "PROMPT", None))
        self.assertEqual("error", events[-1].reason)
        self.assertIn("não encontrada", events[-1].error)
        mock_popen.assert_not_called()

    def test_nonzero_exit_emits_terminal_error_with_stderr(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.communicate.return_value = ("", "sessão expirada")
            process.returncode = 1
            events = list(generate_via_cli("Anthropic", "PROMPT", None))
        self.assertEqual("error", events[-1].reason)
        self.assertIn("omitidos", events[-1].error)
        self.assertNotIn("sessão expirada", events[-1].error)

    def test_timeout_emits_terminal_error(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.poll.return_value = 0
            events = list(generate_via_cli("Anthropic", "PROMPT", None, timeout=0))
            process.wait.assert_not_called()
        self.assertEqual("error", events[-1].reason)
        self.assertIn("timeout", events[-1].error)

    def test_scratch_dir_is_removed_after_call(self):
        created_dirs = []
        real_mkdtemp = tempfile.mkdtemp

        def spy_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created_dirs.append(d)
            return d

        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.tempfile.mkdtemp", side_effect=spy_mkdtemp), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.communicate.return_value = ('{"result": "ok"}', "")
            process.returncode = 0
            list(generate_via_cli("Anthropic", "PROMPT", None))

        self.assertEqual(len(created_dirs), 1)
        self.assertFalse(os.path.exists(created_dirs[0]))

    def test_scratch_dir_is_removed_after_cancellation(self):
        created_dirs = []
        real_mkdtemp = tempfile.mkdtemp
        cancelled = threading.Event()
        cancelled.set()

        def spy_mkdtemp(*args, **kwargs):
            directory = real_mkdtemp(*args, **kwargs)
            created_dirs.append(directory)
            return directory

        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/claude"), \
             patch("api.ai_cli_client.tempfile.mkdtemp", side_effect=spy_mkdtemp), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.poll.return_value = 0
            with self.assertRaises(OperationCancelled):
                list(generate_via_cli("Anthropic", "PROMPT", is_cancelled=cancelled.is_set))

        self.assertEqual(len(created_dirs), 1)
        self.assertFalse(os.path.exists(created_dirs[0]))


class TestGenerateViaCliOpenAI(unittest.TestCase):
    def test_reads_output_file_written_by_codex(self):
        def fake_communicate(input, timeout):
            cmd = mock_popen.call_args.args[0]
            idx = cmd.index("-o")
            with open(cmd[idx + 1], "w", encoding="utf-8") as f:
                f.write("Relatório via Codex")
            return "", ""

        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/codex"), \
             patch("api.ai_cli_client.probe_cli_capabilities", return_value=CLICapabilities()), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.communicate.side_effect = fake_communicate
            process.returncode = 0
            chunks = list(generate_via_cli("OpenAI", "PROMPT", None))

        self.assertEqual(
            chunks,
            [AIStreamEvent.text_chunk("Relatório via Codex"), AIStreamEvent.final("stop")],
        )

    def test_missing_binary_emits_terminal_error_before_running(self):
        with patch("api.ai_cli_client.shutil.which", return_value=None), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            events = list(generate_via_cli("OpenAI", "PROMPT", None))
        self.assertEqual("error", events[-1].reason)
        mock_popen.assert_not_called()

    def test_nonzero_exit_emits_terminal_error_with_stderr(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/codex"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.communicate.return_value = ("", "autenticação necessária")
            process.returncode = 1
            events = list(generate_via_cli("OpenAI", "PROMPT", None))
        self.assertEqual("error", events[-1].reason)
        self.assertIn("omitidos", events[-1].error)
        self.assertNotIn("autenticação necessária", events[-1].error)

    def test_timeout_emits_terminal_error(self):
        with patch("api.ai_cli_client.shutil.which", return_value="/usr/bin/codex"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.poll.return_value = 0
            events = list(generate_via_cli("OpenAI", "PROMPT", None, timeout=0))
        self.assertEqual("error", events[-1].reason)


class TestCliSubprocessCancellation(unittest.TestCase):
    def test_binary_not_found_is_distinct(self):
        with patch("api.ai_cli_client.subprocess.Popen", side_effect=FileNotFoundError):
            with self.assertRaises(CLIBinaryNotFoundError):
                _run_cli_subprocess(["missing-cli"], "", tempfile.gettempdir())

    def test_posix_cancellation_terminates_the_process_group(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("api.ai_cli_client.subprocess.Popen") as mock_popen, \
             patch("api.ai_cli_client.os.killpg") as mock_killpg:
            process = mock_popen.return_value
            process.pid = 4321
            process.poll.side_effect = [None, None, 0]
            with self.assertRaisesRegex(OperationCancelled, "cancelada"):
                _run_cli_subprocess(["cli"], "prompt", tempfile.gettempdir(), is_cancelled=cancelled.is_set)

        mock_killpg.assert_called_once_with(4321, signal.SIGTERM)
        process.communicate.assert_called_once_with(timeout=1.0)

    def test_timeout_terminates_the_process_group(self):
        with patch("api.ai_cli_client.subprocess.Popen") as mock_popen, \
             patch("api.ai_cli_client.os.killpg") as mock_killpg, \
             patch("api.ai_cli_client.time.monotonic", side_effect=[0, 1]):
            process = mock_popen.return_value
            process.pid = 4322
            process.poll.side_effect = [None, None, 0]
            with self.assertRaises(CLITimeoutError):
                _run_cli_subprocess(["cli"], "prompt", tempfile.gettempdir(), timeout=1)

        mock_killpg.assert_called_once_with(4322, signal.SIGTERM)

    def test_streaming_yields_a_fixture_chunk_then_honors_cancellation(self):
        cancelled = threading.Event()
        payload = (
            '{"type":"stream_event","event":{"type":"content_block_delta",'
            '"delta":{"type":"text_delta","text":"primeiro"}}}'
        )
        code = (
            f"import sys, time; print({payload!r}); "
            "sys.stdout.flush(); time.sleep(30)"
        )
        stream = _run_cli_streaming_subprocess(
            [sys.executable, "-c", code],
            "",
            tempfile.gettempdir(),
            ClaudeCLIAdapter().parse_stream_line,
            timeout=5,
            is_cancelled=cancelled.is_set,
        )
        self.assertEqual(next(stream), "primeiro")
        cancelled.set()
        with self.assertRaisesRegex(OperationCancelled, "cancelada"):
            next(stream)

    def test_streaming_timeout_terminates_the_process(self):
        stream = _run_cli_streaming_subprocess(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            "",
            tempfile.gettempdir(),
            ClaudeCLIAdapter().parse_stream_line,
            timeout=0.01,
        )
        with self.assertRaises(CLITimeoutError):
            list(stream)

    def test_windows_uses_taskkill_for_the_process_tree(self):
        with patch("api.ai_cli_client.os.name", "nt"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            taskkill = mock_popen.return_value
            taskkill.returncode = 0
            process = MagicMock()
            process.pid = 99
            process.poll.side_effect = [None, None, 0]
            _terminate_process_tree(process)

        mock_popen.assert_called_once_with(
            ["taskkill", "/PID", "99", "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        taskkill.wait.assert_called_once_with(timeout=1.0)
        process.terminate.assert_not_called()

    def test_windows_falls_back_when_taskkill_fails(self):
        with patch("api.ai_cli_client.os.name", "nt"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            mock_popen.return_value.returncode = 1
            process = MagicMock()
            process.pid = 100
            process.poll.return_value = None
            _terminate_process_tree(process)

        process.terminate.assert_called_once_with()

    def test_windows_falls_back_when_taskkill_times_out(self):
        with patch("api.ai_cli_client.os.name", "nt"), \
             patch("api.ai_cli_client.subprocess.Popen") as mock_popen:
            taskkill = mock_popen.return_value
            taskkill.wait.side_effect = [subprocess.TimeoutExpired("taskkill", 1), None]
            process = MagicMock()
            process.pid = 101
            process.poll.return_value = None
            _terminate_process_tree(process)

        taskkill.kill.assert_called_once_with()
        process.terminate.assert_called_once_with()

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_posix_exit_race_still_reaps_process(self):
        process = MagicMock()
        process.pid = 101
        process.poll.return_value = None
        with patch("api.ai_cli_client.os.killpg", side_effect=ProcessLookupError):
            _terminate_process_tree(process)

        process.communicate.assert_called_once_with(timeout=1.0)

    @unittest.skipUnless(os.name == "posix", "integração de grupo de processo é específica de POSIX")
    def test_posix_integration_cancellation_ends_child(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = os.path.join(directory, "child.pid")
            code = (
                "import pathlib, subprocess, sys, time; "
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
            )
            cancelled = threading.Event()

            def cancel_after_child_starts():
                deadline = time.monotonic() + 2
                while not os.path.exists(pid_file) and time.monotonic() < deadline:
                    time.sleep(0.01)
                cancelled.set()

            canceller = threading.Thread(target=cancel_after_child_starts)
            canceller.start()
            with self.assertRaisesRegex(OperationCancelled, "cancelada"):
                _run_cli_subprocess(
                    [sys.executable, "-c", code, pid_file],
                    "",
                    directory,
                    timeout=5,
                    is_cancelled=cancelled.is_set,
                )
            canceller.join(2)
            self.assertTrue(cancelled.is_set())
            with open(pid_file, encoding="utf-8") as f:
                child_pid = int(f.read())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                proc_state_path = f"/proc/{child_pid}/stat"
                if os.path.exists(proc_state_path):
                    with open(proc_state_path, encoding="utf-8") as f:
                        if f.read().split()[2] == "Z":
                            break
                time.sleep(0.02)
            else:
                self.fail("o processo filho da CLI continuou em execução após o cancelamento")


if __name__ == "__main__":
    unittest.main()

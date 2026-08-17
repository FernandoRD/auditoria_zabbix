"""CLI adapters for subscription-authenticated AI providers.

Streaming formats are intentionally opt-in per installed CLI capability.  A
provider changing its help output therefore falls back to a final response
instead of making an unverified JSONL assumption about audit data.
"""

from dataclasses import dataclass
import json
import os
import queue
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time

from api.ai_prompts import AIStreamEvent, SYSTEM_PROMPT
from core.operation import OperationCancelled


CLI_BINARIES = {
    "Anthropic": "claude",
    "OpenAI": "codex",
    "Google Gemini": "gemini",
}

# Import-compatible alias; the definition lives in ``ai_prompts``.
CLI_SYSTEM_PROMPT = SYSTEM_PROMPT

GEMINI_LEAD_PROMPT = (
    "Gere o relatório de auditoria com base nas instruções e dados a seguir, "
    "enviados via entrada padrão."
)

_POLL_INTERVAL_SECONDS = 0.1
_TERMINATION_GRACE_SECONDS = 1.0
_HELP_TIMEOUT_SECONDS = 10


def _help_lists_json_format(help_text):
    """Return whether help names the standalone ``json`` output format.

    ``stream-json`` alone must not authorize the distinct final ``json`` mode.
    """
    return bool(re.search(r"(?<![\\w-])json(?![\\w-])", help_text.lower()))


class CLIBinaryNotFoundError(RuntimeError):
    """Raised when the configured CLI executable is not available."""


class CLITimeoutError(RuntimeError):
    """Raised when a CLI command exceeds its configured deadline."""


class CLIProcessError(RuntimeError):
    """Raised when a CLI command exits unsuccessfully."""


@dataclass(frozen=True)
class CLICapabilities:
    """Capabilities confirmed by this installed binary's ``--help`` output."""

    stream_format: str | None = None
    json_fallback: bool = False
    partial_messages: bool = False

    @property
    def supports_streaming(self):
        return self.stream_format is not None


class BaseCLIAdapter:
    """Provider-specific command construction and narrowly scoped parsing."""

    provider = ""
    binary = ""

    def help_command(self):
        return [self.binary, "--help"]

    def detect_capabilities(self, help_text):
        return CLICapabilities()

    def build_command(self, model_override=None, capabilities=None, output_file=None):
        raise NotImplementedError

    def input_text(self, prompt):
        return f"{CLI_SYSTEM_PROMPT}\n\n{prompt}"

    def parse_stream_line(self, raw_line):
        return None


class ClaudeCLIAdapter(BaseCLIAdapter):
    provider = "Anthropic"
    binary = "claude"

    def detect_capabilities(self, help_text):
        normalized = help_text.lower()
        has_output_format = "--output-format" in normalized
        stream_json = has_output_format and "stream-json" in normalized
        partial_messages = "--include-partial-messages" in normalized
        return CLICapabilities(
            stream_format=(
                "claude-stream-json"
                if stream_json and "--verbose" in normalized and partial_messages
                else None
            ),
            json_fallback=has_output_format and _help_lists_json_format(help_text),
            partial_messages=partial_messages,
        )

    def build_command(self, model_override=None, capabilities=None, output_file=None):
        capabilities = capabilities or CLICapabilities()
        cmd = [
            self.binary, "-p", "--allowedTools", "", "--system-prompt", CLI_SYSTEM_PROMPT,
        ]
        if model_override:
            cmd += ["--model", model_override]
        if capabilities.stream_format == "claude-stream-json":
            cmd += ["--output-format", "stream-json", "--verbose"]
            cmd.append("--include-partial-messages")
        elif capabilities.json_fallback:
            cmd += ["--output-format", "json"]
        return cmd

    def input_text(self, prompt):
        # Claude has a dedicated system-prompt option; do not duplicate it in stdin.
        return prompt

    def parse_stream_line(self, raw_line):
        """Parse the documented stream-json text-delta envelope only.

        Other event shapes are ignored deliberately: accepting arbitrary fields
        would risk showing metadata or a repeated final transcript as report text.
        """
        try:
            event = json.loads(raw_line)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(event, dict) or event.get("type") != "stream_event":
            return None
        payload = event.get("event")
        if not isinstance(payload, dict) or payload.get("type") != "content_block_delta":
            return None
        delta = payload.get("delta")
        if not isinstance(delta, dict) or delta.get("type") != "text_delta":
            return None
        text = delta.get("text")
        return text if isinstance(text, str) and text else None


class CodexCLIAdapter(BaseCLIAdapter):
    provider = "OpenAI"
    binary = "codex"

    def help_command(self):
        # ``--json`` belongs to the non-interactive exec subcommand, not its root.
        return [self.binary, "exec", "--help"]

    def detect_capabilities(self, help_text):
        return CLICapabilities(
            stream_format="codex-jsonl" if "--json" in help_text.lower() else None,
        )

    def build_command(self, model_override=None, capabilities=None, output_file=None):
        if not output_file:
            raise ValueError("codex_output_file é obrigatório para o provedor OpenAI.")
        capabilities = capabilities or CLICapabilities()
        cmd = [
            self.binary, "exec", "--sandbox", "read-only", "--skip-git-repo-check",
            "-o", output_file,
        ]
        if model_override:
            cmd += ["-m", model_override]
        if capabilities.stream_format == "codex-jsonl":
            cmd.append("--json")
        return cmd

    def parse_stream_line(self, raw_line):
        """Parse only Codex's JSONL ``agent_message`` completion event."""
        try:
            event = json.loads(raw_line)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            return None
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            return None
        text = item.get("text")
        return text if isinstance(text, str) and text else None


class GeminiCLIAdapter(BaseCLIAdapter):
    provider = "Google Gemini"
    binary = "gemini"

    def detect_capabilities(self, help_text):
        normalized = help_text.lower()
        # Gemini's available help does not expose a stable, fixture-backed JSONL
        # text-delta schema, so it remains deliberately non-streaming.
        return CLICapabilities(
            json_fallback="--output-format" in normalized and _help_lists_json_format(help_text),
        )

    def build_command(self, model_override=None, capabilities=None, output_file=None):
        capabilities = capabilities or CLICapabilities()
        cmd = [self.binary, "--approval-mode", "plan", "-p", GEMINI_LEAD_PROMPT]
        if model_override:
            cmd += ["--model", model_override]
        if capabilities.json_fallback:
            cmd += ["--output-format", "json"]
        return cmd


CLI_ADAPTERS = {
    ClaudeCLIAdapter.provider: ClaudeCLIAdapter(),
    CodexCLIAdapter.provider: CodexCLIAdapter(),
    GeminiCLIAdapter.provider: GeminiCLIAdapter(),
}


def get_cli_adapter(provider):
    try:
        return CLI_ADAPTERS[provider]
    except KeyError:
        raise ValueError(f"Provedor '{provider}' não suporta modo CLI local.") from None


def _taskkill_process_tree(process, timeout=_TERMINATION_GRACE_SECONDS):
    """Return whether Windows accepted a request to terminate the process tree."""
    try:
        taskkill = subprocess.Popen(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        taskkill.wait(timeout=timeout)
    except OSError:
        return False
    except subprocess.TimeoutExpired:
        taskkill.kill()
        try:
            taskkill.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        return False
    return taskkill.returncode == 0


def cli_binary_status(provider):
    """Return ``(binary, path)`` or ``(None, None)`` for unsupported providers."""
    binary = CLI_BINARIES.get(provider)
    if not binary:
        return None, None
    return binary, shutil.which(binary)


def build_cli_command(provider, model_override=None, codex_output_file=None, capabilities=None):
    """Compatibility wrapper around the provider adapters.

    Without a successful capability probe it chooses only non-streaming commands;
    callers must never infer that an output format is universally available.
    """
    return get_cli_adapter(provider).build_command(
        model_override=model_override,
        capabilities=capabilities,
        output_file=codex_output_file,
    )


def build_cli_input_text(provider, prompt):
    """Return the stdin payload for the provider's adapter."""
    return get_cli_adapter(provider).input_text(prompt)


def extract_cli_json_text(raw_stdout):
    """Extract a final text field from a confirmed non-streaming JSON response."""
    try:
        data = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        return raw_stdout.strip()
    if isinstance(data, dict):
        for key in ("result", "response", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return raw_stdout.strip()


def _terminate_process_tree(
    process, grace_seconds=_TERMINATION_GRACE_SECONDS, reap_with_communicate=True,
):
    """Stop *process* and children, then reap it without leaking a process tree."""
    if process.poll() is not None:
        return

    if os.name == "nt":
        if not _taskkill_process_tree(process):
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    try:
        if reap_with_communicate:
            process.communicate(timeout=grace_seconds)
        else:
            process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name == "nt":
        if not _taskkill_process_tree(process):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        if reap_with_communicate:
            process.communicate(timeout=grace_seconds)
        else:
            process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def _popen_kwargs(cwd):
    kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": cwd,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _run_cli_subprocess(cmd, input_text, cwd, timeout=600, is_cancelled=None):
    """Run a final-response CLI command with deadline and cancellation polling."""
    try:
        process = subprocess.Popen(cmd, **_popen_kwargs(cwd))
    except FileNotFoundError:
        raise CLIBinaryNotFoundError(f"Binário '{cmd[0]}' não encontrado no PATH.") from None

    deadline = time.monotonic() + timeout
    first_communicate = True
    try:
        while True:
            if is_cancelled is not None and is_cancelled():
                raise OperationCancelled("Geração pela CLI cancelada pelo usuário.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CLITimeoutError(f"A CLI '{cmd[0]}' não respondeu em {timeout}s (timeout).")
            try:
                if first_communicate:
                    stdout, _stderr = process.communicate(
                        input=input_text, timeout=min(_POLL_INTERVAL_SECONDS, remaining),
                    )
                    first_communicate = False
                else:
                    stdout, _stderr = process.communicate(
                        timeout=min(_POLL_INTERVAL_SECONDS, remaining),
                    )
            except subprocess.TimeoutExpired:
                first_communicate = False
                continue
            break
    except BaseException:
        if process.poll() is None:
            _terminate_process_tree(process)
        raise

    if process.returncode != 0:
        # stderr/stdout can include an echoed audit prompt. Do not expose it to logs.
        raise CLIProcessError(
            f"A CLI '{cmd[0]}' retornou erro (código {process.returncode}); "
            "detalhes foram omitidos para proteger os dados da auditoria."
        )
    return stdout


def _drain_pipe(pipe, output_queue=None):
    """Read a pipe in a daemon thread; stderr is drained but never retained."""
    try:
        for line in iter(pipe.readline, ""):
            if output_queue is not None:
                output_queue.put(line)
    finally:
        pipe.close()
        if output_queue is not None:
            output_queue.put(None)


def _write_stdin(pipe, input_text):
    try:
        pipe.write(input_text)
        pipe.close()
    except (BrokenPipeError, OSError, ValueError):
        # Process outcome below gives the user a safe, provider-independent error.
        pass


def _run_cli_streaming_subprocess(cmd, input_text, cwd, parse_line, timeout=600, is_cancelled=None):
    """Yield parsed JSONL chunks while preserving CLI-01 cancellation guarantees."""
    kwargs = _popen_kwargs(cwd)
    kwargs["bufsize"] = 1
    try:
        process = subprocess.Popen(cmd, **kwargs)
    except FileNotFoundError:
        raise CLIBinaryNotFoundError(f"Binário '{cmd[0]}' não encontrado no PATH.") from None

    lines = queue.Queue()
    stdout_reader = threading.Thread(target=_drain_pipe, args=(process.stdout, lines), daemon=True)
    stderr_reader = threading.Thread(target=_drain_pipe, args=(process.stderr,), daemon=True)
    writer = threading.Thread(target=_write_stdin, args=(process.stdin, input_text), daemon=True)
    stdout_reader.start()
    stderr_reader.start()
    writer.start()
    deadline = time.monotonic() + timeout
    stdout_closed = False
    try:
        while not stdout_closed or process.poll() is None:
            if is_cancelled is not None and is_cancelled():
                raise OperationCancelled("Geração pela CLI cancelada pelo usuário.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CLITimeoutError(f"A CLI '{cmd[0]}' não respondeu em {timeout}s (timeout).")
            try:
                line = lines.get(timeout=min(_POLL_INTERVAL_SECONDS, remaining))
            except queue.Empty:
                continue
            if line is None:
                stdout_closed = True
                continue
            text = parse_line(line)
            if text:
                yield text
    except BaseException:
        if process.poll() is None:
            # Reader threads already own the pipes; communicate() would compete
            # for those descriptors during cancellation/timeout.
            _terminate_process_tree(process, reap_with_communicate=False)
        raise
    finally:
        stdout_reader.join(_TERMINATION_GRACE_SECONDS)
        stderr_reader.join(_TERMINATION_GRACE_SECONDS)
        writer.join(_TERMINATION_GRACE_SECONDS)

    if process.returncode != 0:
        raise CLIProcessError(
            f"A CLI '{cmd[0]}' retornou erro (código {process.returncode}); "
            "detalhes foram omitidos para proteger os dados da auditoria."
        )


def probe_cli_capabilities(provider, cwd, timeout=600, is_cancelled=None):
    """Inspect the installed CLI help before selecting a structured output mode.

    A failed/slow help probe is intentionally non-fatal: the adapter falls back
    to its safe final-response command rather than guessing a streaming format.
    """
    adapter = get_cli_adapter(provider)
    if is_cancelled is not None and is_cancelled():
        raise OperationCancelled("Geração pela CLI cancelada pelo usuário.")
    try:
        help_text = _run_cli_subprocess(
            adapter.help_command(), "", cwd,
            timeout=min(timeout, _HELP_TIMEOUT_SECONDS), is_cancelled=is_cancelled,
        )
    except (CLIProcessError, CLITimeoutError):
        return CLICapabilities()
    return adapter.detect_capabilities(help_text)


def _read_codex_output(output_file):
    try:
        with open(output_file, "r", encoding="utf-8") as file_handle:
            return file_handle.read()
    except FileNotFoundError:
        return ""


def generate_via_cli(provider, prompt, model_override=None, timeout=600, is_cancelled=None):
    """Generate CLI events, streaming only in a help-confirmed, fixture-tested mode."""
    binary, path = cli_binary_status(provider)
    if not binary:
        yield AIStreamEvent.final(
            "error", partial=True, error=f"Provedor '{provider}' não suporta modo CLI local.",
        )
        return
    if not path:
        yield AIStreamEvent.final(
            "error", partial=True,
            error=(
                f"CLI '{binary}' não encontrada no PATH. Instale-a e autentique com "
                f"'{binary} login' antes de usar o modo CLI local."
            ),
        )
        return

    adapter = get_cli_adapter(provider)
    scratch_dir = tempfile.mkdtemp(prefix="zabbix_audit_cli_")
    try:
        capabilities = probe_cli_capabilities(provider, scratch_dir, timeout, is_cancelled)
        input_text = adapter.input_text(prompt)
        output_file = os.path.join(scratch_dir, "codex_output.txt") if provider == "OpenAI" else None
        cmd = adapter.build_command(model_override, capabilities, output_file)

        if capabilities.supports_streaming:
            emitted_chunk = False
            for text in _run_cli_streaming_subprocess(
                cmd, input_text, scratch_dir, adapter.parse_stream_line, timeout, is_cancelled,
            ):
                emitted_chunk = True
                yield AIStreamEvent.text_chunk(text)
            # Codex writes a reliable final file even when a future JSON event schema
            # is not recognized. Do not duplicate it after recognized JSONL chunks.
            if not emitted_chunk and output_file:
                text = _read_codex_output(output_file)
                if text:
                    yield AIStreamEvent.text_chunk(text)
        else:
            stdout = _run_cli_subprocess(cmd, input_text, scratch_dir, timeout, is_cancelled)
            if output_file:
                text = _read_codex_output(output_file)
            else:
                text = extract_cli_json_text(stdout) if capabilities.json_fallback else stdout.strip()
            if text:
                yield AIStreamEvent.text_chunk(text)
        yield AIStreamEvent.final("stop")
    except OperationCancelled:
        raise
    except Exception as exc:
        yield AIStreamEvent.final("error", partial=True, error=str(exc))
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

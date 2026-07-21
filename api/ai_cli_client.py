import json
import os
import shutil
import subprocess
import tempfile

CLI_BINARIES = {
    "Anthropic": "claude",
    "OpenAI": "codex",
    "Google Gemini": "gemini",
}

CLI_SYSTEM_PROMPT = (
    "Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. "
    "Formate a saída em Markdown e cite dados exatos do JSON fornecido."
)

GEMINI_LEAD_PROMPT = (
    "Gere o relatório de auditoria com base nas instruções e dados a seguir, "
    "enviados via entrada padrão."
)


def cli_binary_status(provider):
    """Retorna (nome_binario, caminho_ou_None) para o provedor informado.
    (nome_binario, None) se não instalado; (None, None) se o provedor não suporta CLI local."""
    binary = CLI_BINARIES.get(provider)
    if not binary:
        return None, None
    return binary, shutil.which(binary)


def build_cli_command(provider, model_override=None, codex_output_file=None):
    """Monta a lista de argumentos do subprocesso da CLI. Função pura, não executa nada."""
    binary = CLI_BINARIES.get(provider)
    if not binary:
        raise ValueError(f"Provedor '{provider}' não suporta modo CLI local.")

    if provider == "Anthropic":
        cmd = [
            binary, "-p", "--allowedTools", "", "--output-format", "json",
            "--system-prompt", CLI_SYSTEM_PROMPT,
        ]
        if model_override:
            cmd += ["--model", model_override]
        return cmd

    if provider == "OpenAI":
        if not codex_output_file:
            raise ValueError("codex_output_file é obrigatório para o provedor OpenAI.")
        cmd = [
            binary, "exec", "--sandbox", "read-only", "--skip-git-repo-check",
            "-o", codex_output_file,
        ]
        if model_override:
            cmd += ["-m", model_override]
        return cmd

    if provider == "Google Gemini":
        cmd = [binary, "--approval-mode", "plan", "--output-format", "json", "-p", GEMINI_LEAD_PROMPT]
        if model_override:
            cmd += ["--model", model_override]
        return cmd

    raise ValueError(f"Provedor '{provider}' não suporta modo CLI local.")


def build_cli_input_text(provider, prompt):
    """Monta o texto enviado via stdin. Anthropic usa --system-prompt dedicado;
    os demais recebem a persona prependada ao prompt."""
    if provider == "Anthropic":
        return prompt
    return f"{CLI_SYSTEM_PROMPT}\n\n{prompt}"


def extract_cli_json_text(raw_stdout):
    """Extrai o texto final de uma saída --output-format json. Cai para o stdout
    bruto se o parsing falhar ou nenhuma chave conhecida for encontrada (defensivo,
    já que o schema de cada CLI pode mudar entre versões)."""
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


def _run_cli_subprocess(cmd, input_text, cwd, timeout=600):
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(f"Binário '{cmd[0]}' não encontrado no PATH.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"A CLI '{cmd[0]}' não respondeu em {timeout}s (timeout).")

    if result.returncode != 0:
        raise RuntimeError(
            f"A CLI '{cmd[0]}' retornou erro (código {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def generate_via_cli(provider, prompt, model_override=None, timeout=600):
    """Gera o relatório usando a CLI local já autenticada do provedor. Gera (yield)
    o texto completo da resposta uma única vez (sem streaming incremental na v1)."""
    binary, path = cli_binary_status(provider)
    if not binary:
        raise ValueError(f"Provedor '{provider}' não suporta modo CLI local.")
    if not path:
        raise RuntimeError(
            f"CLI '{binary}' não encontrada no PATH. Instale-a e autentique com "
            f"'{binary} login' antes de usar o modo CLI local."
        )

    scratch_dir = tempfile.mkdtemp(prefix="zabbix_audit_cli_")
    try:
        input_text = build_cli_input_text(provider, prompt)

        if provider == "OpenAI":
            output_file = os.path.join(scratch_dir, "codex_output.txt")
            cmd = build_cli_command(provider, model_override, codex_output_file=output_file)
            try:
                result = subprocess.run(
                    cmd,
                    input=input_text,
                    cwd=scratch_dir,
                    timeout=timeout,
                )
            except FileNotFoundError:
                raise RuntimeError(f"Binário '{cmd[0]}' não encontrado no PATH.")
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"A CLI '{cmd[0]}' não respondeu em {timeout}s (timeout).")

            if result.returncode != 0:
                raise RuntimeError(f"A CLI '{cmd[0]}' retornou erro (código {result.returncode})")

            with open(output_file, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            cmd = build_cli_command(provider, model_override)
            stdout = _run_cli_subprocess(cmd, input_text, scratch_dir, timeout)
            text = extract_cli_json_text(stdout)

        yield text
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

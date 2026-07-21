import json
import shutil

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

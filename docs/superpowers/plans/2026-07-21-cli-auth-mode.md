# Autenticação via CLI local dos provedores de IA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que cada conta de IA (Anthropic/OpenAI/Google Gemini) use, como alternativa à API key, a CLI oficial já instalada e autenticada na máquina (`claude`/`codex`/`gemini`) em modo headless, sem tocar em OAuth/tokens diretamente.

**Architecture:** Novo módulo `api/ai_cli_client.py` concentra toda a lógica de montar comandos, rodar o subprocesso (sandboxed, sem ferramentas, cwd isolado) e extrair o texto da resposta. `AIClient` (`api/ai_api.py`) ganha um campo `auth_mode` e delega para esse módulo quando `auth_mode == "cli"`. A GUI (`manage_accounts_view.py`, `main_view.py`) ganha um toggle por conta e mostra se o binário foi detectado. `controller.py` propaga `auth_mode`/`cli_model_override` ao construir o `AIClient` e ajusta a validação de campos obrigatórios (a API key deixa de ser obrigatória em modo CLI).

**Tech Stack:** Python 3, stdlib apenas (`subprocess`, `shutil`, `tempfile`, `json`, `os`) — nenhuma dependência nova. Testes com `unittest` (stdlib, sem pytest) para manter a filosofia "sem dependências novas sem justificativa" do projeto.

## Global Constraints

- Nenhuma dependência Python nova — usar apenas stdlib (`subprocess`, `shutil`, `tempfile`).
- `auth_mode` deve ser retrocompatível: contas antigas sem esse campo se comportam como `"api_key"` (`.get("auth_mode", "api_key")` em todo lugar que ler o dict de conta).
- Nunca usar `claude --bare` — essa flag desativa leitura de OAuth/keychain, quebrando a autenticação que este recurso depende.
- Todo subprocesso de CLI roda com ferramentas desabilitadas/sandbox somente-leitura: `claude` com `--allowedTools ""`, `codex` com `--sandbox read-only --skip-git-repo-check`, `gemini` com `--approval-mode plan`.
- Todo subprocesso roda com `cwd` em um diretório temporário isolado (`tempfile.mkdtemp`), removido em `finally`.
- Timeout de 600s por chamada de CLI.
- v1 não faz streaming real — cada CLI devolve o texto completo de uma vez (`yield` único), mesmo quando `--output-format json`/`stream-json` existir.
- Testes automatizados não devem invocar as CLIs de verdade (consumiriam cota real da assinatura do usuário) — sempre mockar `subprocess.run`/`shutil.which`.
- Referência da spec: `docs/superpowers/specs/2026-07-21-cli-auth-mode-design.md`.

---

### Task 1: `api/ai_cli_client.py` — funções puras (comando, input, parsing, detecção de binário)

**Files:**
- Create: `api/ai_cli_client.py`
- Create: `tests/__init__.py`
- Test: `tests/test_ai_cli_client.py`

**Interfaces:**
- Consumes: nada (módulo novo, independente).
- Produces (usado pelas Tasks 2 e 3):
  - `CLI_BINARIES: dict[str, str]` — mapa `provider -> nome do binário`.
  - `CLI_SYSTEM_PROMPT: str` — persona usada quando o provedor não tem flag de system prompt dedicada.
  - `cli_binary_status(provider: str) -> tuple[str | None, str | None]` — `(nome_binario, caminho_ou_None)`.
  - `build_cli_command(provider: str, model_override: str | None = None, codex_output_file: str | None = None) -> list[str]` — levanta `ValueError` se `provider` não suportado ou (para OpenAI) `codex_output_file` ausente.
  - `build_cli_input_text(provider: str, prompt: str) -> str`.
  - `extract_cli_json_text(raw_stdout: str) -> str`.

- [ ] **Step 1: Criar `tests/__init__.py` vazio**

```python
```

- [ ] **Step 2: Escrever os testes (vão falhar — o módulo `api/ai_cli_client.py` ainda não existe)**

Criar `tests/test_ai_cli_client.py`:

```python
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
```

- [ ] **Step 3: Rodar os testes para confirmar que falham (módulo ainda não existe)**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_ai_cli_client -v`
Expected: `ModuleNotFoundError: No module named 'api.ai_cli_client'`

- [ ] **Step 4: Implementar `api/ai_cli_client.py`**

```python
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
```

- [ ] **Step 5: Rodar os testes novamente para confirmar que passam**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_ai_cli_client -v`
Expected: `OK` (14 testes passando)

- [ ] **Step 6: Commit**

```bash
git add api/ai_cli_client.py tests/__init__.py tests/test_ai_cli_client.py
git commit -m "feat: adiciona funções puras de montagem de comando CLI dos provedores de IA"
```

---

### Task 2: `api/ai_cli_client.py` — execução do subprocesso e orquestração (`generate_via_cli`)

**Files:**
- Modify: `api/ai_cli_client.py`
- Test: `tests/test_ai_cli_client.py`

**Interfaces:**
- Consumes: `CLI_BINARIES`, `build_cli_command`, `build_cli_input_text`, `extract_cli_json_text` (Task 1, mesmo módulo).
- Produces (usado pela Task 3): `generate_via_cli(provider: str, prompt: str, model_override: str | None = None, timeout: int = 600) -> Generator[str, None, None]` — gerador que faz `yield` do texto completo da resposta uma única vez; levanta `RuntimeError` se o binário não for encontrado, o processo retornar erro, ou expirar o timeout.

- [ ] **Step 1: Adicionar os testes (vão falhar — as funções ainda não existem)**

Adicionar ao final de `tests/test_ai_cli_client.py` (antes do `if __name__ == "__main__":`):

```python
import os
import subprocess
import tempfile

from api.ai_cli_client import generate_via_cli


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
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_ai_cli_client -v`
Expected: `ImportError: cannot import name 'generate_via_cli'`

- [ ] **Step 3: Implementar `_run_cli_subprocess` e `generate_via_cli`**

Adicionar ao final de `api/ai_cli_client.py` (após as funções da Task 1; adicionar `import os`, `import subprocess`, `import tempfile` ao topo do arquivo, junto de `import json` e `import shutil`):

```python
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
            _run_cli_subprocess(cmd, input_text, scratch_dir, timeout)
            with open(output_file, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            cmd = build_cli_command(provider, model_override)
            stdout = _run_cli_subprocess(cmd, input_text, scratch_dir, timeout)
            text = extract_cli_json_text(stdout)

        yield text
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
```

- [ ] **Step 4: Rodar os testes novamente para confirmar que passam**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_ai_cli_client -v`
Expected: `OK` (19 testes passando)

- [ ] **Step 5: Commit**

```bash
git add api/ai_cli_client.py tests/test_ai_cli_client.py
git commit -m "feat: adiciona execução sandboxed do subprocesso das CLIs de IA"
```

---

### Task 3: `api/ai_api.py` — `AIClient` ganha `auth_mode` e delega para `ai_cli_client`

**Files:**
- Modify: `api/ai_api.py`
- Test: `tests/test_ai_api_cli_mode.py`

**Interfaces:**
- Consumes: `api.ai_cli_client.generate_via_cli` (Task 2).
- Produces (usado pela Task 6): `AIClient(provider, api_key, auth_mode="api_key", cli_model_override=None)` — construtor com dois parâmetros novos, ambos opcionais e retrocompatíveis.

- [ ] **Step 1: Escrever o teste (vai falhar — `AIClient` ainda não aceita `auth_mode`)**

Criar `tests/test_ai_api_cli_mode.py`:

```python
import unittest
from unittest.mock import patch

from api.ai_api import AIClient


class TestAiClientCliMode(unittest.TestCase):
    def test_get_available_models_returns_empty_in_cli_mode(self):
        client = AIClient("Anthropic", api_key="", auth_mode="cli")
        self.assertEqual(client.get_available_models(), [])

    def test_generate_audit_report_delegates_to_cli_client(self):
        client = AIClient("Anthropic", api_key="", auth_mode="cli", cli_model_override="opus")

        with patch("api.ai_api.ai_cli_client.generate_via_cli") as mock_generate:
            mock_generate.return_value = iter(["texto do relatório"])
            chunks = list(client.generate_audit_report({"host": 1}, "modelo-ignorado"))

        self.assertEqual(chunks, ["texto do relatório"])
        args, kwargs = mock_generate.call_args
        self.assertEqual(args[0], "Anthropic")
        self.assertIn("host", args[1])  # o prompt monta o JSON dos dados de auditoria
        self.assertEqual(kwargs.get("model_override") or args[2], "opus")

    def test_default_auth_mode_is_api_key(self):
        client = AIClient("Anthropic", api_key="sk-fake")
        self.assertEqual(client.auth_mode, "api_key")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_ai_api_cli_mode -v`
Expected: `TypeError: __init__() got an unexpected keyword argument 'auth_mode'`

- [ ] **Step 3: Modificar `api/ai_api.py`**

No topo do arquivo, adicionar o import (junto dos demais imports):

```python
from api import ai_cli_client
```

Substituir o construtor (linhas 11-13 do arquivo atual):

```python
    def __init__(self, provider, api_key):
        self.provider = provider
        self.api_key = api_key
```

por:

```python
    def __init__(self, provider, api_key, auth_mode="api_key", cli_model_override=None):
        self.provider = provider
        self.api_key = api_key
        self.auth_mode = auth_mode
        self.cli_model_override = cli_model_override
```

No início de `get_available_models` (logo após a docstring, antes de `if not self.api_key:`), adicionar:

```python
        if self.auth_mode == "cli":
            return []
```

Em `generate_audit_report`, logo após o bloco que monta `prompt` (após o `except FileNotFoundError: raise FileNotFoundError(...)` e antes de `if self.provider == "Google Gemini":`), adicionar:

```python
        if self.auth_mode == "cli":
            yield from ai_cli_client.generate_via_cli(self.provider, prompt, self.cli_model_override)
            return

```

- [ ] **Step 4: Rodar o teste novamente para confirmar que passa**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_ai_api_cli_mode -v`
Expected: `OK` (3 testes passando)

- [ ] **Step 5: Rodar toda a suíte para garantir que nada quebrou**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest discover -s tests -v`
Expected: `OK` (22 testes passando)

- [ ] **Step 6: Commit**

```bash
git add api/ai_api.py tests/test_ai_api_cli_mode.py
git commit -m "feat: AIClient delega para a CLI local quando auth_mode=cli"
```

---

### Task 4: `gui/manage_accounts_view.py` — toggle de autenticação por conta

**Files:**
- Modify: `gui/manage_accounts_view.py` (reescrita completa — arquivo pequeno, 95 linhas, mais claro reescrever do que remendar)

**Interfaces:**
- Consumes: `api.ai_cli_client.cli_binary_status` (Task 1).
- Produces (usado pela Task 5): contas salvas em `self.parent.ai_accounts[nome]` agora incluem as chaves `"auth_mode"` (`"api_key"`/`"cli"`) e `"cli_model_override"` (string, pode ser vazia).

Sem teste automatizado — é uma janela Tkinter (`ttk.Toplevel`), o projeto não tem infraestrutura de teste de GUI e não vamos introduzir uma só para isso. Verificação é manual (Step 3).

- [ ] **Step 1: Substituir o conteúdo completo do arquivo**

```python
import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT
from api.ai_cli_client import cli_binary_status

class ManageAccountsWindow(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Gerenciar Contas de IA")
        self.geometry("500x400")
        self.grab_set()

        self.account_list = list(self.parent.ai_accounts.keys())
        self.selected_account = ttk.StringVar(value="<Nova Conta>")

        self.account_name_var = ttk.StringVar()
        self.base_provider_var = ttk.StringVar(value="Google Gemini")
        self.token_var = ttk.StringVar()
        self.auth_mode_var = ttk.StringVar(value="api_key")
        self.model_override_var = ttk.StringVar()
        self.cli_status_var = ttk.StringVar(value="")

        self.create_widgets()
        self.base_provider_var.trace_add("write", self.on_base_provider_change)
        self.on_account_select()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=BOTH, expand=True)

        row0 = ttk.Frame(main_frame)
        row0.pack(fill=X, pady=5)
        ttk.Label(row0, text="Selecionar Conta:", width=18).pack(side=LEFT)
        self.combo_accounts = ttk.Combobox(row0, textvariable=self.selected_account, values=["<Nova Conta>"] + self.account_list, state="readonly")
        self.combo_accounts.pack(side=LEFT, fill=X, expand=True)
        self.selected_account.trace_add("write", self.on_account_select)

        row1 = ttk.Frame(main_frame)
        row1.pack(fill=X, pady=5)
        ttk.Label(row1, text="Nome da Conta:", width=18).pack(side=LEFT)
        ttk.Entry(row1, textvariable=self.account_name_var).pack(side=LEFT, fill=X, expand=True)

        row2 = ttk.Frame(main_frame)
        row2.pack(fill=X, pady=5)
        ttk.Label(row2, text="Provedor Base:", width=18).pack(side=LEFT)
        ttk.Combobox(row2, textvariable=self.base_provider_var, values=["Google Gemini", "OpenAI", "Anthropic", "Ollama"], state="readonly").pack(side=LEFT, fill=X, expand=True)

        row_toggle = ttk.Frame(main_frame)
        row_toggle.pack(fill=X, pady=5)
        self.auth_mode_toggle = ttk.Checkbutton(
            row_toggle,
            text="Usar CLI local (assinatura) em vez de API Key",
            variable=self.auth_mode_var,
            onvalue="cli",
            offvalue="api_key",
            bootstyle="round-toggle",
            command=self.on_auth_mode_change
        )
        self.auth_mode_toggle.pack(side=LEFT)

        self.row_token = ttk.Frame(main_frame)
        ttk.Label(self.row_token, text="Token/URL:", width=18).pack(side=LEFT)
        ttk.Entry(self.row_token, textvariable=self.token_var, show="*").pack(side=LEFT, fill=X, expand=True)

        self.row_cli = ttk.Frame(main_frame)
        ttk.Label(self.row_cli, text="Modelo (opcional):", width=18).pack(side=LEFT)
        ttk.Entry(self.row_cli, textvariable=self.model_override_var).pack(side=LEFT, fill=X, expand=True)

        self.row_status = ttk.Frame(main_frame)
        ttk.Label(self.row_status, text="", width=18).pack(side=LEFT)
        ttk.Label(self.row_status, textvariable=self.cli_status_var).pack(side=LEFT, fill=X, expand=True)

        self.btn_frame = ttk.Frame(main_frame)
        self.btn_frame.pack(fill=X, pady=20)
        ttk.Button(self.btn_frame, text="Salvar", bootstyle="success", command=self.save_account).pack(side=LEFT, padx=5)
        ttk.Button(self.btn_frame, text="Remover", bootstyle="danger", command=self.remove_account).pack(side=LEFT, padx=5)
        ttk.Button(self.btn_frame, text="Cancelar", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)

        self.row_token.pack(fill=X, pady=5, before=self.btn_frame)

    def on_auth_mode_change(self):
        if self.auth_mode_var.get() == "cli":
            self.row_token.pack_forget()
            self.row_cli.pack(fill=X, pady=5, before=self.btn_frame)
            self.row_status.pack(fill=X, pady=5, before=self.btn_frame)
            self.update_cli_status()
        else:
            self.row_cli.pack_forget()
            self.row_status.pack_forget()
            self.row_token.pack(fill=X, pady=5, before=self.btn_frame)

    def on_base_provider_change(self, *args):
        if self.base_provider_var.get() == "Ollama":
            self.auth_mode_var.set("api_key")
            self.auth_mode_toggle.configure(state="disabled")
            self.on_auth_mode_change()
        else:
            self.auth_mode_toggle.configure(state="normal")
        self.update_cli_status()

    def update_cli_status(self):
        if self.auth_mode_var.get() != "cli":
            return
        binary, path = cli_binary_status(self.base_provider_var.get())
        if not binary:
            self.cli_status_var.set("Provedor sem suporte a CLI local.")
        elif path:
            self.cli_status_var.set(f"Binário detectado: {path} ✅")
        else:
            self.cli_status_var.set(f"Binário '{binary}' não encontrado no PATH ❌")

    def on_account_select(self, *args):
        selected = self.selected_account.get()
        if selected == "<Nova Conta>":
            self.account_name_var.set("")
            self.base_provider_var.set("Google Gemini")
            self.token_var.set("")
            self.auth_mode_var.set("api_key")
            self.model_override_var.set("")
        elif selected in self.parent.ai_accounts:
            account = self.parent.ai_accounts[selected]
            self.account_name_var.set(selected)
            self.base_provider_var.set(account["provider"])
            self.token_var.set(account["api_key"])
            self.auth_mode_var.set(account.get("auth_mode", "api_key"))
            self.model_override_var.set(account.get("cli_model_override", ""))
        self.on_auth_mode_change()

    def save_account(self):
        old_name = self.selected_account.get()
        new_name = self.account_name_var.get().strip()
        base_prov = self.base_provider_var.get()
        token = self.token_var.get().strip()
        auth_mode = self.auth_mode_var.get()
        model_override = self.model_override_var.get().strip()

        if not new_name:
            return

        if old_name != "<Nova Conta>" and old_name != new_name:
            if old_name in self.parent.ai_accounts:
                del self.parent.ai_accounts[old_name]

        self.parent.ai_accounts[new_name] = {
            "provider": base_prov,
            "api_key": token,
            "auth_mode": auth_mode,
            "cli_model_override": model_override
        }

        self.parent.save_settings()
        self.parent.refresh_accounts(new_name)
        self.destroy()

    def remove_account(self):
        selected = self.selected_account.get()
        if selected != "<Nova Conta>" and selected in self.parent.ai_accounts:
            del self.parent.ai_accounts[selected]
            self.parent.save_settings()

            next_acc = list(self.parent.ai_accounts.keys())[0] if self.parent.ai_accounts else ""
            self.parent.refresh_accounts(next_acc)
            self.destroy()
```

- [ ] **Step 2: Verificar sintaxe**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m py_compile gui/manage_accounts_view.py`
Expected: nenhuma saída (sucesso)

- [ ] **Step 3: Verificação manual (requer Tasks 5 e 6 aplicadas para abrir a janela de dentro do app; se estiver executando esta task isoladamente, adie este passo até a Task 6 estar pronta)**

1. Rodar `python3 main.py`.
2. Clicar em "⚙️ Gerenciar" ao lado de "Conta/Provedor".
3. Selecionar `<Nova Conta>`, escolher "Provedor Base: Anthropic", ativar o toggle "Usar CLI local".
   - Esperado: campo "Token/URL" some, aparecem "Modelo (opcional)" e o status do binário (`/usr/bin/claude ✅`, já que está instalado).
4. Trocar "Provedor Base" para "Ollama" com o toggle ainda ativo.
   - Esperado: toggle é desativado automaticamente e volta para "API Key" (Ollama não tem CLI local).
5. Desativar o toggle manualmente.
   - Esperado: campo "Token/URL" volta a aparecer, "Modelo (opcional)" e o status somem.
6. Salvar uma conta em modo CLI e reabrir "Gerenciar Contas" — confirmar que o toggle e o modelo override persistem corretamente ao reselecionar a conta.

- [ ] **Step 4: Commit**

```bash
git add gui/manage_accounts_view.py
git commit -m "feat: adiciona toggle de autenticação via CLI local em Gerenciar Contas"
```

---

### Task 5: `gui/main_view.py` — propagar `auth_mode`, desabilitar campo de chave, mostrar status

**Files:**
- Modify: `gui/main_view.py`

**Interfaces:**
- Consumes: `api.ai_cli_client.cli_binary_status` (Task 1).
- Produces (usado pela Task 6): `MainView.get_selected_auth_mode() -> str`, `MainView.get_selected_cli_model_override() -> str`.

Sem teste automatizado (GUI Tkinter). Verificação manual no Step 6.

- [ ] **Step 1: Import novo**

No topo do arquivo, junto dos demais imports locais (`from gui.manage_accounts_view import ManageAccountsWindow`, etc.), adicionar:

```python
from api.ai_cli_client import cli_binary_status
```

- [ ] **Step 2: Adicionar `auth_mode`/`cli_model_override` às contas padrão**

Localizar (no `__init__`):

```python
        self.ai_accounts = {
            "Google Gemini": {"provider": "Google Gemini", "api_key": os.getenv("GEMINI_API_KEY", "")},
            "OpenAI": {"provider": "OpenAI", "api_key": os.getenv("OPENAI_API_KEY", "")},
            "Anthropic": {"provider": "Anthropic", "api_key": os.getenv("ANTHROPIC_API_KEY", "")},
            "Ollama": {"provider": "Ollama", "api_key": os.getenv("OLLAMA_URL", "http://localhost:11434")}
        }
```

Substituir por:

```python
        self.ai_accounts = {
            "Google Gemini": {"provider": "Google Gemini", "api_key": os.getenv("GEMINI_API_KEY", ""), "auth_mode": "api_key", "cli_model_override": ""},
            "OpenAI": {"provider": "OpenAI", "api_key": os.getenv("OPENAI_API_KEY", ""), "auth_mode": "api_key", "cli_model_override": ""},
            "Anthropic": {"provider": "Anthropic", "api_key": os.getenv("ANTHROPIC_API_KEY", ""), "auth_mode": "api_key", "cli_model_override": ""},
            "Ollama": {"provider": "Ollama", "api_key": os.getenv("OLLAMA_URL", "http://localhost:11434"), "auth_mode": "api_key", "cli_model_override": ""}
        }
```

- [ ] **Step 3: Preservar `auth_mode`/`cli_model_override` ao salvar contas em `save_settings`**

Localizar:

```python
        # Salva o dicionário de contas sem vazar as API Keys para o arquivo JSON
        ai_accounts_safe = {}
        for k, v in self.ai_accounts.items():
            ai_accounts_safe[k] = {"provider": v.get("provider", k), "api_key": ""}
        self.settings["ai_accounts"] = ai_accounts_safe
```

Substituir por:

```python
        # Salva o dicionário de contas sem vazar as API Keys para o arquivo JSON
        ai_accounts_safe = {}
        for k, v in self.ai_accounts.items():
            ai_accounts_safe[k] = {
                "provider": v.get("provider", k),
                "api_key": "",
                "auth_mode": v.get("auth_mode", "api_key"),
                "cli_model_override": v.get("cli_model_override", "")
            }
        self.settings["ai_accounts"] = ai_accounts_safe
```

- [ ] **Step 4: Novos métodos de leitura + atualização de `on_provider_change`**

Localizar:

```python
    def on_provider_change(self, *args):
        account = self.ai_provider_var.get()
        account_info = self.ai_accounts.get(account, {})
        self.ai_key_var.set(account_info.get("api_key", ""))
        
        base_provider = account_info.get("provider", "")
        if hasattr(self, 'ai_key_entry'):
            if base_provider == "Ollama":
                self.ai_key_entry.configure(show="")
            else:
                self.ai_key_entry.configure(show="*")

    def get_selected_base_provider(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("provider", "Google Gemini")
```

Substituir por:

```python
    def on_provider_change(self, *args):
        account = self.ai_provider_var.get()
        account_info = self.ai_accounts.get(account, {})
        self.ai_key_var.set(account_info.get("api_key", ""))

        base_provider = account_info.get("provider", "")
        auth_mode = account_info.get("auth_mode", "api_key")
        if hasattr(self, 'ai_key_entry'):
            if base_provider == "Ollama":
                self.ai_key_entry.configure(show="")
            else:
                self.ai_key_entry.configure(show="*")
            self.ai_key_entry.configure(state="disabled" if auth_mode == "cli" else "normal")
        if hasattr(self, 'ai_auth_mode_label'):
            if auth_mode == "cli":
                binary, path = cli_binary_status(base_provider)
                if path:
                    self.ai_auth_mode_label.configure(text=f"Modo: CLI local ({binary}) ✅")
                else:
                    self.ai_auth_mode_label.configure(text=f"Modo: CLI local ({binary or '?'}) — binário não encontrado no PATH ❌")
            else:
                self.ai_auth_mode_label.configure(text="")

    def get_selected_base_provider(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("provider", "Google Gemini")

    def get_selected_auth_mode(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("auth_mode", "api_key")

    def get_selected_cli_model_override(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("cli_model_override", "")
```

- [ ] **Step 5: Adicionar o label de status na aba de Configurações**

Localizar:

```python
        ttk.Label(ai_frame, text="Key / URL:").grid(row=1, column=0, sticky="w", pady=5)
        self.ai_key_entry = ttk.Entry(ai_frame, textvariable=self.ai_key_var, show="*")
        self.ai_key_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=5)

        # Atualiza a visibilidade do campo caso a IA salva por padrão seja o Ollama
        self.on_provider_change()
        
        ttk.Button(ai_frame, text="🔄 Validar Conexão / Atualizar Modelos", command=self.validate_and_load_models, bootstyle="info-outline").grid(row=2, column=0, columnspan=3, pady=(10, 0))
```

Substituir por:

```python
        ttk.Label(ai_frame, text="Key / URL:").grid(row=1, column=0, sticky="w", pady=5)
        self.ai_key_entry = ttk.Entry(ai_frame, textvariable=self.ai_key_var, show="*")
        self.ai_key_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=5)

        self.ai_auth_mode_label = ttk.Label(ai_frame, text="", bootstyle="info")
        self.ai_auth_mode_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=5)

        # Atualiza a visibilidade do campo caso a IA salva por padrão seja o Ollama
        self.on_provider_change()

        ttk.Button(ai_frame, text="🔄 Validar Conexão / Atualizar Modelos", command=self.validate_and_load_models, bootstyle="info-outline").grid(row=3, column=0, columnspan=3, pady=(10, 0))
```

- [ ] **Step 6: Verificar sintaxe e rodar a suíte de testes existente (garantir que nada quebrou)**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m py_compile gui/main_view.py && python3 -m unittest discover -s tests -v`
Expected: sem erro de sintaxe; `OK` nos testes (esta task não adiciona testes novos, é só para checar regressão)

- [ ] **Step 7: Verificação manual**

1. Rodar `python3 main.py`.
2. Na aba "⚙️ Configurações", trocar "Conta/Provedor" para uma conta em modo CLI (criada na verificação manual da Task 4).
   - Esperado: campo "Key / URL" fica desabilitado (cinza); abaixo dele aparece "Modo: CLI local (claude) ✅".
3. Trocar de volta para uma conta em API Key.
   - Esperado: campo "Key / URL" volta a ficar editável; o label de status some.

- [ ] **Step 8: Commit**

```bash
git add gui/main_view.py
git commit -m "feat: main_view mostra e propaga o modo de autenticação CLI local"
```

---

### Task 6: `core/controller.py` — propagar `auth_mode` ao `AIClient` e ajustar validação

**Files:**
- Modify: `core/controller.py`
- Test: `tests/test_controller_cli_mode.py`

**Interfaces:**
- Consumes: `MainView.get_selected_auth_mode()`, `MainView.get_selected_cli_model_override()` (Task 5); `AIClient(provider, api_key, auth_mode, cli_model_override)` (Task 3).
- Produces: nada consumido por tasks futuras (fim da cadeia de wiring).

**Contexto importante:** hoje `run_audit_flow` exige `ai_key` não-vazio (`if not all([z_url, ai_key, ai_mod])`) antes de iniciar a auditoria. Em modo CLI o campo de API key fica vazio de propósito — sem este ajuste, contas em modo CLI nunca conseguiriam iniciar uma auditoria (a validação bloquearia antes mesmo de chegar no `AIClient`). Este é o motivo do teste no Step 1.

- [ ] **Step 1: Escrever o teste (vai falhar — `load_models_async` ainda não trata `auth_mode`)**

Criar `tests/test_controller_cli_mode.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from core.controller import Controller


def make_mock_view(auth_mode="api_key", cli_model_override=""):
    view = MagicMock()
    view.get_selected_base_provider.return_value = "Anthropic"
    view.get_selected_auth_mode.return_value = auth_mode
    view.get_selected_cli_model_override.return_value = cli_model_override
    view.ai_key_var.get.return_value = ""
    return view


class TestLoadModelsAsyncCliMode(unittest.TestCase):
    def test_cli_mode_skips_network_call_and_uses_placeholder(self):
        view = make_mock_view(auth_mode="cli", cli_model_override="")
        with patch("core.controller.threading.Thread") as mock_thread:
            controller = Controller(view=view)
            view.update_model_list.reset_mock()
            mock_thread.reset_mock()

            controller.load_models_async()

        mock_thread.assert_not_called()
        view.update_model_list.assert_called_once_with(
            ["(modelo padrão da CLI)"], "(modelo padrão da CLI)"
        )

    def test_cli_mode_uses_configured_override(self):
        view = make_mock_view(auth_mode="cli", cli_model_override="opus")
        with patch("core.controller.threading.Thread"):
            controller = Controller(view=view)
            view.update_model_list.reset_mock()

            controller.load_models_async()

        view.update_model_list.assert_called_once_with(["opus"], "opus")

    def test_api_key_mode_still_starts_a_thread(self):
        view = make_mock_view(auth_mode="api_key")
        view.ai_key_var.get.return_value = "sk-fake"
        with patch("core.controller.threading.Thread") as mock_thread:
            controller = Controller(view=view)
            mock_thread.reset_mock()

            controller.load_models_async()

        mock_thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_controller_cli_mode -v`
Expected: `AttributeError` ou `AssertionError` — `load_models_async` ainda chama `ai_key_var.get()` incondicionalmente e nunca usa `get_selected_auth_mode`.

- [ ] **Step 3: Modificar `core/controller.py`**

Localizar:

```python
    def load_models_async(self):
        """Inicia a busca pelos modelos na IA escolhida."""
        provider = self.view.get_selected_base_provider()
        api_key = self.view.ai_key_var.get().strip()
        
        if not api_key:
            self.view.update_model_list(["Insira a API Key primeiro..."], None)
            return
            
        self.view.model_combo.set(f"Conectando à {provider}...")
        thread = threading.Thread(target=self._fetch_and_update_models)
        thread.daemon = True
        thread.start()
```

Substituir por:

```python
    def load_models_async(self):
        """Inicia a busca pelos modelos na IA escolhida."""
        provider = self.view.get_selected_base_provider()

        if self.view.get_selected_auth_mode() == "cli":
            override = self.view.get_selected_cli_model_override()
            model = override if override else "(modelo padrão da CLI)"
            self.view.update_model_list([model], model)
            return

        api_key = self.view.ai_key_var.get().strip()

        if not api_key:
            self.view.update_model_list(["Insira a API Key primeiro..."], None)
            return

        self.view.model_combo.set(f"Conectando à {provider}...")
        thread = threading.Thread(target=self._fetch_and_update_models)
        thread.daemon = True
        thread.start()
```

Localizar (início de `run_audit_flow`):

```python
    def run_audit_flow(self, use_cache):
        z_url = self.view.zabbix_url_var.get().strip()
        auth_method = self.view.zabbix_auth_method_var.get()
        z_user = self.view.zabbix_user_var.get().strip()
        z_pass = self.view.zabbix_pass_var.get().strip()
        z_token = self.view.zabbix_token_var.get().strip()
        verify_ssl = not self.view.zabbix_ignore_ssl_var.get()
        anonymize = self.view.anonymize_data_var.get()
        ai_prov = self.view.get_selected_base_provider()
        ai_key = self.view.ai_key_var.get().strip()
        ai_mod = self.view.get_selected_model()
        history_limit = self.view.history_limit_var.get()
        sample_limit = self.view.sample_limit_var.get()
        template_limit = self.view.template_limit_var.get()
        only_used_templates = self.view.only_used_templates_var.get()
        
        if not all([z_url, ai_key, ai_mod]):
            self.view.log("ERRO: Preencha todas as configurações na aba 'Configurações' antes de iniciar.", "danger")
            self.view.set_ui_state('normal')
            return
```

Substituir por:

```python
    def run_audit_flow(self, use_cache):
        z_url = self.view.zabbix_url_var.get().strip()
        auth_method = self.view.zabbix_auth_method_var.get()
        z_user = self.view.zabbix_user_var.get().strip()
        z_pass = self.view.zabbix_pass_var.get().strip()
        z_token = self.view.zabbix_token_var.get().strip()
        verify_ssl = not self.view.zabbix_ignore_ssl_var.get()
        anonymize = self.view.anonymize_data_var.get()
        ai_prov = self.view.get_selected_base_provider()
        ai_key = self.view.ai_key_var.get().strip()
        ai_mod = self.view.get_selected_model()
        ai_auth_mode = self.view.get_selected_auth_mode()
        ai_cli_model_override = self.view.get_selected_cli_model_override()
        history_limit = self.view.history_limit_var.get()
        sample_limit = self.view.sample_limit_var.get()
        template_limit = self.view.template_limit_var.get()
        only_used_templates = self.view.only_used_templates_var.get()

        required_fields = [z_url, ai_mod] if ai_auth_mode == "cli" else [z_url, ai_key, ai_mod]
        if not all(required_fields):
            self.view.log("ERRO: Preencha todas as configurações na aba 'Configurações' antes de iniciar.", "danger")
            self.view.set_ui_state('normal')
            return
```

Localizar:

```python
            ai_client = ai_api.AIClient(ai_prov, ai_key)
```

Substituir por:

```python
            ai_client = ai_api.AIClient(ai_prov, ai_key, auth_mode=ai_auth_mode, cli_model_override=ai_cli_model_override)
```

- [ ] **Step 4: Rodar o teste novamente para confirmar que passa**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_controller_cli_mode -v`
Expected: `OK` (3 testes passando)

- [ ] **Step 5: Rodar toda a suíte**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest discover -s tests -v`
Expected: `OK` (25 testes passando)

- [ ] **Step 6: Verificação manual do bug que este task corrige**

1. Rodar `python3 main.py`, selecionar uma conta em modo CLI (Anthropic/`claude`).
2. Deixar o campo "Key / URL" vazio (já vem desabilitado/vazio).
3. Preencher URL/credenciais do Zabbix normalmente e clicar "▶ Iniciar Auditoria".
   - Esperado: a auditoria **não** para com "ERRO: Preencha todas as configurações" — ela segue para a coleta do Zabbix e, na etapa de IA, tenta rodar `claude -p ...` de verdade (isso consome uso real da sua assinatura Claude — só faça este passo se estiver de acordo; caso contrário, apenas confirme visualmente que passou da validação e cancele com "⏹ Cancelar" antes da etapa de IA).

- [ ] **Step 7: Commit**

```bash
git add core/controller.py tests/test_controller_cli_mode.py
git commit -m "fix: controller propaga auth_mode ao AIClient e permite iniciar auditoria sem API key em modo CLI"
```

---

### Task 7: Atualizar `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Adicionar nova subseção em "✨ Funcionalidades"**

Localizar a linha (dentro da lista de funcionalidades):

```
- **Suporte Multi-IA**: Compatível com provedores líderes de mercado (**Google Gemini**, **OpenAI**, **Anthropic Claude**) e suporte a execução de LLMs locais via **Ollama** para ambientes restritos ou isolados.
```

Adicionar logo abaixo dela (nova linha da mesma lista):

```
- **Autenticação via CLI local (assinatura)**: Além de API key, cada conta Anthropic/OpenAI/Google Gemini pode usar a CLI oficial já instalada e autenticada na máquina (`claude`, `codex`, `gemini`) em vez de cobrança por token — útil para quem já tem Claude Pro/Max, ChatGPT Plus/Pro ou Gemini Advanced. A aplicação chama a CLI em modo headless/somente-leitura (sem acesso a arquivos ou shell), nunca lê ou manipula o token OAuth diretamente. Veja "Modo CLI local" abaixo.
```

- [ ] **Step 2: Adicionar nova seção completa antes de "## ⚠️ Avisos e Segurança"**

Localizar:

```
## ⚠️ Avisos e Segurança
```

Inserir imediatamente antes:

```markdown
## 🖥️ Modo CLI local (alternativa à API Key)

Em vez de pagar por token via API, cada conta de IA (Anthropic, OpenAI, Google Gemini) pode ser configurada para usar a CLI oficial do provedor, já autenticada na sua máquina com a sua assinatura:

| Provedor | CLI | Autenticar com |
|---|---|---|
| Anthropic | [`claude`](https://docs.claude.com/claude-code) (Claude Code) | `claude login` |
| OpenAI | [`codex`](https://developers.openai.com/codex/cli) | `codex login` |
| Google Gemini | [`gemini`](https://github.com/google-gemini/gemini-cli) | `gemini` (fluxo de login na primeira execução) |

**Como habilitar:** em "⚙️ Gerenciar" (ao lado de "Conta/Provedor"), ative o toggle "Usar CLI local (assinatura) em vez de API Key" na conta desejada. A tela mostra se o binário foi encontrado no `PATH`. Ollama não tem esse modo — já é local.

**Importante:**
- O binário precisa estar instalado e autenticado (`claude login`/`codex login`/login do `gemini`) *antes* de rodar uma auditoria nesse modo — a aplicação não faz login por você e não lê/gera tokens OAuth.
- Esse modo usa o modo headless/scriptável oficial de cada CLI, sempre com ferramentas desabilitadas ou sandbox somente-leitura (a aplicação nunca deixa a CLI executar comandos ou editar arquivos no seu sistema).
- Usar a assinatura fora da CLI/app oficial pode estar sujeito aos Termos de Uso do provedor — este modo usa a CLI oficial diretamente (não reimplementa o login), mas a responsabilidade pelo uso de acordo com a assinatura contratada é do usuário.
- A v1 não tem streaming incremental no modo CLI: o relatório aparece de uma vez quando a CLI termina, em vez de "digitando" aos poucos como no modo API key.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: documenta o modo de autenticação via CLI local no README"
```

---

### Task 8: Atualizar `TECHNICAL_REFERENCE.md`

**Files:**
- Modify: `TECHNICAL_REFERENCE.md`

- [ ] **Step 1: Adicionar nova entrada em "⚙️ Fluxos de Funcionamento Interno"**

Localizar o final da seção 4 (antes de "### 5. Renderização de Gráficos..."), ou seja, logo após:

```
* **Stream Mode:** O SDK da IA correspondente é chamado com `stream=True`. O `yield` do Python retorna os pedaços (*chunks*) do texto assim que chegam. O método `append_report_chunk` da GUI usa o `self.after(0, ...)` do Tkinter para desenhar essas letras na interface em tempo real de forma thread-safe.
```

Inserir logo abaixo (novo item "4.1", antes do "### 5."):

```markdown
### 4.1. Modo CLI local dos provedores de IA (`api/ai_cli_client.py`)

Alternativa ao SDK: quando a conta tem `auth_mode == "cli"`, `AIClient.generate_audit_report()` não chama nenhum SDK — delega para `ai_cli_client.generate_via_cli(provider, prompt, model_override)`, que roda o binário da CLI oficial do provedor (`claude`/`codex`/`gemini`) como subprocesso.

* **Por que não SDK/API key:** o objetivo é usar a assinatura (Claude Pro/Max, ChatGPT Plus/Pro, Gemini Advanced) do usuário, não cobrança por token. Isso é feito chamando a própria CLI oficial em modo headless — não reimplementando o fluxo OAuth dela (o que violaria os Termos de Uso de cada provedor e dependeria de Client IDs não documentados).
* **Sandboxing obrigatório:** as três CLIs são agentes de codificação por padrão (têm acesso a shell/arquivos). `generate_via_cli` sempre roda com ferramentas desabilitadas ou sandbox somente-leitura (`--allowedTools ""` no `claude`, `--sandbox read-only` no `codex`, `--approval-mode plan` no `gemini`) e com `cwd` em um diretório temporário isolado (removido em `finally`), para que a CLI se comporte só como motor de texto.
* **Entrada via stdin:** o prompt completo (JSON de auditoria + template) é enviado via stdin do subprocesso, nunca como argumento de linha de comando — evita estourar limites de tamanho de argumento do SO com JSONs grandes.
* **Extração da resposta:** `claude`/`gemini` usam `--output-format json`; `extract_cli_json_text` tenta as chaves `result`/`response`/`text`/`content` e cai para o stdout bruto se o schema não bater (defensivo — os schemas dessas CLIs não são um contrato público estável). `codex` grava a última mensagem direto em arquivo via `-o` (`--output-last-message`), sem necessidade de parsing.
* **Sem streaming na v1:** todas as três variantes fazem `yield` do texto completo de uma vez (sem incrementalidade) — os schemas de evento `stream-json` de `codex`/`gemini` não foram validados contra chamadas reais.
```

- [ ] **Step 2: Adicionar novo "Gotcha"**

Localizar, na seção "⚠️ Pontos Críticos de Atenção (Gotchas)":

```
- **Limpeza de Temp:** O gerador Mermaid cria instâncias e imagens temporárias. O bloco `finally` dentro da exportação deve ser mantido para garantir `shutil.rmtree()` e evitar esgotamento de disco no SO (inodes).
```

Adicionar logo abaixo:

```
- **Nunca use `claude --bare` em `ai_cli_client.py`:** essa flag desativa explicitamente a leitura de OAuth/keychain ("Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper... OAuth and keychain are never read") — quebraria exatamente a autenticação via assinatura que o modo CLI local depende. Reduções de overhead da CLI devem vir do `cwd` isolado (diretório temp sem `CLAUDE.md`/config de projeto por perto), não dessa flag.
```

- [ ] **Step 3: Commit**

```bash
git add TECHNICAL_REFERENCE.md
git commit -m "docs: documenta o mecanismo interno do modo CLI local no TECHNICAL_REFERENCE"
```

---

### Task 9: Verificação final ponta a ponta

**Files:** nenhum arquivo novo — só verificação.

- [ ] **Step 1: Rodar a suíte de testes completa**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest discover -s tests -v`
Expected: `OK` (25 testes passando, 0 falhas)

- [ ] **Step 2: Checar sintaxe de todos os arquivos Python tocados**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m py_compile api/ai_cli_client.py api/ai_api.py core/controller.py gui/main_view.py gui/manage_accounts_view.py`
Expected: nenhuma saída (sucesso)

- [ ] **Step 3 (opcional, consome cota real — confirme com o usuário antes): smoke test end-to-end com uma CLI real**

1. Criar uma conta "Anthropic (Claude Code)" em modo CLI local (já autenticada via `claude login` na sua máquina).
2. Carregar o cache de uma auditoria pequena (ou rodar uma nova) e clicar "🔄 Regerar (Apenas IA)".
3. Confirmar que o relatório aparece por completo na aba "Relatório Final" (sem efeito de streaming, conforme esperado na v1) e que nenhum arquivo foi criado/alterado fora do diretório temporário (`ls` no diretório do projeto antes/depois não deve mostrar diferenças).

- [ ] **Step 4: Commit final (se houver ajustes desta verificação)**

```bash
git add -A
git commit -m "chore: ajustes finais de verificação do modo CLI local"
```

(Pular este commit se nada precisou ser ajustado.)

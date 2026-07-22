# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python desktop GUI app (`ttkbootstrap`/Tkinter) that audits a Zabbix environment: it pulls metrics via the Zabbix JSON-RPC API, sends them to an LLM (Gemini, OpenAI, Anthropic, or local Ollama) to generate a prioritized technical audit report, renders Mermaid.js charts, and exports the result to PDF/DOCX/Markdown/TXT/ODT.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run
python main.py

# Test (unittest, stdlib — no pytest)
python3 -m unittest discover -s tests -v

# Docker (GUI over X11/Wayland via xhost)
./build_image.fish          # builds and pushes fernandord/auditoria-zabbix image
./exec_wayland.fish         # runs the container with X11/Wayland sockets mounted
```

`tests/` covers `api/ai_cli_client.py`, the CLI branch of `AIClient`, and the `auth_mode` wiring in `controller.py` — all via mocked `subprocess`/`shutil.which`, never real CLI calls. There is no linter/formatter configured — don't assume `ruff`/`black` are wired up. The GUI itself (`gui/*.py`) has no automated tests (Tkinter, no test framework for it in this repo) — verify GUI changes by actually running `python main.py`.

If a venv exists at `venv/` (`python -m venv venv && pip install -r requirements.txt`), always run tests through `venv/bin/python3` — the system `python3` typically lacks `google-genai`/`openai`/`anthropic`, and `api/ai_api.py` imports all three unconditionally at module level, so even CLI-mode-only tests fail to import without them.

Credentials (Zabbix + AI provider API keys) are read from the OS keyring (via the `keyring` package), not from `.env` in normal GUI use — `.env.example` documents the fallback/env-based config (`ZABBIX_URL`, `ZABBIX_USER`, `ZABBIX_PASS`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_URL`).

## Architecture

Loosely MVC, three layers wired together in `main.py`:

- **`gui/` (View)** — `ttkbootstrap` (Darkly theme) UI, runs on the Tkinter main thread.
  - `main_view.py` — main window, tabs, progress bar, report export engine, credential management via `keyring`.
  - `manage_accounts_view.py`, `manage_attachments_view.py`, `style_settings_view.py` — secondary modal windows, split out to keep `main_view.py` smaller.
- **`api/` (Model / integrations)**
  - `zabbix_api.py` — `ZabbixClient`: JSON-RPC protocol, auth, version detection, HA cluster node discovery, data collection/sampling.
  - `ai_api.py` — `AIClient`: unifies Gemini/OpenAI/Anthropic/Ollama behind one streaming interface. Each account has an `auth_mode`: `"api_key"` (default, uses the provider SDK) or `"cli"` (delegates to `ai_cli_client.py`).
  - `ai_cli_client.py` — runs the provider's official CLI (`claude`/`codex`/`gemini`) as a sandboxed subprocess instead of an API key, for users who want to spend a Claude Pro/Max, ChatGPT Plus/Pro, or Gemini Advanced subscription instead of metered API billing. See "CLI auth mode" below.
- **`core/controller.py` (Controller)** — `Controller` orchestrates user actions, runs work on background threads to keep the GUI responsive, and drives GUI state (buttons, progress bar).
- **`core/chart_renderer.py`** — parses the AI-generated `xychart-beta` Mermaid syntax and renders it to PNG via matplotlib (Agg backend, OO API only). Used by both `gui/main_view.py` (report export) and `gui/style_settings_view.py` (style preview).
- **`prompts/report_template.txt`** — the system prompt: persona, required report structure, formatting rules (e.g. mandatory Mermaid.js usage).
- **`templates/`** — `report_template.typ` (Typst template: cover page, margins, page numbering, for PDF export) and `report_template.docx` (Pandoc reference doc for Word export).

### Threading rule (critical)

Never touch Tkinter widgets (`self.log_text`, `self.progress_bar`, etc.) directly from `core/controller.py` background threads — always go through the view's thread-safe methods (`self.view.log()`, `self.after(0, ...)`). Doing otherwise causes silent segfaults, not exceptions.

### Zabbix API version/auth handling

Zabbix changed auth from payload-based (`"auth": token`) to `Authorization: Bearer` headers in 6.4+. `discover_version()` does an unauthenticated `apiinfo.version` call first and sets `self.use_header_auth`; `api_call()` then injects the token in the right place per call.

### HA cluster node discovery (`get_active_node_hostid`)

Triple fallback to find the *Active* node in an HA cluster (avoids collecting empty/flatline metrics from a Standby node):
1. `hanode.get` (native, Zabbix 6.0+)
2. Compare `clock` freshness of `zabbix[process,poller...]` items across hosts
3. Static fallback to a host literally named `"Zabbix server"`

### Data sampling for trend charts

Zabbix history can return millions of rows — too much for an LLM context window. `collect_data()` sends only Top-N items (GUI-controlled) and, for trend charts, fetches N recent points (e.g. 500) then uses reverse-stride indexing (`history_data[0::step][:15]`) to compress hours/days of history into ~15 representative points instead of the most recent 15 minutes.

### Report generation flow

`Controller` merges the Zabbix JSON, custom on-screen instructions, and attached OS evidence text (`evidencias_os.txt`) into `prompts/report_template.txt`, then calls `AIClient` with `stream=True`. Chunks are yielded and drawn into the GUI live via `self.after(0, ...)` (thread-safe).

### CLI auth mode (`api/ai_cli_client.py`)

An alternative to API-key billing: instead of calling a provider SDK, `generate_via_cli(provider, prompt, model_override)` shells out to the user's own already-authenticated CLI (`claude`, `codex`, or `gemini`) in headless mode — this uses the CLI's officially-supported non-interactive mode, not a reimplementation of its OAuth flow (which would violate the provider's Terms of Service). Every provider runs with tools/write-access disabled (`--allowedTools ""` for claude, `--sandbox read-only` for codex, `--approval-mode plan` for gemini), cwd in an isolated temp dir removed in `finally`, prompt sent via stdin (not argv, to avoid OS arg-length limits with large audit JSONs), and a 600s timeout. No streaming in v1 — one `yield` of the full response text. Toggled per-account in `gui/manage_accounts_view.py`'s "Usar CLI local" switch; `MainView.get_selected_auth_mode()`/`get_selected_cli_model_override()` feed it through `core/controller.py` into `AIClient`.

### Chart rendering + export pipeline

1. `core/chart_renderer.py` extracts ```mermaid``` blocks, parses the `xychart-beta` syntax (title/x-axis/y-axis/line|bar), and renders each to PNG via matplotlib (OO API + Agg, never `pyplot`) in a temp dir. Non-`xychart-beta` or unparseable blocks are left as code blocks — export never aborts because of one bad chart.
2. Markdown mermaid blocks are replaced with image links to those PNGs.
3. `pypandoc` converts the processed Markdown to the target format. DOCX/ODT consume it directly. PDF converts it to Typst markup instead (`pypandoc.convert_text(..., 'typst', ...)`, needs Pandoc >= 3.1.7), rewrites the chart image paths to be relative to the chart temp dir (Typst resolves relative paths against the referencing `.typ` file's own directory, not the compiler's `root`), wraps it with `templates/report_template.typ` (cover page, margins, page numbering), and compiles straight to PDF via `typst.compile(..., root=<chart temp dir>)` — no browser, no intermediate HTML.
4. The `finally` block that `shutil.rmtree()`s the temp chart directory must be preserved — skipping it leaks temp files/inodes.

## Extending

- **New AI provider**: add it to `self.ai_accounts` in `gui/main_view.py.__init__`, then in `api/ai_api.py` implement `get_available_models()` and the streaming branch of `generate_audit_report()` (`for chunk in response: yield chunk.text`).
- **New Zabbix metric**: add collection logic to `collect_data()` in `api/zabbix_api.py` under a new `audit_data[...]` key, and — required, or the LLM will silently ignore it — add explicit instructions for that key in `prompts/report_template.txt`.

## Gotchas

- `google-generativeai` was deprecated in favor of `google-genai` in 2025; `ai_api.py` already targets the new `Client`/`types.GenerateContentConfig` API — don't downgrade back to the old SDK shape.
- The Docker/Wayland run path (`exec_wayland.fish`) mounts `/tmp/.X11-unix` and forwards `DISPLAY`/`WAYLAND_DISPLAY` because Tkinter needs a display server; there's no headless mode.
- **`ttkbootstrap` must stay pinned to a 1.x release (currently `1.20.4`).** Version `2.0.0` reorganized the package internals (`ttkbootstrap.scrolled`/`ttkbootstrap.tooltip` moved under `ttkbootstrap.widgets`), which breaks `gui/main_view.py`'s imports at startup (`ModuleNotFoundError`). This actually happened once — don't bump this dependency without verifying `python main.py` still launches.
- **Never pass `--bare` to `claude` in `ai_cli_client.py`.** That flag explicitly disables reading OAuth/keychain credentials, which breaks the exact subscription-based auth the CLI mode depends on. Reduce CLI overhead via the isolated temp `cwd` instead (no `CLAUDE.md`/project config nearby to auto-discover).
- **`core/chart_renderer.py` must only use matplotlib's OO API (`Figure` + `FigureCanvasAgg`), never `pyplot`.** Chart rendering runs on background threads (report export, style preview); `pyplot`'s global figure/backend state can collide with Tkinter's main-thread event loop.
- **PDF export needs Pandoc >= 3.1.7** (Typst writer support) — `_export_report_thread` checks the version and calls `pypandoc.download_pandoc()` if it's older or missing, same fallback already used for a missing Pandoc.
- **Fonts in `templates/report_template.typ` must be genuinely bundled in the `typst` wheel, not just installed on your machine.** Typst falls back to a different font *silently* (no error) when the requested one isn't found, so a "wrong" font name still compiles a valid-looking PDF. This already happened once: the template used `"DejaVu Sans"`, which only worked because the dev machine had it installed system-wide — the `typst` wheel only bundles `DejaVu Sans Mono`, `Libertinus Serif`, and `New Computer Modern`. On Docker/Windows without that font, the PDF silently rendered wrong — defeating the entire point of this migration. Before changing the template's font, verify the name is in `typst.Fonts(include_system_fonts=False, include_embedded_fonts=True).families()`.

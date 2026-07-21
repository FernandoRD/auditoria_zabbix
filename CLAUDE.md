# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python desktop GUI app (`ttkbootstrap`/Tkinter) that audits a Zabbix environment: it pulls metrics via the Zabbix JSON-RPC API, sends them to an LLM (Gemini, OpenAI, Anthropic, or local Ollama) to generate a prioritized technical audit report, renders Mermaid.js charts, and exports the result to PDF/DOCX/Markdown/TXT/ODT.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install          # required once, for Mermaid chart + PDF rendering

# Run
python main.py

# Docker (GUI over X11/Wayland via xhost)
./build_image.fish          # builds and pushes fernandord/auditoria-zabbix image
./exec_wayland.fish         # runs the container with X11/Wayland sockets mounted
```

There is no test suite, linter, or formatter configured in this repo — don't assume `pytest`/`ruff`/`black` are wired up.

Credentials (Zabbix + AI provider API keys) are read from the OS keyring (via the `keyring` package), not from `.env` in normal GUI use — `.env.example` documents the fallback/env-based config (`ZABBIX_URL`, `ZABBIX_USER`, `ZABBIX_PASS`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_URL`).

## Architecture

Loosely MVC, three layers wired together in `main.py`:

- **`gui/` (View)** — `ttkbootstrap` (Darkly theme) UI, runs on the Tkinter main thread.
  - `main_view.py` — main window, tabs, progress bar, report export engine, credential management via `keyring`.
  - `manage_accounts_view.py`, `manage_attachments_view.py`, `style_settings_view.py` — secondary modal windows, split out to keep `main_view.py` smaller.
- **`api/` (Model / integrations)**
  - `zabbix_api.py` — `ZabbixClient`: JSON-RPC protocol, auth, version detection, HA cluster node discovery, data collection/sampling.
  - `ai_api.py` — `AIClient`: unifies Gemini/OpenAI/Anthropic/Ollama behind one streaming interface.
- **`core/controller.py` (Controller)** — `Controller` orchestrates user actions, runs work on background threads to keep the GUI responsive, and drives GUI state (buttons, progress bar).
- **`prompts/report_template.txt`** — the system prompt: persona, required report structure, formatting rules (e.g. mandatory Mermaid.js usage).
- **`templates/`** — `mermaid_template.html` (chart rendering shell) and `report_template.docx` (Pandoc reference doc for Word export).

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

### Chart rendering + export pipeline

1. Regex extracts ```mermaid``` blocks from the generated Markdown.
2. Playwright (headless Chromium) injects each block into `templates/mermaid_template.html` with the GUI's color/font prefs, waits for SVG render, and screenshots it to PNG in a temp dir.
3. Markdown mermaid blocks are replaced with image links to those PNGs.
4. `pypandoc` converts the processed Markdown to the target format. PDF specifically skips LaTeX (avoids a ~1GB dependency): a styled HTML (with a CSS cover page) is built from the Pandoc output and printed to PDF via Playwright.
5. The `finally` block that `shutil.rmtree()`s the temp chart directory must be preserved — skipping it leaks temp files/inodes.

## Extending

- **New AI provider**: add it to `self.ai_accounts` in `gui/main_view.py.__init__`, then in `api/ai_api.py` implement `get_available_models()` and the streaming branch of `generate_audit_report()` (`for chunk in response: yield chunk.text`).
- **New Zabbix metric**: add collection logic to `collect_data()` in `api/zabbix_api.py` under a new `audit_data[...]` key, and — required, or the LLM will silently ignore it — add explicit instructions for that key in `prompts/report_template.txt`.

## Gotchas

- `google-generativeai` was deprecated in favor of `google-genai` in 2025; `ai_api.py` already targets the new `Client`/`types.GenerateContentConfig` API — don't downgrade back to the old SDK shape.
- The Docker/Wayland run path (`exec_wayland.fish`) mounts `/tmp/.X11-unix` and forwards `DISPLAY`/`WAYLAND_DISPLAY` because Tkinter needs a display server; there's no headless mode.

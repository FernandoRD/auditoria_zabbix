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

# Docker (GUI over authenticated X11/XWayland)
./build_image.fish          # builds a local image only
./build_image.fish --push   # requires visible confirmation before publishing
./exec_wayland.fish         # runs the container with X11/Wayland sockets mounted
```

`tests/` uses stdlib `unittest` and covers Zabbix/AI transports, snapshots and controller operations, the GUI event queue with fakes, persistence, security, packaging, chart parsing and real export smoke paths. Tests mock external Zabbix/AI calls and do not require a display. The CI lint gate is Ruff 0.16.0 with `E9,F63,F7,F82`; there is no full style/formatting policy. Visual layout changes still need a real `python main.py` smoke test.

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
- **`core/run_config.py`** — frozen request/configuration snapshots built from Tk state on the main thread; secret fields use `repr=False` and attachment lists become tuples.
- **`core/operation.py`** — one unique `OperationContext` per active operation, with cooperative cancellation and completion/cancellation race handling.
- **`core/anonymizer.py`** — structural secret redaction and stable per-audit IPv4/IPv6 pseudonyms; this is not complete de-identification of names or business text.
- **`core/paths.py` + `core/persistence.py`** — bundled resources stay read-only; settings, cache and data use platform-native user directories with validation and atomic writes.
- **`core/chart_renderer.py`** — parses the AI-generated `xychart-beta` Mermaid syntax and renders it to PNG via matplotlib (Agg backend, OO API only). Used by both `gui/main_view.py` (report export) and `gui/style_settings_view.py` (style preview).
- **`prompts/report_template.txt`** — the system prompt: persona, required report structure, formatting rules (e.g. mandatory Mermaid.js usage).
- **`templates/`** — `report_template.typ` (Typst template: cover page, margins, page numbering, for PDF export) and `report_template.docx` (Pandoc reference doc for Word export).

### Threading rule (critical)

Never read or write Tkinter widgets/variables from a background thread, including `.get()`, `.set()`, `.configure()`, `after()`, notebook selection or mutable GUI lists. `MainView` builds frozen `AuditRequest`/`CollectionRequest` snapshots on the main thread. Workers may call view publisher methods such as `log()`, `update_progress()` and `append_report_chunk()` because those methods only enqueue plain Python events; only `_consume_ui_events()` touches Tk. Closing the window seals and drains the queue so late events are discarded.

Only one Zabbix/AI operation may own the controller at a time. Never reset or reuse an old cancellation event: create a new `OperationContext`, check its cancellation callback inside loops/retry waits, publish chunks through `run_if_active()`, and let only the matching operation's `finally` release the UI.

### Zabbix API version/auth handling

Zabbix changed auth from payload-based (`"auth": token`) to `Authorization: Bearer` headers in 6.4+. `discover_version()` does an unauthenticated `apiinfo.version` call first and sets `self.use_header_auth`; `api_call()` then injects the token in the right place per call. The tested compatibility boundaries are 5.0, 5.2, 6.0, 6.4, 7.0 and 7.4: login changes from `user` to `username` at 5.4, roles exist from 5.2, and proxy fields switch from `host`/`status` to `name`/`operating_mode` at 7.0.

### HA cluster node discovery (`get_active_node_hostid`)

Triple fallback to find the *Active* node in an HA cluster (avoids collecting empty/flatline metrics from a Standby node):
1. `hanode.get` (native, Zabbix 6.0+)
2. Compare `clock` freshness of `zabbix[process,poller...]` items across hosts
3. Static fallback to a host literally named `"Zabbix server"`

### Data sampling for trend charts

Zabbix history can return millions of rows — too much for an LLM context window. `collect_data()` sends only Top-N items (GUI-controlled) and, for trend charts, fetches N recent points (e.g. 500) then uses reverse-stride indexing (`history_data[0::step][:15]`) to compress hours/days of history into ~15 representative points instead of the most recent 15 minutes.

`ZabbixClient._fetch_trend_values()` wraps this with a fallback: if `history.get` comes back empty (common when an environment shortens `history` retention for internal items but keeps `trends` much longer), it retries via `trend.get`. Reuse this helper for any new historical metric instead of calling `history.get` directly — see the "Zabbix collection" gotcha below.

### Report generation flow

`Controller` merges the Zabbix JSON, snapshotted custom instructions, and bounded text attachments into `prompts/report_template.txt`, then consumes provider-neutral `AIStreamEvent`s from `AIClient`. Text chunks are published through the GUI queue. Exactly one terminal event is required before the report is called complete; errors, token limits, missing final events and failures after the first text preserve the visible output as partial.

The GUI has four action buttons in `main_view.py`'s `control_frame`: **"▶ Iniciar Auditoria"** (fresh collection + AI), **"🔄 Regerar (Apenas IA)"** (versioned cache + AI), **"📥 Apenas Coleta"** (collection to a user-selected JSON, no AI), and **"📂 Iniciar de Coleta"** (selected JSON + AI, no Zabbix connection). Main-thread handlers build `AuditRequest`/`CollectionRequest` snapshots and pass them to the controller. The connect+collect+anonymize+cache-write logic lives in `Controller._collect_zabbix_data()` and is shared by fresh audit and collection-only flows; keep new collection logic there so the entry points do not drift.

### CLI auth mode (`api/ai_cli_client.py`)

An alternative to API-key billing: `generate_via_cli(provider, prompt, model_override)` runs the user's authenticated `claude`, `codex`, or `gemini` CLI in headless mode. Tools/write access are disabled (`--allowedTools ""`, `--sandbox read-only`, or `--approval-mode plan`), the prompt goes through stdin, and cwd is an isolated temp directory removed in `finally`. A help probe enables only capabilities advertised by the installed version. Claude `stream-json` and Codex `exec --json` are parsed incrementally only for the fixture-covered event schemas; Gemini and unsupported versions fall back to the final response. Cancellation/timeout terminate the process tree on POSIX and Windows, and errors never echo full stdout/stderr. CLI-local does not mean local inference: these CLIs may still send the prompt to the provider cloud.

### Persistence, cache, attachments, and cloud boundary

Writable files never use `resource_path()` or depend on cwd. `platformdirs` supplies config/cache/data roots; settings and the versioned collection cache are atomic/private where the OS permits. Settings are saved at defined actions (starting/testing flows and confirming account/style/path changes), not on every keystroke. Every fresh collection attempts an automatic cache update. Reports and logs require explicit save/export.

Imported JSON is capped at 10 MiB and attachments at 10 files, 1 MiB each/5 MiB total. Prompts receive only attachment basenames. With anonymization enabled, structural secret keys and IPs are redacted in collection/import/cache data and attachments before AI generation, but host/person/company names and other context can remain. API and CLI modes for cloud providers send the resulting JSON, instructions and attachments remotely; only an Ollama endpoint under the operator's control is a local-processing choice.

### Chart rendering + export pipeline

1. `core/chart_renderer.py` extracts ```mermaid``` blocks, parses the `xychart-beta` syntax (title/x-axis/y-axis/line|bar), and renders each to PNG via matplotlib (OO API + Agg, never `pyplot`) in a temp dir. Non-`xychart-beta` or unparseable blocks are left as code blocks — export never aborts because of one bad chart.
2. Markdown mermaid blocks are replaced with image links to those PNGs.
3. `pypandoc` converts the processed Markdown to the target format. DOCX/ODT consume it directly. PDF converts it to Typst markup instead (`pypandoc.convert_text(..., 'typst', ...)`, needs Pandoc >= 3.1.7), rewrites the chart image paths to be relative to the chart temp dir (Typst resolves relative paths against the referencing `.typ` file's own directory, not the compiler's `root`), wraps it with `templates/report_template.typ` (cover page, margins, page numbering), and compiles straight to PDF via `typst.compile(..., root=<chart temp dir>)` — no browser, no intermediate HTML.
4. The `finally` block that `shutil.rmtree()`s the temp chart directory must be preserved — skipping it leaks temp files/inodes.

## Extending

- **New AI provider**: add it to `SUPPORTED_AI_PROVIDERS` and the initial GUI accounts, implement model discovery and a transport that yields `AIStreamEvent.text_chunk()` plus exactly one `AIStreamEvent.final()`, then test normal completion, partial/error, token limit, retry and cancellation behavior.
- **New Zabbix metric**: add collection logic to `collect_data()` in `api/zabbix_api.py` under a new `audit_data[...]` key, and — required, or the LLM will silently ignore it — add explicit instructions for that key in `prompts/report_template.txt`.

## Gotchas

- `google-generativeai` was deprecated in favor of `google-genai` in 2025; `ai_api.py` already targets the new `Client`/`types.GenerateContentConfig` API — don't downgrade back to the old SDK shape.
- The Docker/Wayland run path (`exec_wayland.fish`) mounts `/tmp/.X11-unix` and forwards `DISPLAY`/`WAYLAND_DISPLAY` because Tkinter needs a display server; there's no headless mode.
- **`ttkbootstrap` must stay pinned to a 1.x release (currently `1.20.4`).** Version `2.0.0` reorganized the package internals (`ttkbootstrap.scrolled`/`ttkbootstrap.tooltip` moved under `ttkbootstrap.widgets`), which breaks `gui/main_view.py`'s imports at startup (`ModuleNotFoundError`). This actually happened once — don't bump this dependency without verifying `python main.py` still launches.
- **Never pass `--bare` to `claude` in `ai_cli_client.py`.** That flag explicitly disables reading OAuth/keychain credentials, which breaks the exact subscription-based auth the CLI mode depends on. Reduce CLI overhead via the isolated temp `cwd` instead (no `CLAUDE.md`/project config nearby to auto-discover).
- **`core/chart_renderer.py` must only use matplotlib's OO API (`Figure` + `FigureCanvasAgg`), never `pyplot`.** Chart rendering runs on background threads (report export, style preview); `pyplot`'s global figure/backend state can collide with Tkinter's main-thread event loop.
- **PDF export needs Pandoc >= 3.1.7** (Typst writer support) — `_export_report_thread` checks the version and calls `pypandoc.download_pandoc()` if it's older or missing, same fallback already used for a missing Pandoc.
- **Fonts in `templates/report_template.typ` must be genuinely bundled in the `typst` wheel, not just installed on your machine.** Typst falls back to a different font *silently* (no error) when the requested one isn't found, so a "wrong" font name still compiles a valid-looking PDF. This already happened once: the template used `"DejaVu Sans"`, which only worked because the dev machine had it installed system-wide — the `typst` wheel only bundles `DejaVu Sans Mono`, `Libertinus Serif`, and `New Computer Modern`. On Docker/Windows without that font, the PDF silently rendered wrong — defeating the entire point of this migration. Before changing the template's font, verify the name is in `typst.Fonts(include_system_fonts=False, include_embedded_fonts=True).families()`.
- **The Zabbix API has no `trends.get` (plural) method.** The correct method is `trend.get` (singular) — calling `trends.get` fails with `"Erro na API do Zabbix (trends.get): Incorrect API 'trends'"`. This already happened once while implementing the history→trend fallback in `_fetch_trend_values()`.
- **Key (`key_`) whitelists in `collect_data()` must be broad prefixes (`"zabbix[process,"`, `"vfs.dev"`), never a closed list of specific names.** A real audit run showed a narrow whitelist (only `"zabbix[process,poller"`/`"zabbix[process,history"`) silently dropping data the Zabbix API was already returning (e.g. `zabbix[process,trapper,...]`, `zabbix[process,unreachable poller,...]`) before it ever reached the JSON — looked like a collection gap, was actually a filtering bug. The same applies to every `audit_data` key: initialize it to `[]`/`0` *before* the `try`, never only inside `if result:` — otherwise "genuinely empty" and "collection failed" are indistinguishable (key just missing) in the final JSON.
- **The fixed `height=20` on the `ScrolledText` inside "Instruções Customizadas para a IA" (`gui/main_view.py`) is a manual pixel calibration, not a dynamic computation.** It exists purely so that LabelFrame's bottom edge lands close to the bottom of "Dados do Analista / Empresa" in the sibling column — two independent `pack` column stacks have no native way to sync each other's height. If either LabelFrame gains/loses fields, re-verify visually (`python main.py`) and recalibrate `height`. Don't reintroduce a shared-row `grid` layout to "solve this properly" — that was tried and rejected: it also stretched `analyst_frame` to fill the row, changing its original appearance, which is exactly what the fix was supposed to avoid.

# Portabilidade: matplotlib + Typst no lugar do Playwright — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover a dependência de Playwright/Chromium do app, substituindo a renderização de gráficos Mermaid por matplotlib e a exportação de PDF por Typst, para que `pip install -r requirements.txt` seja suficiente em qualquer distro Linux e no Windows.

**Architecture:** Novo módulo `core/chart_renderer.py` concentra o parsing da sintaxe `xychart-beta` (que a IA já é forçada a usar pelo prompt, sem mudança de contrato) e a renderização em PNG via matplotlib (API OO + backend Agg, nunca `pyplot`, por causa das threads). `gui/main_view.py` e `gui/style_settings_view.py` passam a chamar esse módulo em vez do Playwright. A exportação em PDF troca "HTML impresso via Chromium" por "Markdown → Typst (pandoc) → PDF (`typst.compile`)", com um template `templates/report_template.typ` para a capa/formatação.

**Tech Stack:** `matplotlib` (Agg, sem GUI) e `typst` (compilador nativo via wheel pip) somam-se às dependências já fixadas; `playwright` sai do `requirements.txt` e do `Dockerfile`.

## Global Constraints

- Nenhuma dependência de sistema além do que os wheels de `matplotlib`/`typst` já trazem — nada de `apt`/`dnf`/`pacman` no fluxo normal de instalação.
- O contrato do prompt com a IA (`prompts/report_template.txt`) permanece emitindo `xychart-beta` — não migrar para JSON estruturado.
- Renderização de gráficos deve usar **exclusivamente** a API orientada a objetos do matplotlib (`matplotlib.figure.Figure` + `matplotlib.backends.backend_agg.FigureCanvasAgg`) — nunca `import matplotlib.pyplot`, pois a renderização roda em threads de background e o estado global do pyplot pode colidir com o event loop do Tkinter na main thread (mesma classe de bug já documentada no projeto sobre nunca tocar widgets Tkinter fora da main thread).
- Blocos Mermaid não-`xychart-beta` (ou malformados) devem degradar graciosamente: permanecem como bloco de código no documento final, nunca abortam a exportação.
- Pandoc precisa ser ≥ 3.1.7 para o writer `typst` — checar a versão antes de converter e usar `pypandoc.download_pandoc()` (já usado hoje como fallback) se for antigo ou ausente.
- Caminhos de imagem dentro do `.typ` são relativos **ao próprio arquivo `.typ`**, não ao `root` do `typst.compile` — o arquivo `.typ` deve ficar no mesmo diretório dos PNGs dos gráficos para que `image("chart_0.png")` resolva sem reescrita de caminho complexa.
- Referência da spec: `docs/superpowers/specs/2026-07-21-matplotlib-typst-portability-design.md`.

---

### Task 1: `core/chart_renderer.py` — parsing puro (`normalize_mermaid`, `parse_xychart`)

**Files:**
- Create: `core/chart_renderer.py`
- Create: `tests/test_chart_renderer.py`

**Interfaces:**
- Consumes: nada (módulo novo, independente).
- Produces (usado pelas Tasks 2, 3 e 4):
  - `MERMAID_CODE_FENCE_RE: re.Pattern` — regex compilada que captura blocos ```` ```mermaid ... ``` ````, grupo 1 = conteúdo interno.
  - `normalize_mermaid(code: str, chart_type_en: str) -> str` — corrige alucinações comuns da IA e força o tipo de série (`"line"`/`"bar"`) escolhido pelo usuário na GUI.
  - `parse_xychart(code: str) -> dict | None` — `{"title": str, "x_labels": list[str], "y_label": str, "y_range": tuple[float,float] | None, "series": [{"type": "line"|"bar", "values": list[float]}]}`, ou `None` se o bloco não for um `xychart-beta` parseável.

- [ ] **Step 1: Escrever os testes (vão falhar — o módulo ainda não existe)**

Criar `tests/test_chart_renderer.py`:

```python
import unittest

from core.chart_renderer import normalize_mermaid, parse_xychart


class TestNormalizeMermaid(unittest.TestCase):
    def test_fixes_linechart_hallucination(self):
        code = "lineChart\n  title \"X\"\n  line [1,2]"
        result = normalize_mermaid(code, "line")
        self.assertTrue(result.startswith("xychart-beta"))

    def test_fixes_barchart_hallucination(self):
        code = "barChart\n  title \"X\"\n  bar [1,2]"
        result = normalize_mermaid(code, "bar")
        self.assertTrue(result.startswith("xychart-beta"))

    def test_fixes_data_colon_hallucination(self):
        code = "xychart-beta\n  data: [1,2,3]"
        result = normalize_mermaid(code, "line")
        self.assertIn("line [1,2,3]", result)
        self.assertNotIn("data:", result)

    def test_forces_series_type_to_user_selection(self):
        code = "xychart-beta\n  bar [1,2,3]"
        result = normalize_mermaid(code, "line")
        self.assertIn("line [1,2,3]", result)

    def test_leaves_correct_syntax_unchanged_in_content(self):
        code = "xychart-beta\n  title \"X\"\n  line [1,2,3]"
        result = normalize_mermaid(code, "line")
        self.assertIn('title "X"', result)
        self.assertIn("line [1,2,3]", result)


class TestParseXychart(unittest.TestCase):
    def test_canonical_prompt_example(self):
        code = (
            'xychart-beta\n'
            '  title "Nome da Métrica"\n'
            '  x-axis ["T1", "T2", "T3", "T4"]\n'
            '  y-axis "Valores"\n'
            '  line [10, 20, 15, 30]'
        )
        result = parse_xychart(code)
        self.assertEqual(result["title"], "Nome da Métrica")
        self.assertEqual(result["x_labels"], ["T1", "T2", "T3", "T4"])
        self.assertEqual(result["y_label"], "Valores")
        self.assertIsNone(result["y_range"])
        self.assertEqual(result["series"], [{"type": "line", "values": [10.0, 20.0, 15.0, 30.0]}])

    def test_y_axis_with_range(self):
        code = (
            'xychart-beta\n'
            '  title "Cache"\n'
            '  x-axis ["1h", "45m"]\n'
            '  y-axis "Uso de Cache (%)" 0 --> 100\n'
            '  bar [20, 35]'
        )
        result = parse_xychart(code)
        self.assertEqual(result["y_label"], "Uso de Cache (%)")
        self.assertEqual(result["y_range"], (0.0, 100.0))
        self.assertEqual(result["series"], [{"type": "bar", "values": [20.0, 35.0]}])

    def test_multiple_series(self):
        code = (
            'xychart-beta\n'
            '  title "Multi"\n'
            '  x-axis ["a","b"]\n'
            '  y-axis "V"\n'
            '  line [1,2]\n'
            '  bar [3,4]'
        )
        result = parse_xychart(code)
        self.assertEqual(result["series"], [
            {"type": "line", "values": [1.0, 2.0]},
            {"type": "bar", "values": [3.0, 4.0]},
        ])

    def test_non_xychart_returns_none(self):
        code = "flowchart TD\n  A --> B"
        self.assertIsNone(parse_xychart(code))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_xychart("isto não é mermaid nenhum"))

    def test_xychart_without_series_returns_none(self):
        code = 'xychart-beta\n  title "Vazio"\n  x-axis ["a"]\n  y-axis "V"'
        self.assertIsNone(parse_xychart(code))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_chart_renderer -v`
Expected: `ModuleNotFoundError: No module named 'core.chart_renderer'`

- [ ] **Step 3: Implementar `core/chart_renderer.py` (parte 1 — parsing)**

```python
import re

MERMAID_CODE_FENCE_RE = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def normalize_mermaid(code, chart_type_en):
    """Corrige alucinações comuns da IA na sintaxe xychart-beta e força o tipo de
    série (line/bar) escolhido pelo usuário na GUI, sobrescrevendo o que a IA gerou."""
    code = re.sub(r'^(?:lineChart|barChart)', 'xychart-beta', code, flags=re.MULTILINE)
    code = re.sub(r'^\s*data:\s*\[', f'  {chart_type_en} [', code, flags=re.MULTILINE)
    code = re.sub(r'^\s*(?:line|bar)\s*\[', f'  {chart_type_en} [', code, flags=re.MULTILINE)
    return code


def parse_xychart(code):
    """Parseia a sintaxe xychart-beta do Mermaid.js (title/x-axis/y-axis/line|bar).
    Retorna um dict com os dados do gráfico, ou None se o bloco não for um
    xychart-beta parseável (ex.: flowchart, sintaxe corrompida)."""
    if 'xychart-beta' not in code:
        return None

    title_match = re.search(r'title\s+"([^"]*)"', code)
    title = title_match.group(1) if title_match else ""

    x_axis_match = re.search(r'x-axis\s*\[(.*?)\]', code)
    x_labels = []
    if x_axis_match:
        x_labels = [s.strip().strip('"') for s in x_axis_match.group(1).split(',') if s.strip()]

    y_axis_match = re.search(r'y-axis\s+"([^"]*)"(?:\s+(-?[\d.]+)\s*-->\s*(-?[\d.]+))?', code)
    y_label = ""
    y_range = None
    if y_axis_match:
        y_label = y_axis_match.group(1)
        if y_axis_match.group(2) and y_axis_match.group(3):
            y_range = (float(y_axis_match.group(2)), float(y_axis_match.group(3)))

    series = []
    for series_match in re.finditer(r'^\s*(line|bar)\s*\[(.*?)\]', code, re.MULTILINE):
        series_type = series_match.group(1)
        values_str = series_match.group(2)
        try:
            values = [float(v.strip()) for v in values_str.split(',') if v.strip()]
        except ValueError:
            continue
        if values:
            series.append({"type": series_type, "values": values})

    if not series:
        return None

    return {
        "title": title,
        "x_labels": x_labels,
        "y_label": y_label,
        "y_range": y_range,
        "series": series,
    }
```

- [ ] **Step 4: Rodar os testes novamente para confirmar que passam**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_chart_renderer -v`
Expected: `OK` (11 testes passando)

- [ ] **Step 5: Commit**

```bash
git add core/chart_renderer.py tests/test_chart_renderer.py
git commit -m "feat: adiciona parser puro da sintaxe xychart-beta do Mermaid"
```

---

### Task 2: `core/chart_renderer.py` — renderização via matplotlib (`render_chart`)

**Files:**
- Modify: `core/chart_renderer.py`
- Modify: `tests/test_chart_renderer.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `parse_xychart` (Task 1, mesmo módulo) para construir os dicts de teste.
- Produces (usado pelas Tasks 3 e 4): `render_chart(chart: dict, style: dict, output_path: str) -> None` — grava um PNG em `output_path`. `style` é um dict com chaves opcionais `chart_color`, `chart_bg_color`, `chart_text_color`, `chart_width`, `chart_height`, `chart_font` (mesmos nomes/valores já usados pelas `StringVar`/`IntVar` da GUI — ver `gui/style_settings_view.py`).

**Achado importante de investigação (guarda isso ao implementar):** matplotlib tenta resolver o nome de fonte literal (ex. `"Arial"`) como arquivo de fonte no sistema; como as pilhas de fonte da GUI são nomes CSS tipo `"Arial, Helvetica, sans-serif"` e normalmente **não existe** fonte "Arial" instalada em distros Linux, usar o primeiro nome da pilha faz o matplotlib emitir um aviso `findfont: Font family 'Arial' not found` **por elemento de texto renderizado** (título, cada tick label, etc. — dezenas de linhas de log por gráfico). A correção é usar a **palavra-chave genérica CSS no final da pilha** (`sans-serif`/`serif`/`monospace`), que é também um nome de família válido no matplotlib e resolve para as fontes DejaVu embutidas sem nenhum aviso — confirmado por teste manual antes de escrever este plano.

- [ ] **Step 1: Adicionar os testes (vão falhar — `render_chart` ainda não existe)**

No topo de `tests/test_chart_renderer.py`, substituir as duas primeiras linhas existentes:
```python
import unittest

from core.chart_renderer import normalize_mermaid, parse_xychart
```
por:
```python
import os
import tempfile
import unittest

from core.chart_renderer import normalize_mermaid, parse_xychart, render_chart
```

Depois, adicionar a classe abaixo ao final do arquivo (antes do `if __name__ == "__main__":`):

```python
class TestRenderChart(unittest.TestCase):
    def setUp(self):
        self.chart = {
            "title": "Teste",
            "x_labels": ["a", "b", "c"],
            "y_label": "V",
            "y_range": None,
            "series": [{"type": "line", "values": [1.0, 5.0, 3.0]}],
        }
        self.tmpdir = tempfile.mkdtemp(prefix="chart_renderer_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_renders_png_with_default_style(self):
        output_path = os.path.join(self.tmpdir, "default.png")
        render_chart(self.chart, {}, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_renders_bar_chart_with_custom_style(self):
        chart = dict(self.chart, series=[{"type": "bar", "values": [4.0, 8.0, 2.0]}])
        style = {
            "chart_color": "Azul",
            "chart_bg_color": "Transparente",
            "chart_text_color": "Branco",
            "chart_width": 1000,
            "chart_height": 500,
            "chart_font": "Verdana, Geneva, sans-serif",
        }
        output_path = os.path.join(self.tmpdir, "custom.png")
        render_chart(chart, style, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_renders_multi_series_with_y_range(self):
        chart = dict(
            self.chart,
            y_range=(0.0, 10.0),
            series=[
                {"type": "line", "values": [1.0, 2.0, 3.0]},
                {"type": "line", "values": [3.0, 2.0, 1.0]},
            ],
        )
        output_path = os.path.join(self.tmpdir, "multi.png")
        render_chart(chart, {}, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_does_not_raise_for_unknown_style_values(self):
        style = {"chart_color": "Cor Inexistente", "chart_bg_color": "Nada", "chart_text_color": "Nada"}
        output_path = os.path.join(self.tmpdir, "fallback.png")
        render_chart(self.chart, style, output_path)
        self.assertTrue(os.path.exists(output_path))
```

- [ ] **Step 2: Adicionar `matplotlib` a `requirements.txt`**

```
matplotlib==3.11.1
```

(adicionar como nova linha, mantendo a ordem alfabética/lógica já usada no arquivo — ver arquivo atual para posicionamento)

Instalar no ambiente de desenvolvimento antes de rodar os testes: `pip install matplotlib==3.11.1` (ou `venv/bin/pip install -r requirements.txt` se estiver usando o venv do projeto).

- [ ] **Step 3: Rodar os testes para confirmar que falham**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_chart_renderer -v`
Expected: `ImportError: cannot import name 'render_chart'`

- [ ] **Step 4: Implementar `render_chart` em `core/chart_renderer.py`**

Adicionar ao topo do arquivo (junto de `import re`):

```python
import logging

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

logging.getLogger('matplotlib').setLevel(logging.ERROR)

_COLOR_MAP = {"Padrão": None, "Azul": "#3498db", "Vermelho": "#e74c3c", "Verde": "#2ecc71", "Laranja": "#e67e22", "Roxo": "#9b59b6"}
_BG_COLOR_MAP = {"Branco": "#ffffff", "Cinza Claro": "#f8f9fa", "Escuro": "#1e1e1e", "Transparente": "transparent"}
_TEXT_COLOR_MAP = {"Preto (Padrão)": "#333333", "Branco": "#ffffff", "Cinza": "#7f8c8d"}
```

Adicionar ao final do arquivo:

```python
def _matplotlib_font_family(css_font_stack):
    """Extrai a palavra-chave genérica (sans-serif/serif/monospace) do fim da pilha
    CSS de fontes usada pela GUI. Usar o primeiro nome da pilha (ex. 'Arial') faria o
    matplotlib emitir um aviso de fonte não encontrada por elemento de texto, já que
    essas fontes normalmente não existem em distros Linux."""
    last = css_font_stack.split(",")[-1].strip().strip("'\"")
    if last in ("sans-serif", "serif", "monospace"):
        return last
    return "sans-serif"


def render_chart(chart, style, output_path):
    """Renderiza um dict de gráfico (ver parse_xychart) em PNG usando a API orientada
    a objetos do matplotlib com backend Agg — nunca pyplot (roda em threads de fundo)."""
    color = _COLOR_MAP.get(style.get("chart_color", "Padrão"))
    bg = _BG_COLOR_MAP.get(style.get("chart_bg_color", "Branco"), "#ffffff")
    text_color = _TEXT_COLOR_MAP.get(style.get("chart_text_color", "Preto (Padrão)"), "#333333")
    width_px = style.get("chart_width", 800)
    height_px = style.get("chart_height", 400)
    font_family = _matplotlib_font_family(style.get("chart_font", "Arial, Helvetica, sans-serif"))
    transparent = (bg == "transparent")

    dpi = 100
    fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    if not transparent:
        fig.patch.set_facecolor(bg)
        ax.set_facecolor(bg)

    x_labels = chart["x_labels"]
    for s in chart["series"]:
        values = s["values"]
        x = x_labels[:len(values)] if x_labels else list(range(len(values)))
        if s["type"] == "bar":
            ax.bar(x, values, color=color)
        else:
            ax.plot(x, values, color=color, marker="o")

    if chart["title"]:
        ax.set_title(chart["title"], color=text_color, fontfamily=font_family)
    if chart["y_label"]:
        ax.set_ylabel(chart["y_label"], color=text_color, fontfamily=font_family)
    if chart["y_range"]:
        ax.set_ylim(chart["y_range"])

    ax.tick_params(colors=text_color)
    for spine in ax.spines.values():
        spine.set_color(text_color)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(font_family)
        label.set_color(text_color)

    fig.tight_layout()
    fig.savefig(output_path, transparent=transparent, facecolor=fig.get_facecolor() if not transparent else "none")
```

- [ ] **Step 5: Rodar os testes novamente para confirmar que passam**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest tests.test_chart_renderer -v`
Expected: `OK` (16 testes passando), **sem nenhuma linha `findfont` na saída** — se aparecer, o mapeamento de fonte da Step 4 está incorreto.

- [ ] **Step 6: Commit**

```bash
git add core/chart_renderer.py tests/test_chart_renderer.py requirements.txt
git commit -m "feat: renderiza gráficos xychart-beta em PNG via matplotlib (Agg)"
```

---

### Task 3: `gui/main_view.py::_render_mermaid_charts` — trocar Playwright por `chart_renderer`

**Files:**
- Modify: `gui/main_view.py`

**Interfaces:**
- Consumes: `core.chart_renderer.MERMAID_CODE_FENCE_RE`, `normalize_mermaid`, `parse_xychart`, `render_chart` (Tasks 1-2).
- Produces: nenhuma mudança de contrato — `_render_mermaid_charts(self, markdown_content) -> (str, str | None)` mantém a mesma assinatura e retorno que a Task 5 (PDF) e o fluxo DOCX/ODT já consomem.

Sem teste automatizado direto (o método pertence a uma classe Tkinter `ttk.Window`, e instanciar `MainView` requer um display). A lógica pesada (parsing/renderização) já está coberta pelas Tasks 1-2; esta task é só o encanamento GUI. Verificação manual no Step 4.

- [ ] **Step 1: Adicionar o import**

No topo de `gui/main_view.py`, junto dos outros imports locais (`from api.ai_cli_client import cli_binary_status`), adicionar:

```python
from core import chart_renderer
```

- [ ] **Step 2: Substituir `_render_mermaid_charts`**

Localizar o método completo (de `def _render_mermaid_charts(self, markdown_content):` até o `return modified_markdown, temp_dir` que fecha o método, imediatamente antes de `def save_report_clicked(self):`) e substituir por:

```python
    def _render_mermaid_charts(self, markdown_content):
        """
        Finds Mermaid xychart-beta blocks, renders them as PNG images using matplotlib,
        and replaces the blocks with image links. Non-xychart-beta blocks (or blocks
        that fail to parse) are left untouched as code blocks.
        Returns the modified markdown and the path to the temporary directory created
        (or None if no chart blocks were found).
        """
        matches = list(chart_renderer.MERMAID_CODE_FENCE_RE.finditer(markdown_content))
        if not matches:
            return markdown_content, None

        temp_dir = tempfile.mkdtemp(prefix="zabbix_audit_charts_")
        modified_markdown = markdown_content

        chart_type = self.chart_type_var.get()
        ctype_en = "bar" if chart_type == "Barra" else "line"
        style = {
            "chart_color": self.chart_color_var.get(),
            "chart_bg_color": self.chart_bg_color_var.get(),
            "chart_text_color": self.chart_text_color_var.get(),
            "chart_width": self.chart_width_var.get(),
            "chart_height": self.chart_height_var.get(),
            "chart_font": self.chart_font_var.get(),
        }

        self.log(f"Encontrados {len(matches)} gráficos Mermaid. Renderizando com matplotlib...", "info")

        for i, match in enumerate(reversed(matches)):
            chart_index = len(matches) - 1 - i
            code = chart_renderer.normalize_mermaid(match.group(1), ctype_en)
            chart = chart_renderer.parse_xychart(code)

            if chart is None:
                self.log(f"Aviso: bloco Mermaid {chart_index+1} não pôde ser interpretado; mantido como bloco de código.", "warning")
                continue

            output_file_path = os.path.join(temp_dir, f"chart_{chart_index}.png")
            try:
                chart_renderer.render_chart(chart, style, output_file_path)
                image_link_path = output_file_path.replace('\\', '/')
                image_link = f"![Gráfico {chart_index+1}]({image_link_path})"
                start, end = match.span()
                modified_markdown = modified_markdown[:start] + image_link + modified_markdown[end:]
                self.log(f"Gráfico {chart_index+1} renderizado com sucesso.", "info")
            except Exception as e:
                self.log(f"Erro ao renderizar gráfico {chart_index+1}: {e}", "danger")
                continue

        return modified_markdown, temp_dir
```

- [ ] **Step 3: Verificar sintaxe**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m py_compile gui/main_view.py`
Expected: nenhuma saída (sucesso) — se falhar por `html`/`pathlib`/`uuid` não usados, **não remova esses imports ainda**: `pathlib`/`uuid`/`html` só ficam órfãos depois da Task 5 (o branch de export em PDF também os usa hoje); a remoção dos imports é o Step 1 da Task 5.

- [ ] **Step 4: Verificação manual**

1. Rodar `python3 main.py` com `pip install matplotlib` já feito no ambiente.
2. Usar "Regerar (Apenas IA)" com um cache de auditoria existente (ou rodar uma auditoria nova) até ter um relatório com pelo menos um bloco ` ```mermaid ` na aba "Relatório Final".
3. Clicar "💾 Salvar / Exportar Relatório", escolher `.docx` (não precisa esperar a Task 5 do PDF).
   - Esperado: log mostra "Encontrados N gráficos Mermaid. Renderizando com matplotlib..." e "Gráfico N renderizado com sucesso.", sem nenhuma linha `findfont`, e o `.docx` gerado contém as imagens dos gráficos.

- [ ] **Step 5: Commit**

```bash
git add gui/main_view.py
git commit -m "feat: renderiza gráficos Mermaid via matplotlib em vez de Playwright"
```

---

### Task 4: `gui/style_settings_view.py::_render_preview_thread` — trocar Playwright por `chart_renderer`

**Files:**
- Modify: `gui/style_settings_view.py`

**Interfaces:**
- Consumes: `core.chart_renderer.parse_xychart`, `render_chart` (Tasks 1-2).
- Produces: nenhuma — é o fim da cadeia (só a prévia visual da janela de estilos).

Sem teste automatizado (janela Tkinter). Verificação manual no Step 3.

- [ ] **Step 1: Adicionar o import**

No topo de `gui/style_settings_view.py`, junto dos demais imports:

```python
from core.chart_renderer import parse_xychart, render_chart
```

- [ ] **Step 2: Substituir `_render_preview_thread`**

Localizar o método completo (de `def _render_preview_thread(self, font, chart_type, chart_color, chart_width, chart_height, chart_bg_color, chart_text_color):` até o `except Exception as e:` / `self.after(0, lambda err=e: ...)` que fecha o método, imediatamente antes de `def _apply_preview_image(self, path):`) e substituir por:

```python
    def _render_preview_thread(self, font, chart_type, chart_color, chart_width, chart_height, chart_bg_color, chart_text_color):
        ctype_en = "bar" if chart_type == "Barra" else "line"
        code = (
            'xychart-beta\n'
            '  title "Exemplo de Desempenho"\n'
            '  x-axis ["1h", "45m", "30m", "15m", "Agora"]\n'
            '  y-axis "Uso de Cache (%)" 0 --> 100\n'
            f'  {ctype_en} [20, 35, 30, 60, 45]'
        )
        chart = parse_xychart(code)

        style = {
            "chart_color": chart_color,
            "chart_bg_color": chart_bg_color,
            "chart_text_color": chart_text_color,
            "chart_width": chart_width,
            "chart_height": chart_height,
            "chart_font": font,
        }

        if not self.temp_preview_dir:
            self.temp_preview_dir = tempfile.mkdtemp(prefix="zabbix_preview_")
        output_path = os.path.join(self.temp_preview_dir, "preview.png")

        try:
            render_chart(chart, style, output_path)
            self.after(0, self._apply_preview_image, output_path)
        except Exception as e:
            self.after(0, lambda err=e: self.preview_label.configure(text=f"Erro na prévia:\n{err}", image=''))
```

- [ ] **Step 3: Atualizar o texto de status e verificar sintaxe**

Em `update_preview` (logo acima de `_render_preview_thread`), localizar:

```python
        self.preview_label.configure(text="Gerando prévia com Playwright... Aguarde.", image='')
```

Substituir por:

```python
        self.preview_label.configure(text="Gerando prévia... Aguarde.", image='')
```

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m py_compile gui/style_settings_view.py`
Expected: nenhuma saída (sucesso)

- [ ] **Step 4: Verificação manual**

1. Rodar `python3 main.py`.
2. Na aba "⚙️ Configurações", clicar "🎨 Configurar Estilos de Gráfico".
3. Trocar cada combo (Fonte, Tipo, Cor, Cor de Fundo, Cor do Texto) e os spinboxes de Largura/Altura.
   - Esperado: a prévia atualiza a cada mudança, sem erro no label, sem `findfont` no terminal.

- [ ] **Step 5: Commit**

```bash
git add gui/style_settings_view.py
git commit -m "feat: prévia de estilos usa matplotlib em vez de Playwright"
```

---

### Task 5: PDF via Typst — template + `_export_report_thread`

**Files:**
- Create: `templates/report_template.typ`
- Delete: `templates/mermaid_template.html`
- Modify: `gui/main_view.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `_render_mermaid_charts` (Task 3) já produz `processed_content` com imagens em caminho absoluto e `temp_dir_to_clean` (diretório onde os PNGs vivem).
- Produces: nenhuma consumida por outras tasks — fim da cadeia de exportação.

**Achado importante de investigação (guarda isso ao implementar):** caminhos relativos dentro de um arquivo `.typ` são resolvidos **em relação à pasta do próprio arquivo `.typ`**, não em relação ao `root` passado para `typst.compile` — confirmado por teste manual antes de escrever este plano (`root` é só um limite de sandbox e precisa conter o arquivo de entrada). Por isso o arquivo `.typ` precisa ser escrito **na mesma pasta dos PNGs dos gráficos** (`temp_dir_to_clean`), não em uma pasta temporária separada.

- [ ] **Step 1: Remover os imports que só serviam ao Playwright**

No topo de `gui/main_view.py`, remover as linhas:

```python
import html
```
e
```python
import pathlib
import uuid
```

(Confirme antes que não sobrou nenhum uso: `grep -n "html\.\|pathlib\.\|uuid\." gui/main_view.py` não deve retornar nada depois desta task.)

- [ ] **Step 2: Criar `templates/report_template.typ`**

```typst
#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.5cm, left: 2cm, right: 2cm),
  numbering: "1 / 1",
)
#set text(font: "DejaVu Sans", size: 11pt, lang: "pt")
#set heading(numbering: none)
#show heading.where(level: 1): set text(size: 18pt, weight: "bold")
#show heading.where(level: 2): set text(size: 14pt, weight: "bold")

#align(center)[
  #v(8cm)
  #text(size: 26pt, weight: "bold")[__TITLE__]
  #v(1.5em)
  #text(size: 14pt, fill: gray)[__AUTHOR__]
  #v(0.5em)
  #text(size: 12pt, fill: gray)[__DATE__]
]
#pagebreak()

__BODY__
```

- [ ] **Step 3: Apagar `templates/mermaid_template.html`**

```bash
git rm templates/mermaid_template.html
```

- [ ] **Step 4: Adicionar a função de escape de texto Typst**

Em `gui/main_view.py`, adicionar uma função em nível de módulo (fora da classe `MainView`, logo após os imports, antes de `class MainView(ttk.Window):`):

```python
def _escape_typst_text(text):
    """Escapa caracteres com significado especial em markup Typst (usado só para os
    campos de texto livre da capa do PDF — nome/empresa do analista)."""
    for ch in ['\\', '#', '*', '_', '`', '<', '>', '@', '$', '[', ']']:
        text = text.replace(ch, '\\' + ch)
    return text
```

- [ ] **Step 5: Reescrever o branch `.pdf` de `_export_report_thread`**

Localizar o bloco completo `if to_format == 'pdf':` até o `except Exception as e:` correspondente (`self.log(f"Erro ao exportar PDF: {e}", "danger")`), que hoje é:

```python
                if to_format == 'pdf':
                    try:
                        html_body = pypandoc.convert_text(processed_content, 'html', format='gfm+hard_line_breaks')
                        
                        author_field = author_name if author_name else "Analista de Monitoramento"
                        if company_name:
                            author_field += f" - {company_name}"
                        current_date = datetime.now().strftime("%d/%m/%Y")
                        
                        full_html = f"""
                        <!DOCTYPE html><html><head><meta charset="UTF-8">
                        <style>
                            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }}
                            h1, h2, h3 {{ color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 5px; margin-top: 30px; }}
                            a {{ color: #3498db; text-decoration: none; }}
                            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; page-break-inside: avoid; }}
                            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                            th {{ background-color: #f8f9fa; font-weight: bold; }}
                            .cover-page {{ text-align: center; margin-top: 30%; page-break-after: always; }}
                            .cover-title {{ font-size: 2.8em; font-weight: bold; margin-bottom: 20px; color: #2c3e50; }}
                            .cover-author {{ font-size: 1.5em; margin-bottom: 10px; color: #7f8c8d; }}
                            .cover-date {{ font-size: 1.2em; color: #95a5a6; }}
                            img {{ max-width: 100%; height: auto; display: block; margin: 15px auto; page-break-inside: avoid; }}
                            pre {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; page-break-inside: avoid; border: 1px solid #eee; }}
                            code {{ font-family: Consolas, monospace; background-color: #f8f9fa; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }}
                            blockquote {{ border-left: 4px solid #3498db; padding-left: 15px; color: #555; font-style: italic; }}
                        </style>
                        </head><body>
                            <div class="cover-page">
                                <div class="cover-title">Relatório Técnico de Auditoria Zabbix</div>
                                <div class="cover-author">{author_field}</div>
                                <div class="cover-date">{current_date}</div>
                            </div>
                            {html_body}
                        </body></html>
                        """
                        
                        temp_html_path = os.path.join(tempfile.gettempdir(), f"zabbix_report_temp_{uuid.uuid4().hex}.html")
                        with open(temp_html_path, "w", encoding="utf-8") as f:
                            f.write(full_html)
                        
                        from playwright.sync_api import sync_playwright
                        with sync_playwright() as p:
                            browser = p.chromium.launch()
                            page = browser.new_page()
                            page.goto(pathlib.Path(temp_html_path).absolute().as_uri())
                            page.wait_for_load_state('networkidle')
                            page.pdf(
                                path=file_path, 
                                format="A4", 
                                margin={"top": "2.5cm", "bottom": "2.5cm", "left": "2cm", "right": "2cm"}, 
                                print_background=True, 
                                display_header_footer=True, 
                                footer_template='<div style="font-size: 10px; text-align: center; width: 100%; color: #7f8c8d;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>', 
                                header_template='<div></div>'
                            )
                            browser.close()
                            
                        os.remove(temp_html_path)
                        self.log(f"Relatório exportado com sucesso em: {file_path}")
                    except Exception as e:
                        self.log(f"Erro ao exportar PDF: {e}", "danger")
```

Substituir por:

```python
                if to_format == 'pdf':
                    try:
                        pandoc_version = pypandoc.get_pandoc_version()
                        version_tuple = tuple(int(p) for p in pandoc_version.split('.')[:3])
                        if version_tuple < (3, 1, 7):
                            self.log(f"Pandoc {pandoc_version} não suporta o writer Typst (requer >= 3.1.7). Baixando versão atualizada...", "warning")
                            pypandoc.download_pandoc()

                        typst_body = pypandoc.convert_text(processed_content, 'typst', format='gfm+hard_line_breaks')

                        pdf_root_dir = temp_dir_to_clean
                        created_pdf_root = False
                        if not pdf_root_dir:
                            pdf_root_dir = tempfile.mkdtemp(prefix="zabbix_report_typst_")
                            created_pdf_root = True
                        else:
                            temp_dir_norm = pdf_root_dir.replace('\\', '/')
                            typst_body = typst_body.replace(f'image("{temp_dir_norm}/', 'image("')

                        try:
                            author_field = author_name if author_name else "Analista de Monitoramento"
                            if company_name:
                                author_field += f" - {company_name}"
                            current_date = datetime.now().strftime("%d/%m/%Y")

                            with open("templates/report_template.typ", "r", encoding="utf-8") as f:
                                typst_template = f.read()

                            full_typst = typst_template.replace("__TITLE__", "Relatório Técnico de Auditoria Zabbix").replace(
                                "__AUTHOR__", _escape_typst_text(author_field)).replace(
                                "__DATE__", current_date).replace(
                                "__BODY__", typst_body)

                            typst_source_path = os.path.join(pdf_root_dir, "report.typ")
                            with open(typst_source_path, "w", encoding="utf-8") as f:
                                f.write(full_typst)

                            import typst
                            typst.compile(typst_source_path, output=file_path, root=pdf_root_dir)
                            self.log(f"Relatório exportado com sucesso em: {file_path}")
                        finally:
                            if created_pdf_root:
                                shutil.rmtree(pdf_root_dir, ignore_errors=True)
                    except Exception as e:
                        self.log(f"Erro ao exportar PDF: {e}", "danger")
```

- [ ] **Step 6: Adicionar `typst` a `requirements.txt`**

```
typst==0.15.0
```

Instalar no ambiente de desenvolvimento: `pip install typst==0.15.0` (ou reinstalar via `requirements.txt`).

- [ ] **Step 7: Verificar sintaxe e ausência de imports órfãos**

Run:
```bash
cd /home/fernando/Documentos/auditoria_zabbix
python3 -m py_compile gui/main_view.py
grep -n "html\.\|pathlib\.\|uuid\.\|playwright" gui/main_view.py
```
Expected: `py_compile` sem saída; o `grep` não deve retornar nenhuma linha.

- [ ] **Step 8: Verificação manual**

1. Rodar `python3 main.py` com `matplotlib`/`typst` instalados no ambiente.
2. Com um relatório carregado (cache ou nova auditoria) contendo pelo menos um gráfico, clicar "💾 Salvar / Exportar Relatório" e escolher `.pdf`.
   - Esperado: log mostra "Relatório exportado com sucesso em: ...pdf"; abrir o PDF e confirmar capa (título/autor/data), numeração de página, texto, tabelas e a imagem do gráfico presentes.
3. Repetir a exportação sem nenhum gráfico no relatório (ex.: um texto simples colado na aba "Relatório Final"), escolher `.pdf`.
   - Esperado: exporta normalmente (cobre o caminho `temp_dir_to_clean is None` / `created_pdf_root = True`).

- [ ] **Step 9: Commit**

```bash
git add gui/main_view.py requirements.txt templates/report_template.typ
git rm templates/mermaid_template.html
git commit -m "feat: exporta PDF via Typst em vez de Playwright/Chromium"
```

---

### Task 6: Remover Playwright de `requirements.txt` e `Dockerfile`

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`

**Interfaces:** nenhuma — task de limpeza de dependências, sem código Python.

- [ ] **Step 1: Remover `playwright` de `requirements.txt`**

Localizar e remover a linha:
```
playwright==1.61.0
```

- [ ] **Step 2: Atualizar `Dockerfile`**

Localizar:

```dockerfile
# Atualizar pacotes e instalar dependências de sistema
# - python3-tk e tk-dev: Necessários para renderizar a interface gráfica Tkinter
# - pandoc: Necessário para o pypandoc exportar os relatórios
# - dependências extras para garantir o correto funcionamento do sistema
RUN apt-get update && apt-get install -y \
    python3-tk \
    tk-dev \
    pandoc \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho
WORKDIR /app

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar as dependências do Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Instalar o Playwright e executar a instalação dos navegadores com dependências do sistema
RUN pip install playwright && \
    playwright install --with-deps chromium
```

Substituir por:

```dockerfile
# Atualizar pacotes e instalar dependências de sistema
# - python3-tk e tk-dev: Necessários para renderizar a interface gráfica Tkinter
# - dependências extras para garantir o correto funcionamento do sistema
RUN apt-get update && apt-get install -y \
    python3-tk \
    tk-dev \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho
WORKDIR /app

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar as dependências do Python (inclui matplotlib e typst, sem dependências de sistema extras)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Baixar o binário do Pandoc (>= 3.1.7, necessário para o writer Typst) via pypandoc,
# em vez do pacote "pandoc" do apt (Debian slim traz uma versão 2.x sem suporte a Typst)
RUN python -c "import pypandoc; pypandoc.download_pandoc()"
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt Dockerfile
git commit -m "chore: remove Playwright de requirements.txt e Dockerfile"
```

---

### Task 7: Ajustar `prompts/report_template.txt`

**Files:**
- Modify: `prompts/report_template.txt`

**Interfaces:** nenhuma — texto de prompt, consumido apenas pela IA.

- [ ] **Step 1: Ajustar a REGRA DE OURO 4**

Localizar a linha final do arquivo:

```
REGRA DE OURO 4: Não resuma demais o relatório, enriqueça-o com elementos visuais, tais como gráficos e fluxogramas.
```

Substituir por:

```
REGRA DE OURO 4: Não resuma demais o relatório, enriqueça-o com elementos visuais, tais como gráficos (sempre na sintaxe `xychart-beta` do Mermaid.js, conforme a REGRA DE OURO 2) e tabelas. Não use outros tipos de diagrama Mermaid (flowchart, sequenceDiagram, etc.) — eles não são renderizados pela ferramenta e apareceriam como texto bruto no relatório final.
```

- [ ] **Step 2: Commit**

```bash
git add prompts/report_template.txt
git commit -m "docs: ajusta o prompt para não pedir diagramas Mermaid não suportados (só xychart-beta)"
```

---

### Task 8: Atualizar `README.md`, `TECHNICAL_REFERENCE.md` e `CLAUDE.md`

**Files:**
- Modify: `README.md`
- Modify: `TECHNICAL_REFERENCE.md`
- Modify: `CLAUDE.md`

**Interfaces:** nenhuma — documentação.

- [ ] **Step 1: `README.md` — remover o passo do Playwright**

Localizar:

```
# Instale as dependências
pip install -r requirements.txt

# (Apenas na primeira vez) Instale os navegadores para o Playwright renderizar os gráficos
playwright install
```

Substituir por:

```
# Instale as dependências (inclui matplotlib e typst, sem passos extras de instalação)
pip install -r requirements.txt
```

- [ ] **Step 2: `README.md` — atualizar a estrutura de diretórios**

Localizar (a árvore já tem um bloco `core/` mais acima, com `controller.py` — este `sed` só adiciona `chart_renderer.py` a ele):

```
├── core/
│   └── controller.py      # Lógica de negócio e orquestração de Threads
```

Substituir por:

```
├── core/
│   ├── chart_renderer.py  # Parsing de xychart-beta + renderização matplotlib
│   └── controller.py      # Lógica de negócio e orquestração de Threads
```

Logo abaixo, na mesma árvore, localizar:

```
├── templates/
│   ├── mermaid_template.html # Template base para renderização vetorial de gráficos
│   └── report_template.docx  # Documento de referência do Pandoc (se existir)
```

Substituir por:

```
├── templates/
│   ├── report_template.docx  # Documento de referência do Pandoc (Word)
│   └── report_template.typ   # Template Typst (capa, margens, numeração) para PDF
```

- [ ] **Step 3: `README.md` — atualizar a descrição de exportação PDF**

Localizar:

```
- **Exportação Profissional e Elegante**:
  - **PDF (.pdf)**: Renderização direta baseada em Chromium via *Playwright*. Gera automaticamente uma Capa de Rosto com os dados do auditor/empresa, paginação inteligente, fontes modernas (Helvetica/Arial) e não depende de LaTeX.
```

Substituir por:

```
- **Exportação Profissional e Elegante**:
  - **PDF (.pdf)**: Renderização via *Typst* (compilador nativo, sem dependência de browser/Chromium). Gera automaticamente uma Capa de Rosto com os dados do auditor/empresa, paginação inteligente e não depende de LaTeX nem de instaladores de sistema.
```

- [ ] **Step 4: `TECHNICAL_REFERENCE.md` — reescrever a seção 5**

Localizar o bloco completo:

```markdown
### 5. Renderização de Gráficos e Exportação (O Motor Playwright + Pandoc)
A IA gera gráficos escrevendo blocos de código vetoriais na linguagem `mermaid`. No entanto, visualizadores offline (PDF/Word) não sabem interpretar blocos *Mermaid*.
* **O Fluxo de Renderização (`_render_mermaid_charts`)**:
  1. Uma expressão regular (`regex`) varre o Markdown extraindo blocos ```mermaid.
  2. O `Playwright` (Navegador Headless Chromium) é instanciado.
  3. O código Mermaid é injetado no arquivo `templates/mermaid_template.html` junto com as preferências de cor/fonte definidas na GUI.
  4. O navegador abre a página, aguarda a injeção SVG (via DOM localizador) e tira um *Screenshot* PNG em um diretório temporário (`/tmp`).
  5. O bloco de texto markdown do Mermaid é substituído localmente por uma tag de imagem `!Grafico`.
* **A Geração Final (`_export_report_thread`)**:
  * O Markdown manipulado (agora com links para imagens PNG reais) é passado para a biblioteca `pypandoc`.
  * No caso do **PDF**, a aplicação não usa LaTeX (para evitar dependências de 1GB). Ela cria um HTML elegante combinando o conteúdo processado pelo Pandoc, gera uma página de Rosto (Capa) com CSS puro, e utiliza o Playwright novamente para imprimir esse HTML diretamente em `.pdf`.
```

Substituir por:

```markdown
### 5. Renderização de Gráficos e Exportação (`core/chart_renderer.py` + Typst)

A IA gera gráficos escrevendo blocos de código na sintaxe `xychart-beta` do Mermaid.js dentro de blocos ```` ```mermaid ````. Em vez de interpretar essa sintaxe via um motor JS real (o que exigiria um browser), o app faz o parsing dela diretamente em Python.

* **O Fluxo de Renderização (`_render_mermaid_charts` → `core/chart_renderer.py`)**:
  1. `chart_renderer.MERMAID_CODE_FENCE_RE` varre o Markdown extraindo blocos ```` ```mermaid ````.
  2. `normalize_mermaid()` corrige alucinações comuns da IA (`lineChart`/`barChart` → `xychart-beta`, `data: [` → `line [`/`bar [`) e força o tipo de série escolhido pelo usuário na GUI.
  3. `parse_xychart()` extrai título, rótulos do eixo X, rótulo/faixa do eixo Y e as séries de valores. Retorna `None` se o bloco não for um `xychart-beta` parseável (ex.: a IA gerou um flowchart, ignorando a REGRA DE OURO 4 do prompt) — nesse caso o bloco permanece como código no documento final, sem abortar a exportação.
  4. `render_chart()` desenha o gráfico com a **API orientada a objetos do matplotlib** (`Figure` + `FigureCanvasAgg`, nunca `pyplot`) e salva um PNG.
  5. O bloco de texto markdown do Mermaid é substituído localmente por uma tag de imagem `![Gráfico N](caminho/absoluto/chart_N.png)`.
* **A Geração Final (`_export_report_thread`)**:
  * Para **Word (.docx)** e **OpenDocument (.odt)**, o Markdown manipulado (com links para os PNGs) é passado direto para `pypandoc`, sem etapa extra.
  * Para **PDF**, o Markdown é convertido para markup **Typst** via `pypandoc.convert_text(..., 'typst', ...)` (requer Pandoc ≥ 3.1.7 — checado e baixado via `pypandoc.download_pandoc()` se necessário). Os caminhos de imagem, absolutos no Markdown, são reescritos para relativos ao diretório dos gráficos (caminhos em `.typ` são resolvidos relativos ao próprio arquivo `.typ`, não ao `root` do compilador). O corpo Typst é combinado com `templates/report_template.typ` (capa, margens, numeração de página) e compilado direto para PDF via `typst.compile(..., root=<diretório dos PNGs>)` — sem HTML intermediário, sem browser.
```

- [ ] **Step 5: `TECHNICAL_REFERENCE.md` — atualizar a lista de módulos**

Localizar:

```
- **`/prompts`**:
  - `report_template.txt`: O *System Prompt* central. Define a persona, a estrutura de tópicos exigida e as regras de formatação (ex: obrigatoriedade do uso de Mermaid.js).
- **`/templates`**:
  - HTMLs e DOCXs base usados pelos motores de renderização para padronizar a identidade visual de saída.
```

Substituir por:

```
- **`/prompts`**:
  - `report_template.txt`: O *System Prompt* central. Define a persona, a estrutura de tópicos exigida e as regras de formatação (ex: obrigatoriedade do uso de Mermaid.js `xychart-beta`).
- **`/templates`**:
  - `report_template.docx`: documento de referência do Pandoc para exportação Word.
  - `report_template.typ`: template Typst (capa, margens, numeração) para exportação PDF.
```

Logo acima desse bloco, na mesma seção "Estrutura de Diretórios e Módulos", localizar:

```
- **`/core` (Controller)**:
  - `controller.py`: Classe `Controller`. Orquestra as ações do usuário. Gerencia as *Threads* (para evitar o congelamento da interface gráfica) e controla o estado da GUI (habilitar/desabilitar botões, atualizar barra de progresso).
```

Substituir por:

```
- **`/core` (Controller)**:
  - `controller.py`: Classe `Controller`. Orquestra as ações do usuário. Gerencia as *Threads* (para evitar o congelamento da interface gráfica) e controla o estado da GUI (habilitar/desabilitar botões, atualizar barra de progresso).
  - `chart_renderer.py`: Parsing puro da sintaxe `xychart-beta` do Mermaid.js e renderização em PNG via matplotlib (Agg). Ver seção 5.
```

- [ ] **Step 6: `TECHNICAL_REFERENCE.md` — adicionar gotcha do matplotlib**

Na seção "⚠️ Pontos Críticos de Atenção (Gotchas)", localizar a última linha do arquivo:

```
- **Nunca use `claude --bare` em `ai_cli_client.py`:** essa flag desativa explicitamente a leitura de OAuth/keychain ("Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper... OAuth and keychain are never read") — quebraria exatamente a autenticação via assinatura que o modo CLI local depende. Reduções de overhead da CLI devem vir do `cwd` isolado (diretório temp sem `CLAUDE.md`/config de projeto por perto), não dessa flag.
```

Adicionar logo abaixo (nova última linha do arquivo):

```
- **Nunca importe `matplotlib.pyplot` em `chart_renderer.py`:** a renderização de gráficos roda em threads de background (tanto na exportação de relatório quanto na prévia de estilos); `pyplot` mantém estado global de figuras/backend que pode colidir com o event loop do Tkinter na main thread. Use sempre `matplotlib.figure.Figure` + `matplotlib.backends.backend_agg.FigureCanvasAgg` diretamente.
```

- [ ] **Step 7: `CLAUDE.md` — atualizar comandos, arquitetura e gotchas**

No bloco de comandos, localizar:

```
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install          # required once, for Mermaid chart + PDF rendering

# Run
python main.py
```

Substituir por:

```
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run
python main.py
```

Na seção `## Architecture`, localizar:

```
- **`core/controller.py` (Controller)** — `Controller` orchestrates user actions, runs work on background threads to keep the GUI responsive, and drives GUI state (buttons, progress bar).
```

Substituir por:

```
- **`core/controller.py` (Controller)** — `Controller` orchestrates user actions, runs work on background threads to keep the GUI responsive, and drives GUI state (buttons, progress bar).
- **`core/chart_renderer.py`** — parses the AI-generated `xychart-beta` Mermaid syntax and renders it to PNG via matplotlib (Agg backend, OO API only). Used by both `gui/main_view.py` (report export) and `gui/style_settings_view.py` (style preview).
```

Localizar a seção `### Chart rendering + export pipeline` completa:

```
### Chart rendering + export pipeline

1. Regex extracts ```mermaid``` blocks from the generated Markdown.
2. Playwright (headless Chromium) injects each block into `templates/mermaid_template.html` with the GUI's color/font prefs, waits for SVG render, and screenshots it to PNG in a temp dir.
3. Markdown mermaid blocks are replaced with image links to those PNGs.
4. `pypandoc` converts the processed Markdown to the target format. PDF specifically skips LaTeX (avoids a ~1GB dependency): a styled HTML (with a CSS cover page) is built from the Pandoc output and printed to PDF via Playwright.
5. The `finally` block that `shutil.rmtree()`s the temp chart directory must be preserved — skipping it leaks temp files/inodes.
```

Substituir por:

```
### Chart rendering + export pipeline

1. `core/chart_renderer.py` extracts ```mermaid``` blocks, parses the `xychart-beta` syntax (title/x-axis/y-axis/line|bar), and renders each to PNG via matplotlib (OO API + Agg, never `pyplot`) in a temp dir. Non-`xychart-beta` or unparseable blocks are left as code blocks — export never aborts because of one bad chart.
2. Markdown mermaid blocks are replaced with image links to those PNGs.
3. `pypandoc` converts the processed Markdown to the target format. DOCX/ODT consume it directly. PDF converts it to Typst markup instead (`pypandoc.convert_text(..., 'typst', ...)`, needs Pandoc >= 3.1.7), rewrites the chart image paths to be relative to the chart temp dir (Typst resolves relative paths against the referencing `.typ` file's own directory, not the compiler's `root`), wraps it with `templates/report_template.typ` (cover page, margins, page numbering), and compiles straight to PDF via `typst.compile(..., root=<chart temp dir>)` — no browser, no intermediate HTML.
4. The `finally` block that `shutil.rmtree()`s the temp chart directory must be preserved — skipping it leaks temp files/inodes.
```

Na seção `## Gotchas`, localizar a última linha do arquivo:

```
- **Never pass `--bare` to `claude` in `ai_cli_client.py`.** That flag explicitly disables reading OAuth/keychain credentials, which breaks the exact subscription-based auth the CLI mode depends on. Reduce CLI overhead via the isolated temp `cwd` instead (no `CLAUDE.md`/project config nearby to auto-discover).
```

Adicionar logo abaixo (novas últimas linhas do arquivo):

```
- **`core/chart_renderer.py` must only use matplotlib's OO API (`Figure` + `FigureCanvasAgg`), never `pyplot`.** Chart rendering runs on background threads (report export, style preview); `pyplot`'s global figure/backend state can collide with Tkinter's main-thread event loop.
- **PDF export needs Pandoc >= 3.1.7** (Typst writer support) — `_export_report_thread` checks the version and calls `pypandoc.download_pandoc()` if it's older or missing, same fallback already used for a missing Pandoc.
```

- [ ] **Step 8: Commit**

```bash
git add README.md TECHNICAL_REFERENCE.md CLAUDE.md
git commit -m "docs: documenta a migração de Playwright para matplotlib + Typst"
```

---

### Task 9: Verificação final

**Files:** nenhum arquivo novo — só verificação.

- [ ] **Step 1: Rodar a suíte de testes completa**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m unittest discover -s tests -v` (usar o Python do venv do projeto se o `python3` do sistema não tiver as dependências — ver `CLAUDE.md`)
Expected: `OK`, sem nenhuma linha `findfont` na saída.

- [ ] **Step 2: Checar sintaxe de todos os arquivos Python tocados**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && python3 -m py_compile core/chart_renderer.py gui/main_view.py gui/style_settings_view.py`
Expected: nenhuma saída (sucesso)

- [ ] **Step 3: Confirmar que não sobrou nenhuma referência a Playwright no código-fonte**

Run: `cd /home/fernando/Documentos/auditoria_zabbix && grep -rn "playwright\|Playwright" --include="*.py" --include="*.txt" --include="Dockerfile" . 2>/dev/null | grep -v ".git/"`
Expected: nenhuma saída.

- [ ] **Step 4: Verificação manual end-to-end**

1. Instalar as dependências atualizadas do zero num ambiente limpo (`pip install -r requirements.txt`) e confirmar que **não** é necessário nenhum passo de `apt`/`pacman`/instalador de browser.
2. Rodar `python3 main.py`, gerar (ou reusar do cache) um relatório com gráficos, e exportar nos 4 formatos que envolvem gráficos/Typst: `.md` (sem processamento de gráficos — controle), `.docx`, `.odt`, `.pdf`.
   - Esperado: os 4 exportam sem erro; `.docx`/`.odt`/`.pdf` mostram as imagens dos gráficos; `.pdf` tem capa com autor/data e numeração de página.
3. Confirmar que a pasta do projeto não acumulou nenhum diretório temporário órfão (`ls /tmp | grep zabbix` antes/depois de um export completo deve voltar ao mesmo estado).

- [ ] **Step 5: Commit final (se houver ajustes desta verificação)**

```bash
git add -A
git commit -m "chore: ajustes finais de verificação da migração matplotlib/Typst"
```

(Pular este commit se nada precisou ser ajustado.)

import re

import logging

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

logging.getLogger('matplotlib').setLevel(logging.ERROR)

_COLOR_MAP = {"Padrão": None, "Azul": "#3498db", "Vermelho": "#e74c3c", "Verde": "#2ecc71", "Laranja": "#e67e22", "Roxo": "#9b59b6"}
_BG_COLOR_MAP = {"Branco": "#ffffff", "Cinza Claro": "#f8f9fa", "Escuro": "#1e1e1e", "Transparente": "transparent"}
_TEXT_COLOR_MAP = {"Preto (Padrão)": "#333333", "Branco": "#ffffff", "Cinza": "#7f8c8d"}

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

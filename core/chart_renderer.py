import re
import math

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
    warnings = []
    for series_index, series_match in enumerate(
        re.finditer(r'^\s*(line|bar)\s*\[(.*?)\]', code, re.MULTILINE), start=1
    ):
        series_type = series_match.group(1)
        values_str = series_match.group(2)
        values = []
        for raw_value in values_str.split(','):
            value = raw_value.strip()
            try:
                number = float(value) if value else math.nan
                values.append(number if math.isfinite(number) else math.nan)
            except ValueError:
                values.append(math.nan)
        if not any(math.isfinite(value) for value in values):
            warnings.append(
                f"Série {series_index} ({series_type}) totalmente inválida."
            )
        series.append({"type": series_type, "values": values})

    if not series:
        return None

    return {
        "title": title,
        "x_labels": x_labels,
        "y_label": y_label,
        "y_range": y_range,
        "series": series,
        "warnings": warnings,
        "chart_type": "xychart",
    }


def parse_pie(code):
    """Parse a Mermaid pie block without applying xychart normalization."""
    if not re.search(r'^\s*pie(?:\s+showData)?\s*$', code, re.MULTILINE | re.IGNORECASE):
        return None

    title_match = re.search(
        r'^\s*title\s+(?:"([^"]*)"|(.+?))\s*$',
        code,
        re.MULTILINE | re.IGNORECASE,
    )
    labels = []
    values = []
    warnings = []
    entry_pattern = re.compile(
        r'^\s*"([^"]+)"\s*:\s*([^\s]+)\s*$', re.MULTILINE
    )
    for label, raw_value in entry_pattern.findall(code):
        try:
            value = float(raw_value)
        except ValueError:
            warnings.append(f"Fatia '{label}' ignorada: valor inválido.")
            continue
        if not math.isfinite(value) or value < 0:
            warnings.append(f"Fatia '{label}' ignorada: valor deve ser finito e não negativo.")
            continue
        labels.append(label.strip())
        values.append(value)

    if not values or sum(values) <= 0:
        return None
    return {
        "title": (title_match.group(1) or title_match.group(2)).strip() if title_match else "",
        "labels": labels,
        "values": values,
        "warnings": warnings,
        "chart_type": "pie",
    }


def parse_mermaid_chart(code):
    """Dispatch supported Mermaid chart types to their independent parsers."""
    return parse_pie(code) or parse_xychart(code)


def _axis_labels(labels, count):
    """Truncate excess labels and synthesize stable labels when they are short."""
    normalized = list(labels[:count])
    normalized.extend(str(index + 1) for index in range(len(normalized), count))
    return normalized


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

    if chart.get("chart_type") == "pie":
        ax.pie(
            chart["values"],
            labels=chart["labels"],
            colors=None,
            textprops={"color": text_color, "fontfamily": font_family},
            autopct="%1.1f%%",
        )
        ax.axis("equal")
    else:
        renderable_series = [
            series
            for series in chart["series"]
            if any(math.isfinite(value) for value in series["values"])
        ]
        if not renderable_series:
            raise ValueError("o gráfico não possui nenhuma série com valor numérico")

        point_count = max(len(series["values"]) for series in renderable_series)
        positions = list(range(point_count))
        labels = _axis_labels(chart.get("x_labels", []), point_count)
        bar_series = [series for series in renderable_series if series["type"] == "bar"]
        bar_width = 0.8 / max(1, len(bar_series))
        bar_index = 0
        for series in renderable_series:
            values = series["values"]
            x = positions[:len(values)]
            if series["type"] == "bar":
                offset = (bar_index - (len(bar_series) - 1) / 2) * bar_width
                ax.bar([position + offset for position in x], values, width=bar_width, color=color)
                bar_index += 1
            else:
                ax.plot(x, values, color=color, marker="o")
        ax.set_xticks(positions, labels)

    if chart["title"]:
        ax.set_title(chart["title"], color=text_color, fontfamily=font_family)
    if chart.get("y_label"):
        ax.set_ylabel(chart["y_label"], color=text_color, fontfamily=font_family)
    if chart.get("y_range"):
        ax.set_ylim(chart["y_range"])

    ax.tick_params(colors=text_color)
    for spine in ax.spines.values():
        spine.set_color(text_color)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(font_family)
        label.set_color(text_color)

    fig.tight_layout()
    fig.savefig(output_path, transparent=transparent, facecolor=fig.get_facecolor() if not transparent else "none")

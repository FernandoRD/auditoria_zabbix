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

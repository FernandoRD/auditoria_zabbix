"""Headless report export pipeline used by the GUI and tests."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile

from core import chart_renderer
from core.pandoc_runtime import load_pandoc
from core.paths import resource_path
from core.persistence import atomic_write_text
from core.run_config import ReportStyle


@dataclass(frozen=True)
class ReportMetadata:
    """Immutable cover metadata captured by the GUI before starting a worker."""

    author_name: str = ""
    company_name: str = ""
    report_date: str = ""
    title: str = "Relatório Técnico de Auditoria Zabbix"

    @property
    def author_field(self):
        author = self.author_name or "Analista de Monitoramento"
        if self.company_name:
            author += f" - {self.company_name}"
        return author


def _escape_typst_text(text):
    """Escape free-form cover text before inserting it into Typst markup."""
    for character in ("\\", "#", "*", "_", "`", "<", ">", "@", "$", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text


class ReportExporter:
    """Convert a Markdown report without depending on Tk or mutable GUI state."""

    RICH_FORMATS = frozenset({".docx", ".odt", ".pdf"})
    DIRECT_FORMATS = frozenset({"", ".md", ".txt"})

    def __init__(
        self,
        *,
        log_callback=None,
        progress_callback=None,
        resource_resolver=resource_path,
        allow_pandoc_download=False,
    ):
        self._log_callback = log_callback or (lambda _message, _style="info": None)
        self._progress_callback = progress_callback or (lambda _value, _text: None)
        self._resource_resolver = resource_resolver
        self._allow_pandoc_download = allow_pandoc_download

    def _log(self, message, style="info"):
        self._log_callback(message, style)

    def _progress(self, value, text):
        self._progress_callback(value, text)

    def export(
        self,
        file_path: str,
        markdown_content: str,
        report_style: ReportStyle,
        metadata: ReportMetadata,
    ):
        """Export *markdown_content* and return the destination path.

        Conversion errors intentionally propagate to the caller. The GUI can then
        publish the appropriate event, while tests can assert the real failure.
        """
        extension = Path(file_path).suffix.lower()
        supported = self.DIRECT_FORMATS | self.RICH_FORMATS
        if extension not in supported:
            raise ValueError(f"Formato de exportação não suportado: {extension or '(sem extensão)'}")

        self._progress(0, "Preparando exportação...")
        if extension in self.DIRECT_FORMATS:
            atomic_write_text(file_path, markdown_content)
            self._progress(100, "Exportação concluída.")
            self._log(f"Relatório salvo com sucesso em: {file_path}")
            return file_path

        working_dir = tempfile.mkdtemp(prefix="zabbix_report_export_")
        try:
            self._progress(15, "Renderizando gráficos...")
            processed_content = self._render_mermaid_charts(
                markdown_content, report_style, working_dir
            )
            self._progress(45, f"Convertendo relatório para {extension}...")
            pypandoc = self._load_pandoc()

            if extension == ".pdf":
                self._export_pdf(
                    file_path,
                    processed_content,
                    metadata,
                    working_dir,
                    pypandoc,
                )
            else:
                self._export_pandoc_document(
                    file_path, extension, processed_content, pypandoc
                )

            self._progress(100, "Exportação concluída.")
            self._log(f"Relatório exportado com sucesso em: {file_path}")
            return file_path
        finally:
            shutil.rmtree(working_dir, ignore_errors=True)
            self._log("Arquivos temporários da exportação removidos.", "info")

    def _render_mermaid_charts(self, markdown_content, report_style, working_dir):
        matches = list(chart_renderer.MERMAID_CODE_FENCE_RE.finditer(markdown_content))
        if not matches:
            return markdown_content

        modified_markdown = markdown_content
        chart_type = "bar" if report_style.chart_type == "Barra" else "line"
        style = {
            "chart_color": report_style.chart_color,
            "chart_bg_color": report_style.chart_bg_color,
            "chart_text_color": report_style.chart_text_color,
            "chart_width": report_style.chart_width,
            "chart_height": report_style.chart_height,
            "chart_font": report_style.chart_font,
        }
        self._log(
            f"Encontrados {len(matches)} gráficos Mermaid. Renderizando com matplotlib..."
        )

        for reverse_index, match in enumerate(reversed(matches)):
            chart_index = len(matches) - 1 - reverse_index
            raw_code = match.group(1)
            pie_chart = chart_renderer.parse_pie(raw_code)
            if pie_chart is not None:
                chart = pie_chart
            else:
                code = chart_renderer.normalize_mermaid(raw_code, chart_type)
                chart = chart_renderer.parse_xychart(code)
            if chart is None:
                self._log(
                    f"Aviso: bloco Mermaid {chart_index + 1} não pôde ser "
                    "interpretado; mantido como bloco de código.",
                    "warning",
                )
                continue

            for warning in chart.get("warnings", ()):
                self._log(f"Aviso no gráfico {chart_index + 1}: {warning}", "warning")

            output_path = os.path.join(working_dir, f"chart_{chart_index}.png")
            try:
                chart_renderer.render_chart(chart, style, output_path)
            except Exception as error:
                self._log(
                    f"Erro ao renderizar gráfico {chart_index + 1}: {error}",
                    "danger",
                )
                continue

            image_path = output_path.replace("\\", "/")
            image_link = f"![Gráfico {chart_index + 1}]({image_path})"
            start, end = match.span()
            modified_markdown = (
                modified_markdown[:start] + image_link + modified_markdown[end:]
            )
            self._log(f"Gráfico {chart_index + 1} renderizado com sucesso.")

        return modified_markdown

    def _load_pandoc(self):
        return load_pandoc(
            allow_download=self._allow_pandoc_download,
            log_callback=self._log,
        )

    def _export_pandoc_document(self, file_path, extension, content, pypandoc):
        extra_args = []
        if extension == ".docx":
            reference_doc = self._resource_resolver("templates/report_template.docx")
            if os.path.exists(reference_doc):
                extra_args.extend(["--reference-doc", reference_doc])
                self._log(f"Usando template Word: {reference_doc}")

        pypandoc.convert_text(
            content,
            extension[1:],
            format="gfm+hard_line_breaks",
            outputfile=file_path,
            extra_args=extra_args,
        )

    def _export_pdf(self, file_path, content, metadata, working_dir, pypandoc):
        typst_body = pypandoc.convert_text(
            content, "typst", format="gfm+hard_line_breaks"
        )
        normalized_working_dir = working_dir.replace("\\", "/")
        typst_body = typst_body.replace(
            f'image("{normalized_working_dir}/', 'image("'
        )

        template_path = self._resource_resolver("templates/report_template.typ")
        with open(template_path, "r", encoding="utf-8") as template_file:
            template = template_file.read()
        typst_source = (
            template.replace("__TITLE__", _escape_typst_text(metadata.title))
            .replace("__AUTHOR__", _escape_typst_text(metadata.author_field))
            .replace("__DATE__", _escape_typst_text(metadata.report_date))
            .replace("__BODY__", typst_body)
        )
        source_path = os.path.join(working_dir, "report.typ")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write(typst_source)

        import typst

        typst.compile(source_path, output=file_path, root=working_dir)

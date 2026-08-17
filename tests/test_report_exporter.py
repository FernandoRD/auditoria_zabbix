import os
import tempfile
import unittest
from unittest import mock

from core.report_exporter import ReportExporter, ReportMetadata
from core.run_config import ReportStyle


def _style():
    return ReportStyle(
        chart_type="Linha",
        chart_color="Padrão",
        chart_bg_color="Branco",
        chart_text_color="Preto (Padrão)",
        chart_width=800,
        chart_height=400,
        chart_font="Arial, Helvetica, sans-serif",
    )


class TestReportExporter(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.TemporaryDirectory(prefix="report_exporter_test_")
        self.addCleanup(self.output_dir.cleanup)
        self.metadata = ReportMetadata(
            author_name="Analista",
            company_name="Empresa",
            report_date="17/08/2026",
        )

    def test_markdown_success_uses_callbacks_and_real_atomic_writer(self):
        logs = []
        progress = []
        destination = os.path.join(self.output_dir.name, "report.md")
        exporter = ReportExporter(
            log_callback=lambda message, style="info": logs.append((message, style)),
            progress_callback=lambda value, text: progress.append((value, text)),
        )

        result = exporter.export(destination, "# Relatório\n", _style(), self.metadata)

        self.assertEqual(result, destination)
        with open(destination, "r", encoding="utf-8") as exported:
            self.assertEqual(exported.read(), "# Relatório\n")
        self.assertEqual([value for value, _text in progress], [0, 100])
        self.assertTrue(any("sucesso" in message for message, _style_name in logs))

    def test_docx_success_cleans_working_directory(self):
        working_dir = os.path.join(self.output_dir.name, "working-success")
        fake_pandoc = mock.Mock()
        destination = os.path.join(self.output_dir.name, "report.docx")
        exporter = ReportExporter(
            resource_resolver=lambda path: os.path.join(
                self.output_dir.name, "missing", path
            )
        )

        with mock.patch(
            "core.report_exporter.tempfile.mkdtemp", return_value=working_dir
        ), mock.patch.object(exporter, "_load_pandoc", return_value=fake_pandoc):
            os.mkdir(working_dir)
            exporter.export(destination, "# Relatório", _style(), self.metadata)

        self.assertFalse(os.path.exists(working_dir))
        fake_pandoc.convert_text.assert_called_once_with(
            "# Relatório",
            "docx",
            format="gfm+hard_line_breaks",
            outputfile=destination,
            extra_args=[],
        )

    def test_pandoc_loader_receives_explicit_download_consent(self):
        exporter = ReportExporter(allow_pandoc_download=True)
        fake_pandoc = mock.Mock()

        with mock.patch(
            "core.report_exporter.load_pandoc", return_value=fake_pandoc
        ) as load:
            self.assertIs(exporter._load_pandoc(), fake_pandoc)

        load.assert_called_once_with(
            allow_download=True,
            log_callback=exporter._log,
        )

    def test_conversion_failure_propagates_and_cleans_working_directory(self):
        working_dir = os.path.join(self.output_dir.name, "working-failure")
        fake_pandoc = mock.Mock()
        fake_pandoc.convert_text.side_effect = RuntimeError("falha sintética")
        destination = os.path.join(self.output_dir.name, "report.odt")
        exporter = ReportExporter()

        with mock.patch(
            "core.report_exporter.tempfile.mkdtemp", return_value=working_dir
        ), mock.patch.object(exporter, "_load_pandoc", return_value=fake_pandoc):
            os.mkdir(working_dir)
            with self.assertRaisesRegex(RuntimeError, "falha sintética"):
                exporter.export(destination, "# Relatório", _style(), self.metadata)

        self.assertFalse(os.path.exists(working_dir))

    def test_unsupported_format_fails_before_creating_temporary_directory(self):
        exporter = ReportExporter()
        destination = os.path.join(self.output_dir.name, "report.html")

        with mock.patch("core.report_exporter.tempfile.mkdtemp") as make_temp:
            with self.assertRaisesRegex(ValueError, "não suportado"):
                exporter.export(destination, "texto", _style(), self.metadata)

        make_temp.assert_not_called()

    def test_valid_pie_is_rendered_but_invalid_pie_is_preserved(self):
        exporter = ReportExporter()
        valid = (
            '```mermaid\npie showData\n  title "Tipos"\n'
            '  "A" : 3\n  "B" : 7\n```'
        )
        invalid = '```mermaid\npie\n  "A" : N/A\n```'

        rendered = exporter._render_mermaid_charts(
            valid, _style(), self.output_dir.name
        )
        preserved = exporter._render_mermaid_charts(
            invalid, _style(), self.output_dir.name
        )

        self.assertIn("![Gráfico 1]", rendered)
        self.assertEqual(invalid, preserved)


if __name__ == "__main__":
    unittest.main()

import os
import shutil
import tempfile
import unittest

from core.report_exporter import ReportExporter, ReportMetadata
from core.run_config import ReportStyle

try:
    import pypandoc
    _PANDOC_VERSION = tuple(int(p) for p in pypandoc.get_pandoc_version().split('.')[:3])
    _PANDOC_OK = _PANDOC_VERSION >= (3, 1, 7)
except Exception:
    _PANDOC_OK = False

try:
    import typst
    _TYPST_OK = True
except ImportError:
    _TYPST_OK = False

@unittest.skipUnless(_PANDOC_OK and _TYPST_OK,
                     "requer pandoc >= 3.1.7 e o pacote typst instalados")
class TestPdfPipeline(unittest.TestCase):
    """Smoke test da costura pandoc -> typst -> PDF usando o template real.

    Guarda contra regressões de helpers que o writer Typst do pandoc emite mas
    que só existem se o template os definir (ex.: '---' vira #horizontalrule,
    que quebrou a exportação em produção antes de ser definido no template)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pdf_pipeline_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compile(self, markdown):
        pdf_path = os.path.join(self.tmpdir, "out.pdf")
        style = ReportStyle(
            chart_type="Linha",
            chart_color="Padrão",
            chart_bg_color="Branco",
            chart_text_color="Preto (Padrão)",
            chart_width=800,
            chart_height=400,
            chart_font="Arial, Helvetica, sans-serif",
        )
        metadata = ReportMetadata(
            author_name="Autor de Teste",
            report_date="01/01/2026",
            title="Título de Teste",
        )
        ReportExporter().export(pdf_path, markdown, style, metadata)
        return pdf_path

    def test_markdown_with_horizontal_rules_compiles(self):
        pdf = self._compile("# Título\n\nAntes\n\n---\n\nDepois\n\n---\n\nFim.")
        self.assertGreater(os.path.getsize(pdf), 0)

    def test_representative_report_constructs_compile(self):
        md = (
            "# Relatório\n\n"
            "Texto com nota[^1] e ~~riscado~~.\n\n"
            "---\n\n"
            "> Citação em bloco\n\n"
            "| Métrica | Valor |\n|---|---|\n| NVPS | 120 |\n\n"
            "- [ ] pendente\n- [x] feita\n\n"
            "```bash\nls -la\n```\n\n"
            "```mermaid\n"
            "xychart-beta\n"
            "  title \"Itens por host\"\n"
            "  x-axis [\"srv-1\", \"srv-2\"]\n"
            "  y-axis \"Itens\" 0 --> 20\n"
            "  line [10, 15]\n"
            "```\n\n"
            "[link](https://example.com)\n\n"
            "[^1]: conteúdo da nota.\n"
        )
        pdf = self._compile(md)
        self.assertGreater(os.path.getsize(pdf), 0)


if __name__ == "__main__":
    unittest.main()

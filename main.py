import os
import sys
import tempfile

import ttkbootstrap as ttk
from gui.main_view import MainView
from core.controller import Controller


def _run_packaging_smoke_test():
    """Exercise bundled Pandoc through DOCX and PDF exports without opening Tk."""
    from core.report_exporter import ReportExporter, ReportMetadata
    from core.run_config import ReportStyle

    style = ReportStyle(
        chart_type="Linha",
        chart_color="Padrão",
        chart_bg_color="Branco",
        chart_text_color="Preto (Padrão)",
        chart_width=800,
        chart_height=400,
        chart_font="Arial, Helvetica, sans-serif",
    )
    metadata = ReportMetadata(author_name="Release smoke test", report_date="2026-01-01")
    with tempfile.TemporaryDirectory(prefix="auditoria_zabbix_bundle_smoke_") as tmpdir:
        for extension in (".docx", ".pdf"):
            output = os.path.join(tmpdir, "smoke" + extension)
            ReportExporter().export(output, "# Bundle smoke test\n", style, metadata)
            if not os.path.isfile(output) or os.path.getsize(output) == 0:
                raise RuntimeError(f"Exportação smoke inválida: {extension}")
    print("Bundle smoke test concluído: Pandoc incorporado, DOCX e PDF válidos.")


def main():
    """
    Ponto de entrada da aplicação.
    Cria a View (GUI), o Controller (lógica) e os conecta.
    """
    if sys.argv[1:] == ["--packaging-smoke-test"]:
        _run_packaging_smoke_test()
        return

    app = MainView()
    controller = Controller(view=app)
    app.set_controller(controller)
    app.mainloop()


if __name__ == "__main__":
    main()

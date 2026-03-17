import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT
import tkinter as tk
import threading
import os
import shutil
import tempfile
import html

class StyleSettingsWindow(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Estilos de Gráfico")
        self.geometry("550x580")
        self.grab_set()

        self.font_var = ttk.StringVar(value=self.parent.chart_font_var.get())
        self.type_var = ttk.StringVar(value=self.parent.chart_type_var.get())
        self.color_var = ttk.StringVar(value=self.parent.chart_color_var.get())

        self.preview_image = None
        self.temp_preview_dir = None

        self.create_widgets()
        self.update_preview()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=BOTH, expand=True)

        row2 = ttk.Frame(main_frame)
        row2.pack(fill=X, pady=5)
        ttk.Label(row2, text="Fonte Principal:", width=18).pack(side=LEFT)
        font_combo = ttk.Combobox(row2, textvariable=self.font_var, values=[
            "Arial, Helvetica, sans-serif", 
            "'Times New Roman', Times, serif", 
            "'Courier New', Courier, monospace", 
            "Verdana, Geneva, sans-serif",
            "Tahoma, Geneva, sans-serif"
        ], state="readonly")
        font_combo.pack(side=LEFT, fill=X, expand=True)
        font_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        row3 = ttk.Frame(main_frame)
        row3.pack(fill=X, pady=5)
        ttk.Label(row3, text="Tipo do Gráfico:", width=18).pack(side=LEFT)
        type_combo = ttk.Combobox(row3, textvariable=self.type_var, values=["Linha", "Barra"], state="readonly")
        type_combo.pack(side=LEFT, fill=X, expand=True)
        type_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        row4 = ttk.Frame(main_frame)
        row4.pack(fill=X, pady=5)
        ttk.Label(row4, text="Cor Principal:", width=18).pack(side=LEFT)
        color_combo = ttk.Combobox(row4, textvariable=self.color_var, values=["Padrão", "Azul", "Vermelho", "Verde", "Laranja", "Roxo"], state="readonly")
        color_combo.pack(side=LEFT, fill=X, expand=True)
        color_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        # Frame para a prévia
        preview_frame = ttk.LabelFrame(main_frame, text="Prévia do Gráfico")
        preview_frame.pack(fill=BOTH, expand=True, pady=15, ipadx=10, ipady=10)
        
        self.preview_label = ttk.Label(preview_frame, text="Gerando prévia... Aguarde.", justify="center")
        self.preview_label.pack(expand=True)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=X, pady=5)
        ttk.Button(btn_frame, text="Salvar", bootstyle="success", command=self.save_styles).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancelar", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)

    def update_preview(self):
        self.preview_label.configure(text="Gerando prévia com Playwright... Aguarde.", image='')
        font = self.font_var.get()
        chart_type = self.type_var.get()
        chart_color = self.color_var.get()
        
        thread = threading.Thread(target=self._render_preview_thread, args=(font, chart_type, chart_color))
        thread.daemon = True
        thread.start()

    def _render_preview_thread(self, font, chart_type, chart_color):
        template_path = os.path.join("templates", "mermaid_template.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                base_html = f.read()
        except FileNotFoundError:
            self.after(0, lambda: self.preview_label.configure(text=f"Erro: '{template_path}' não encontrado.", image=''))
            return

        try:
            from playwright.sync_api import sync_playwright
            
            ctype_en = "bar" if chart_type == "Barra" else "line"
            code = f"xychart-beta\n  title \"Exemplo de Desempenho\"\n  x-axis [\"1h\", \"45m\", \"30m\", \"15m\", \"Agora\"]\n  y-axis \"Uso de Cache (%)\" 0 --> 100\n  {ctype_en} [20, 35, 30, 60, 45]"
            
            color_map = {"Padrão": "", "Azul": "#3498db", "Vermelho": "#e74c3c", "Verde": "#2ecc71", "Laranja": "#e67e22", "Roxo": "#9b59b6"}
            hex_color = color_map.get(chart_color, "")
            theme_vars = f",\n                            themeVariables: {{ xyChart: {{ plotColorPalette: '{hex_color}' }} }}" if hex_color else ""
            
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                
                html_content = base_html.replace("__EXTRA_STYLE__", "display: inline-block;").replace(
                    "__CODE__", html.escape(code)).replace(
                    "__FONT__", font).replace(
                    "__THEME_VARS__", theme_vars)
                
                if not self.temp_preview_dir:
                    self.temp_preview_dir = tempfile.mkdtemp(prefix="zabbix_preview_")
                output_path = os.path.join(self.temp_preview_dir, "preview.png")
                
                page.set_content(html_content)
                page.wait_for_selector('#mermaid-container > svg', timeout=15000)
                chart_element = page.locator('body')
                chart_element.screenshot(path=output_path)
                browser.close()
                
                self.after(0, self._apply_preview_image, output_path)
        except Exception as e:
            self.after(0, lambda err=e: self.preview_label.configure(text=f"Erro na prévia:\n{err}", image=''))

    def _apply_preview_image(self, path):
        try:
            self.preview_image = tk.PhotoImage(file=path)
            self.preview_label.configure(image=self.preview_image, text="")
        except Exception as e:
            self.preview_label.configure(text=f"Erro ao carregar imagem:\n{e}", image='')

    def save_styles(self):
        self.parent.chart_font_var.set(self.font_var.get())
        self.parent.chart_type_var.set(self.type_var.get())
        self.parent.chart_color_var.set(self.color_var.get())
        self.parent.save_settings()
        self.destroy()

    def destroy(self):
        if self.temp_preview_dir:
            shutil.rmtree(self.temp_preview_dir, ignore_errors=True)
        super().destroy()
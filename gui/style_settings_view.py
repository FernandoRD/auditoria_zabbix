import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT
import tkinter as tk
import threading
import os
import shutil
import tempfile

from core.chart_renderer import parse_xychart, render_chart

class StyleSettingsWindow(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Estilos de Gráfico")
        self.geometry("1000x850")
        self.grab_set()

        self.font_var = ttk.StringVar(value=self.parent.chart_font_var.get())
        self.type_var = ttk.StringVar(value=self.parent.chart_type_var.get())
        self.color_var = ttk.StringVar(value=self.parent.chart_color_var.get())
        self.width_var = ttk.IntVar(value=self.parent.chart_width_var.get())
        self.height_var = ttk.IntVar(value=self.parent.chart_height_var.get())
        self.bg_color_var = ttk.StringVar(value=self.parent.chart_bg_color_var.get())
        self.text_color_var = ttk.StringVar(value=self.parent.chart_text_color_var.get())

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

        row5 = ttk.Frame(main_frame)
        row5.pack(fill=X, pady=5)
        ttk.Label(row5, text="Largura (px):", width=18).pack(side=LEFT)
        width_spin = ttk.Spinbox(row5, from_=400, to=2000, increment=50, textvariable=self.width_var)
        width_spin.pack(side=LEFT, fill=X, expand=True)
        width_spin.bind("<KeyRelease>", lambda e: self.update_preview())
        width_spin.bind("<<Increment>>", lambda e: self.update_preview())
        width_spin.bind("<<Decrement>>", lambda e: self.update_preview())

        row6 = ttk.Frame(main_frame)
        row6.pack(fill=X, pady=5)
        ttk.Label(row6, text="Altura (px):", width=18).pack(side=LEFT)
        height_spin = ttk.Spinbox(row6, from_=200, to=1000, increment=50, textvariable=self.height_var)
        height_spin.pack(side=LEFT, fill=X, expand=True)
        height_spin.bind("<KeyRelease>", lambda e: self.update_preview())
        height_spin.bind("<<Increment>>", lambda e: self.update_preview())
        height_spin.bind("<<Decrement>>", lambda e: self.update_preview())

        row7 = ttk.Frame(main_frame)
        row7.pack(fill=X, pady=5)
        ttk.Label(row7, text="Cor de Fundo:", width=18).pack(side=LEFT)
        bg_combo = ttk.Combobox(row7, textvariable=self.bg_color_var, values=["Branco", "Cinza Claro", "Escuro", "Transparente"], state="readonly")
        bg_combo.pack(side=LEFT, fill=X, expand=True)
        bg_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        row8 = ttk.Frame(main_frame)
        row8.pack(fill=X, pady=5)
        ttk.Label(row8, text="Cor do Texto/Eixos:", width=18).pack(side=LEFT)
        txt_combo = ttk.Combobox(row8, textvariable=self.text_color_var, values=["Preto (Padrão)", "Branco", "Cinza"], state="readonly")
        txt_combo.pack(side=LEFT, fill=X, expand=True)
        txt_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        # Frame para a prévia
        preview_frame = ttk.LabelFrame(main_frame, text="Prévia do Gráfico")
        preview_frame.pack(fill=BOTH, expand=True, pady=15)
        
        self.preview_canvas = tk.Canvas(preview_frame, highlightthickness=0)
        hbar = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.preview_canvas.xview)
        vbar = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_canvas.yview)
        self.preview_canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        
        hbar.pack(side="bottom", fill="x")
        vbar.pack(side="right", fill="y")
        self.preview_canvas.pack(side="left", fill="both", expand=True)
        
        self.inner_preview_frame = ttk.Frame(self.preview_canvas)
        self.preview_canvas.create_window((0, 0), window=self.inner_preview_frame, anchor="nw")
        self.inner_preview_frame.bind("<Configure>", lambda e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))
        
        self.preview_label = ttk.Label(self.inner_preview_frame, text="Gerando prévia... Aguarde.", justify="center")
        self.preview_label.pack(padx=20, pady=20)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=X, pady=5)
        ttk.Button(btn_frame, text="Salvar", bootstyle="success", command=self.save_styles).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancelar", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)

    def update_preview(self):
        self.preview_label.configure(text="Gerando prévia... Aguarde.", image='')
        font = self.font_var.get()
        chart_type = self.type_var.get()
        chart_color = self.color_var.get()
        chart_bg_color = self.bg_color_var.get()
        chart_text_color = self.text_color_var.get()
        
        try:
            chart_width = self.width_var.get()
        except tk.TclError:
            chart_width = 800
            
        try:
            chart_height = self.height_var.get()
        except tk.TclError:
            chart_height = 400
        
        thread = threading.Thread(target=self._render_preview_thread, args=(font, chart_type, chart_color, chart_width, chart_height, chart_bg_color, chart_text_color))
        thread.daemon = True
        thread.start()

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
        
        try:
            self.parent.chart_width_var.set(self.width_var.get())
        except tk.TclError:
            self.parent.chart_width_var.set(800)
            
        try:
            self.parent.chart_height_var.set(self.height_var.get())
        except tk.TclError:
            self.parent.chart_height_var.set(400)
        self.parent.chart_bg_color_var.set(self.bg_color_var.get())
        self.parent.chart_text_color_var.set(self.text_color_var.get())
        self.parent.save_settings()
        self.destroy()

    def destroy(self):
        if self.temp_preview_dir:
            shutil.rmtree(self.temp_preview_dir, ignore_errors=True)
        super().destroy()
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT, WORD, END
import tkinter as tk
import threading
from tkinter import filedialog
import os
import re
import json
import shutil
import tempfile
from dotenv import load_dotenv
import html
from datetime import datetime
import pathlib

class MainView(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Auditoria Inteligente de Zabbix")
        self.geometry("900x700")
        self.controller = None

        # Carrega defaults do .env (se existir)
        load_dotenv()
        self.settings_file = "settings.json"
        self.ai_accounts = {
            "Google Gemini": {"provider": "Google Gemini", "api_key": os.getenv("GEMINI_API_KEY", "")},
            "OpenAI": {"provider": "OpenAI", "api_key": os.getenv("OPENAI_API_KEY", "")},
            "Anthropic": {"provider": "Anthropic", "api_key": os.getenv("ANTHROPIC_API_KEY", "")},
            "Ollama": {"provider": "Ollama", "api_key": os.getenv("OLLAMA_URL", "http://localhost:11434")}
        }
        self.settings = {}
        self.load_settings()

        default_account = self.settings.get("ai_account", "Google Gemini")
        if default_account not in self.ai_accounts:
            default_account = list(self.ai_accounts.keys())[0] if self.ai_accounts else ""

        self.zabbix_url_var = ttk.StringVar(value=self.settings.get("zabbix_url", os.getenv("ZABBIX_URL", "")))
        self.zabbix_user_var = ttk.StringVar(value=self.settings.get("zabbix_user", os.getenv("ZABBIX_USER", "")))
        self.zabbix_pass_var = ttk.StringVar(value=self.settings.get("zabbix_pass", os.getenv("ZABBIX_PASS", "")))
        self.ai_provider_var = ttk.StringVar(value=default_account)
        self.ai_key_var = ttk.StringVar(value=self.ai_accounts.get(default_account, {}).get("api_key", ""))

        self.analyst_name_var = ttk.StringVar(value=self.settings.get("analyst_name", ""))
        self.analyst_company_var = ttk.StringVar(value=self.settings.get("analyst_company", ""))
        self.analyst_email_var = ttk.StringVar(value=self.settings.get("analyst_email", ""))
        self.analyst_phone_var = ttk.StringVar(value=self.settings.get("analyst_phone", ""))

        self.chart_font_var = ttk.StringVar(value=self.settings.get("chart_font", "Arial, Helvetica, sans-serif"))

        self.chart_type_var = ttk.StringVar(value=self.settings.get("chart_type", "Linha"))
        self.chart_color_var = ttk.StringVar(value=self.settings.get("chart_color", "Padrão"))

        # Rastreadores (Traces) para detectar alterações na interface e mudar a chave correta
        self.ai_key_var.trace_add("write", self.update_key_dict)
        self.ai_provider_var.trace_add("write", self.on_provider_change)

        self.attached_files = []
        self.create_widgets()

    def set_controller(self, controller):
        self.controller = controller

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
                    if "ai_accounts" in self.settings:
                        self.ai_accounts = self.settings["ai_accounts"]
                    elif "api_keys" in self.settings:
                        for k, v in self.settings["api_keys"].items():
                            if k in self.ai_accounts:
                                self.ai_accounts[k]["api_key"] = v
            except Exception:
                pass

    def save_settings(self):
        self.settings["zabbix_url"] = self.zabbix_url_var.get()
        self.settings["zabbix_user"] = self.zabbix_user_var.get()
        self.settings["zabbix_pass"] = self.zabbix_pass_var.get()
        self.settings["ai_account"] = self.ai_provider_var.get()
        self.settings["ai_accounts"] = self.ai_accounts
        
        self.settings["analyst_name"] = self.analyst_name_var.get()
        self.settings["analyst_company"] = self.analyst_company_var.get()
        self.settings["analyst_email"] = self.analyst_email_var.get()
        self.settings["analyst_phone"] = self.analyst_phone_var.get()
        
        self.settings["chart_font"] = self.chart_font_var.get()
        self.settings["chart_type"] = self.chart_type_var.get()
        self.settings["chart_color"] = self.chart_color_var.get()
        if "api_keys" in self.settings:
            del self.settings["api_keys"]
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def update_key_dict(self, *args):
        account = self.ai_provider_var.get()
        if account in self.ai_accounts:
            self.ai_accounts[account]["api_key"] = self.ai_key_var.get()

    def on_provider_change(self, *args):
        account = self.ai_provider_var.get()
        account_info = self.ai_accounts.get(account, {})
        self.ai_key_var.set(account_info.get("api_key", ""))
        
        base_provider = account_info.get("provider", "")
        if hasattr(self, 'ai_key_entry'):
            if base_provider == "Ollama":
                self.ai_key_entry.configure(show="")
            else:
                self.ai_key_entry.configure(show="*")

    def get_selected_base_provider(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("provider", "Google Gemini")

    def open_manage_accounts_window(self):
        ManageAccountsWindow(self)
        
    def open_style_settings_window(self):
        StyleSettingsWindow(self)
        
    def refresh_accounts(self, select_account=""):
        account_names = list(self.ai_accounts.keys())
        self.provider_combo['values'] = account_names
        if select_account and select_account in account_names:
            self.ai_provider_var.set(select_account)
        elif account_names:
            self.ai_provider_var.set(account_names[0])
        else:
            self.ai_provider_var.set("")

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=BOTH, expand=True)

        # --- Painel de Controle ---
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=X, pady=(0, 10))

        self.start_button = ttk.Button(
            control_frame,
            text="Iniciar Auditoria",
            command=self.start_audit_clicked,
            bootstyle="success-outline"
        )
        self.start_button.pack(side=LEFT, padx=(0, 10))

        ttk.Label(control_frame, text="Modelo IA:").pack(side=LEFT, padx=(10, 5))
        self.model_var = ttk.StringVar()
        self.model_combo = ttk.Combobox(
            control_frame,
            textvariable=self.model_var,
            state="readonly",
            width=25
        )
        self.model_combo.pack(side=LEFT, padx=(0, 10))
        self.model_combo.set("Carregando modelos...")

        self.attach_button = ttk.Button(
            control_frame,
            text="📎 Anexar Evidências OS",
            command=self.attach_files_clicked,
            bootstyle="secondary-outline"
        )
        self.attach_button.pack(side=LEFT, padx=(0, 5))
        
        self.manage_attach_button = ttk.Button(
            control_frame,
            text="⚙️ Gerenciar",
            command=self.open_manage_attachments,
            bootstyle="warning-outline",
            state="disabled"
        )
        self.manage_attach_button.pack(side=LEFT, padx=(0, 10))

        self.files_label = ttk.Label(control_frame, text="")
        self.files_label.pack(side=LEFT)

        # --- Notebook (Abas) ---
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=BOTH, expand=True)

        # 1. Aba de Configurações
        config_frame = ttk.Frame(notebook, padding=15)
        notebook.add(config_frame, text="⚙️ Configurações")
        
        z_frame = ttk.LabelFrame(config_frame, text="Credenciais do Zabbix")
        z_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        ttk.Label(z_frame, text="URL da API:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(z_frame, textvariable=self.zabbix_url_var, width=55).grid(row=0, column=1, sticky="w", pady=5, padx=5)
        ttk.Label(z_frame, text="(ex: http://meu-ip/zabbix/api_jsonrpc.php)").grid(row=0, column=2, sticky="w")
        
        ttk.Label(z_frame, text="Usuário:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(z_frame, textvariable=self.zabbix_user_var, width=30).grid(row=1, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Label(z_frame, text="Senha:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(z_frame, textvariable=self.zabbix_pass_var, width=30, show="*").grid(row=2, column=1, sticky="w", pady=5, padx=5)
        
        ai_frame = ttk.LabelFrame(config_frame, text="Inteligência Artificial")
        ai_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        ttk.Label(ai_frame, text="Conta/Provedor:").grid(row=0, column=0, sticky="w", pady=5)
        self.provider_combo = ttk.Combobox(ai_frame, textvariable=self.ai_provider_var, values=list(self.ai_accounts.keys()), state="readonly", width=25)
        self.provider_combo.grid(row=0, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Button(ai_frame, text="⚙️ Gerenciar Contas", command=self.open_manage_accounts_window, bootstyle="secondary-outline").grid(row=0, column=2, padx=5)
        
        ttk.Label(ai_frame, text="Key / URL:").grid(row=1, column=0, sticky="w", pady=5)
        self.ai_key_entry = ttk.Entry(ai_frame, textvariable=self.ai_key_var, width=55, show="*")
        self.ai_key_entry.grid(row=1, column=1, sticky="w", pady=5, padx=5)
        
        # Atualiza a visibilidade do campo caso a IA salva por padrão seja o Ollama
        self.on_provider_change()
        
        ttk.Button(ai_frame, text="🔄 Validar Conexão / Atualizar Modelos", command=self.validate_and_load_models, bootstyle="info-outline").grid(row=1, column=2, padx=5)

        # --- Dados do Analista ---
        analyst_frame = ttk.LabelFrame(config_frame, text="Dados do Analista / Empresa (Cabeçalho do Relatório)")
        analyst_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        
        ttk.Label(analyst_frame, text="Nome:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(analyst_frame, textvariable=self.analyst_name_var, width=30).grid(row=0, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Label(analyst_frame, text="Empresa:").grid(row=0, column=2, sticky="w", pady=5, padx=(10, 0))
        ttk.Entry(analyst_frame, textvariable=self.analyst_company_var, width=30).grid(row=0, column=3, sticky="w", pady=5, padx=5)
        
        ttk.Label(analyst_frame, text="E-mail:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(analyst_frame, textvariable=self.analyst_email_var, width=30).grid(row=1, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Label(analyst_frame, text="Telefone:").grid(row=1, column=2, sticky="w", pady=5, padx=(10, 0))
        ttk.Entry(analyst_frame, textvariable=self.analyst_phone_var, width=30).grid(row=1, column=3, sticky="w", pady=5, padx=5)

        # --- Estilos de Gráfico e Exportação ---
        export_frame = ttk.LabelFrame(config_frame, text="Aparência e Exportação")
        export_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        ttk.Button(export_frame, text="🎨 Configurar Estilos de Gráfico", command=self.open_style_settings_window, bootstyle="info-outline").pack(side=LEFT, padx=10, pady=5)

        # 2. Aba de Logs
        log_frame = ttk.Frame(notebook, padding=5)
        self.log_text = ScrolledText(log_frame, wrap=WORD, autohide=True, state="disabled")
        self.log_text.pack(fill=BOTH, expand=True)
        
        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.pack(fill=X, pady=(5, 0))
        ttk.Button(log_btn_frame, text="💾 Salvar Logs", command=self.save_logs_clicked, bootstyle="secondary").pack(side=LEFT)
        notebook.add(log_frame, text="Logs da Execução")

        # 3. Aba de Relatório
        report_frame = ttk.Frame(notebook, padding=5)
        self.report_text = ScrolledText(report_frame, wrap=WORD, autohide=True, state="disabled")
        self.report_text.pack(fill=BOTH, expand=True)
        
        report_btn_frame = ttk.Frame(report_frame)
        report_btn_frame.pack(fill=X, pady=(5, 0))
        ttk.Button(report_btn_frame, text="💾 Salvar / Exportar Relatório", command=self.save_report_clicked, bootstyle="primary").pack(side=LEFT)
        notebook.add(report_frame, text="Relatório Final")

    def update_model_list(self, models, default_model=None):
        self.model_combo['values'] = models
        if default_model and default_model in models:
            self.model_combo.set(default_model)
        elif models:
            self.model_combo.set(models[0])
        else:
            self.model_combo.set("Nenhum modelo")

    def get_selected_model(self):
        return self.model_var.get()

    def attach_files_clicked(self):
        files = filedialog.askopenfilenames(
            title="Selecione os arquivos de configuração ou log",
            filetypes=(("Text/Log/Conf", "*.txt *.log *.conf"), ("All files", "*.*"))
        )
        if files:
            for f in files:
                if f not in self.attached_files:
                    self.attached_files.append(f)
            self.update_attachments_ui()

    def update_attachments_ui(self):
        count = len(self.attached_files)
        if count > 0:
            self.files_label.configure(text=f"{count} arquivo(s) anexado(s)")
            self.manage_attach_button.configure(state="normal")
        else:
            self.files_label.configure(text="")
            self.manage_attach_button.configure(state="disabled")

    def open_manage_attachments(self):
        ManageAttachmentsWindow(self)

    def validate_and_load_models(self):
        self.save_settings()
        if self.controller:
            self.controller.load_models_async()

    def save_logs_clicked(self):
        initial_dir = self.settings.get("last_log_dir", os.path.expanduser("~"))
        file_path = filedialog.asksaveasfilename(
            title="Salvar Logs",
            initialdir=initial_dir,
            defaultextension=".txt",
            filetypes=[("Arquivos de Texto", "*.txt"), ("Todos os arquivos", "*.*")]
        )
        if file_path:
            try:
                self.settings["last_log_dir"] = os.path.dirname(file_path)
                self.save_settings()
                
                log_content = self.log_text.text.get("1.0", END)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(log_content)
                self.log(f"Logs salvos com sucesso em: {file_path}")
            except Exception as e:
                self.log(f"Erro ao salvar logs: {e}")

    def _render_mermaid_charts(self, markdown_content):
        """
        Finds Mermaid blocks, renders them as images using a headless browser (Playwright), 
        and replaces the blocks with image links.
        Returns the modified markdown and the path to the temporary directory created.
        """
        try:
            from playwright.sync_api import sync_playwright, Error as PlaywrightError
        except ImportError:
            self.log("Aviso: Biblioteca 'playwright' não instalada.", "warning")
            self.log("Execute 'pip install playwright' e 'playwright install' para habilitar a renderização de gráficos.", "warning")
            return markdown_content, None

        temp_dir = tempfile.mkdtemp(prefix="zabbix_audit_charts_")
        modified_markdown = markdown_content
        
        mermaid_regex = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
        matches = list(mermaid_regex.finditer(modified_markdown))

        if not matches:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return markdown_content, None

        self.log(f"Encontrados {len(matches)} gráficos Mermaid. Renderizando com Playwright...", "info")
        self.update()
        
        template_path = os.path.join("templates", "mermaid_template.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                base_html = f.read()
        except FileNotFoundError:
            self.log(f"Erro: Arquivo '{template_path}' não encontrado. Abortando renderização.", "danger")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return markdown_content, None

        chart_font = self.chart_font_var.get()
        chart_type = self.chart_type_var.get()
        chart_color = self.chart_color_var.get()
        ctype_en = "bar" if chart_type == "Barra" else "line"
        color_map = {"Padrão": "", "Azul": "#3498db", "Vermelho": "#e74c3c", "Verde": "#2ecc71", "Laranja": "#e67e22", "Roxo": "#9b59b6"}
        hex_color = color_map.get(chart_color, "")
        theme_vars = f",\n                                themeVariables: {{ xyChart: {{ plotColorPalette: '{hex_color}' }} }}" if hex_color else ""
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()

                for i, match in enumerate(reversed(matches)):
                    chart_index = len(matches) - 1 - i
                    code = match.group(1)
                    # Corrige alucinações comuns da IA e força a escolha do usuário
                    code = re.sub(r'^(?:lineChart|barChart)', 'xychart-beta', code, flags=re.MULTILINE)
                    code = re.sub(r'^\s*data:\s*\[', f'  {ctype_en} [', code, flags=re.MULTILINE)
                    code = re.sub(r'^\s*(?:line|bar)\s*\[', f'  {ctype_en} [', code, flags=re.MULTILINE)
                    output_file_path = os.path.join(temp_dir, f"chart_{chart_index}.png")

                    html_content = base_html.replace("__EXTRA_STYLE__", "").replace(
                        "__CODE__", html.escape(code)).replace(
                        "__FONT__", chart_font).replace(
                        "__THEME_VARS__", theme_vars)

                    try:
                        page.set_content(html_content)
                        page.wait_for_selector('#mermaid-container > svg', timeout=15000)
                        chart_element = page.locator('#mermaid-container > svg')
                        
                        chart_element.screenshot(path=output_file_path)

                        image_link_path = output_file_path.replace('\\', '/')
                        image_link = f"![Gráfico Mermaid {chart_index+1}]({image_link_path})"
                        start, end = match.span()
                        modified_markdown = modified_markdown[:start] + image_link + modified_markdown[end:]
                        self.log(f"Gráfico {chart_index+1} renderizado com sucesso.", "info")

                    except Exception as e:
                        self.log(f"Erro ao renderizar gráfico Mermaid {chart_index+1} com Playwright: {e}", "danger")
                        continue
                
                browser.close()
        except PlaywrightError:
            self.log("Erro no Playwright: Navegadores não encontrados.", "danger")
            self.log("Execute 'playwright install' no seu terminal para baixar os navegadores.", "danger")
            self.log("A exportação continuará, mas os gráficos aparecerão como blocos de código.", "warning")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return markdown_content, None
        
        return modified_markdown, temp_dir

    def save_report_clicked(self):
        initial_dir = self.settings.get("last_report_dir", os.path.expanduser("~"))
        type_var = ttk.StringVar(value="Markdown")
        filetypes_list = [("Markdown", "*.md"), ("Word Document", "*.docx"), ("PDF", "*.pdf"), ("OpenDocument Text", "*.odt"), ("Texto Puro", "*.txt"), ("Todos os arquivos", "*.*")]
        file_path = filedialog.asksaveasfilename(
            title="Exportar Relatório",
            initialdir=initial_dir,
            typevariable=type_var,
            filetypes=filetypes_list
        )
        if not file_path:
            return

        temp_dir_to_clean = None
        try:
            if not os.path.splitext(file_path)[1]:
                selected = type_var.get()
                for name, ext_pattern in filetypes_list:
                    if name == selected and ext_pattern != "*.*":
                        file_path += ext_pattern.replace("*", "")
                        break
                else:
                    file_path += ".md"

            self.settings["last_report_dir"] = os.path.dirname(file_path)
            self.save_settings()
            
            report_content = self.report_text.text.get("1.0", END).strip()
            if not report_content:
                self.log("Aviso: O relatório está vazio.", "warning")
                return
                
            # Limpa bloco de código caso a IA tenha encapsulado toda a resposta
            clean_content = report_content
            if clean_content.startswith("```markdown"):
                clean_content = clean_content[11:]
            elif clean_content.startswith("```md"):
                clean_content = clean_content[5:]
            elif clean_content.startswith("```"):
                clean_content = clean_content[3:]
                
            if clean_content.endswith("```"):
                clean_content = clean_content[:-3]
                
            report_content = clean_content.strip()
            
            ext = os.path.splitext(file_path)[1].lower()
            
            processed_content = report_content
            if ext in ['.pdf', '.docx', '.odt']:
                processed_content, temp_dir_to_clean = self._render_mermaid_charts(report_content)
            
            if ext in ['.md', '.txt', '']:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(report_content)
                self.log(f"Relatório salvo com sucesso em: {file_path}")
            else:
                self.log(f"Convertendo relatório para {ext}... Aguarde (pode demorar).", "info")
                self.update()
                
                import pypandoc
                try:
                    pypandoc.get_pandoc_version()
                except OSError:
                    self.log("Pandoc não encontrado. Baixando e instalando...", "warning")
                    self.update()
                    pypandoc.download_pandoc()
                
                to_format = 'pdf' if ext == '.pdf' else ext.replace('.', '')
                extra_args = []
                
                if to_format == 'docx':
                    reference_doc_path = 'templates/report_template.docx'
                    if os.path.exists(reference_doc_path):
                        extra_args.extend(['--reference-doc', reference_doc_path])
                        self.log(f"Usando template Word: {reference_doc_path}", "info")
                
                if to_format == 'pdf':
                    # Exportação de PDF usando Playwright + HTML (Elimina necessidade de LaTeX)
                    try:
                        html_body = pypandoc.convert_text(processed_content, 'html', format='gfm+hard_line_breaks')
                        
                        author_name = self.analyst_name_var.get().strip()
                        company_name = self.analyst_company_var.get().strip()
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
                        
                        temp_html_path = os.path.join(tempfile.gettempdir(), "zabbix_report_temp.html")
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
                else:
                    try:
                        pypandoc.convert_text(processed_content, to_format, format='gfm+hard_line_breaks', outputfile=file_path, extra_args=extra_args)
                        self.log(f"Relatório exportado com sucesso em: {file_path}")
                    except Exception as e:
                        self.log(f"Erro ao converter com Pandoc: {e}", "danger")

        except Exception as e:
            self.log(f"Erro ao exportar relatório: {e}", "danger")
        finally:
            if temp_dir_to_clean:
                self.log("Limpando arquivos temporários dos gráficos...", "info")
                shutil.rmtree(temp_dir_to_clean, ignore_errors=True)

    def start_audit_clicked(self):
        self.save_settings()
        if self.controller:
            self.controller.start_audit()

    def log(self, message, style="info"):
        self.log_text.text.configure(state="normal")
        self.log_text.text.insert(END, f"{message}\n")
        self.log_text.text.see(END) # Auto-scroll
        self.log_text.text.configure(state="disabled")

    def show_report(self, report_content):
        self.report_text.text.configure(state="normal")
        self.report_text.text.delete("1.0", END)
        self.report_text.text.insert("1.0", report_content)
        self.report_text.text.configure(state="disabled")

    def set_ui_state(self, state):
        self.start_button.configure(state=state)

class ManageAccountsWindow(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Gerenciar Contas de IA")
        self.geometry("500x320")
        self.grab_set()

        self.account_list = list(self.parent.ai_accounts.keys())
        self.selected_account = ttk.StringVar(value="<Nova Conta>")
        
        self.account_name_var = ttk.StringVar()
        self.base_provider_var = ttk.StringVar(value="Google Gemini")
        self.token_var = ttk.StringVar()

        self.create_widgets()
        self.on_account_select()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=BOTH, expand=True)

        row0 = ttk.Frame(main_frame)
        row0.pack(fill=X, pady=5)
        ttk.Label(row0, text="Selecionar Conta:", width=18).pack(side=LEFT)
        self.combo_accounts = ttk.Combobox(row0, textvariable=self.selected_account, values=["<Nova Conta>"] + self.account_list, state="readonly")
        self.combo_accounts.pack(side=LEFT, fill=X, expand=True)
        self.selected_account.trace_add("write", self.on_account_select)

        row1 = ttk.Frame(main_frame)
        row1.pack(fill=X, pady=5)
        ttk.Label(row1, text="Nome da Conta:", width=18).pack(side=LEFT)
        ttk.Entry(row1, textvariable=self.account_name_var).pack(side=LEFT, fill=X, expand=True)

        row2 = ttk.Frame(main_frame)
        row2.pack(fill=X, pady=5)
        ttk.Label(row2, text="Provedor Base:", width=18).pack(side=LEFT)
        ttk.Combobox(row2, textvariable=self.base_provider_var, values=["Google Gemini", "OpenAI", "Anthropic", "Ollama"], state="readonly").pack(side=LEFT, fill=X, expand=True)

        row3 = ttk.Frame(main_frame)
        row3.pack(fill=X, pady=5)
        ttk.Label(row3, text="Token/URL:", width=18).pack(side=LEFT)
        ttk.Entry(row3, textvariable=self.token_var, show="*").pack(side=LEFT, fill=X, expand=True)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=X, pady=20)
        ttk.Button(btn_frame, text="Salvar", bootstyle="success", command=self.save_account).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Remover", bootstyle="danger", command=self.remove_account).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancelar", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)

    def on_account_select(self, *args):
        selected = self.selected_account.get()
        if selected == "<Nova Conta>":
            self.account_name_var.set("")
            self.base_provider_var.set("Google Gemini")
            self.token_var.set("")
        elif selected in self.parent.ai_accounts:
            self.account_name_var.set(selected)
            self.base_provider_var.set(self.parent.ai_accounts[selected]["provider"])
            self.token_var.set(self.parent.ai_accounts[selected]["api_key"])

    def save_account(self):
        old_name = self.selected_account.get()
        new_name = self.account_name_var.get().strip()
        base_prov = self.base_provider_var.get()
        token = self.token_var.get().strip()

        if not new_name:
            return

        if old_name != "<Nova Conta>" and old_name != new_name:
            if old_name in self.parent.ai_accounts:
                del self.parent.ai_accounts[old_name]

        self.parent.ai_accounts[new_name] = {
            "provider": base_prov,
            "api_key": token
        }

        self.parent.save_settings()
        self.parent.refresh_accounts(new_name)
        self.destroy()

    def remove_account(self):
        selected = self.selected_account.get()
        if selected != "<Nova Conta>" and selected in self.parent.ai_accounts:
            del self.parent.ai_accounts[selected]
            self.parent.save_settings()
            
            next_acc = list(self.parent.ai_accounts.keys())[0] if self.parent.ai_accounts else ""
            self.parent.refresh_accounts(next_acc)
            self.destroy()

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

class ManageAttachmentsWindow(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Gerenciar Anexos")
        self.geometry("600x400")
        self.grab_set()

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=BOTH, expand=True)

        ttk.Label(main_frame, text="Arquivos Selecionados:", font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(0, 5))

        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=BOTH, expand=True, pady=(0, 15))
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=RIGHT, fill="y")
        
        self.listbox = tk.Listbox(list_frame, selectmode="extended", yscrollcommand=scrollbar.set)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        for f in self.parent.attached_files:
            self.listbox.insert(tk.END, f)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=X)

        ttk.Button(btn_frame, text="Adicionar Mais", bootstyle="success", command=self.add_files).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Remover Selecionado", bootstyle="danger", command=self.remove_files).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Limpar Tudo", bootstyle="warning", command=self.clear_all).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="Fechar", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Selecione os arquivos de configuração ou log",
            filetypes=(("Text/Log/Conf", "*.txt *.log *.conf"), ("All files", "*.*"))
        )
        if files:
            for f in files:
                if f not in self.parent.attached_files:
                    self.parent.attached_files.append(f)
                    self.listbox.insert(tk.END, f)
            self.parent.update_attachments_ui()

    def remove_files(self):
        selected_indices = list(self.listbox.curselection())
        selected_indices.reverse()  # Remove do último para o primeiro para não alterar os índices
        for i in selected_indices:
            file_to_remove = self.listbox.get(i)
            if file_to_remove in self.parent.attached_files:
                self.parent.attached_files.remove(file_to_remove)
            self.listbox.delete(i)
        self.parent.update_attachments_ui()

    def clear_all(self):
        self.parent.attached_files.clear()
        self.listbox.delete(0, tk.END)
        self.parent.update_attachments_ui()
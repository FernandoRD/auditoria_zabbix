import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT, WORD, END
from tkinter import filedialog
import os
import json
from dotenv import load_dotenv

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
        self.attach_button.pack(side=LEFT, padx=(0, 10))
        
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
            self.attached_files.extend(files)
            self.files_label.configure(text=f"{len(self.attached_files)} arquivo(s) anexado(s)")

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

    def save_report_clicked(self):
        initial_dir = self.settings.get("last_report_dir", os.path.expanduser("~"))
        
        type_var = ttk.StringVar(value="Markdown")
        filetypes_list = [
            ("Markdown", "*.md"),
            ("Word Document", "*.docx"),
            ("PDF", "*.pdf"),
            ("OpenDocument Text", "*.odt"),
            ("Texto Puro", "*.txt"),
            ("Todos os arquivos", "*.*")
        ]
        
        file_path = filedialog.asksaveasfilename(
            title="Exportar Relatório",
            initialdir=initial_dir,
            typevariable=type_var,
            filetypes=filetypes_list
        )
        if file_path:
            try:
                # Se o usuário não digitou a extensão, pegamos a do menu selecionado
                if not os.path.splitext(file_path)[1]:
                    selected = type_var.get()
                    for name, ext in filetypes_list:
                        if name == selected and ext != "*.*":
                            file_path += ext.replace("*", "")
                            break
                    else:
                        file_path += ".md"  # Fallback caso nada seja escolhido

                self.settings["last_report_dir"] = os.path.dirname(file_path)
                self.save_settings()
                
                report_content = self.report_text.text.get("1.0", END).strip()
                if not report_content:
                    self.log("Aviso: O relatório está vazio.", "warning")
                    return
                    
                ext = os.path.splitext(file_path)[1].lower()
                
                if ext in ['.md', '.txt', '']:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(report_content)
                    self.log(f"Relatório salvo com sucesso em: {file_path}")
                elif ext == '.pdf':
                    self.log("Gerando PDF nativo a partir do Markdown... Aguarde.", "info")
                    self.update()
                    import markdown
                    from xhtml2pdf import pisa
                    
                    # Interpreta o Markdown para HTML e aplica CSS para ficar organizado
                    html_content = markdown.markdown(report_content, extensions=['tables', 'fenced_code'])
                    styled_html = f"""
                    <html><head>
                    <meta charset="UTF-8">
                    <style>
                        body {{ font-family: Helvetica, Arial, sans-serif; font-size: 12px; line-height: 1.5; }}
                        h1, h2, h3 {{ color: #2c3e50; }}
                        table {{ border-collapse: collapse; width: 100%; margin-bottom: 15px; }}
                        th, td {{ border: 1px solid #ddd; padding: 6px; text-align: left; }}
                        th {{ background-color: #f8f9fa; }}
                        code {{ background-color: #f4f4f4; padding: 2px 4px; border-radius: 4px; font-family: monospace; }}
                        pre {{ background-color: #f8f9fa; padding: 10px; border: 1px solid #ddd; border-radius: 4px; }}
                    </style></head><body>{html_content}</body></html>
                    """
                    with open(file_path, "wb") as pdf_file:
                        pisa_status = pisa.CreatePDF(styled_html.encode('utf-8'), dest=pdf_file, encoding='utf-8')
                    if pisa_status.err:
                        self.log("Erro ao gerar o arquivo PDF.", "danger")
                    else:
                        self.log(f"Relatório exportado com sucesso em: {file_path}")
                else:
                    self.log(f"Convertendo relatório para {ext}... Aguarde (pode demorar na 1ª vez).", "info")
                    self.update() # Força a interface a desenhar o log
                    
                    import pypandoc
                    try:
                        pypandoc.get_pandoc_version()
                    except OSError:
                        self.log("Pandoc não encontrado. Baixando e instalando nos bastidores...", "warning")
                        self.update()
                        pypandoc.download_pandoc()
                    
                    to_format = ext.replace('.', '')
                    try:
                        # O Pandoc exige que a instrução de formato seja 'markdown' e não 'md'
                        pypandoc.convert_text(report_content, to_format, format='markdown', outputfile=file_path)
                        self.log(f"Relatório exportado com sucesso em: {file_path}")
                    except Exception as e:
                        self.log(f"Erro ao converter com Pandoc: {e}", "danger")
            except ImportError:
                self.log("ERRO: Biblioteca ausente. Execute: pip install pypandoc markdown xhtml2pdf", "danger")
            except Exception as e:
                self.log(f"Erro ao exportar relatório: {e}", "danger")

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
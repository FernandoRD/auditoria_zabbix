import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT, WORD, END
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.tooltip import ToolTip
import tkinter as tk
import threading
from tkinter import filedialog
import os
import re
import json
import shutil
import keyring
import tempfile
from dotenv import load_dotenv
from datetime import datetime
from gui.manage_accounts_view import ManageAccountsWindow
from gui.style_settings_view import StyleSettingsWindow
from gui.manage_attachments_view import ManageAttachmentsWindow
from api.ai_cli_client import cli_binary_status
from core.paths import resource_path
from core import chart_renderer

def _escape_typst_text(text):
    """Escapa caracteres com significado especial em markup Typst (usado só para os
    campos de texto livre da capa do PDF — nome/empresa do analista)."""
    for ch in ['\\', '#', '*', '_', '`', '<', '>', '@', '$', '[', ']']:
        text = text.replace(ch, '\\' + ch)
    return text

class MainView(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Auditoria Inteligente de Zabbix")
        self.geometry("1100x710")
        self.controller = None

        # Carrega defaults do .env (se existir)
        load_dotenv()
        self.settings_file = "settings.json"
        self.ai_accounts = {
            "Google Gemini": {"provider": "Google Gemini", "api_key": os.getenv("GEMINI_API_KEY", ""), "auth_mode": "api_key", "cli_model_override": ""},
            "OpenAI": {"provider": "OpenAI", "api_key": os.getenv("OPENAI_API_KEY", ""), "auth_mode": "api_key", "cli_model_override": ""},
            "Anthropic": {"provider": "Anthropic", "api_key": os.getenv("ANTHROPIC_API_KEY", ""), "auth_mode": "api_key", "cli_model_override": ""},
            "Ollama": {"provider": "Ollama", "api_key": os.getenv("OLLAMA_URL", "http://localhost:11434"), "auth_mode": "api_key", "cli_model_override": ""}
        }
        self.settings = {}
        self.load_settings()

        default_account = self.settings.get("ai_account", "Google Gemini")
        if default_account not in self.ai_accounts:
            default_account = list(self.ai_accounts.keys())[0] if self.ai_accounts else ""

        self.zabbix_url_var = ttk.StringVar(value=self.settings.get("zabbix_url", os.getenv("ZABBIX_URL", "")))
        self.zabbix_auth_method_var = ttk.StringVar(value=self.settings.get("zabbix_auth_method", "user_pass"))
        self.zabbix_user_var = ttk.StringVar(value=self.settings.get("zabbix_user", os.getenv("ZABBIX_USER", "")))
        self.zabbix_pass_var = ttk.StringVar(value=self.settings.get("zabbix_pass", os.getenv("ZABBIX_PASS", "")))
        self.zabbix_token_var = ttk.StringVar(value=self.settings.get("zabbix_token", os.getenv("ZABBIX_TOKEN", "")))
        self.zabbix_ignore_ssl_var = ttk.BooleanVar(value=self.settings.get("zabbix_ignore_ssl", False))
        self.ai_provider_var = ttk.StringVar(value=default_account)
        self.ai_key_var = ttk.StringVar(value=self.ai_accounts.get(default_account, {}).get("api_key", ""))

        self.analyst_name_var = ttk.StringVar(value=self.settings.get("analyst_name", ""))
        self.analyst_company_var = ttk.StringVar(value=self.settings.get("analyst_company", ""))
        self.analyst_email_var = ttk.StringVar(value=self.settings.get("analyst_email", ""))
        self.analyst_phone_var = ttk.StringVar(value=self.settings.get("analyst_phone", ""))

        self.chart_font_var = ttk.StringVar(value=self.settings.get("chart_font", "Arial, Helvetica, sans-serif"))

        self.chart_type_var = ttk.StringVar(value=self.settings.get("chart_type", "Linha"))
        self.chart_color_var = ttk.StringVar(value=self.settings.get("chart_color", "Padrão"))
        self.chart_width_var = ttk.IntVar(value=self.settings.get("chart_width", 800))
        self.chart_height_var = ttk.IntVar(value=self.settings.get("chart_height", 400))
        self.chart_bg_color_var = ttk.StringVar(value=self.settings.get("chart_bg_color", "Branco"))
        self.chart_text_color_var = ttk.StringVar(value=self.settings.get("chart_text_color", "Preto (Padrão)"))

        self.history_limit_var = ttk.IntVar(value=self.settings.get("history_limit", 500))
        self.sample_limit_var = ttk.IntVar(value=self.settings.get("sample_limit", 15))
        self.template_limit_var = ttk.IntVar(value=self.settings.get("template_limit", 200))
        self.only_used_templates_var = ttk.BooleanVar(value=self.settings.get("only_used_templates", False))
        self.anonymize_data_var = ttk.BooleanVar(value=self.settings.get("anonymize_data", False))

        self.custom_instructions_var = self.settings.get("custom_instructions", "")

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

        # Carrega dados sensíveis do Cofre do Sistema Operacional
        try:
            service = "AuditoriaZabbix"
            z_pass = keyring.get_password(service, "zabbix_pass")
            if z_pass is not None: self.settings["zabbix_pass"] = z_pass
                
            z_token = keyring.get_password(service, "zabbix_token")
            if z_token is not None: self.settings["zabbix_token"] = z_token
                
            for account in self.ai_accounts.keys():
                ai_key = keyring.get_password(service, f"{account}_api_key")
                if ai_key is not None:
                    self.ai_accounts[account]["api_key"] = ai_key
        except Exception as e:
            print(f"Aviso: Falha ao acessar o cofre de credenciais: {e}")

    def save_settings(self):
        self.settings["zabbix_url"] = self.zabbix_url_var.get()
        self.settings["zabbix_auth_method"] = self.zabbix_auth_method_var.get()
        self.settings["zabbix_user"] = self.zabbix_user_var.get()
        self.settings["zabbix_ignore_ssl"] = self.zabbix_ignore_ssl_var.get()
        self.settings["ai_account"] = self.ai_provider_var.get()
        
        # Salva o dicionário de contas sem vazar as API Keys para o arquivo JSON
        ai_accounts_safe = {}
        for k, v in self.ai_accounts.items():
            ai_accounts_safe[k] = {
                "provider": v.get("provider", k),
                "api_key": "",
                "auth_mode": v.get("auth_mode", "api_key"),
                "cli_model_override": v.get("cli_model_override", "")
            }
        self.settings["ai_accounts"] = ai_accounts_safe

        self.settings["analyst_name"] = self.analyst_name_var.get()
        self.settings["analyst_company"] = self.analyst_company_var.get()
        self.settings["analyst_email"] = self.analyst_email_var.get()
        self.settings["analyst_phone"] = self.analyst_phone_var.get()
        
        self.settings["chart_font"] = self.chart_font_var.get()
        self.settings["chart_type"] = self.chart_type_var.get()
        self.settings["chart_color"] = self.chart_color_var.get()
        self.settings["chart_width"] = self.chart_width_var.get()
        self.settings["chart_height"] = self.chart_height_var.get()
        self.settings["chart_bg_color"] = self.chart_bg_color_var.get()
        self.settings["chart_text_color"] = self.chart_text_color_var.get()
        self.settings["history_limit"] = self.history_limit_var.get()
        self.settings["sample_limit"] = self.sample_limit_var.get()
        self.settings["template_limit"] = self.template_limit_var.get()
        self.settings["only_used_templates"] = self.only_used_templates_var.get()
        self.settings["anonymize_data"] = self.anonymize_data_var.get()
        self.settings["custom_instructions"] = self.custom_instructions_text.text.get("1.0", END).strip()

        # Remove chaves legadas sensíveis do dicionário (se existirem de versões antigas)
        for key in ["zabbix_pass", "zabbix_token", "api_keys"]:
            if key in self.settings:
                del self.settings[key]

        # Grava os dados sensíveis no Cofre do Sistema Operacional (Keyring)
        try:
            service = "AuditoriaZabbix"
            def safe_set(username, val):
                if val:
                    keyring.set_password(service, username, val)
                else:
                    try:
                        keyring.delete_password(service, username)
                    except Exception:
                        pass
            
            safe_set("zabbix_pass", self.zabbix_pass_var.get())
            safe_set("zabbix_token", self.zabbix_token_var.get())
            
            for account, info in self.ai_accounts.items():
                safe_set(f"{account}_api_key", info.get("api_key", ""))
        except Exception as e:
            print(f"Aviso: Falha ao salvar no cofre de credenciais: {e}")

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
        auth_mode = account_info.get("auth_mode", "api_key")
        if hasattr(self, 'ai_key_entry'):
            if base_provider == "Ollama":
                self.ai_key_entry.configure(show="")
            else:
                self.ai_key_entry.configure(show="*")
            self.ai_key_entry.configure(state="disabled" if auth_mode == "cli" else "normal")
        if hasattr(self, 'ai_auth_mode_label'):
            if auth_mode == "cli":
                binary, path = cli_binary_status(base_provider)
                if path:
                    self.ai_auth_mode_label.configure(text=f"Modo: CLI local ({binary}) ✅")
                else:
                    self.ai_auth_mode_label.configure(text=f"Modo: CLI local ({binary or '?'}) — binário não encontrado no PATH ❌")
            else:
                self.ai_auth_mode_label.configure(text="")

    def get_selected_base_provider(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("provider", "Google Gemini")

    def get_selected_auth_mode(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("auth_mode", "api_key")

    def get_selected_cli_model_override(self):
        account = self.ai_provider_var.get()
        return self.ai_accounts.get(account, {}).get("cli_model_override", "")

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
            text="▶ Iniciar Auditoria",
            command=self.start_audit_clicked,
            bootstyle="success-outline"
        )
        self.start_button.pack(side=LEFT, padx=(0, 10))
        
        self.regerar_button = ttk.Button(
            control_frame,
            text="🔄 Regerar (Apenas IA)",
            command=self.regerar_audit_clicked,
            bootstyle="info"
        )
        self.regerar_button.pack(side=LEFT, padx=(0, 5))

        self.coletar_button = ttk.Button(
            control_frame,
            text="📥 Apenas Coleta",
            command=self.collect_only_clicked,
            bootstyle="secondary"
        )
        self.coletar_button.pack(side=LEFT, padx=(0, 10))

        self.cancel_button = ttk.Button(
            control_frame,
            text="⏹ Cancelar",
            command=self.cancel_audit_clicked,
            bootstyle="danger",
            state="disabled"
        )
        self.cancel_button.pack(side=LEFT, padx=(0, 10))

        ttk.Label(control_frame, text="Modelo IA:").pack(side=LEFT, padx=(10, 5))
        self.model_var = ttk.StringVar()
        self.model_combo = ttk.Combobox(
            control_frame,
            textvariable=self.model_var,
            state="readonly",
            width=50
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

        # --- Progress Bar (Bottom) ---
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=X, side=tk.BOTTOM, pady=(10, 0))
        self.status_var = ttk.StringVar(value="Pronto.")
        ttk.Label(progress_frame, textvariable=self.status_var, width=35).pack(side=LEFT)
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', maximum=100)
        self.progress_bar.pack(side=LEFT, fill=X, expand=True, padx=(10, 0))

        # --- Notebook (Abas) ---
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=BOTH, expand=True, side=tk.TOP)

        # 1. Aba de Configurações
        config_frame = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(config_frame, text="⚙️ Configurações")
        
        cols_frame = ttk.Frame(config_frame)
        cols_frame.pack(fill=BOTH, expand=True)
        
        left_col = ttk.Frame(cols_frame)
        left_col.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        
        right_col = ttk.Frame(cols_frame)
        right_col.pack(side=RIGHT, fill=BOTH, expand=True, padx=(10, 0))

        # --- COLUNA ESQUERDA ---
        z_frame = ttk.LabelFrame(left_col, text="Credenciais do Zabbix")
        z_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        z_frame.columnconfigure(1, weight=1)
        
        ttk.Label(z_frame, text="URL da API:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(z_frame, textvariable=self.zabbix_url_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=5, padx=5)
        ttk.Label(z_frame, text="(ex: http://meu-ip/zabbix/api_jsonrpc.php)", font=("Helvetica", 8)).grid(row=1, column=1, columnspan=2, sticky="w", padx=5, pady=(0, 5))
        
        self.auth_switch = ttk.Checkbutton(
            z_frame, 
            text="Autenticar via API Token", 
            variable=self.zabbix_auth_method_var, 
            onvalue="token", 
            offvalue="user_pass", 
            bootstyle="round-toggle",
            command=self.toggle_zabbix_auth_fields
        )
        self.auth_switch.grid(row=2, column=0, columnspan=3, sticky="w", pady=5)

        self.lbl_user = ttk.Label(z_frame, text="Usuário:")
        self.lbl_user.grid(row=3, column=0, sticky="w", pady=5)
        self.ent_user = ttk.Entry(z_frame, textvariable=self.zabbix_user_var)
        self.ent_user.grid(row=3, column=1, sticky="ew", pady=5, padx=5)
        
        self.lbl_pass = ttk.Label(z_frame, text="Senha:")
        self.lbl_pass.grid(row=4, column=0, sticky="w", pady=5)
        self.ent_pass = ttk.Entry(z_frame, textvariable=self.zabbix_pass_var, show="*")
        self.ent_pass.grid(row=4, column=1, sticky="ew", pady=5, padx=5)

        self.lbl_token = ttk.Label(z_frame, text="Token:")
        self.ent_token = ttk.Entry(z_frame, textvariable=self.zabbix_token_var, show="*")

        self.test_zabbix_button = ttk.Button(z_frame, text="🔌 Testar", command=self.test_zabbix_clicked, bootstyle="info-outline")
        self.test_zabbix_button.grid(row=4, column=2, padx=5)
        
        ttk.Checkbutton(z_frame, text="Ignorar Validação SSL/TLS (Inseguro)", variable=self.zabbix_ignore_ssl_var, bootstyle="danger-round-toggle").grid(row=5, column=0, columnspan=3, sticky="w", pady=5)
        
        self.toggle_zabbix_auth_fields()

        # --- Parâmetros de Coleta ---
        collect_frame = ttk.LabelFrame(left_col, text="Parâmetros de Coleta (API)")
        collect_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        
        ttk.Label(collect_frame, text="Profundidade do Histórico (Trends):").grid(row=0, column=0, sticky="w", pady=5, padx=5)
        ttk.Spinbox(collect_frame, from_=50, to=5000, increment=50, textvariable=self.history_limit_var, width=10).grid(row=0, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Label(collect_frame, text="Limite de Amostras de Problemas:").grid(row=1, column=0, sticky="w", pady=5, padx=5)
        ttk.Spinbox(collect_frame, from_=5, to=200, increment=5, textvariable=self.sample_limit_var, width=10).grid(row=1, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Label(collect_frame, text="Limite de Templates/Itens Globais:").grid(row=2, column=0, sticky="w", pady=5, padx=5)
        ttk.Spinbox(collect_frame, from_=50, to=1000, increment=50, textvariable=self.template_limit_var, width=10).grid(row=2, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Checkbutton(collect_frame, text="Coletar apenas templates em uso (vinculados a hosts)", variable=self.only_used_templates_var, bootstyle="round-toggle").grid(row=3, column=0, columnspan=2, sticky="w", pady=5, padx=5)
        
        ttk.Checkbutton(collect_frame, text="Anonimizar Dados Sensíveis (Ocultar IPs e Senhas)", variable=self.anonymize_data_var, bootstyle="info-round-toggle").grid(row=4, column=0, columnspan=2, sticky="w", pady=5, padx=5)
        
        # --- Dados do Analista ---
        analyst_frame = ttk.LabelFrame(left_col, text="Dados do Analista / Empresa (Cabeçalho do Relatório)")
        analyst_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        analyst_frame.columnconfigure(1, weight=1)
        
        ttk.Label(analyst_frame, text="Nome:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(analyst_frame, textvariable=self.analyst_name_var).grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        
        ttk.Label(analyst_frame, text="Empresa:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(analyst_frame, textvariable=self.analyst_company_var).grid(row=1, column=1, sticky="ew", pady=5, padx=5)
        
        ttk.Label(analyst_frame, text="E-mail:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(analyst_frame, textvariable=self.analyst_email_var).grid(row=2, column=1, sticky="ew", pady=5, padx=5)
        
        ttk.Label(analyst_frame, text="Telefone:").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(analyst_frame, textvariable=self.analyst_phone_var).grid(row=3, column=1, sticky="ew", pady=5, padx=5)
        
        # --- COLUNA DIREITA ---
        ai_frame = ttk.LabelFrame(right_col, text="Inteligência Artificial")
        ai_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        ai_frame.columnconfigure(1, weight=1)
        
        ttk.Label(ai_frame, text="Conta/Provedor:").grid(row=0, column=0, sticky="w", pady=5)
        self.provider_combo = ttk.Combobox(ai_frame, textvariable=self.ai_provider_var, values=list(self.ai_accounts.keys()), state="readonly")
        self.provider_combo.grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        ttk.Button(ai_frame, text="⚙️ Gerenciar", command=self.open_manage_accounts_window, bootstyle="secondary-outline").grid(row=0, column=2, padx=5)
        
        ttk.Label(ai_frame, text="Key / URL:").grid(row=1, column=0, sticky="w", pady=5)
        self.ai_key_entry = ttk.Entry(ai_frame, textvariable=self.ai_key_var, show="*")
        self.ai_key_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=5)

        self.ai_auth_mode_label = ttk.Label(ai_frame, text="", bootstyle="info")
        self.ai_auth_mode_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=5)

        # Atualiza a visibilidade do campo caso a IA salva por padrão seja o Ollama
        self.on_provider_change()

        ttk.Button(ai_frame, text="🔄 Validar Conexão / Atualizar Modelos", command=self.validate_and_load_models, bootstyle="info-outline").grid(row=3, column=0, columnspan=3, pady=(10, 0))

        # --- Estilos de Gráfico e Exportação ---
        export_frame = ttk.LabelFrame(right_col, text="Aparência e Exportação")
        export_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        ttk.Button(export_frame, text="🎨 Configurar Estilos de Gráfico", command=self.open_style_settings_window, bootstyle="info-outline").pack(side=LEFT, padx=10, pady=5)

        # --- Instruções Customizadas ---
        inst_frame = ttk.LabelFrame(right_col, text="Instruções Customizadas para a IA")
        inst_frame.pack(fill=BOTH, expand=True, pady=(0, 10), ipadx=10, ipady=10)
        self.custom_instructions_text = ScrolledText(inst_frame, wrap=WORD, autohide=True)
        self.custom_instructions_text.pack(fill=BOTH, expand=True, padx=5, pady=5)
        self.custom_instructions_text.text.insert(END, self.custom_instructions_var)

        # 2. Aba de Logs
        log_frame = ttk.Frame(self.notebook, padding=5)
        self.log_text = ScrolledText(log_frame, wrap=WORD, autohide=True, state="disabled")
        self.log_text.pack(fill=BOTH, expand=True)
        
        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.pack(fill=X, pady=(5, 0))
        ttk.Button(log_btn_frame, text="💾 Salvar Logs", command=self.save_logs_clicked, bootstyle="secondary").pack(side=LEFT)
        self.notebook.add(log_frame, text="Logs da Execução")

        # 3. Aba de Relatório
        report_frame = ttk.Frame(self.notebook, padding=5)
        self.report_text = ScrolledText(report_frame, wrap=WORD, autohide=True, state="disabled")
        self.report_text.pack(fill=BOTH, expand=True)
        
        report_btn_frame = ttk.Frame(report_frame)
        report_btn_frame.pack(fill=X, pady=(5, 0))
        ttk.Button(report_btn_frame, text="💾 Salvar / Exportar Relatório", command=self.save_report_clicked, bootstyle="primary").pack(side=LEFT)
        self.notebook.add(report_frame, text="Relatório Final")

    def toggle_zabbix_auth_fields(self):
        if self.zabbix_auth_method_var.get() == "token":
            self.lbl_user.grid_remove()
            self.ent_user.grid_remove()
            self.lbl_pass.grid_remove()
            self.ent_pass.grid_remove()
            
            self.lbl_token.grid(row=4, column=0, sticky="w", pady=5)
            self.ent_token.grid(row=4, column=1, sticky="ew", pady=5, padx=5)
        else:
            self.lbl_token.grid_remove()
            self.ent_token.grid_remove()
            
            self.lbl_user.grid()
            self.ent_user.grid()
            self.lbl_pass.grid()
            self.ent_pass.grid()

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
        Finds Mermaid xychart-beta blocks, renders them as PNG images using matplotlib,
        and replaces the blocks with image links. Non-xychart-beta blocks (or blocks
        that fail to parse) are left untouched as code blocks.
        Returns the modified markdown and the path to the temporary directory created
        (or None if no chart blocks were found).
        """
        matches = list(chart_renderer.MERMAID_CODE_FENCE_RE.finditer(markdown_content))
        if not matches:
            return markdown_content, None

        temp_dir = tempfile.mkdtemp(prefix="zabbix_audit_charts_")
        modified_markdown = markdown_content

        chart_type = self.chart_type_var.get()
        ctype_en = "bar" if chart_type == "Barra" else "line"
        style = {
            "chart_color": self.chart_color_var.get(),
            "chart_bg_color": self.chart_bg_color_var.get(),
            "chart_text_color": self.chart_text_color_var.get(),
            "chart_width": self.chart_width_var.get(),
            "chart_height": self.chart_height_var.get(),
            "chart_font": self.chart_font_var.get(),
        }

        self.log(f"Encontrados {len(matches)} gráficos Mermaid. Renderizando com matplotlib...", "info")

        for i, match in enumerate(reversed(matches)):
            chart_index = len(matches) - 1 - i
            code = chart_renderer.normalize_mermaid(match.group(1), ctype_en)
            chart = chart_renderer.parse_xychart(code)

            if chart is None:
                self.log(f"Aviso: bloco Mermaid {chart_index+1} não pôde ser interpretado; mantido como bloco de código.", "warning")
                continue

            output_file_path = os.path.join(temp_dir, f"chart_{chart_index}.png")
            try:
                chart_renderer.render_chart(chart, style, output_file_path)
                image_link_path = output_file_path.replace('\\', '/')
                image_link = f"![Gráfico {chart_index+1}]({image_link_path})"
                start, end = match.span()
                modified_markdown = modified_markdown[:start] + image_link + modified_markdown[end:]
                self.log(f"Gráfico {chart_index+1} renderizado com sucesso.", "info")
            except Exception as e:
                self.log(f"Erro ao renderizar gráfico {chart_index+1}: {e}", "danger")
                continue

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
            m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", report_content, re.DOTALL | re.IGNORECASE)
            if m:
                report_content = m.group(1).strip()
            
            ext = os.path.splitext(file_path)[1].lower()
            
            author_name = self.analyst_name_var.get().strip()
            company_name = self.analyst_company_var.get().strip()
            
            self.log(f"Iniciando exportação para {ext}... Aguarde.", "info")
            
            # Passa a lógica pesada de exportação para uma Thread separada
            thread = threading.Thread(
                target=self._export_report_thread, 
                args=(file_path, ext, report_content, author_name, company_name)
            )
            thread.daemon = True
            thread.start()

        except Exception as e:
            self.log(f"Erro inesperado: {e}", "danger")

    def _export_report_thread(self, file_path, ext, report_content, author_name, company_name):
        temp_dir_to_clean = None
        try:
            processed_content = report_content
            if ext in ['.pdf', '.docx', '.odt']:
                processed_content, temp_dir_to_clean = self._render_mermaid_charts(report_content)
            
            if ext in ['.md', '.txt', '']:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(processed_content)
                self.log(f"Relatório salvo com sucesso em: {file_path}")
                self.show_dialog("Sucesso", f"Relatório exportado em:\n{file_path}")
            else:
                self.log(f"Convertendo relatório para {ext}... Aguarde.", "info")
                
                import pypandoc
                try:
                    pypandoc.get_pandoc_version()
                except OSError:
                    self.log("Pandoc não encontrado. Baixando e instalando...", "warning")
                    pypandoc.download_pandoc()
                
                to_format = 'pdf' if ext == '.pdf' else ext.replace('.', '')
                extra_args = []
                
                if to_format == 'docx':
                    reference_doc_path = resource_path('templates/report_template.docx')
                    if os.path.exists(reference_doc_path):
                        extra_args.extend(['--reference-doc', reference_doc_path])
                        self.log(f"Usando template Word: {reference_doc_path}", "info")
                
                if to_format == 'pdf':
                    try:
                        pandoc_version = pypandoc.get_pandoc_version()
                        version_tuple = tuple(int(p) for p in pandoc_version.split('.')[:3])
                        if version_tuple < (3, 1, 7):
                            self.log(f"Pandoc {pandoc_version} não suporta o writer Typst (requer >= 3.1.7). Baixando versão atualizada...", "warning")
                            pypandoc.download_pandoc()

                        typst_body = pypandoc.convert_text(processed_content, 'typst', format='gfm+hard_line_breaks')

                        pdf_root_dir = temp_dir_to_clean
                        created_pdf_root = False
                        if not pdf_root_dir:
                            pdf_root_dir = tempfile.mkdtemp(prefix="zabbix_report_typst_")
                            created_pdf_root = True
                        else:
                            temp_dir_norm = pdf_root_dir.replace('\\', '/')
                            typst_body = typst_body.replace(f'image("{temp_dir_norm}/', 'image("')

                        try:
                            author_field = author_name if author_name else "Analista de Monitoramento"
                            if company_name:
                                author_field += f" - {company_name}"
                            current_date = datetime.now().strftime("%d/%m/%Y")

                            with open(resource_path("templates/report_template.typ"), "r", encoding="utf-8") as f:
                                typst_template = f.read()

                            full_typst = typst_template.replace("__TITLE__", "Relatório Técnico de Auditoria Zabbix").replace(
                                "__AUTHOR__", _escape_typst_text(author_field)).replace(
                                "__DATE__", current_date).replace(
                                "__BODY__", typst_body)

                            typst_source_path = os.path.join(pdf_root_dir, "report.typ")
                            with open(typst_source_path, "w", encoding="utf-8") as f:
                                f.write(full_typst)

                            import typst
                            typst.compile(typst_source_path, output=file_path, root=pdf_root_dir)
                            self.log(f"Relatório exportado com sucesso em: {file_path}")
                        finally:
                            if created_pdf_root:
                                shutil.rmtree(pdf_root_dir, ignore_errors=True)
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
            self.controller.start_audit(use_cache=False)
            
    def regerar_audit_clicked(self):
        self.save_settings()
        if self.controller:
            self.controller.start_audit(use_cache=True)

    def collect_only_clicked(self):
        z_url = self.zabbix_url_var.get().strip()
        if not z_url:
            self.show_dialog("Configuração Incompleta", "Preencha a URL do Zabbix na aba 'Configurações' antes de coletar.", is_error=True)
            return

        initial_dir = self.settings.get("last_collect_dir", os.path.expanduser("~"))
        file_path = filedialog.asksaveasfilename(
            title="Salvar Coleta de Dados",
            initialdir=initial_dir,
            initialfile="coleta_zabbix.json",
            defaultextension=".json",
            filetypes=[("Arquivos JSON", "*.json"), ("Todos os arquivos", "*.*")]
        )
        if not file_path:
            return

        self.settings["last_collect_dir"] = os.path.dirname(file_path)
        self.save_settings()

        if self.controller:
            self.controller.start_collection_only(file_path)

    def cancel_audit_clicked(self):
        if self.controller:
            self.controller.cancel_audit()
            
    def test_zabbix_clicked(self):
        self.save_settings()
        if self.controller:
            self.controller.test_zabbix_connection()
            
    def update_progress(self, value, text):
        def _update():
            self.progress_bar['value'] = value
            self.status_var.set(text)
        self.after(0, _update)

    def log(self, message, style="info"):
        def _log():
            self.log_text.text.configure(state="normal")
            self.log_text.text.insert(END, f"{message}\n")
            self.log_text.text.see(END) # Auto-scroll
            self.log_text.text.configure(state="disabled")
        self.after(0, _log)

    def clear_report(self):
        self.report_text.text.configure(state="normal")
        self.report_text.text.delete("1.0", END)
        self.report_text.text.configure(state="disabled")
        
    def append_report_chunk(self, chunk):
        def _append():
            self.report_text.text.configure(state="normal")
            self.report_text.text.insert(END, chunk)
            self.report_text.text.see(END)
            self.report_text.text.configure(state="disabled")
        self.after(0, _append)

    def show_dialog(self, title, message, is_error=False):
        def _show():
            if is_error:
                Messagebox.show_error(message, title, parent=self)
            else:
                Messagebox.show_info(message, title, parent=self)
        self.after(0, _show)

    def set_ui_state(self, state):
        self.start_button.configure(state=state)
        if hasattr(self, 'regerar_button'): self.regerar_button.configure(state=state)
        if hasattr(self, 'coletar_button'): self.coletar_button.configure(state=state)
        if hasattr(self, 'test_zabbix_button'): self.test_zabbix_button.configure(state=state)
        if hasattr(self, 'cancel_button'): self.cancel_button.configure(state="normal" if state == "disabled" else "disabled")
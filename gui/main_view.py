import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledText, ScrolledFrame
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT, WORD, END
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.tooltip import ToolTip
import tkinter as tk
import threading
import queue
from tkinter import filedialog
import os
import re
import keyring
import ipaddress
from urllib.parse import urlparse
from dotenv import load_dotenv
from datetime import datetime
from gui.manage_accounts_view import ManageAccountsWindow
from gui.style_settings_view import StyleSettingsWindow
from gui.manage_attachments_view import ManageAttachmentsWindow
from api.ai_cli_client import cli_binary_status
from core.paths import get_app_paths
from core.persistence import SettingsStore, atomic_write_text
from core.report_exporter import ReportExporter, ReportMetadata
from core.pandoc_runtime import pandoc_download_requirement
from core.run_config import (
    AIConfig,
    AnalystData,
    AuditRequest,
    CollectionLimits,
    CollectionRequest,
    ReportStyle,
    ZabbixConfig,
)

def _is_local_ollama_destination(ai_config):
    """Return whether the selected AI destination stays on this machine."""
    if ai_config.provider.casefold() != "ollama":
        return False
    if ai_config.auth_mode.casefold() == "cli":
        return True

    endpoint = ai_config.api_key.strip()
    if not endpoint:
        return False
    parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
    hostname = parsed.hostname
    if not hostname:
        return False
    normalized_host = hostname.rstrip(".").casefold()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False

class MainView(ttk.Window):
    UI_EVENT_POLL_MS = 50

    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Auditoria Inteligente de Zabbix")
        self.geometry("1500x760")
        self.controller = None
        self.ui_event_queue = queue.Queue()
        self._ui_event_lock = threading.Lock()
        self._ui_events_closed = False
        self._startup_warnings = []
        self._model_state = "idle"
        self._model_values = ()
        self._model_load_id = 0

        # Carrega defaults do .env (se existir)
        load_dotenv()
        self.app_paths = get_app_paths()
        self.settings_store = SettingsStore(
            self.app_paths, legacy_file=os.path.join(os.getcwd(), "settings.json")
        )
        self.settings_file = self.settings_store.path
        self._legacy_credentials = {}
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
        self.anonymize_data_var = ttk.BooleanVar(value=self.settings.get("anonymize_data", True))

        self.custom_instructions_var = self.settings.get("custom_instructions", "")

        # Rastreadores (Traces) para detectar alterações na interface e mudar a chave correta
        self.ai_key_var.trace_add("write", self.update_key_dict)
        self.ai_provider_var.trace_add("write", self.on_provider_change)

        self.attached_files = []
        self.create_widgets()
        self.after(self.UI_EVENT_POLL_MS, self._consume_ui_events)
        for warning in self._startup_warnings:
            self.log(warning, "warning")

    def set_controller(self, controller):
        self.controller = controller

    def load_settings(self):
        result = self.settings_store.load()
        self.settings = result.settings
        self._legacy_credentials = result.legacy_credentials
        self._startup_warnings.extend(result.warnings)
        if "ai_accounts" in self.settings:
            self.ai_accounts = self.settings["ai_accounts"]

        # Carrega dados sensíveis do Cofre do Sistema Operacional
        try:
            service = "AuditoriaZabbix"
            def load_secret(username):
                stored = keyring.get_password(service, username)
                legacy = self._legacy_credentials.get(username)
                if stored is None and legacy:
                    keyring.set_password(service, username, legacy)
                    self._startup_warnings.append(
                        f"Credencial legada '{username}' migrada para o cofre do sistema."
                    )
                    return legacy
                return stored

            z_pass = load_secret("zabbix_pass")
            if z_pass is not None: self.settings["zabbix_pass"] = z_pass
                
            z_token = load_secret("zabbix_token")
            if z_token is not None: self.settings["zabbix_token"] = z_token
                
            for account in self.ai_accounts.keys():
                ai_key = load_secret(f"{account}_api_key")
                if ai_key is not None:
                    self.ai_accounts[account]["api_key"] = ai_key
        except Exception as e:
            self._startup_warnings.append(f"Falha ao acessar o cofre de credenciais: {e}")

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

        try:
            self.settings, warnings = self.settings_store.save(self.settings)
            for warning in warnings:
                self.log(warning, "warning")
        except Exception as e:
            self.log(f"Falha ao salvar configurações: {e}", "danger")
            return False

        # Só altera o cofre depois que a configuração sem segredos foi persistida.
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
            self.log(f"Falha ao salvar no cofre de credenciais: {e}", "warning")
        return True

    def delete_ai_account_credential(self, account_name):
        """Remove a credencial antiga somente após a nova configuração persistir."""
        try:
            keyring.delete_password("AuditoriaZabbix", f"{account_name}_api_key")
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as error:
            self.log(
                f"Falha ao remover a credencial antiga da conta '{account_name}': {error}",
                "warning",
            )

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
        if hasattr(self, "model_combo"):
            # Invalidate the previous selection immediately on the main thread;
            # the queued event only updates the visible combobox.
            self._model_state = "idle"
            self._model_values = ()
            self.set_model_state("idle", (), None, "Aguardando validação", None)
            if self.controller:
                self.controller.load_models_async(self.build_ai_config())

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
        self.coletar_button.pack(side=LEFT, padx=(0, 5))

        self.iniciar_de_arquivo_button = ttk.Button(
            control_frame,
            text="📂 Iniciar de Coleta",
            command=self.start_from_file_clicked,
            bootstyle="secondary"
        )
        self.iniciar_de_arquivo_button.pack(side=LEFT, padx=(0, 10))

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
        self.model_combo.set("Aguardando validação")

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

        # 1. Aba de Configurações (dashboard) — ScrolledFrame para não cortar campos quando a
        # janela/DPI deixa o conteúdo mais alto do que a área visível da aba.
        config_frame = ScrolledFrame(self.notebook, autohide=True, padding=15)
        self.notebook.add(config_frame.container, text="⚙️ Configurações")
        
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
        
        ttk.Checkbutton(collect_frame, text="Anonimizar Dados Sensíveis (Recomendado)", variable=self.anonymize_data_var, bootstyle="info-round-toggle").grid(row=4, column=0, columnspan=2, sticky="w", pady=5, padx=5)
        
        # --- Dados do Analista ---
        analyst_frame = ttk.LabelFrame(left_col, text="Dados do Analista / Empresa (Cabeçalho do Relatório)")
        analyst_frame.pack(fill=X, pady=(0, 7), ipadx=10, ipady=7)
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
        # Sem expand=True (igual às outras LabelFrames à esquerda): o topo continua exatamente
        # onde ficava antes (logo abaixo de export_frame) e a altura passa a ser a do próprio
        # ScrolledText (height em linhas), não mais "esticar até o fim da aba". analyst_frame não
        # é tocado — só a base de Instruções sobe para ficar perto da base de Dados do Analista.
        inst_frame = ttk.LabelFrame(right_col, text="Instruções Customizadas para a IA")
        inst_frame.pack(fill=X, pady=(0, 10), ipadx=10, ipady=10)
        self.custom_instructions_text = ScrolledText(inst_frame, wrap=WORD, autohide=True, height=20)
        self.custom_instructions_text.pack(fill=BOTH, expand=True, padx=5, pady=5)
        self.custom_instructions_text.text.insert(END, self.custom_instructions_var)

        # 2. Aba de Logs
        log_frame = ttk.Frame(self.notebook, padding=5)
        self.log_text = ScrolledText(log_frame, wrap=WORD, autohide=True, state="disabled")
        self.log_text.pack(fill=BOTH, expand=True)
        self.log_text.text.tag_configure("info", foreground="#f8f9fa")
        self.log_text.text.tag_configure("warning", foreground="#ffc107")
        self.log_text.text.tag_configure("danger", foreground="#dc3545")
        self.log_text.text.tag_configure("success", foreground="#198754")
        
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
        self.set_model_state("ready", tuple(models), default_model, "", None)

    def set_model_state(
        self, state, models=(), default_model=None, message="", load_id=None
    ):
        self._enqueue_ui_event(
            "model_state", state, tuple(models), default_model, message, load_id
        )

    def get_selected_model(self):
        return self.model_var.get()

    def build_zabbix_config(self):
        """Capture all Zabbix inputs while running on Tk's main thread."""
        return ZabbixConfig(
            url=self.zabbix_url_var.get().strip(),
            auth_method=self.zabbix_auth_method_var.get(),
            username=self.zabbix_user_var.get().strip(),
            password=self.zabbix_pass_var.get().strip(),
            token=self.zabbix_token_var.get().strip(),
            verify_ssl=not self.zabbix_ignore_ssl_var.get(),
        )

    def build_ai_config(self):
        """Capture the selected account and model without exposing Tk to workers."""
        account = self.ai_provider_var.get()
        account_info = self.ai_accounts.get(account, {})
        selected_model = self.model_var.get()
        if self._model_state != "ready" or selected_model not in self._model_values:
            selected_model = ""
        return AIConfig(
            provider=account_info.get("provider", "Google Gemini"),
            api_key=self.ai_key_var.get().strip(),
            model=selected_model,
            auth_mode=account_info.get("auth_mode", "api_key"),
            cli_model_override=account_info.get("cli_model_override", ""),
        )

    def build_analyst_data(self):
        return AnalystData(
            name=self.analyst_name_var.get().strip(),
            company=self.analyst_company_var.get().strip(),
            email=self.analyst_email_var.get().strip(),
            phone=self.analyst_phone_var.get().strip(),
        )

    def build_collection_limits(self):
        return CollectionLimits(
            history_limit=self.history_limit_var.get(),
            sample_limit=self.sample_limit_var.get(),
            template_limit=self.template_limit_var.get(),
            only_used_templates=self.only_used_templates_var.get(),
        )

    def build_report_style(self):
        return ReportStyle(
            chart_type=self.chart_type_var.get(),
            chart_color=self.chart_color_var.get(),
            chart_bg_color=self.chart_bg_color_var.get(),
            chart_text_color=self.chart_text_color_var.get(),
            chart_width=self.chart_width_var.get(),
            chart_height=self.chart_height_var.get(),
            chart_font=self.chart_font_var.get(),
        )

    def build_audit_request(self, use_cache=False, data_file=None):
        return AuditRequest(
            zabbix=self.build_zabbix_config(),
            ai=self.build_ai_config(),
            analyst=self.build_analyst_data(),
            limits=self.build_collection_limits(),
            style=self.build_report_style(),
            custom_instructions=self.custom_instructions_text.text.get("1.0", END).strip(),
            attached_files=tuple(self.attached_files),
            anonymize=self.anonymize_data_var.get(),
            use_cache=use_cache,
            data_file=data_file,
        )

    def build_collection_request(self, output_file):
        return CollectionRequest(
            zabbix=self.build_zabbix_config(),
            limits=self.build_collection_limits(),
            output_file=output_file,
            anonymize=self.anonymize_data_var.get(),
        )

    def confirm_unanonymized_remote_audit(self, request):
        """Require an explicit opt-in before sending identifiable remote data."""
        if request.anonymize or _is_local_ollama_destination(request.ai):
            return True

        answer = Messagebox.yesno(
            "A anonimização está desativada e os dados serão enviados para um "
            f"destino externo ({request.ai.provider}). Isso pode expor IPs, nomes "
            "e outros dados sensíveis. Deseja continuar sem anonimizar?",
            "Confirmar envio de dados não anonimizados",
            alert=True,
            parent=self,
        )
        confirmed = isinstance(answer, str) and answer.casefold() in {"yes", "sim"}
        if not confirmed:
            self.log("Envio para a IA cancelado: anonimização desativada sem confirmação.", "warning")
        return confirmed

    def confirm_insecure_zabbix_transport(self, warnings):
        """Ask for explicit consent before credentials use an unsafe transport."""
        details = []
        if "remote_http" in warnings:
            details.append(
                "A conexão usa HTTP fora de localhost; usuário/senha ou token "
                "podem trafegar sem criptografia."
            )
        if "unverified_tls" in warnings:
            details.append(
                "A validação do certificado TLS está desativada; não será "
                "possível confirmar a identidade do servidor."
            )

        answer = Messagebox.yesno(
            "\n\n".join(details) + "\n\nDeseja continuar mesmo assim?",
            "Confirmar conexão insegura com Zabbix",
            alert=True,
            parent=self,
        )
        return isinstance(answer, str) and answer.casefold() in {"yes", "sim"}

    def confirm_cache_mismatch(self, summary, reasons):
        """Confirm reuse when cached origin/settings differ from the current GUI."""
        details = "\n".join(f"- {reason}" for reason in reasons)
        answer = Messagebox.yesno(
            "O cache selecionado diverge da configuração atual:\n"
            f"{details}\n\n"
            f"Origem: {summary.get('server_name', 'desconhecida')}\n"
            f"Data UTC: {summary.get('created_at_utc', 'desconhecida')}\n"
            f"Versão Zabbix: {summary.get('zabbix_version') or 'desconhecida'}\n"
            f"Anonimizado: {'sim' if summary.get('anonymized') else 'não'}\n\n"
            "Deseja regenerar o relatório usando este cache?",
            "Confirmar reutilização de cache divergente",
            alert=True,
            parent=self,
        )
        return isinstance(answer, str) and answer.casefold() in {"yes", "sim"}

    def confirm_pandoc_download(self, reason):
        """Require explicit consent for source-only Pandoc downloads."""
        answer = Messagebox.yesno(
            f"{reason}\n\n"
            "A exportação DOCX, ODT e PDF depende desse componente. Deseja "
            "baixá-lo agora para o diretório de dados da aplicação?",
            "Baixar Pandoc",
            alert=True,
            parent=self,
        )
        return isinstance(answer, str) and answer.casefold() in {"yes", "sim"}

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

    def _default_data_dir(self):
        try:
            return str(self.app_paths.ensure_data_dir())
        except OSError:
            return os.path.expanduser("~")

    def validate_and_load_models(self):
        self.save_settings()
        if self.controller:
            self.controller.load_models_async(self.build_ai_config())

    def save_logs_clicked(self):
        initial_dir = self.settings.get("last_log_dir", self._default_data_dir())
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
                atomic_write_text(file_path, log_content)
                self.log(f"Logs salvos com sucesso em: {file_path}")
            except Exception as e:
                self.log(f"Erro ao salvar logs: {e}")

    def save_report_clicked(self):
        initial_dir = self.settings.get("last_report_dir", self._default_data_dir())
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
            report_style = self.build_report_style()
            report_metadata = ReportMetadata(
                author_name=author_name,
                company_name=company_name,
                report_date=datetime.now().strftime("%d/%m/%Y"),
            )

            allow_pandoc_download = False
            if ext in ReportExporter.RICH_FORMATS:
                download_reason = pandoc_download_requirement()
                if download_reason:
                    if not self.confirm_pandoc_download(download_reason):
                        self.log(
                            "Exportação cancelada: download do Pandoc não autorizado.",
                            "warning",
                        )
                        return
                    allow_pandoc_download = True
            
            self.log(f"Iniciando exportação para {ext}... Aguarde.", "info")
            
            # Passa a lógica pesada de exportação para uma Thread separada
            thread = threading.Thread(
                target=self._export_report_thread, 
                args=(
                    file_path,
                    ext,
                    report_content,
                    report_style,
                    report_metadata,
                    allow_pandoc_download,
                )
            )
            thread.daemon = True
            thread.start()

        except Exception as e:
            self.log(f"Erro inesperado: {e}", "danger")

    def _export_report_thread(
        self,
        file_path,
        ext,
        report_content,
        report_style,
        report_metadata,
        allow_pandoc_download=False,
    ):
        try:
            exporter = ReportExporter(
                log_callback=self.log,
                progress_callback=self.update_progress,
                allow_pandoc_download=allow_pandoc_download,
            )
            exporter.export(file_path, report_content, report_style, report_metadata)
            self.show_dialog("Sucesso", f"Relatório exportado em:\n{file_path}")
        except Exception as e:
            self.log(f"Erro ao exportar relatório: {e}", "danger")
            self.show_dialog(
                "Erro na exportação",
                f"Não foi possível exportar o relatório para {ext or '.md'}:\n{e}",
                True,
            )

    def start_audit_clicked(self):
        self.save_settings()
        if self.controller:
            request = self.build_audit_request(use_cache=False)
            if self.confirm_unanonymized_remote_audit(request):
                self.controller.start_audit(request)
            
    def regerar_audit_clicked(self):
        self.save_settings()
        if self.controller:
            request = self.build_audit_request(use_cache=True)
            if self.confirm_unanonymized_remote_audit(request):
                self.controller.start_audit(request)

    def collect_only_clicked(self):
        initial_dir = self.settings.get("last_collect_dir", self._default_data_dir())
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
            self.controller.start_collection_only(self.build_collection_request(file_path))

    def start_from_file_clicked(self):
        initial_dir = self.settings.get("last_collect_dir", self._default_data_dir())
        file_path = filedialog.askopenfilename(
            title="Selecionar Coleta Existente",
            initialdir=initial_dir,
            filetypes=[("Arquivos JSON", "*.json"), ("Todos os arquivos", "*.*")]
        )
        if not file_path:
            return

        self.settings["last_collect_dir"] = os.path.dirname(file_path)
        self.save_settings()

        if self.controller:
            request = self.build_audit_request(data_file=file_path)
            if self.confirm_unanonymized_remote_audit(request):
                self.controller.start_audit(request)

    def cancel_audit_clicked(self):
        if self.controller:
            self.controller.cancel_audit()
            
    def test_zabbix_clicked(self):
        self.save_settings()
        if self.controller:
            self.controller.test_zabbix_connection(self.build_zabbix_config())

    def show_model_loading(self, provider):
        self.set_model_state("loading", (), None, f"Conectando à {provider}...", None)

    def select_logs_tab(self):
        self._enqueue_ui_event("select_tab", 1)

    def select_report_tab(self):
        self._enqueue_ui_event("select_tab", 2)
            
    def update_progress(self, value, text):
        self._enqueue_ui_event("progress", value, text)

    def log(self, message, style="info"):
        self._enqueue_ui_event("log", message, style)

    def clear_report(self):
        self._enqueue_ui_event("clear_report")
        
    def append_report_chunk(self, chunk):
        self._enqueue_ui_event("report_chunk", chunk)

    def show_dialog(self, title, message, is_error=False):
        self._enqueue_ui_event("dialog", title, message, is_error)

    def set_ui_state(self, state):
        self._enqueue_ui_event("ui_state", state)

    def set_operation_state(self, state):
        self._enqueue_ui_event("operation_state", state)

    def _enqueue_ui_event(self, event_type, *payload):
        """Publish a plain-Python event without touching Tk from the caller."""
        with self._ui_event_lock:
            if self._ui_events_closed:
                return False
            self.ui_event_queue.put((event_type, payload))
        return True

    def _consume_ui_events(self):
        """Apply queued events on Tk's main thread and schedule the next poll."""
        if self._ui_events_closed:
            return

        while True:
            try:
                event_type, payload = self.ui_event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._apply_ui_event(event_type, payload)
            except tk.TclError:
                self._close_ui_event_queue()
                return

        if not self._ui_events_closed:
            self.after(self.UI_EVENT_POLL_MS, self._consume_ui_events)

    def _apply_ui_event(self, event_type, payload):
        if event_type == "model_state":
            state, models, default_model, message, load_id = payload
            if load_id is not None and load_id < self._model_load_id:
                return
            if load_id is not None:
                self._model_load_id = load_id
            self._model_state = state
            self._model_values = tuple(models)
            self.model_combo['values'] = models
            if state == "ready" and default_model and default_model in models:
                self.model_combo.set(default_model)
            elif state == "ready" and models:
                self.model_combo.set(models[0])
            else:
                self.model_combo.set(message or state.capitalize())
        elif event_type == "select_tab":
            self.notebook.select(payload[0])
        elif event_type == "progress":
            value, text = payload
            self.progress_bar['value'] = value
            self.status_var.set(text)
        elif event_type == "log":
            message, style = payload
            self.log_text.text.configure(state="normal")
            self.log_text.text.insert(END, f"{message}\n", style)
            self.log_text.text.see(END)
            self.log_text.text.configure(state="disabled")
        elif event_type == "clear_report":
            self.report_text.text.configure(state="normal")
            self.report_text.text.delete("1.0", END)
            self.report_text.text.configure(state="disabled")
        elif event_type == "report_chunk":
            self.report_text.text.configure(state="normal")
            self.report_text.text.insert(END, payload[0])
            self.report_text.text.see(END)
            self.report_text.text.configure(state="disabled")
        elif event_type == "dialog":
            title, message, is_error = payload
            if is_error:
                Messagebox.show_error(message, title, parent=self)
            else:
                Messagebox.show_info(message, title, parent=self)
        elif event_type == "ui_state":
            state = payload[0]
            self.start_button.configure(state=state)
            if hasattr(self, 'regerar_button'): self.regerar_button.configure(state=state)
            if hasattr(self, 'coletar_button'): self.coletar_button.configure(state=state)
            if hasattr(self, 'iniciar_de_arquivo_button'): self.iniciar_de_arquivo_button.configure(state=state)
            if hasattr(self, 'test_zabbix_button'): self.test_zabbix_button.configure(state=state)
            if hasattr(self, 'cancel_button'): self.cancel_button.configure(state="normal" if state == "disabled" else "disabled")
        elif event_type == "operation_state":
            operation_state = payload[0]
            controls_state = "normal" if operation_state == "idle" else "disabled"
            cancel_state = "normal" if operation_state == "running" else "disabled"
            self.start_button.configure(state=controls_state)
            if hasattr(self, 'regerar_button'): self.regerar_button.configure(state=controls_state)
            if hasattr(self, 'coletar_button'): self.coletar_button.configure(state=controls_state)
            if hasattr(self, 'iniciar_de_arquivo_button'): self.iniciar_de_arquivo_button.configure(state=controls_state)
            if hasattr(self, 'test_zabbix_button'): self.test_zabbix_button.configure(state=controls_state)
            if hasattr(self, 'cancel_button'): self.cancel_button.configure(state=cancel_state)

    def _close_ui_event_queue(self):
        with self._ui_event_lock:
            self._ui_events_closed = True
            while True:
                try:
                    self.ui_event_queue.get_nowait()
                except queue.Empty:
                    break

    def destroy(self):
        self._close_ui_event_queue()
        super().destroy()

import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.constants import BOTH, X, LEFT, WORD, END
from tkinter import filedialog
import os
from dotenv import load_dotenv

class MainView(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Auditoria Inteligente de Zabbix")
        self.geometry("900x700")
        self.controller = None

        # Carrega defaults do .env (se existir)
        load_dotenv()
        self.zabbix_url_var = ttk.StringVar(value=os.getenv("ZABBIX_URL", ""))
        self.zabbix_user_var = ttk.StringVar(value=os.getenv("ZABBIX_USER", ""))
        self.zabbix_pass_var = ttk.StringVar(value=os.getenv("ZABBIX_PASS", ""))
        self.ai_provider_var = ttk.StringVar(value="Google Gemini")
        self.ai_key_var = ttk.StringVar(value=os.getenv("GEMINI_API_KEY", ""))

        self.attached_files = []
        self.create_widgets()

    def set_controller(self, controller):
        self.controller = controller

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
        ttk.Label(ai_frame, text="Provedor:").grid(row=0, column=0, sticky="w", pady=5)
        provider_combo = ttk.Combobox(ai_frame, textvariable=self.ai_provider_var, values=["Google Gemini", "OpenAI"], state="readonly", width=25)
        provider_combo.grid(row=0, column=1, sticky="w", pady=5, padx=5)
        
        ttk.Label(ai_frame, text="API Key:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(ai_frame, textvariable=self.ai_key_var, width=55, show="*").grid(row=1, column=1, sticky="w", pady=5, padx=5)
        ttk.Button(ai_frame, text="🔄 Validar Conexão / Atualizar Modelos", command=lambda: self.controller.load_models_async() if self.controller else None, bootstyle="info-outline").grid(row=1, column=2, padx=5)

        # 2. Aba de Logs
        log_frame = ttk.Frame(notebook, padding=5)
        self.log_text = ScrolledText(log_frame, wrap=WORD, autohide=True, state="disabled")
        self.log_text.pack(fill=BOTH, expand=True)
        notebook.add(log_frame, text="Logs da Execução")

        # 3. Aba de Relatório
        report_frame = ttk.Frame(notebook, padding=5)
        self.report_text = ScrolledText(report_frame, wrap=WORD, autohide=True, state="disabled")
        self.report_text.pack(fill=BOTH, expand=True)
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

    def start_audit_clicked(self):
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
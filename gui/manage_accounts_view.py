import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT
from api.ai_cli_client import cli_binary_status

class ManageAccountsWindow(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Gerenciar Contas de IA")
        self.geometry("500x400")
        self.grab_set()

        self.account_list = list(self.parent.ai_accounts.keys())
        self.selected_account = ttk.StringVar(value="<Nova Conta>")

        self.account_name_var = ttk.StringVar()
        self.base_provider_var = ttk.StringVar(value="Google Gemini")
        self.token_var = ttk.StringVar()
        self.auth_mode_var = ttk.StringVar(value="api_key")
        self.model_override_var = ttk.StringVar()
        self.cli_status_var = ttk.StringVar(value="")

        self.create_widgets()
        self.base_provider_var.trace_add("write", self.on_base_provider_change)
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

        row_toggle = ttk.Frame(main_frame)
        row_toggle.pack(fill=X, pady=5)
        self.auth_mode_toggle = ttk.Checkbutton(
            row_toggle,
            text="Usar CLI local (assinatura) em vez de API Key",
            variable=self.auth_mode_var,
            onvalue="cli",
            offvalue="api_key",
            bootstyle="round-toggle",
            command=self.on_auth_mode_change
        )
        self.auth_mode_toggle.pack(side=LEFT)

        self.row_token = ttk.Frame(main_frame)
        ttk.Label(self.row_token, text="Token/URL:", width=18).pack(side=LEFT)
        ttk.Entry(self.row_token, textvariable=self.token_var, show="*").pack(side=LEFT, fill=X, expand=True)

        self.row_cli = ttk.Frame(main_frame)
        ttk.Label(self.row_cli, text="Modelo (opcional):", width=18).pack(side=LEFT)
        ttk.Entry(self.row_cli, textvariable=self.model_override_var).pack(side=LEFT, fill=X, expand=True)

        self.row_status = ttk.Frame(main_frame)
        ttk.Label(self.row_status, text="", width=18).pack(side=LEFT)
        ttk.Label(self.row_status, textvariable=self.cli_status_var).pack(side=LEFT, fill=X, expand=True)

        self.btn_frame = ttk.Frame(main_frame)
        self.btn_frame.pack(fill=X, pady=20)
        ttk.Button(self.btn_frame, text="Salvar", bootstyle="success", command=self.save_account).pack(side=LEFT, padx=5)
        ttk.Button(self.btn_frame, text="Remover", bootstyle="danger", command=self.remove_account).pack(side=LEFT, padx=5)
        ttk.Button(self.btn_frame, text="Cancelar", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)

        self.row_token.pack(fill=X, pady=5, before=self.btn_frame)

    def on_auth_mode_change(self):
        if self.auth_mode_var.get() == "cli":
            self.row_token.pack_forget()
            self.row_cli.pack(fill=X, pady=5, before=self.btn_frame)
            self.row_status.pack(fill=X, pady=5, before=self.btn_frame)
            self.update_cli_status()
        else:
            self.row_cli.pack_forget()
            self.row_status.pack_forget()
            self.row_token.pack(fill=X, pady=5, before=self.btn_frame)

    def on_base_provider_change(self, *args):
        if self.base_provider_var.get() == "Ollama":
            self.auth_mode_var.set("api_key")
            self.auth_mode_toggle.configure(state="disabled")
            self.on_auth_mode_change()
        else:
            self.auth_mode_toggle.configure(state="normal")
        self.update_cli_status()

    def update_cli_status(self):
        if self.auth_mode_var.get() != "cli":
            return
        binary, path = cli_binary_status(self.base_provider_var.get())
        if not binary:
            self.cli_status_var.set("Provedor sem suporte a CLI local.")
        elif path:
            self.cli_status_var.set(f"Binário detectado: {path} ✅")
        else:
            self.cli_status_var.set(f"Binário '{binary}' não encontrado no PATH ❌")

    def on_account_select(self, *args):
        selected = self.selected_account.get()
        if selected == "<Nova Conta>":
            self.account_name_var.set("")
            self.base_provider_var.set("Google Gemini")
            self.token_var.set("")
            self.auth_mode_var.set("api_key")
            self.model_override_var.set("")
        elif selected in self.parent.ai_accounts:
            account = self.parent.ai_accounts[selected]
            self.account_name_var.set(selected)
            self.base_provider_var.set(account["provider"])
            self.token_var.set(account["api_key"])
            self.auth_mode_var.set(account.get("auth_mode", "api_key"))
            self.model_override_var.set(account.get("cli_model_override", ""))
        self.on_auth_mode_change()

    def save_account(self):
        old_name = self.selected_account.get()
        new_name = self.account_name_var.get().strip()
        base_prov = self.base_provider_var.get()
        token = self.token_var.get().strip()
        auth_mode = self.auth_mode_var.get()
        model_override = self.model_override_var.get().strip()

        if not new_name:
            return

        if old_name != "<Nova Conta>" and old_name != new_name:
            if old_name in self.parent.ai_accounts:
                del self.parent.ai_accounts[old_name]

        self.parent.ai_accounts[new_name] = {
            "provider": base_prov,
            "api_key": token,
            "auth_mode": auth_mode,
            "cli_model_override": model_override
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

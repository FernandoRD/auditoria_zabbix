import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT

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
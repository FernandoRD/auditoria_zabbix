import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X, LEFT, RIGHT
import tkinter as tk
from tkinter import filedialog

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
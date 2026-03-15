import ttkbootstrap as ttk
from gui.main_view import MainView
from core.controller import Controller

def main():
    """
    Ponto de entrada da aplicação.
    Cria a View (GUI), o Controller (lógica) e os conecta.
    """
    app = MainView()
    controller = Controller(view=app)
    app.set_controller(controller)
    app.mainloop()

if __name__ == "__main__":
    main()
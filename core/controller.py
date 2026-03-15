import threading
from api import zabbix_api, gemini_api

class Controller:
    def __init__(self, view):
        self.view = view
        self.auth_token = None
        self.load_models_async()

    def load_models_async(self):
        """Inicia a busca pelos modelos do Gemini em uma thread separada."""
        thread = threading.Thread(target=self._fetch_and_update_models)
        thread.daemon = True
        thread.start()

    def _fetch_and_update_models(self):
        try:
            gemini_api.setup_gemini()
            models = gemini_api.get_available_models()
            default = "models/gemini-1.5-pro-latest" if "models/gemini-1.5-pro-latest" in models else None
            self.view.update_model_list(models, default)
        except Exception as e:
            self.view.log(f"Aviso: Não foi possível carregar modelos online: {e}")
            self.view.update_model_list(["gemini-1.5-pro-latest", "gemini-1.5-flash-latest"], "gemini-1.5-pro-latest")

    def start_audit(self):
        """Inicia o processo de auditoria em uma nova thread para não travar a GUI."""
        self.view.set_ui_state('disabled')
        self.view.log("Iniciando auditoria...")
        
        # A execução da auditoria é feita em uma thread separada
        audit_thread = threading.Thread(target=self.run_audit_flow)
        audit_thread.daemon = True
        audit_thread.start()

    def run_audit_flow(self):
        """
        Executa o fluxo completo da auditoria: autentica, coleta, gera relatório e desloga.
        """
        try:
            # 0. Configura APIs
            self.view.log("Configurando APIs...")
            gemini_api.setup_gemini()

            # 1. Descobre a versão e autentica no Zabbix
            self.view.log("Detectando versão do Zabbix...")
            version, use_header = zabbix_api.discover_zabbix_version()
            if version:
                auth_method = 'Header Bearer' if use_header else 'Payload'
                self.view.log(f"Versão do Zabbix detectada: {version} (Autenticação via {auth_method})")

            self.view.log("Autenticando no Zabbix...")
            self.auth_token = zabbix_api.authenticate_zabbix()
            self.view.log("Autenticação realizada com sucesso.")

            # 2. Coleta os dados
            self.view.log("Iniciando coleta de dados do ambiente Zabbix...")
            zabbix_data = zabbix_api.collect_zabbix_data(self.auth_token)
            self.view.log("Coleta de dados concluída.")

            # 3. Gera o relatório com a IA
            os_evidence_text = ""
            if self.view.attached_files:
                self.view.log(f"Lendo e processando {len(self.view.attached_files)} arquivo(s) de evidência do SO...")
                for filepath in self.view.attached_files:
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            os_evidence_text += f"\n\n--- INÍCIO DO ARQUIVO: {filepath.split('/')[-1]} ---\n"
                            os_evidence_text += f.read()
                            os_evidence_text += f"\n--- FIM DO ARQUIVO: {filepath.split('/')[-1]} ---\n"
                    except Exception as e:
                        self.view.log(f"Aviso: Não foi possível ler o arquivo {filepath}: {e}")

            selected_model = self.view.get_selected_model()
            self.view.log(f"Enviando dados para análise da IA (Modelo: {selected_model}). Isso pode levar um momento...")
            report = gemini_api.generate_audit_report(zabbix_data, selected_model, os_evidence_text)
            self.view.log("Relatório gerado com sucesso!")

            # 4. Salva e exibe o relatório
            report_filename = "relatorio_auditoria_zabbix.md"
            with open(report_filename, "w", encoding="utf-8") as f:
                f.write(report)
            self.view.log(f"Relatório salvo como: {report_filename}")
            self.view.show_report(report)

        except Exception as e:
            self.view.log(f"ERRO: {e}", "danger")
        finally:
            # 5. Desloga do Zabbix por segurança
            if self.auth_token:
                self.view.log("Encerrando sessão do Zabbix...")
                zabbix_api.logout_zabbix(self.auth_token)
            self.view.set_ui_state('normal')
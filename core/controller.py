import threading
from api import zabbix_api, ai_api

class Controller:
    def __init__(self, view):
        self.view = view
        self.load_models_async()

    def load_models_async(self):
        """Inicia a busca pelos modelos na IA escolhida."""
        provider = self.view.ai_provider_var.get()
        api_key = self.view.ai_key_var.get().strip()
        
        if not api_key:
            self.view.update_model_list(["Insira a API Key primeiro..."], None)
            return
            
        self.view.model_combo.set(f"Conectando à {provider}...")
        thread = threading.Thread(target=self._fetch_and_update_models)
        thread.daemon = True
        thread.start()

    def _fetch_and_update_models(self):
        try:
            provider = self.view.ai_provider_var.get()
            api_key = self.view.ai_key_var.get().strip()
            client = ai_api.AIClient(provider, api_key)
            models = client.get_available_models()
            
            default = next((m for m in models if "pro" in m.lower() or "gpt-4" in m.lower() or "o1" in m.lower()), models[0] if models else None)
            self.view.update_model_list(models if models else ["Nenhum modelo compatível"], default)
        except Exception as e:
            self.view.log(f"Aviso: Não foi possível carregar modelos online: {e}")
            self.view.update_model_list(["Falha na conexão"], None)

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
        z_url = self.view.zabbix_url_var.get().strip()
        z_user = self.view.zabbix_user_var.get().strip()
        z_pass = self.view.zabbix_pass_var.get().strip()
        ai_prov = self.view.ai_provider_var.get()
        ai_key = self.view.ai_key_var.get().strip()
        ai_mod = self.view.get_selected_model()
        
        if not all([z_url, z_user, z_pass, ai_key, ai_mod]):
            self.view.log("ERRO: Preencha todas as configurações na aba 'Configurações' antes de iniciar.", "danger")
            self.view.set_ui_state('normal')
            return
            
        try:
            zabbix = zabbix_api.ZabbixClient(z_url, z_user, z_pass)
            self.view.log(f"Conectando ao Zabbix em {z_url}...")
            version = zabbix.discover_version()
            if version:
                self.view.log(f"Versão do Zabbix detectada: {version}")

            self.view.log("Autenticando no Zabbix...")
            zabbix.authenticate()
            self.view.log("Autenticação realizada com sucesso.")

            # 2. Coleta os dados
            self.view.log("Iniciando varredura e extração via API...")
            zabbix_data = zabbix.collect_data()
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

            self.view.log(f"Enviando dados para {ai_prov} (Modelo: {ai_mod}). Aguarde...")
            ai_client = ai_api.AIClient(ai_prov, ai_key)
            report = ai_client.generate_audit_report(zabbix_data, ai_mod, os_evidence_text)
            self.view.log("Relatório gerado com sucesso!")

            # 4. Exibe o relatório na tela
            self.view.show_report(report)

        except Exception as e:
            self.view.log(f"ERRO: {e}", "danger")
        finally:
            if 'zabbix' in locals() and getattr(zabbix, 'auth_token', None):
                zabbix.logout()
            self.view.set_ui_state('normal')
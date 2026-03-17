import threading
from api import zabbix_api, ai_api
import json
import os

class Controller:
    def __init__(self, view):
        self.view = view
        self.cancel_event = threading.Event()
        self.load_models_async()

    def load_models_async(self):
        """Inicia a busca pelos modelos na IA escolhida."""
        provider = self.view.get_selected_base_provider()
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
            provider = self.view.get_selected_base_provider()
            api_key = self.view.ai_key_var.get().strip()
            client = ai_api.AIClient(provider, api_key)
            models = client.get_available_models()
            
            default = next((m for m in models if "pro" in m.lower() or "gpt-4" in m.lower() or "o1" in m.lower()), models[0] if models else None)
            self.view.update_model_list(models if models else ["Nenhum modelo compatível"], default)
        except Exception as e:
            self.view.log(f"Aviso: Não foi possível carregar modelos online: {e}")
            self.view.update_model_list(["Falha na conexão"], None)

    def test_zabbix_connection(self):
        self.view.set_ui_state('disabled')
        self.view.update_progress(0, "Testando conexão...")
        threading.Thread(target=self._test_zabbix_flow, daemon=True).start()

    def _test_zabbix_flow(self):
        z_url = self.view.zabbix_url_var.get().strip()
        z_user = self.view.zabbix_user_var.get().strip()
        z_pass = self.view.zabbix_pass_var.get().strip()
        try:
            self.view.log(f"Testando conexão com o Zabbix em {z_url}...")
            zabbix = zabbix_api.ZabbixClient(z_url, z_user, z_pass)
            version = zabbix.discover_version()
            if not version:
                raise Exception("Não foi possível detectar a versão via API.")
            zabbix.authenticate()
            zabbix.logout()
            self.view.log(f"✅ Conexão bem-sucedida! Versão do Zabbix: {version}")
            self.view.update_progress(100, "Conexão Zabbix OK!")
        except Exception as e:
            self.view.log(f"❌ Falha na conexão com Zabbix: {e}", "danger")
            self.view.update_progress(0, "Falha na conexão Zabbix.")
        finally:
            self.view.set_ui_state('normal')

    def cancel_audit(self):
        """Sinaliza para a thread de auditoria parar."""
        self.cancel_event.set()
        self.view.log("Aviso: Cancelamento solicitado pelo usuário. Interrompendo...", "warning")
        self.view.update_progress(0, "Operação Cancelada.")
        self.view.set_ui_state('normal')

    def start_audit(self, use_cache=False):
        """Inicia o processo de auditoria em uma nova thread para não travar a GUI."""
        self.cancel_event.clear()
        self.view.set_ui_state('disabled')
        self.view.log("Iniciando auditoria (Usando Cache)..." if use_cache else "Iniciando auditoria (Nova Coleta)...")
        
        audit_thread = threading.Thread(target=self.run_audit_flow, args=(use_cache,))
        audit_thread.daemon = True
        audit_thread.start()

    def run_audit_flow(self, use_cache):
        z_url = self.view.zabbix_url_var.get().strip()
        z_user = self.view.zabbix_user_var.get().strip()
        z_pass = self.view.zabbix_pass_var.get().strip()
        ai_prov = self.view.get_selected_base_provider()
        ai_key = self.view.ai_key_var.get().strip()
        ai_mod = self.view.get_selected_model()
        
        if not all([z_url, z_user, z_pass, ai_key, ai_mod]):
            self.view.log("ERRO: Preencha todas as configurações na aba 'Configurações' antes de iniciar.", "danger")
            self.view.set_ui_state('normal')
            return
            
        try:
            zabbix_data = {}
            if not use_cache:
                self.view.update_progress(10, "Conectando ao Zabbix...")
                zabbix = zabbix_api.ZabbixClient(z_url, z_user, z_pass)
                self.view.log(f"Conectando ao Zabbix em {z_url}...")
                version = zabbix.discover_version()
                if version:
                    self.view.log(f"Versão do Zabbix detectada: {version}")
    
                self.view.update_progress(20, "Autenticando no Zabbix...")
                zabbix.authenticate()
    
                if self.cancel_event.is_set(): return
                self.view.update_progress(30, "Coletando dados da API (Pode demorar)...")
                self.view.log("Iniciando varredura profunda no Zabbix...")
                zabbix_data = zabbix.collect_data()
                self.view.log("Coleta de dados concluída com sucesso.")
                
                try:
                    with open("last_audit_cache.json", "w", encoding="utf-8") as f:
                        json.dump(zabbix_data, f, ensure_ascii=False)
                except: pass
            else:
                self.view.update_progress(30, "Carregando dados do cache local...")
                try:
                    with open("last_audit_cache.json", "r", encoding="utf-8") as f:
                        zabbix_data = json.load(f)
                    self.view.log("Dados da última auditoria (cache) carregados com sucesso.")
                except Exception as e:
                    self.view.log("Erro: Não há cache salvo. Execute a Auditoria normal primeiro.", "danger")
                    self.view.update_progress(0, "Erro de Cache.")
                    return

            if self.cancel_event.is_set(): return

            # 3. Gera o relatório com a IA
            self.view.update_progress(50, "Processando evidências e sistema...")
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

            analyst_data = {
                "name": self.view.analyst_name_var.get().strip(),
                "company": self.view.analyst_company_var.get().strip(),
                "email": self.view.analyst_email_var.get().strip(),
                "phone": self.view.analyst_phone_var.get().strip()
            }
            
            custom_inst = self.view.custom_instructions_text.text.get("1.0", "end").strip()

            if self.cancel_event.is_set(): return
            self.view.update_progress(60, "Conectando à Inteligência Artificial...")
            self.view.log(f"Enviando dados para {ai_prov} (Modelo: {ai_mod}). Aguarde...")
            ai_client = ai_api.AIClient(ai_prov, ai_key)
            
            self.view.clear_report()
            self.view.notebook.select(2) # Troca a aba visual para o "Relatório Final" automaticamente
            
            self.view.update_progress(80, "Recebendo Stream da Inteligência Artificial...")
            report_stream = ai_client.generate_audit_report(zabbix_data, ai_mod, os_evidence_text, analyst_data, custom_inst)
            
            for chunk in report_stream:
                if self.cancel_event.is_set():
                    self.view.log("Geração abortada pelo usuário.", "warning")
                    break
                self.view.append_report_chunk(chunk)

            if not self.cancel_event.is_set():
                self.view.log("Relatório gerado com sucesso!")
                self.view.update_progress(100, "Auditoria Concluída!")

        except Exception as e:
            self.view.log(f"ERRO: {e}", "danger")
            self.view.update_progress(0, "Erro durante a execução.")
        finally:
            if 'zabbix' in locals() and getattr(zabbix, 'auth_token', None):
                zabbix.logout()
            self.view.set_ui_state('normal')
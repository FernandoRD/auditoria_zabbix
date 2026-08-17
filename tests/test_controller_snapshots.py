import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from api.ai_prompts import AIStreamEvent
from core.controller import Controller
from core.run_config import (
    AIConfig,
    AnalystData,
    AuditRequest,
    CollectionLimits,
    ReportStyle,
    ZabbixConfig,
)


def make_request(**changes):
    values = {
        "zabbix": ZabbixConfig(
            url="https://zabbix.invalid/api_jsonrpc.php",
            auth_method="token",
            token="zabbix-secret",
        ),
        "ai": AIConfig(provider="OpenAI", api_key="ai-secret", model="gpt-test"),
        "analyst": AnalystData(name="Analista"),
        "limits": CollectionLimits(500, 15, 200, False),
        "style": ReportStyle("Linha", "Padrão", "Branco", "Preto", 800, 400, "Arial"),
    }
    values.update(changes)
    return AuditRequest(**values)


class WidgetGuardView:
    """A controller test double with no widgets or Tk variables to read."""

    def __init__(self):
        self.events = []

    def build_ai_config(self):
        return AIConfig(provider="Anthropic", auth_mode="cli")

    def __getattr__(self, name):
        if name.endswith("_var") or name in {
            "notebook",
            "model_combo",
            "custom_instructions_text",
            "attached_files",
        }:
            raise AssertionError(f"controller tried to read GUI state: {name}")
        raise AttributeError(name)

    def update_model_list(self, models, default=None):
        self.events.append(("models", models, default))

    def set_model_state(self, *state):
        self.events.append(("model_state",) + state)

    def show_model_loading(self, provider):
        self.events.append(("loading", provider))

    def log(self, message, style="info"):
        self.events.append(("log", message, style))

    def update_progress(self, value, message):
        self.events.append(("progress", value, message))

    def set_ui_state(self, state):
        self.events.append(("state", state))

    def select_logs_tab(self):
        self.events.append(("tab", "logs"))

    def select_report_tab(self):
        self.events.append(("tab", "report"))

    def clear_report(self):
        self.events.append(("clear",))

    def append_report_chunk(self, chunk):
        self.events.append(("chunk", chunk))

    def show_dialog(self, title, message, is_error=False):
        self.events.append(("dialog", title, message, is_error))


class TestRunConfig(unittest.TestCase):
    def test_snapshots_are_frozen_hide_secrets_and_copy_attachments(self):
        files = ["one.log"]
        request = make_request(attached_files=files)
        files.append("two.log")

        self.assertEqual(("one.log",), request.attached_files)
        self.assertNotIn("zabbix-secret", repr(request))
        self.assertNotIn("ai-secret", repr(request))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.anonymize = True

    def test_zabbix_credentials_are_validated_by_snapshot(self):
        missing_token = ZabbixConfig("https://zabbix.invalid", "token")
        missing_password = ZabbixConfig("https://zabbix.invalid", "user_pass", username="user")

        self.assertIn("Token", missing_token.validation_error())
        self.assertIn("Senha", missing_password.validation_error())


class TestControllerUsesSnapshots(unittest.TestCase):
    def setUp(self):
        self.view = WidgetGuardView()
        self.controller = Controller(self.view)

    def test_audit_worker_uses_request_without_reading_widgets(self):
        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "collection.json"
            data_file.write_text(json.dumps({"hosts": 3}), encoding="utf-8")
            request = make_request(
                data_file=str(data_file),
                attached_files=[str(data_file)],
                custom_instructions="Seja conciso",
            )
            client = MagicMock()
            client.generate_audit_report.return_value = iter([
                AIStreamEvent.text_chunk("parte 1"),
                AIStreamEvent.text_chunk("parte 2"),
                AIStreamEvent.final("stop"),
            ])

            with patch("core.controller.ai_api.AIClient", return_value=client):
                self.controller.run_audit_flow(request)

        client.generate_audit_report.assert_called_once_with(
            {"hosts": 3},
            "gpt-test",
            unittest.mock.ANY,
            {"name": "Analista", "company": "", "email": "", "phone": ""},
            "Seja conciso",
            is_cancelled=unittest.mock.ANY,
        )
        self.assertIn(("tab", "report"), self.view.events)
        self.assertIn(("chunk", "parte 2"), self.view.events)

    def test_connection_worker_uses_zabbix_snapshot(self):
        config = ZabbixConfig(
            "https://zabbix.invalid/api_jsonrpc.php",
            "user_pass",
            username="api-user",
            password="api-password",
            verify_ssl=False,
        )
        client = MagicMock()
        client.discover_version.return_value = "7.0"

        with patch("core.controller.zabbix_api.ZabbixClient", return_value=client) as client_class:
            self.controller._test_zabbix_flow(config)

        client_class.assert_called_once_with(
            config.url,
            user="api-user",
            password="api-password",
            verify_ssl=False,
            logger=unittest.mock.ANY,
        )
        client.authenticate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

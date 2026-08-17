import unittest
from unittest.mock import MagicMock, patch

from core.controller import (
    Controller,
    insecure_zabbix_transport_warnings,
    validate_zabbix_url,
)
from core.run_config import ZabbixConfig
from core.run_config import (
    AIConfig,
    AnalystData,
    AuditRequest,
    CollectionLimits,
    CollectionRequest,
    ReportStyle,
)


class SecurityView:
    def __init__(self, confirmation=True):
        self.confirmation = confirmation
        self.confirmation_calls = []
        self.logs = []

    def confirm_insecure_zabbix_transport(self, warnings):
        self.confirmation_calls.append(warnings)
        return self.confirmation

    def log(self, message, style="info"):
        self.logs.append((message, style))

    def update_progress(self, *_args):
        pass

    def show_dialog(self, *_args, **_kwargs):
        pass


def config(url, verify_ssl=True):
    return ZabbixConfig(
        url=url,
        auth_method="token",
        token="zabbix-api-token",
        verify_ssl=verify_ssl,
    )


def limits():
    return CollectionLimits(500, 15, 200, False)


def fresh_audit_request(url):
    return AuditRequest(
        zabbix=config(url),
        ai=AIConfig("OpenAI", api_key="synthetic-ai-key", model="synthetic-model"),
        analyst=AnalystData(),
        limits=limits(),
        style=ReportStyle("line", "Azul", "Branco", "Preto", 800, 400, "sans-serif"),
    )


class TestZabbixTransportValidation(unittest.TestCase):
    def test_url_validation_is_pure_and_rejects_credentials_in_url(self):
        self.assertIsNone(validate_zabbix_url("https://zabbix.example/api_jsonrpc.php"))
        self.assertIn("campos próprios", validate_zabbix_url("https://user:secret@zabbix.example"))
        self.assertIn("HTTP ou HTTPS", validate_zabbix_url("ftp://zabbix.example"))

    def test_https_does_not_require_confirmation(self):
        self.assertEqual((), insecure_zabbix_transport_warnings(config("https://zabbix.example")))

    def test_http_localhost_does_not_require_confirmation(self):
        self.assertEqual((), insecure_zabbix_transport_warnings(config("http://[::1]/api_jsonrpc.php")))

    def test_http_remote_requires_confirmation(self):
        self.assertEqual(
            ("remote_http",),
            insecure_zabbix_transport_warnings(config("http://zabbix.example")),
        )

    def test_https_with_tls_validation_disabled_requires_confirmation(self):
        self.assertEqual(
            ("unverified_tls",),
            insecure_zabbix_transport_warnings(
                config("https://zabbix.example", verify_ssl=False)
            ),
        )


class TestZabbixTransportConsentAndLogs(unittest.TestCase):
    def _controller(self, confirmation=True):
        controller = Controller.__new__(Controller)
        controller.view = SecurityView(confirmation=confirmation)
        controller._start_operation = MagicMock(return_value=True)
        return controller

    def test_remote_http_cancellation_prevents_connection(self):
        controller = self._controller(confirmation=False)

        controller.test_zabbix_connection(config("http://zabbix.example"))

        self.assertEqual([("remote_http",)], controller.view.confirmation_calls)
        controller._start_operation.assert_not_called()
        self.assertIn("cancelada", controller.view.logs[-1][0])

    def test_tls_exception_requires_confirmation_before_connection(self):
        controller = self._controller(confirmation=True)

        controller.test_zabbix_connection(config("https://zabbix.example", verify_ssl=False))

        self.assertEqual([("unverified_tls",)], controller.view.confirmation_calls)
        controller._start_operation.assert_called_once()

    def test_collection_and_fresh_audit_do_not_start_without_confirmation(self):
        controller = self._controller(confirmation=False)
        remote_url = "http://zabbix.example/api_jsonrpc.php"

        controller.start_collection_only(
            CollectionRequest(config(remote_url), limits(), "synthetic-output.json")
        )
        controller.start_audit(fresh_audit_request(remote_url))

        self.assertEqual(
            [("remote_http",), ("remote_http",)],
            controller.view.confirmation_calls,
        )
        controller._start_operation.assert_not_called()

    def test_connection_failure_log_redacts_credentials_and_authorization(self):
        controller = self._controller()
        zabbix_config = ZabbixConfig(
            "https://zabbix.example",
            "user_pass",
            username="admin",
            password="super-secret-password",
            token="zabbix-api-token",
        )
        client = MagicMock()
        client.discover_version.side_effect = RuntimeError(
            "Authorization: Bearer leaked-header-token "
            "password=super-secret-password token=zabbix-api-token"
        )

        with patch("core.controller.zabbix_api.ZabbixClient", return_value=client):
            controller._test_zabbix_flow(zabbix_config)

        logged = "\n".join(message for message, _style in controller.view.logs)
        self.assertNotIn("super-secret-password", logged)
        self.assertNotIn("zabbix-api-token", logged)
        self.assertNotIn("leaked-header-token", logged)
        self.assertNotIn("Authorization", logged)


if __name__ == "__main__":
    unittest.main()

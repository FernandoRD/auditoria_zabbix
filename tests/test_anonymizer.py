import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.anonymizer import Anonymizer, REDACTED_VALUE
from core.controller import Controller
from core.run_config import (
    AIConfig,
    AnalystData,
    AuditRequest,
    CollectionRequest,
    CollectionLimits,
    ReportStyle,
    ZabbixConfig,
)
from gui.main_view import MainView, _is_local_ollama_destination


class TestStructuralAnonymizer(unittest.TestCase):
    def test_request_snapshots_enable_anonymization_by_default(self):
        zabbix = ZabbixConfig("https://zabbix.invalid", "token", token="token")
        limits = CollectionLimits(500, 15, 200, False)
        audit_request = AuditRequest(
            zabbix=zabbix,
            ai=AIConfig("OpenAI", api_key="key", model="model"),
            analyst=AnalystData(),
            limits=limits,
            style=ReportStyle("Linha", "Padrão", "Branco", "Preto", 800, 400, "Arial"),
        )
        collection_request = CollectionRequest(zabbix, limits, "collection.json")

        self.assertTrue(audit_request.anonymize)
        self.assertTrue(collection_request.anonymize)

    def test_recursively_redacts_all_sensitive_key_variants(self):
        sensitive_keys = (
            "password",
            "PASSWD",
            "SenhaAdmin",
            "db_pwd",
            "clientSecret",
            "accessToken",
            "ApiKey",
            "api_key_backup",
            "snmpCommunity",
            "credentialId",
            "tlsPSK",
        )
        source = {key: {"nested": "must disappear"} for key in sensitive_keys}
        source["ordinary"] = [True, 7, None]

        result = Anonymizer().anonymize(source)

        for key in sensitive_keys:
            with self.subTest(key=key):
                self.assertEqual(REDACTED_VALUE, result[key])
        self.assertEqual([True, 7, None], result["ordinary"])

    def test_valid_ips_are_stable_and_oid_and_invalid_ipv4_are_untouched(self):
        anonymizer = Anonymizer()
        result = anonymizer.anonymize(
            {
                "primary": "192.0.2.10",
                "log": "peer=192.0.2.10 via 198.51.100.3",
                "ipv6": ["2001:db8::8", "2001:0db8:0:0:0:0:0:8"],
                "oid": "1.3.6.1.4.1.8072.3.2.10",
                "invalid": "999.1.2.3",
            }
        )

        self.assertEqual("<IPv4-1>", result["primary"])
        self.assertEqual("peer=<IPv4-1> via <IPv4-2>", result["log"])
        self.assertEqual(["<IPv6-1>", "<IPv6-1>"], result["ipv6"])
        self.assertEqual("1.3.6.1.4.1.8072.3.2.10", result["oid"])
        self.assertEqual("999.1.2.3", result["invalid"])

    def test_structural_oid_fields_preserve_short_oids_without_bypassing_redaction(self):
        result = Anonymizer().anonymize(
            {
                "oid": "1.3.6.1",
                "snmp_oid": "1.3.6.1",
                "ordinary_ip": "1.3.6.1",
                "ordinary_text": "password=must-not-leak",
            }
        )

        self.assertEqual("1.3.6.1", result["oid"])
        self.assertEqual("1.3.6.1", result["snmp_oid"])
        self.assertEqual("<IPv4-1>", result["ordinary_ip"])
        self.assertEqual("password=***", result["ordinary_text"])

    def test_free_text_redactor_handles_json_mixed_case_tokens_and_quotes(self):
        text = (
            'PaSsWoRd="two words" TOKEN: abc123 '
            '{"api_key": "key-value", "community": "public"} '
            "PSK='dead beef' endpoint=[2001:db8::5] oid=1.3.6.1.4.1"
        )

        result = Anonymizer().redact_text(text)

        for secret in ("two words", "abc123", "key-value", "public", "dead beef"):
            self.assertNotIn(secret, result)
        self.assertIn("TOKEN: ***", result)
        self.assertIn('"api_key": "***"', result)
        self.assertIn("endpoint=[<IPv6-1>]", result)
        self.assertIn("oid=1.3.6.1.4.1", result)

    def test_text_redactor_preserves_short_oid_masks_ip_with_punctuation_and_handles_escaped_quotes(self):
        anonymizer = Anonymizer()

        self.assertEqual("oid=1.3.6.1", anonymizer.redact_text("oid=1.3.6.1"))
        self.assertEqual("peer <IPv4-1>.", anonymizer.redact_text("peer 192.0.2.1."))
        self.assertEqual(
            '{"password":"***"}',
            anonymizer.redact_text(r'{"password":"abc\"def"}'),
        )

    def test_text_redactor_masks_ipv6_with_punctuation_and_full_non_string_json_values(self):
        anonymizer = Anonymizer()

        self.assertEqual("IP <IPv6-1>.", anonymizer.redact_text("IP 2001:db8::1."))
        for source in ('{"token": 12345}', '{"token": {"value":"abc"}}'):
            with self.subTest(source=source):
                redacted = anonymizer.redact_text(source)
                self.assertEqual({"token": REDACTED_VALUE}, json.loads(redacted))
                self.assertNotIn("12345", redacted)
                self.assertNotIn("abc", redacted)


def _audit_request(ai, *, anonymize=False, data_file=None, attached_files=()):
    return AuditRequest(
        zabbix=ZabbixConfig("https://zabbix.invalid", "token", token="zabbix-token"),
        ai=ai,
        analyst=AnalystData(name="Analista"),
        limits=CollectionLimits(500, 15, 200, False),
        style=ReportStyle("Linha", "Padrão", "Branco", "Preto", 800, 400, "Arial"),
        anonymize=anonymize,
        data_file=data_file,
        attached_files=attached_files,
    )


class RecordingView:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.events.append((name, args, kwargs))

        return record


class TestControllerAnonymization(unittest.TestCase):
    def test_imported_json_and_evidence_share_one_audit_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "collection.json"
            evidence_file = Path(directory) / "evidence.log"
            data_file.write_text(
                json.dumps({"host": "192.0.2.10", "AuthToken": "json-secret"}),
                encoding="utf-8",
            )
            evidence_file.write_text(
                "peer=192.0.2.10 token=evidence-secret",
                encoding="utf-8",
            )
            request = _audit_request(
                AIConfig("OpenAI", api_key="ai-key", model="gpt-test"),
                anonymize=True,
                data_file=str(data_file),
                attached_files=(str(evidence_file),),
            )
            client = MagicMock()
            client.generate_audit_report.return_value = iter(())
            controller = Controller.__new__(Controller)
            controller.view = RecordingView()

            with patch("core.controller.ai_api.AIClient", return_value=client):
                controller.run_audit_flow(request)

        sent_data, _, sent_evidence = client.generate_audit_report.call_args.args[:3]
        self.assertEqual(REDACTED_VALUE, sent_data["AuthToken"])
        self.assertEqual("<IPv4-1>", sent_data["host"])
        self.assertIn("peer=<IPv4-1>", sent_evidence)
        self.assertNotIn("json-secret", repr(sent_data))
        self.assertNotIn("evidence-secret", sent_evidence)


class ConfirmationHarness:
    confirm_unanonymized_remote_audit = MainView.confirm_unanonymized_remote_audit

    def __init__(self):
        self.logs = []

    def log(self, message, style="info"):
        self.logs.append((message, style))


class TestUnanonymizedConfirmation(unittest.TestCase):
    def test_only_loopback_ollama_is_considered_local(self):
        local_endpoints = (
            "http://localhost:11434",
            "127.0.0.1:11434",
            "http://[::1]:11434",
        )
        for endpoint in local_endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertTrue(
                    _is_local_ollama_destination(AIConfig("Ollama", endpoint, "model"))
                )

        self.assertFalse(
            _is_local_ollama_destination(AIConfig("Ollama", "http://ollama.example", "model"))
        )
        self.assertFalse(
            _is_local_ollama_destination(AIConfig("OpenAI", "http://localhost", "model"))
        )

    def test_remote_unanonymized_audit_requires_affirmative_answer(self):
        harness = ConfirmationHarness()
        request = _audit_request(AIConfig("OpenAI", "key", "model"))

        with patch("gui.main_view.Messagebox.yesno", return_value="No") as yesno:
            self.assertFalse(harness.confirm_unanonymized_remote_audit(request))

        yesno.assert_called_once()
        self.assertTrue(harness.logs)

        with patch("gui.main_view.Messagebox.yesno", return_value="Yes"):
            self.assertTrue(harness.confirm_unanonymized_remote_audit(request))

    def test_anonymized_or_local_ollama_audit_does_not_prompt(self):
        harness = ConfirmationHarness()
        requests = (
            _audit_request(AIConfig("OpenAI", "key", "model"), anonymize=True),
            _audit_request(AIConfig("Ollama", "http://localhost:11434", "model")),
        )

        with patch("gui.main_view.Messagebox.yesno") as yesno:
            self.assertTrue(harness.confirm_unanonymized_remote_audit(requests[0]))
            self.assertTrue(harness.confirm_unanonymized_remote_audit(requests[1]))

        yesno.assert_not_called()


if __name__ == "__main__":
    unittest.main()

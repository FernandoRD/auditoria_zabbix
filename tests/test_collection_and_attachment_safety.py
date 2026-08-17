import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from api.zabbix_api import ZabbixClient, parse_update_interval
from core.controller import Controller
from core.operation import OperationContext


def running_operation():
    operation = OperationContext()
    operation.mark_running()
    return operation


class TestResilientCollection(unittest.TestCase):
    def test_optional_phase_failure_preserves_previous_data_and_metadata(self):
        client = ZabbixClient("https://zabbix.invalid", max_retries=0)
        client.api_version = "7.4.0"
        calls = []

        def api_call(method, params, auth_required=True):
            calls.append(method)
            if method == "host.get" and calls.count(method) == 1:
                return [{"hostid": "1", "host": "server", "status": "0"}]
            if method == "hostgroup.get":
                raise RuntimeError("permission denied for host groups")
            return []

        client.api_call = api_call
        progress = []
        result = client.collect_data(
            is_cancelled=lambda: False,
            progress_callback=lambda value, phase: progress.append((value, phase)),
        )

        self.assertEqual(1, result["total_hosts"])
        self.assertEqual(0, result["total_host_groups"])
        self.assertIn("zabbix_server_os_metrics", result)
        metadata = result["_collection_metadata"]
        self.assertEqual(1, metadata["schema_version"])
        self.assertEqual("7.4.0", metadata["zabbix_version"])
        self.assertFalse(metadata["anonymized"])
        self.assertTrue(metadata["warnings"])
        self.assertIn(
            "hostgroup.get",
            [warning.get("method") for warning in metadata["warnings"]],
        )
        self.assertEqual(sorted(progress), progress)

    def test_item_intervals_lld_authentication_and_call_count_are_explicit(self):
        client = ZabbixClient("https://zabbix.invalid", max_retries=0)
        client.api_version = "7.4.0"
        client.api_version_tuple = (7, 4, 0)
        calls = []

        def api_call(method, params, auth_required=True):
            calls.append(method)
            if method == "item.get" and len([call for call in calls if call == "item.get"]) == 1:
                return [
                    {"itemid": "1", "name": "Trapper", "type": "2", "delay": "0", "key_": "trap", "state": "0", "error": ""},
                    {"itemid": "2", "name": "Fast", "type": "0", "delay": "20s", "key_": "fast", "state": "0", "error": ""},
                    {"itemid": "3", "name": "Macro", "type": "0", "delay": "{$INTERVAL}", "key_": "macro", "state": "1", "error": "not supported"},
                ]
            if method == "discoveryrule.get":
                return [{"name": "Discover disks", "key_": "vfs.fs.discovery", "delay": "1h", "error": ""}]
            return []

        client.api_call = api_call
        result = client.collect_data(is_cancelled=lambda: False)

        self.assertEqual(1, result["aggressive_polling_count"])
        self.assertEqual("fast", result["aggressive_polling_samples"][0]["key"])
        self.assertEqual(1, result["unclassifiable_item_intervals_count"])
        self.assertEqual("macro", result["unclassifiable_item_intervals_samples"][0]["key"])
        self.assertEqual(
            {"key": "macro", "error": "not supported"},
            result["unsupported_items_samples"][0],
        )
        self.assertEqual(1, result["active_discovery_rules_count"])
        self.assertIn("discoveryrule.get", calls)
        self.assertNotIn("drule.get", calls)
        self.assertFalse(result["authentication_summary"]["available"])
        self.assertEqual(len(calls), result["_collection_metadata"]["api_call_count"])

    def test_mfa_endpoint_is_not_called_before_zabbix_70(self):
        client = ZabbixClient("https://zabbix.invalid", max_retries=0)
        client.api_version = "6.4.18"
        client.api_version_tuple = (6, 4, 18)
        calls = []

        def api_call(method, params, auth_required=True):
            calls.append(method)
            return []

        client.api_call = api_call
        result = client.collect_data(is_cancelled=lambda: False)

        self.assertNotIn("mfa.get", calls)
        self.assertEqual(
            "MFA requer Zabbix 7.0 ou superior",
            result["authentication_summary"]["unavailability_reason"],
        )


class TestUpdateIntervalParsing(unittest.TestCase):
    def test_simple_suffixes_are_parsed_and_complex_values_are_not_classified(self):
        self.assertEqual(20, parse_update_interval("20s"))
        self.assertEqual(120, parse_update_interval("2m"))
        self.assertEqual(0, parse_update_interval("0"))
        self.assertIsNone(parse_update_interval("{$INTERVAL}"))
        self.assertIsNone(parse_update_interval("30s;1-7,00:00-24:00"))


class TestAttachmentSafety(unittest.TestCase):
    def setUp(self):
        self.controller = Controller.__new__(Controller)
        self.controller.view = MagicMock()

    def test_attachment_is_bounded_and_uses_only_basename_in_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            attachment = Path(directory) / "sensitive evidence.log"
            attachment.write_text("abcdefghijk", encoding="utf-8")
            self.controller.MAX_ATTACHMENT_BYTES = 5
            self.controller.MAX_TOTAL_ATTACHMENT_BYTES = 5

            evidence = self.controller._read_attached_evidence(
                (str(attachment),), running_operation()
            )

        self.assertIn("sensitive evidence.log", evidence)
        self.assertNotIn(str(attachment), evidence)
        self.assertIn("abcde", evidence)
        self.assertNotIn("fghijk", evidence)
        self.assertTrue(
            any("truncado" in call.args[0] for call in self.controller.view.log.call_args_list)
        )

    def test_json_requires_object_root_and_known_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            list_file = directory / "list.json"
            list_file.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            future_file = directory / "future.json"
            future_file.write_text(
                json.dumps({"_collection_metadata": {"schema_version": 2}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "raiz"):
                Controller._load_audit_json(list_file)
            with self.assertRaisesRegex(ValueError, "schema"):
                Controller._load_audit_json(future_file)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

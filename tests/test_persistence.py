import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.controller import Controller
from core.paths import AppPaths, get_app_paths
from core.persistence import (
    CacheStore,
    SettingsStore,
    atomic_write_text,
    build_cache_envelope,
    cache_mismatch_reasons,
    normalize_settings,
    parse_cache_envelope,
    server_fingerprint,
)
from core.run_config import (
    AIConfig,
    AnalystData,
    AuditRequest,
    CollectionLimits,
    ReportStyle,
    ZabbixConfig,
)


def app_paths(root):
    root = Path(root)
    return AppPaths(root / "config", root / "cache", root / "data")


def audit_request(url, *, anonymize=True):
    return AuditRequest(
        zabbix=ZabbixConfig(url, "token"),
        ai=AIConfig("OpenAI", api_key="synthetic-key", model="synthetic-model"),
        analyst=AnalystData(),
        limits=CollectionLimits(500, 15, 200, False),
        style=ReportStyle("Linha", "Padrão", "Branco", "Preto", 800, 400, "sans-serif"),
        anonymize=anonymize,
        use_cache=True,
    )


class CacheConsentView:
    def __init__(self, confirmation=False):
        self.confirmation = confirmation
        self.confirmations = []
        self.logs = []

    def log(self, message, style="info"):
        self.logs.append((message, style))

    def confirm_cache_mismatch(self, summary, reasons):
        self.confirmations.append((summary, reasons))
        return self.confirmation


class TestPlatformPaths(unittest.TestCase):
    def test_writable_paths_do_not_depend_on_current_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_cwd = root / "first"
            second_cwd = root / "second"
            first_cwd.mkdir()
            second_cwd.mkdir()
            environment = {
                "XDG_CONFIG_HOME": str(root / "xdg-config"),
                "XDG_CACHE_HOME": str(root / "xdg-cache"),
                "XDG_DATA_HOME": str(root / "xdg-data"),
            }
            previous_cwd = Path.cwd()
            try:
                with patch.dict(os.environ, environment, clear=False):
                    os.chdir(first_cwd)
                    first = get_app_paths()
                    os.chdir(second_cwd)
                    second = get_app_paths()
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(first, second)
        self.assertNotIn(str(first_cwd), str(first.settings_file))
        self.assertNotIn(str(second_cwd), str(first.audit_cache_file))

    def test_user_directories_are_created_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = app_paths(directory)
            self.assertFalse(paths.data_dir.exists())

            created = paths.ensure_data_dir()

            self.assertEqual(paths.data_dir, created)
            self.assertTrue(created.is_dir())
            if os.name == "posix":
                self.assertEqual(0o700, created.stat().st_mode & 0o777)


class TestAtomicWrites(unittest.TestCase):
    def test_replace_failure_preserves_previous_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "settings.json"
            target.write_text("anterior", encoding="utf-8")

            with patch("core.persistence.os.replace", side_effect=OSError("interrompido")):
                with self.assertRaisesRegex(OSError, "interrompido"):
                    atomic_write_text(target, "novo")

            self.assertEqual("anterior", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    @unittest.skipUnless(os.name == "posix", "permissões POSIX")
    def test_atomic_file_is_restricted_to_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cache.json"
            atomic_write_text(target, "segredo sintético")
            self.assertEqual(0o600, target.stat().st_mode & 0o777)


class TestSettingsStore(unittest.TestCase):
    def test_invalid_types_and_limits_use_defaults_with_warnings(self):
        normalized, warnings = normalize_settings(
            {
                "history_limit": "muitos",
                "sample_limit": 0,
                "chart_width": 99_999,
                "anonymize_data": "sim",
                "zabbix_auth_method": "oauth",
                "custom_instructions": ["não é texto"],
            }
        )

        self.assertEqual(500, normalized["history_limit"])
        self.assertEqual(15, normalized["sample_limit"])
        self.assertEqual(800, normalized["chart_width"])
        self.assertTrue(normalized["anonymize_data"])
        self.assertEqual("user_pass", normalized["zabbix_auth_method"])
        self.assertNotIn("custom_instructions", normalized)
        self.assertGreaterEqual(len(warnings), 6)

    def test_legacy_settings_migrate_atomically_without_credentials_or_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = app_paths(directory)
            legacy = Path(directory) / "settings.json"
            legacy.write_text(
                json.dumps(
                    {
                        "history_limit": 700,
                        "zabbix_pass": "legacy-password",
                        "api_keys": {"OpenAI": "legacy-api-key"},
                    }
                ),
                encoding="utf-8",
            )

            result = SettingsStore(paths, legacy).load()

            self.assertTrue(legacy.exists())
            self.assertTrue(paths.settings_file.exists())
            migrated = json.loads(paths.settings_file.read_text(encoding="utf-8"))
            self.assertEqual({"history_limit": 700}, migrated)
            self.assertEqual("legacy-password", result.legacy_credentials["zabbix_pass"])
            self.assertEqual("legacy-api-key", result.legacy_credentials["OpenAI_api_key"])
            self.assertNotIn("legacy-password", paths.settings_file.read_text(encoding="utf-8"))
            self.assertTrue(any("original foi preservado" in warning for warning in result.warnings))

    def test_invalid_json_loads_defaults_and_reports_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = app_paths(directory)
            paths.config_dir.mkdir(parents=True)
            paths.settings_file.write_text("{incompleto", encoding="utf-8")

            result = SettingsStore(paths).load()

            self.assertEqual({}, result.settings)
            self.assertTrue(any("usando padrões" in warning for warning in result.warnings))

    def test_non_object_settings_load_defaults_and_report_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = app_paths(directory)
            paths.config_dir.mkdir(parents=True)
            paths.settings_file.write_text("[]", encoding="utf-8")

            result = SettingsStore(paths).load()

            self.assertEqual({}, result.settings)
            self.assertTrue(any("objeto JSON" in warning for warning in result.warnings))


class TestCacheStore(unittest.TestCase):
    def setUp(self):
        self.data = {
            "hosts_count": 3,
            "_collection_metadata": {
                "schema_version": 1,
                "collected_at_utc": "2026-08-17T12:00:00+00:00",
                "zabbix_version": "7.4.0",
                "anonymized": True,
                "warnings": [{"method": "mfa.get", "message": "indisponível"}],
            },
        }

    def test_cache_envelope_contains_required_metadata_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CacheStore(app_paths(directory))
            saved = store.save(
                self.data,
                "https://user:ignored@example.test/zabbix/api_jsonrpc.php?token=ignored",
                True,
            )
            loaded = store.load()
            raw = json.loads(store.path.read_text(encoding="utf-8"))

            self.assertEqual(1, raw["cache_schema_version"])
            self.assertEqual("example.test", raw["server"]["name"])
            self.assertNotIn("user", json.dumps(raw["server"]))
            self.assertNotIn("ignored", json.dumps(raw["server"]))
            self.assertEqual("7.4.0", raw["zabbix_version"])
            self.assertTrue(raw["anonymized"])
            self.assertEqual(self.data, saved.data)
            self.assertEqual(saved, loaded)

    def test_legacy_cache_migrates_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = app_paths(directory)
            legacy = Path(directory) / "last_audit_cache.json"
            legacy.write_text(json.dumps(self.data), encoding="utf-8")
            store = CacheStore(paths, legacy)

            record = store.load("https://zabbix.example/api_jsonrpc.php")

            self.assertTrue(legacy.exists())
            self.assertTrue(paths.audit_cache_file.exists())
            self.assertEqual(str(legacy), record.migrated_from)
            self.assertEqual(self.data, record.data)
            self.assertIsNone(record.server_fingerprint)
            self.assertEqual("servidor-desconhecido", record.server_name)
            self.assertTrue(
                cache_mismatch_reasons(
                    record, "https://zabbix.example/api_jsonrpc.php", True
                )
            )

    def test_mismatch_detects_server_and_anonymization(self):
        record = parse_cache_envelope(
            build_cache_envelope(
                self.data, "https://first.example/api_jsonrpc.php", True
            )
        )

        reasons = cache_mismatch_reasons(
            record, "https://second.example/api_jsonrpc.php", False
        )

        self.assertEqual(2, len(reasons))
        self.assertNotEqual(
            server_fingerprint("https://first.example/api_jsonrpc.php"),
            server_fingerprint("https://second.example/api_jsonrpc.php"),
        )
        self.assertEqual(
            server_fingerprint("https://user:one@first.example/api_jsonrpc.php?token=one"),
            server_fingerprint("https://user:two@first.example/api_jsonrpc.php?token=two"),
        )

    def test_controller_requires_confirmation_before_divergent_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CacheStore(app_paths(directory))
            store.save(self.data, "https://first.example/api_jsonrpc.php", True)
            view = CacheConsentView(confirmation=False)
            controller = Controller.__new__(Controller)
            controller.view = view
            controller.cache_store = store
            controller._start_operation = MagicMock(return_value=True)

            result = controller.start_audit(
                audit_request("https://second.example/api_jsonrpc.php", anonymize=False)
            )

            self.assertIsNone(result)
            controller._start_operation.assert_not_called()
            self.assertEqual(1, len(view.confirmations))
            summary, reasons = view.confirmations[0]
            self.assertEqual("first.example", summary["server_name"])
            self.assertEqual(2, len(reasons))
            self.assertTrue(any("origem first.example" in message for message, _ in view.logs))

    def test_matching_cache_starts_without_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CacheStore(app_paths(directory))
            source_url = "https://zabbix.example/api_jsonrpc.php"
            store.save(self.data, source_url, True)
            view = CacheConsentView()
            controller = Controller.__new__(Controller)
            controller.view = view
            controller.cache_store = store
            controller._start_operation = MagicMock(return_value=True)

            result = controller.start_audit(audit_request(source_url, anonymize=True))

            self.assertTrue(result)
            self.assertEqual([], view.confirmations)
            controller._start_operation.assert_called_once()

    def test_controller_accepts_versioned_cache_as_imported_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "cache.json"
            cache_file.write_text(
                json.dumps(
                    build_cache_envelope(
                        self.data, "https://zabbix.example/api_jsonrpc.php", True
                    )
                ),
                encoding="utf-8",
            )

            loaded = Controller._load_audit_json(cache_file)

            self.assertEqual(self.data, loaded)


if __name__ == "__main__":
    unittest.main()

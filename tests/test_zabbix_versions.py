import json
import unittest
from unittest.mock import MagicMock, call, patch

from api.zabbix_api import (
    ZabbixClient,
    ZabbixVersionError,
    parse_zabbix_version,
)


class FakeResponse:
    def __init__(self, result, request_id):
        self.result = result
        self.request_id = request_id
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"jsonrpc": "2.0", "result": self.result, "id": self.request_id}


class TestVersionParsing(unittest.TestCase):
    def test_parses_numeric_components_and_ignores_release_suffix(self):
        self.assertEqual((5, 0, 42), parse_zabbix_version("5.0.42"))
        self.assertEqual((7, 4, 1), parse_zabbix_version(" 7.4.1rc1"))
        self.assertEqual((7, 4, 1), parse_zabbix_version("7.4.1beta2"))
        self.assertEqual((7, 4, 1), parse_zabbix_version("7.4.1ALPHA3"))

    def test_rejects_non_version_values(self):
        for value in (
            None,
            "",
            "release-seven",
            "7.4.",
            "7.4.1-custom",
            "7.4.1rc-candidate",
        ):
            with self.subTest(value=value), self.assertRaises(ZabbixVersionError):
                parse_zabbix_version(value)


class TestAuthenticationCompatibility(unittest.TestCase):
    def _exercise_password_auth(self, version):
        session = MagicMock()
        session.post.side_effect = [
            FakeResponse(version, 1),
            FakeResponse("session-token", 2),
            FakeResponse([], 3),
        ]
        with patch("api.zabbix_api.requests.Session", return_value=session):
            client = ZabbixClient(
                "https://zabbix.invalid", user="Admin", password="secret"
            )
            client.discover_version()
            client.authenticate()
            client.api_call("host.get", {})
        return session.post.call_args_list

    def test_zabbix_50_uses_user_and_payload_auth(self):
        calls = self._exercise_password_auth("5.0.42")
        self.assertEqual(
            {"user": "Admin", "password": "secret"}, calls[1].kwargs["json"]["params"]
        )
        self.assertEqual("session-token", calls[2].kwargs["json"]["auth"])
        self.assertNotIn("Authorization", calls[2].kwargs["headers"])

    def test_zabbix_60_uses_username_and_payload_auth(self):
        calls = self._exercise_password_auth("6.0.39")
        self.assertEqual(
            {"username": "Admin", "password": "secret"},
            calls[1].kwargs["json"]["params"],
        )
        self.assertEqual("session-token", calls[2].kwargs["json"]["auth"])

    def test_zabbix_64_uses_username_and_bearer_auth(self):
        calls = self._exercise_password_auth("6.4.18")
        self.assertEqual(
            {"username": "Admin", "password": "secret"},
            calls[1].kwargs["json"]["params"],
        )
        self.assertNotIn("auth", calls[2].kwargs["json"])
        self.assertEqual(
            "Bearer session-token", calls[2].kwargs["headers"]["Authorization"]
        )

    def test_api_token_follows_the_discovered_auth_transport(self):
        for version, expected_header in (("6.0.39", False), ("6.4.18", True)):
            with self.subTest(version=version):
                session = MagicMock()
                session.post.side_effect = [
                    FakeResponse(version, 1),
                    FakeResponse([{"userid": "1"}], 2),
                ]
                with patch("api.zabbix_api.requests.Session", return_value=session):
                    client = ZabbixClient(
                        "https://zabbix.invalid", token="synthetic-api-token"
                    )
                    client.discover_version()
                    client.authenticate()

                request = session.post.call_args_list[1].kwargs
                if expected_header:
                    self.assertEqual(
                        "Bearer synthetic-api-token",
                        request["headers"]["Authorization"],
                    )
                    self.assertNotIn("auth", request["json"])
                else:
                    self.assertEqual("synthetic-api-token", request["json"]["auth"])
                    self.assertNotIn("Authorization", request["headers"])


class VersionedClientTestCase(unittest.TestCase):
    def make_client(self, version, responses, logger=None):
        client = ZabbixClient(
            "https://zabbix.invalid", logger=logger, max_retries=0
        )
        client.api_version = version
        client.api_version_tuple = parse_zabbix_version(version)
        client.api_call = MagicMock(side_effect=responses)
        return client


class TestSuperAdminCompatibility(VersionedClientTestCase):
    def test_zabbix_50_uses_user_type_and_normalizes_alias(self):
        client = self.make_client(
            "5.0.42", [[{"alias": "root-admin", "name": "Root"}]]
        )

        result = client._collect_super_admin_summary(10)

        client.api_call.assert_called_once_with(
            "user.get", {"output": ["alias", "name"], "filter": {"type": 3}}
        )
        self.assertEqual(1, result["super_admin_users_count"])
        self.assertEqual(["root-admin"], result["super_admin_users_samples"])

    def test_zabbix_52_uses_roles_but_still_normalizes_alias(self):
        client = self.make_client(
            "5.2.7",
            [
                [{"roleid": "3"}],
                [{"alias": "root-admin", "name": "Root"}],
            ],
        )

        result = client._collect_super_admin_summary(10)

        self.assertEqual(
                call(
                    "user.get",
                    {"output": ["alias", "name"], "filter": {"roleid": ["3"]}},
            ),
            client.api_call.call_args_list[1],
        )
        self.assertEqual(["root-admin"], result["super_admin_users_samples"])

    def test_zabbix_60_uses_roles_then_roleids(self):
        client = self.make_client(
            "6.0.39",
            [
                [{"roleid": "3"}],
                [{"username": "root-admin", "name": "Root"}],
            ],
        )

        result = client._collect_super_admin_summary(10)

        self.assertEqual(
            [
                call(
                    "role.get", {"output": ["roleid"], "filter": {"type": 3}}
                ),
                call(
                    "user.get",
                    {
                        "output": ["username", "name"],
                        "filter": {"roleid": ["3"]},
                    },
                ),
            ],
            client.api_call.call_args_list,
        )
        self.assertEqual(["root-admin"], result["super_admin_users_samples"])


class TestProxyCompatibility(VersionedClientTestCase):
    def test_zabbix_64_uses_legacy_fields_and_normalizes_output(self):
        client = self.make_client(
            "6.4.18",
            [[{"host": "proxy-a", "status": "5", "lastaccess": "10", "version": "6.4"}]],
        )

        result = client._collect_proxies_summary(10)

        client.api_call.assert_called_once_with(
            "proxy.get", {"output": ["host", "status", "lastaccess", "version"]}
        )
        proxy = result["proxies_details"][0]
        self.assertEqual("proxy-a", proxy["name"])
        self.assertEqual("active", proxy["operating_mode"])
        self.assertEqual("delayed", proxy["state"])
        self.assertIsInstance(proxy["lag_seconds"], int)
        self.assertEqual("10", proxy["lastaccess"])
        self.assertEqual("6.4", proxy["version"])

    def test_zabbix_70_uses_modern_fields_and_normalizes_output(self):
        client = self.make_client(
            "7.0.12",
            [[{"name": "proxy-b", "operating_mode": "1", "lastaccess": "20", "version": "7.0"}]],
        )

        result = client._collect_proxies_summary(10)

        client.api_call.assert_called_once_with(
            "proxy.get",
            {"output": ["name", "operating_mode", "lastaccess", "version"]},
        )
        self.assertEqual("passive", result["proxies_details"][0]["operating_mode"])

    def test_zabbix_74_keeps_the_same_normalized_schema(self):
        client = self.make_client(
            "7.4.0",
            [[{"name": "proxy-c", "operating_mode": "0", "lastaccess": "30", "version": "7.4"}]],
        )

        result = client._collect_proxies_summary(10)

        self.assertEqual(
            {"name", "operating_mode", "state", "lag_seconds", "lastaccess", "version"},
            set(result["proxies_details"][0]),
        )
        self.assertEqual("active", result["proxies_details"][0]["operating_mode"])

    def test_incompatibility_is_reported_as_structured_warning(self):
        warnings = []
        client = self.make_client(
            "7.4.0", [RuntimeError("unsupported field")], warnings.append
        )

        result = client._collect_proxies_summary(10)

        self.assertEqual([], result["proxies_details"])
        warning = json.loads(warnings[0])
        self.assertEqual("zabbix_compatibility", warning["category"])
        self.assertEqual("proxies", warning["feature"])
        self.assertEqual("7.4.0", warning["version"])
        self.assertEqual([warning], client.compatibility_warnings)

    def test_incompatibility_warning_is_retained_without_a_logger(self):
        client = self.make_client("7.4.0", [RuntimeError("unsupported field")])

        client._collect_proxies_summary(10)

        self.assertEqual(1, len(client.compatibility_warnings))
        self.assertEqual("proxies", client.compatibility_warnings[0]["feature"])


if __name__ == "__main__":
    unittest.main()

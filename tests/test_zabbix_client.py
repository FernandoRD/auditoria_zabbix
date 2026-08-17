import unittest
import warnings
from unittest.mock import MagicMock, call, mock_open, patch

import requests
import urllib3

from api.zabbix_api import (
    ZabbixAPIError,
    ZabbixClient,
    ZabbixInvalidResponseError,
)
from core.controller import Controller
from core.operation import OperationCancelled, OperationContext
from core.run_config import CollectionLimits, ZabbixConfig


class FakeResponse:
    def __init__(self, body=None, status_code=200, json_error=None):
        self.body = body
        self.status_code = status_code
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self
            )

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.body


def running_operation():
    operation = OperationContext()
    operation.mark_running()
    return operation


class TestZabbixHTTPClient(unittest.TestCase):
    def test_reuses_one_session_uses_split_timeout_and_increments_ids(self):
        session = MagicMock()
        session.post.side_effect = [
            FakeResponse({"jsonrpc": "2.0", "result": [], "id": 1}),
            FakeResponse({"jsonrpc": "2.0", "result": [], "id": 2}),
        ]

        with patch("api.zabbix_api.requests.Session", return_value=session) as factory:
            client = ZabbixClient(
                "https://zabbix.invalid/api_jsonrpc.php",
                connect_timeout=3,
                read_timeout=17,
                max_retries=0,
            )
            client.api_call("host.get", {})
            client.api_call("item.get", {})

        factory.assert_called_once_with()
        self.assertEqual(2, session.post.call_count)
        sent_ids = [entry.kwargs["json"]["id"] for entry in session.post.call_args_list]
        self.assertEqual([1, 2], sent_ids)
        for entry in session.post.call_args_list:
            self.assertEqual((3, 17), entry.kwargs["timeout"])

    def test_retries_only_idempotent_calls_with_exponential_backoff(self):
        session = MagicMock()
        session.post.side_effect = [
            requests.exceptions.ReadTimeout("read timed out"),
            FakeResponse(status_code=503),
            FakeResponse({"jsonrpc": "2.0", "result": ["ok"], "id": 1}),
        ]

        with (
            patch("api.zabbix_api.requests.Session", return_value=session),
            patch("api.zabbix_api.time.sleep") as sleep,
        ):
            client = ZabbixClient(
                "https://zabbix.invalid/api_jsonrpc.php",
                max_retries=2,
                backoff_factor=0.25,
            )
            result = client.api_call("history.get", {})

        self.assertEqual(["ok"], result)
        self.assertEqual(3, session.post.call_count)
        sleep.assert_has_calls([call(0.25), call(0.5)])
        self.assertEqual(
            [1, 1, 1],
            [entry.kwargs["json"]["id"] for entry in session.post.call_args_list],
        )

    def test_does_not_retry_ambiguous_login(self):
        session = MagicMock()
        session.post.side_effect = requests.exceptions.ReadTimeout("ambiguous login")

        with patch("api.zabbix_api.requests.Session", return_value=session):
            client = ZabbixClient(
                "https://zabbix.invalid/api_jsonrpc.php",
                user="user",
                password="password",
                max_retries=5,
            )
            with self.assertRaises(ConnectionError):
                client.authenticate()

        session.post.assert_called_once()

    def test_invalid_json_and_json_rpc_error_have_distinct_exceptions(self):
        session = MagicMock()
        session.post.side_effect = [
            FakeResponse(json_error=ValueError("not json")),
            FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": "Invalid params", "data": "bad"},
                    "id": 2,
                }
            ),
        ]

        with patch("api.zabbix_api.requests.Session", return_value=session):
            client = ZabbixClient("https://zabbix.invalid", max_retries=0)
            with self.assertRaises(ZabbixInvalidResponseError):
                client.api_call("host.get", {})
            with self.assertRaises(ZabbixAPIError) as caught:
                client.api_call("item.get", {})

        self.assertEqual("item.get", caught.exception.method)
        self.assertEqual(-32602, caught.exception.error["code"])

    def test_insecure_warning_is_suppressed_only_inside_that_request(self):
        session = MagicMock()

        def response_with_warning(*args, **kwargs):
            warnings.warn("insecure", urllib3.exceptions.InsecureRequestWarning)
            return FakeResponse({"jsonrpc": "2.0", "result": [], "id": 1})

        session.post.side_effect = response_with_warning
        with patch("api.zabbix_api.requests.Session", return_value=session):
            client = ZabbixClient("https://zabbix.invalid", verify_ssl=False)
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                client.api_call("host.get", {})
                warnings.warn("outside", urllib3.exceptions.InsecureRequestWarning)

        self.assertEqual(1, len(captured))
        self.assertIn("outside", str(captured[0].message))
        self.assertFalse(session.post.call_args.kwargs["verify"])


class TestZabbixLifecycle(unittest.TestCase):
    def test_password_session_logs_out_once_and_always_closes_http_session(self):
        session = MagicMock()
        session.post.side_effect = [
            FakeResponse({"jsonrpc": "2.0", "result": "session-token", "id": 1}),
            FakeResponse({"jsonrpc": "2.0", "result": True, "id": 2}),
        ]

        with patch("api.zabbix_api.requests.Session", return_value=session):
            with ZabbixClient(
                "https://zabbix.invalid", user="user", password="password"
            ) as client:
                client.authenticate()

        methods = [entry.kwargs["json"]["method"] for entry in session.post.call_args_list]
        self.assertEqual(["user.login", "user.logout"], methods)
        session.close.assert_called_once_with()

    def test_token_session_never_logs_out_but_closes_http_session(self):
        session = MagicMock()
        session.post.return_value = FakeResponse(
            {"jsonrpc": "2.0", "result": [{"userid": "1"}], "id": 1}
        )

        with patch("api.zabbix_api.requests.Session", return_value=session):
            client = ZabbixClient("https://zabbix.invalid", token="api-token")
            client.authenticate()
            client.close()
            client.close()

        methods = [entry.kwargs["json"]["method"] for entry in session.post.call_args_list]
        self.assertEqual(["user.get"], methods)
        session.close.assert_called_once_with()

    def test_ambiguous_logout_is_not_retried_and_http_session_still_closes(self):
        session = MagicMock()
        session.post.side_effect = requests.exceptions.ReadTimeout("ambiguous logout")
        messages = []

        with patch("api.zabbix_api.requests.Session", return_value=session):
            client = ZabbixClient(
                "https://zabbix.invalid",
                user="user",
                password="password",
                logger=messages.append,
                max_retries=5,
            )
            client.auth_token = "authenticated-session"
            client.close()

        session.post.assert_called_once()
        session.close.assert_called_once_with()
        self.assertTrue(any("encerrar a sessão" in message for message in messages))


class TestControllerZabbixLifecycle(unittest.TestCase):
    def setUp(self):
        self.controller = Controller.__new__(Controller)
        self.controller.view = MagicMock()
        self.config = ZabbixConfig(
            "https://zabbix.invalid", "token", token="api-token"
        )
        self.limits = CollectionLimits(500, 15, 200, False)

    def test_connection_test_closes_client_on_success_and_failure(self):
        for failure in (None, RuntimeError("authentication failed")):
            with self.subTest(failure=failure):
                client = MagicMock()
                client.discover_version.return_value = "7.0"
                if failure:
                    client.authenticate.side_effect = failure
                with patch(
                    "core.controller.zabbix_api.ZabbixClient", return_value=client
                ):
                    self.controller._test_zabbix_flow(self.config)
                client.close.assert_called_once_with()

    def test_collection_closes_client_on_success_failure_and_cancellation(self):
        outcomes = ({"hosts": 1}, RuntimeError("collection failed"), OperationCancelled())
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                client = MagicMock()
                client.discover_version.return_value = "7.0"
                if isinstance(outcome, BaseException):
                    client.collect_data.side_effect = outcome
                else:
                    client.collect_data.return_value = outcome
                with (
                    patch("core.controller.zabbix_api.ZabbixClient", return_value=client),
                    patch("builtins.open", mock_open()),
                ):
                    if isinstance(outcome, BaseException):
                        with self.assertRaises(type(outcome)):
                            self.controller._collect_zabbix_data(
                                self.config, self.limits, False, running_operation()
                            )
                    else:
                        self.controller._collect_zabbix_data(
                            self.config, self.limits, False, running_operation()
                        )
                client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

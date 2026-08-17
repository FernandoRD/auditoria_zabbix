import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from api.zabbix_api import ZabbixClient
from api.ai_prompts import AIStreamEvent
from core.controller import Controller
from core.operation import OperationCancelled, OperationContext, OperationState
from core.run_config import (
    AIConfig,
    AnalystData,
    AuditRequest,
    CollectionLimits,
    CollectionRequest,
    ReportStyle,
    ZabbixConfig,
)


class RecordingView:
    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def _record(self, *event):
        with self._lock:
            self.events.append(event)

    def build_ai_config(self):
        return AIConfig(provider="Anthropic", auth_mode="cli")

    def update_model_list(self, models, default=None):
        self._record("models", tuple(models), default)

    def set_model_state(self, *state):
        self._record("model_state", *state)

    def set_operation_state(self, state):
        self._record("operation_state", state)

    def select_logs_tab(self):
        self._record("tab", "logs")

    def select_report_tab(self):
        self._record("tab", "report")

    def update_progress(self, value, message):
        self._record("progress", value, message)

    def log(self, message, style="info"):
        self._record("log", message, style)

    def clear_report(self):
        self._record("clear",)

    def append_report_chunk(self, chunk):
        self._record("chunk", chunk)

    def show_dialog(self, title, message, is_error=False):
        self._record("dialog", title, message, is_error)


def make_audit_request(data_file):
    return AuditRequest(
        zabbix=ZabbixConfig("https://zabbix.invalid", "token", token="secret"),
        ai=AIConfig("OpenAI", api_key="secret", model="gpt-test"),
        analyst=AnalystData(name="Analista"),
        limits=CollectionLimits(500, 15, 200, False),
        style=ReportStyle("Linha", "Padrão", "Branco", "Preto", 800, 400, "Arial"),
        data_file=str(data_file),
    )


class TestOperationContext(unittest.TestCase):
    def test_contexts_have_unique_events_ids_and_terminal_state(self):
        first = OperationContext()
        second = OperationContext()

        self.assertNotEqual(first.id, second.id)
        self.assertIsNot(first.cancel_event, second.cancel_event)
        first.mark_running()
        self.assertTrue(first.request_cancel())
        self.assertEqual(OperationState.CANCELLING, first.state)
        with self.assertRaises(OperationCancelled):
            first.raise_if_cancelled()
        first.mark_finished()
        self.assertFalse(first.request_cancel())


class TestControllerOperationIsolation(unittest.TestCase):
    def setUp(self):
        self.view = RecordingView()
        self.controller = Controller(self.view)

    def test_cancel_blocks_immediate_restart_and_drops_late_chunks(self):
        waiting = threading.Event()
        release = threading.Event()
        second_waiting = threading.Event()
        release_second = threading.Event()

        def stream(*args):
            yield "antes"
            waiting.set()
            release.wait(2)
            yield AIStreamEvent.final("stop")

        def second_stream():
            second_waiting.set()
            release_second.wait(2)
            yield "nova"
            yield AIStreamEvent.final("stop")

        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "collection.json"
            data_file.write_text(json.dumps({"hosts": 2}), encoding="utf-8")
            request = make_audit_request(data_file)
            client = MagicMock()
            client.generate_audit_report.side_effect = [stream(), second_stream()]

            with patch("core.controller.ai_api.AIClient", return_value=client):
                self.assertTrue(self.controller.start_audit(request))
                first = self.controller.active_operation
                self.assertTrue(waiting.wait(2))

                self.assertTrue(self.controller.cancel_audit())
                self.assertFalse(self.controller.start_audit(request))
                self.assertIs(first, self.controller.active_operation)
                self.assertEqual(OperationState.CANCELLING, first.state)

                release.set()
                first.thread.join(2)

                self.assertTrue(self.controller.start_audit(request))
                self.assertTrue(second_waiting.wait(2))
                second = self.controller.active_operation
                self.assertIsNotNone(second)
                self.assertNotEqual(first.id, second.id)
                release_second.set()
                second.thread.join(2)

        self.assertFalse(first.thread.is_alive())
        self.assertFalse(second.thread.is_alive())
        self.assertIsNone(self.controller.active_operation)
        chunks = [event[1] for event in self.view.events if event[0] == "chunk"]
        self.assertEqual(["antes", "nova"], chunks)
        self.assertNotIn("depois", chunks)
        states = [event[1] for event in self.view.events if event[0] == "operation_state"]
        self.assertEqual(["running", "cancelling", "idle", "running", "idle"], states)
        self.assertIn(("progress", 0, "Cancelando..."), self.view.events)
        self.assertFalse(any(event[0] == "log" and event[2] == "danger" for event in self.view.events))

    def test_stale_finally_cannot_release_a_new_operation(self):
        first = OperationContext()
        first.mark_running()
        second = OperationContext()
        second.mark_running()
        self.controller._active_operation = second

        self.controller._finish_operation(first)

        self.assertIs(second, self.controller.active_operation)
        self.assertNotIn(("operation_state", "idle"), self.view.events)

    def test_cancel_during_collection_reaches_callback_and_skips_output(self):
        collecting = threading.Event()
        callback_seen = []

        def collect_data(**kwargs):
            is_cancelled = kwargs["is_cancelled"]
            callback_seen.append(is_cancelled)
            collecting.set()
            while not is_cancelled():
                threading.Event().wait(0.01)
            raise OperationCancelled("cancelled in collection")

        zabbix = MagicMock()
        zabbix.discover_version.return_value = "7.0"
        zabbix.collect_data.side_effect = collect_data

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            request = CollectionRequest(
                zabbix=ZabbixConfig("https://zabbix.invalid", "token", token="secret"),
                limits=CollectionLimits(500, 15, 200, False),
                output_file=str(output),
            )
            with patch("core.controller.zabbix_api.ZabbixClient", return_value=zabbix):
                self.assertTrue(self.controller.start_collection_only(request))
                operation = self.controller.active_operation
                self.assertTrue(collecting.wait(2))
                self.assertTrue(self.controller.cancel_audit())
                operation.thread.join(2)

            self.assertFalse(output.exists())

        self.assertEqual(1, len(callback_seen))
        self.assertTrue(callback_seen[0]())
        self.assertIsNone(self.controller.active_operation)

    def test_cancel_during_ai_generation_reaches_provider_callback(self):
        generating = threading.Event()
        callback_seen = []

        def generate_report(*args, is_cancelled=None, **kwargs):
            callback_seen.append(is_cancelled)

            def stream():
                generating.set()
                while not is_cancelled():
                    threading.Event().wait(0.01)
                raise OperationCancelled("cancelled in provider")
                yield  # pragma: no cover - mantém a função como generator

            return stream()

        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "collection.json"
            data_file.write_text(json.dumps({"hosts": 2}), encoding="utf-8")
            request = make_audit_request(data_file)
            client = MagicMock()
            client.generate_audit_report.side_effect = generate_report

            with patch("core.controller.ai_api.AIClient", return_value=client):
                self.assertTrue(self.controller.start_audit(request))
                operation = self.controller.active_operation
                self.assertTrue(generating.wait(2))
                self.assertTrue(self.controller.cancel_audit())
                operation.thread.join(2)

        self.assertFalse(operation.thread.is_alive())
        self.assertEqual(1, len(callback_seen))
        self.assertTrue(callback_seen[0]())
        self.assertIsNone(self.controller.active_operation)
        self.assertNotIn(
            ("progress", 100, "Auditoria Concluída!"),
            self.view.events,
        )


class TestZabbixCollectionCancellation(unittest.TestCase):
    def test_collect_data_checks_cancellation_between_phases(self):
        cancelled = threading.Event()
        calls = []
        client = ZabbixClient("https://zabbix.invalid")

        def api_call(method, params, auth_required=True):
            calls.append(method)
            cancelled.set()
            return []

        client.api_call = api_call

        with self.assertRaises(OperationCancelled):
            client.collect_data(is_cancelled=cancelled.is_set)

        self.assertEqual(["host.get"], calls)


if __name__ == "__main__":
    unittest.main()

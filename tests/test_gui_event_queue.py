import json
import queue
import threading
import tempfile
import types
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
from gui.main_view import MainView


class RecordingText:
    def __init__(self, operations, main_thread):
        self.operations = operations
        self.main_thread = main_thread

    def _guard(self):
        if threading.get_ident() != self.main_thread:
            raise AssertionError("a worker acessou um widget")

    def configure(self, **kwargs):
        self._guard()

    def delete(self, start, end):
        self._guard()
        self.operations.append(("clear",))

    def insert(self, index, value, *tags):
        self._guard()
        self.operations.append(("insert", value, tags))

    def see(self, index):
        self._guard()


class RecordingNotebook:
    def __init__(self, operations, main_thread):
        self.operations = operations
        self.main_thread = main_thread

    def select(self, tab):
        if threading.get_ident() != self.main_thread:
            raise AssertionError("a worker acessou o notebook")
        self.operations.append(("tab", tab))


class RecordingButton:
    def __init__(self, name, operations, main_thread):
        self.name = name
        self.operations = operations
        self.main_thread = main_thread

    def configure(self, **kwargs):
        if threading.get_ident() != self.main_thread:
            raise AssertionError("a worker acessou um botão")
        self.operations.append(("button", self.name, kwargs["state"]))


class RecordingCombo:
    def __init__(self):
        self.values = ()
        self.value = ""

    def __setitem__(self, key, value):
        if key == "values":
            self.values = tuple(value)

    def set(self, value):
        self.value = value


class QueueHarness:
    UI_EVENT_POLL_MS = MainView.UI_EVENT_POLL_MS
    _enqueue_ui_event = MainView._enqueue_ui_event
    _consume_ui_events = MainView._consume_ui_events
    _apply_ui_event = MainView._apply_ui_event
    _close_ui_event_queue = MainView._close_ui_event_queue
    update_model_list = MainView.update_model_list
    set_model_state = MainView.set_model_state
    show_model_loading = MainView.show_model_loading
    select_logs_tab = MainView.select_logs_tab
    select_report_tab = MainView.select_report_tab
    update_progress = MainView.update_progress
    log = MainView.log
    clear_report = MainView.clear_report
    append_report_chunk = MainView.append_report_chunk
    show_dialog = MainView.show_dialog
    set_ui_state = MainView.set_ui_state
    set_operation_state = MainView.set_operation_state

    def __init__(self):
        self.main_thread = threading.get_ident()
        self.operations = []
        self.ui_event_queue = queue.Queue()
        self._ui_event_lock = threading.Lock()
        self._ui_events_closed = False
        self._model_state = "idle"
        self._model_values = ()
        self._model_load_id = 0
        self.model_combo = RecordingCombo()
        self.report_text = types.SimpleNamespace(
            text=RecordingText(self.operations, self.main_thread)
        )
        self.log_text = types.SimpleNamespace(
            text=RecordingText(self.operations, self.main_thread)
        )
        self.notebook = RecordingNotebook(self.operations, self.main_thread)
        self.start_button = RecordingButton("start", self.operations, self.main_thread)
        self.regerar_button = RecordingButton("regenerate", self.operations, self.main_thread)
        self.coletar_button = RecordingButton("collect", self.operations, self.main_thread)
        self.iniciar_de_arquivo_button = RecordingButton("from_file", self.operations, self.main_thread)
        self.test_zabbix_button = RecordingButton("test", self.operations, self.main_thread)
        self.cancel_button = RecordingButton("cancel", self.operations, self.main_thread)
        self.after_calls = []

    def after(self, delay, callback):
        if threading.get_ident() != self.main_thread:
            raise AssertionError("a worker chamou after()")
        self.after_calls.append((delay, callback))


class TestMainViewEventQueue(unittest.TestCase):
    def test_worker_publishes_clear_tab_and_chunks_in_fifo_order(self):
        view = QueueHarness()

        def publish():
            view.clear_report()
            view.select_report_tab()
            view.append_report_chunk("parte 1")
            view.append_report_chunk("parte 2")

        worker = threading.Thread(target=publish)
        worker.start()
        worker.join()

        self.assertEqual([], view.operations)
        view._consume_ui_events()

        visible_operations = [
            operation
            for operation in view.operations
            if operation[0] in {"clear", "tab", "insert"}
        ]
        self.assertEqual(
            [
                ("clear",),
                ("tab", 2),
                ("insert", "parte 1", ()),
                ("insert", "parte 2", ()),
            ],
            visible_operations,
        )
        self.assertEqual(1, len(view.after_calls))

    def test_log_style_is_applied_only_by_consumer(self):
        view = QueueHarness()

        worker = threading.Thread(target=view.log, args=("atenção", "warning"))
        worker.start()
        worker.join()

        self.assertEqual([], view.operations)
        view._consume_ui_events()

        self.assertIn(("insert", "atenção\n", ("warning",)), view.operations)

    def test_all_controller_outputs_are_plain_python_events(self):
        view = QueueHarness()
        models = ["modelo-a", "modelo-b"]

        view.update_model_list(models, "modelo-b")
        models.append("alteração tardia")
        view.show_model_loading("OpenAI")
        view.select_logs_tab()
        view.update_progress(25, "Coletando")
        view.log("mensagem", "danger")
        view.clear_report()
        view.append_report_chunk("chunk")
        view.show_dialog("Título", "Mensagem", True)
        view.set_ui_state("disabled")

        events = []
        while not view.ui_event_queue.empty():
            events.append(view.ui_event_queue.get_nowait())

        self.assertEqual(
            [
                "model_state",
                "model_state",
                "select_tab",
                "progress",
                "log",
                "clear_report",
                "report_chunk",
                "dialog",
                "ui_state",
            ],
            [event_type for event_type, _ in events],
        )
        self.assertEqual(("modelo-a", "modelo-b"), events[0][1][1])

    def test_visual_placeholder_is_never_a_selectable_model(self):
        view = QueueHarness()

        view.set_model_state("loading", (), None, "Conectando à OpenAI...", 4)
        view._consume_ui_events()

        self.assertEqual((), view.model_combo.values)
        self.assertEqual("Conectando à OpenAI...", view.model_combo.value)
        self.assertEqual("loading", view._model_state)

    def test_older_model_event_is_ignored(self):
        view = QueueHarness()

        view.set_model_state("ready", ("novo",), "novo", "", 7)
        view.set_model_state("ready", ("antigo",), "antigo", "", 6)
        view._consume_ui_events()

        self.assertEqual(("novo",), view.model_combo.values)
        self.assertEqual("novo", view.model_combo.value)

    def test_events_are_discarded_safely_after_close(self):
        view = QueueHarness()
        view.log("pendente")

        view._close_ui_event_queue()
        accepted = view._enqueue_ui_event("log", "tardio", "info")
        view._consume_ui_events()

        self.assertFalse(accepted)
        self.assertTrue(view.ui_event_queue.empty())
        self.assertEqual([], view.operations)
        self.assertEqual([], view.after_calls)

    def test_cancelling_state_keeps_start_disabled_and_disables_cancel(self):
        view = QueueHarness()

        worker = threading.Thread(target=view.set_operation_state, args=("cancelling",))
        worker.start()
        worker.join()

        self.assertEqual([], view.operations)
        view._consume_ui_events()

        self.assertIn(("button", "start", "disabled"), view.operations)
        self.assertIn(("button", "cancel", "disabled"), view.operations)


class TestControllerWorkerEventBoundary(unittest.TestCase):
    def test_audit_worker_only_publishes_events_until_main_thread_consumes(self):
        view = QueueHarness()
        controller = Controller.__new__(Controller)
        controller.view = view

        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "collection.json"
            data_file.write_text(json.dumps({"hosts": 2}), encoding="utf-8")
            request = AuditRequest(
                zabbix=ZabbixConfig("https://zabbix.invalid", "token", token="secret"),
                ai=AIConfig("OpenAI", api_key="secret", model="gpt-test"),
                analyst=AnalystData(name="Analista"),
                limits=CollectionLimits(500, 15, 200, False),
                style=ReportStyle("Linha", "Padrão", "Branco", "Preto", 800, 400, "Arial"),
                data_file=str(data_file),
            )
            client = MagicMock()
            client.generate_audit_report.return_value = iter([
                AIStreamEvent.text_chunk("um"),
                AIStreamEvent.text_chunk("dois"),
                AIStreamEvent.final("stop"),
            ])

            with patch("core.controller.ai_api.AIClient", return_value=client):
                worker = threading.Thread(target=controller.run_audit_flow, args=(request,))
                worker.start()
                worker.join()

        self.assertEqual([], view.operations)
        queued_events = list(view.ui_event_queue.queue)
        event_types = [event_type for event_type, _ in queued_events]
        clear_index = event_types.index("clear_report")
        report_tab_index = event_types.index("select_tab", clear_index)
        first_chunk_index = event_types.index("report_chunk", report_tab_index)
        second_chunk_index = event_types.index("report_chunk", first_chunk_index + 1)
        self.assertLess(clear_index, report_tab_index)
        self.assertLess(report_tab_index, first_chunk_index)
        self.assertLess(first_chunk_index, second_chunk_index)


if __name__ == "__main__":
    unittest.main()

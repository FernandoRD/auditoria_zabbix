import queue
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gui.main_view import MainView
from gui.manage_accounts_view import ManageAccountsWindow
from gui.style_settings_view import StyleSettingsWindow


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class AccountParent:
    def __init__(self, accounts, save_result=True):
        self.ai_accounts = accounts
        self.save_result = save_result
        self.operations = []

    def save_settings(self):
        self.operations.append("persist")
        return self.save_result

    def delete_ai_account_credential(self, account):
        self.operations.append(("delete", account))

    def refresh_accounts(self, account):
        self.operations.append(("refresh", account))


class AccountHarness:
    save_account = ManageAccountsWindow.save_account
    remove_account = ManageAccountsWindow.remove_account

    def __init__(self, parent, selected, new_name=None):
        self.parent = parent
        self.selected_account = Value(selected)
        account = parent.ai_accounts.get(selected, {})
        self.account_name_var = Value(new_name if new_name is not None else selected)
        self.base_provider_var = Value(account.get("provider", "OpenAI"))
        self.token_var = Value(account.get("api_key", "new-secret"))
        self.auth_mode_var = Value(account.get("auth_mode", "api_key"))
        self.model_override_var = Value(account.get("cli_model_override", ""))
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class TestAccountTransactions(unittest.TestCase):
    def test_existing_name_requires_overwrite_confirmation(self):
        accounts = {
            "Origem": {"provider": "OpenAI", "api_key": "one"},
            "Destino": {"provider": "Anthropic", "api_key": "two"},
        }
        parent = AccountParent(accounts)
        window = AccountHarness(parent, "Origem", "Destino")

        with patch(
            "gui.manage_accounts_view.Messagebox.yesno", return_value="No"
        ) as confirm:
            window.save_account()

        confirm.assert_called_once()
        self.assertEqual(accounts, parent.ai_accounts)
        self.assertEqual([], parent.operations)

    def test_rename_deletes_old_keyring_name_only_after_persistence(self):
        parent = AccountParent(
            {"Antiga": {"provider": "OpenAI", "api_key": "secret"}}
        )
        window = AccountHarness(parent, "Antiga", "Nova")

        window.save_account()

        self.assertEqual("persist", parent.operations[0])
        self.assertEqual(("delete", "Antiga"), parent.operations[1])
        self.assertIn("Nova", parent.ai_accounts)
        self.assertNotIn("Antiga", parent.ai_accounts)

    def test_failed_persistence_rolls_back_and_keeps_old_credential(self):
        original = {"Antiga": {"provider": "OpenAI", "api_key": "secret"}}
        expected = {name: dict(account) for name, account in original.items()}
        parent = AccountParent(original, save_result=False)
        window = AccountHarness(parent, "Antiga", "Nova")

        window.save_account()

        self.assertEqual(expected, parent.ai_accounts)
        self.assertEqual(["persist"], parent.operations)
        self.assertFalse(window.destroyed)

    def test_removal_requires_confirmation_and_deletes_keyring_after_save(self):
        parent = AccountParent(
            {"Conta": {"provider": "OpenAI", "api_key": "secret"}}
        )
        window = AccountHarness(parent, "Conta")

        with patch(
            "gui.manage_accounts_view.Messagebox.yesno", return_value="Yes"
        ):
            window.remove_account()

        self.assertEqual("persist", parent.operations[0])
        self.assertEqual(("delete", "Conta"), parent.operations[1])
        self.assertEqual({}, parent.ai_accounts)

    def test_keyring_credential_uses_expected_service_and_username(self):
        harness = SimpleNamespace(log=MagicMock())
        with patch("gui.main_view.keyring.delete_password") as delete:
            MainView.delete_ai_account_credential(harness, "Conta")

        delete.assert_called_once_with("AuditoriaZabbix", "Conta_api_key")


class PreviewHarness:
    PREVIEW_DEBOUNCE_MS = StyleSettingsWindow.PREVIEW_DEBOUNCE_MS
    PREVIEW_POLL_MS = StyleSettingsWindow.PREVIEW_POLL_MS
    update_preview = StyleSettingsWindow.update_preview
    _start_preview = StyleSettingsWindow._start_preview
    _consume_preview_results = StyleSettingsWindow._consume_preview_results

    def __init__(self):
        self.preview_label = MagicMock()
        self.font_var = Value("Arial, sans-serif")
        self.type_var = Value("Linha")
        self.color_var = Value("Padrão")
        self.width_var = Value(800)
        self.height_var = Value(400)
        self.bg_color_var = Value("Branco")
        self.text_color_var = Value("Preto (Padrão)")
        self.temp_preview_dir = tempfile.mkdtemp(prefix="preview_harness_")
        self._preview_results = queue.Queue()
        self._preview_generation = 0
        self._preview_debounce_id = None
        self._preview_poll_id = None
        self._preview_closed = False
        self.after_ids = []
        self.cancelled = []
        self.applied = []

    def after(self, delay, callback):
        callback_id = f"after-{len(self.after_ids) + 1}"
        self.after_ids.append((callback_id, delay, callback))
        return callback_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)

    def _render_preview_thread(self, *args):
        pass

    def _apply_preview_image(self, path):
        self.applied.append(path)


class ImmediateThread:
    def __init__(self, target, args):
        self.target = target
        self.args = args
        self.daemon = False

    def start(self):
        self.target(*self.args)


class TestPreviewCoordination(unittest.TestCase):
    def test_debounce_cancels_previous_callback_before_starting_thread(self):
        view = PreviewHarness()
        view.update_preview()
        first_id = view._preview_debounce_id
        view.update_preview()

        self.assertIn(first_id, view.cancelled)
        self.assertNotEqual(first_id, view._preview_debounce_id)

    def test_each_generation_uses_unique_file(self):
        view = PreviewHarness()
        captured = []
        view._render_preview_thread = lambda *args: captured.append(args[1])

        with patch("gui.style_settings_view.threading.Thread", ImmediateThread):
            view._start_preview()
            view._start_preview()

        self.assertEqual(2, len(set(captured)))
        self.assertTrue(captured[0].endswith("preview_1.png"))
        self.assertTrue(captured[1].endswith("preview_2.png"))

    def test_old_preview_result_is_ignored(self):
        view = PreviewHarness()
        view._preview_generation = 2
        view._preview_results.put((1, "old.png", None))
        view._preview_results.put((2, "new.png", None))

        view._consume_preview_results()

        self.assertEqual(["new.png"], view.applied)


class ExportHarness:
    _export_report_thread = MainView._export_report_thread

    def __init__(self):
        self.logs = []
        self.dialogs = []

    def log(self, message, style="info"):
        self.logs.append((message, style))

    def update_progress(self, *_args):
        pass

    def show_dialog(self, *args):
        self.dialogs.append(args)


class TestExportFeedback(unittest.TestCase):
    def test_source_pandoc_download_requires_affirmative_confirmation(self):
        harness = SimpleNamespace()
        harness.confirm_pandoc_download = MainView.confirm_pandoc_download.__get__(
            harness
        )

        with patch("gui.main_view.Messagebox.yesno", return_value="No"):
            self.assertFalse(harness.confirm_pandoc_download("Pandoc ausente."))
        with patch("gui.main_view.Messagebox.yesno", return_value="Yes"):
            self.assertTrue(harness.confirm_pandoc_download("Pandoc ausente."))

    def test_all_supported_formats_show_success(self):
        for extension in (".md", ".txt", ".docx", ".odt", ".pdf"):
            view = ExportHarness()
            with patch("gui.main_view.ReportExporter") as exporter:
                view._export_report_thread(
                    f"report{extension}", extension, "body", MagicMock(), MagicMock()
                )
            exporter.return_value.export.assert_called_once()
            self.assertEqual("Sucesso", view.dialogs[-1][0])

    def test_export_failure_logs_and_shows_error(self):
        view = ExportHarness()
        with patch("gui.main_view.ReportExporter") as exporter:
            exporter.return_value.export.side_effect = RuntimeError("falha sintética")
            view._export_report_thread(
                "report.pdf", ".pdf", "body", MagicMock(), MagicMock()
            )

        self.assertEqual("danger", view.logs[-1][1])
        self.assertTrue(view.dialogs[-1][2])


if __name__ == "__main__":
    unittest.main()

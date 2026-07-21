import unittest
from unittest.mock import MagicMock, patch

from core.controller import Controller


def make_mock_view(auth_mode="api_key", cli_model_override=""):
    view = MagicMock()
    view.get_selected_base_provider.return_value = "Anthropic"
    view.get_selected_auth_mode.return_value = auth_mode
    view.get_selected_cli_model_override.return_value = cli_model_override
    view.ai_key_var.get.return_value = ""
    return view


class TestLoadModelsAsyncCliMode(unittest.TestCase):
    def test_cli_mode_skips_network_call_and_uses_placeholder(self):
        view = make_mock_view(auth_mode="cli", cli_model_override="")
        with patch("core.controller.threading.Thread") as mock_thread:
            controller = Controller(view=view)
            view.update_model_list.reset_mock()
            mock_thread.reset_mock()

            controller.load_models_async()

        mock_thread.assert_not_called()
        view.update_model_list.assert_called_once_with(
            ["(modelo padrão da CLI)"], "(modelo padrão da CLI)"
        )

    def test_cli_mode_uses_configured_override(self):
        view = make_mock_view(auth_mode="cli", cli_model_override="opus")
        with patch("core.controller.threading.Thread"):
            controller = Controller(view=view)
            view.update_model_list.reset_mock()

            controller.load_models_async()

        view.update_model_list.assert_called_once_with(["opus"], "opus")

    def test_api_key_mode_still_starts_a_thread(self):
        view = make_mock_view(auth_mode="api_key")
        view.ai_key_var.get.return_value = "sk-fake"
        with patch("core.controller.threading.Thread") as mock_thread:
            controller = Controller(view=view)
            mock_thread.reset_mock()

            controller.load_models_async()

        mock_thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()

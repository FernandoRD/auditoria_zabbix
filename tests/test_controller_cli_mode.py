import unittest
from unittest.mock import MagicMock, patch

from core.controller import Controller
from core.run_config import AIConfig


def make_mock_view(auth_mode="api_key", cli_model_override=""):
    view = MagicMock()
    view.build_ai_config.return_value = AIConfig(
        provider="Anthropic",
        auth_mode=auth_mode,
        cli_model_override=cli_model_override,
    )
    return view


class TestLoadModelsAsyncCliMode(unittest.TestCase):
    def test_cli_mode_skips_network_call_and_uses_placeholder(self):
        view = make_mock_view(auth_mode="cli", cli_model_override="")
        with patch("core.controller.threading.Thread") as mock_thread:
            controller = Controller(view=view)
            view.set_model_state.reset_mock()
            mock_thread.reset_mock()

            controller.load_models_async(view.build_ai_config())

        mock_thread.assert_not_called()
        view.set_model_state.assert_called_once_with(
            "ready", (), None, "Modelo padrão da CLI", unittest.mock.ANY
        )

    def test_cli_mode_uses_configured_override(self):
        view = make_mock_view(auth_mode="cli", cli_model_override="opus")
        with patch("core.controller.threading.Thread"):
            controller = Controller(view=view)
            view.set_model_state.reset_mock()

            controller.load_models_async(view.build_ai_config())

        view.set_model_state.assert_called_once_with(
            "ready", ("opus",), "opus", "opus", unittest.mock.ANY
        )

    def test_api_key_mode_still_starts_a_thread(self):
        view = make_mock_view(auth_mode="api_key")
        config = AIConfig(provider="Anthropic", api_key="sk-fake")
        view.build_ai_config.return_value = config
        with patch("core.controller.threading.Thread") as mock_thread:
            controller = Controller(view=view)
            mock_thread.reset_mock()

            controller.load_models_async(config)

        mock_thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()

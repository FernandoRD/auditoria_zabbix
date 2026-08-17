import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.ai_api import AIClient
from core.controller import Controller
from core.run_config import AIConfig


class ModelView:
    def __init__(self):
        self.states = []
        self.logs = []

    def set_model_state(self, *state):
        self.states.append(state)

    def log(self, message, style="info"):
        self.logs.append((message, style))


def controller_harness():
    controller = Controller.__new__(Controller)
    controller.view = ModelView()
    controller._model_load_lock = threading.Lock()
    controller._model_load_id = 0
    return controller


class TestAnthropicModelDiscovery(unittest.TestCase):
    def test_uses_anthropic_models_list(self):
        api = MagicMock()
        api.models.list.return_value = SimpleNamespace(
            data=[SimpleNamespace(id="claude-b"), SimpleNamespace(id="claude-a")]
        )
        with patch("api.ai_api.anthropic.Anthropic", return_value=api):
            client = AIClient("Anthropic", "synthetic-key")
            models = client.get_available_models()

        api.models.list.assert_called_once_with()
        self.assertEqual(["claude-a", "claude-b"], models)
        self.assertIsNone(client.model_discovery_warning)

    def test_anthropic_failure_returns_small_labeled_fallback(self):
        with patch(
            "api.ai_api.anthropic.Anthropic",
            side_effect=RuntimeError("offline"),
        ):
            client = AIClient("Anthropic", "synthetic-key")
            models = client.get_available_models()

        self.assertEqual(list(client.ANTHROPIC_FALLBACK_MODELS), models)
        self.assertIn("fallback", client.model_discovery_warning)


class TestModelLoadState(unittest.TestCase):
    def test_old_response_after_provider_change_is_ignored(self):
        controller = controller_harness()
        controller._model_load_id = 2
        old_client = MagicMock()
        old_client.get_available_models.return_value = ["modelo-antigo"]

        with patch("core.controller.ai_api.AIClient", return_value=old_client):
            controller._fetch_and_update_models(
                AIConfig("OpenAI", api_key="key"), load_id=1
            )

        self.assertEqual([], controller.view.states)

    def test_current_failure_sets_error_without_selectable_placeholder(self):
        controller = controller_harness()
        controller._model_load_id = 3
        with patch(
            "core.controller.ai_api.AIClient",
            side_effect=ConnectionError("offline"),
        ):
            controller._fetch_and_update_models(
                AIConfig("OpenAI", api_key="key"), load_id=3
            )

        self.assertEqual(
            ("error", (), None, "Falha na conexão", 3),
            controller.view.states[-1],
        )
        self.assertEqual("warning", controller.view.logs[-1][1])

    def test_placeholders_fail_api_validation_but_cli_default_is_allowed(self):
        api = AIConfig("OpenAI", api_key="key", model="Falha na conexão")
        cli = AIConfig("Anthropic", auth_mode="cli", model="")

        self.assertIn("modelo", api.validation_error().lower())
        self.assertIsNone(cli.validation_error())


if __name__ == "__main__":
    unittest.main()

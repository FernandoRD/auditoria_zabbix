import unittest
from unittest.mock import patch

from api.ai_api import AIClient


class TestAiClientCliMode(unittest.TestCase):
    def test_get_available_models_returns_empty_in_cli_mode(self):
        client = AIClient("Anthropic", api_key="", auth_mode="cli")
        self.assertEqual(client.get_available_models(), [])

    def test_generate_audit_report_delegates_to_cli_client(self):
        client = AIClient("Anthropic", api_key="", auth_mode="cli", cli_model_override="opus")

        with patch("api.ai_api.ai_cli_client.generate_via_cli") as mock_generate:
            mock_generate.return_value = iter(["texto do relatório"])
            chunks = list(client.generate_audit_report({"host": 1}, "modelo-ignorado"))

        self.assertEqual(chunks, ["texto do relatório"])
        args, kwargs = mock_generate.call_args
        self.assertEqual(args[0], "Anthropic")
        self.assertIn("host", args[1])  # o prompt monta o JSON dos dados de auditoria
        self.assertEqual(kwargs.get("model_override") or args[2], "opus")

    def test_default_auth_mode_is_api_key(self):
        client = AIClient("Anthropic", api_key="sk-fake")
        self.assertEqual(client.auth_mode, "api_key")


if __name__ == "__main__":
    unittest.main()

import types
import unittest
from unittest.mock import MagicMock, patch

from api.ai_api import AIClient
from api.ai_prompts import AIStreamEvent


class TestProviderStreamContract(unittest.TestCase):
    def _events(self, provider):
        return list(AIClient(provider, "synthetic-key").generate_audit_report({}, "test-model"))

    def test_gemini_ignores_empty_text_and_records_stop_reason(self):
        client = MagicMock()
        client.models.generate_content_stream.return_value = [
            types.SimpleNamespace(text=None, candidates=[]),
            types.SimpleNamespace(
                text="Gemini", candidates=[types.SimpleNamespace(finish_reason="STOP")]
            ),
        ]
        with patch("api.ai_api.genai.Client", return_value=client) as mock_client:
            events = self._events("Google Gemini")

        self.assertEqual([AIStreamEvent.text_chunk("Gemini"), AIStreamEvent.final("stop")], events)
        self.assertEqual(300_000, mock_client.call_args.kwargs["http_options"].timeout)

    def test_openai_marks_length_as_partial(self):
        client = MagicMock()
        client.chat.completions.create.return_value = [
            types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="Open"), finish_reason=None)]),
            types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=None), finish_reason="length")]),
        ]
        with patch("api.ai_api.openai.OpenAI", return_value=client):
            events = self._events("OpenAI")

        self.assertEqual("Open", events[0].text)
        self.assertEqual("length", events[-1].reason)
        self.assertTrue(events[-1].partial)

    def test_anthropic_uses_configurable_limit_and_max_tokens_reason(self):
        client = MagicMock()
        client.messages.create.return_value = [
            types.SimpleNamespace(type="content_block_delta", delta=types.SimpleNamespace(text="Claude")),
            types.SimpleNamespace(type="message_delta", delta=types.SimpleNamespace(stop_reason="max_tokens")),
        ]
        audit_client = AIClient("Anthropic", "synthetic-key", anthropic_max_tokens=9000)
        with patch("api.ai_api.anthropic.Anthropic", return_value=client):
            events = list(audit_client.generate_audit_report({}, "claude-test"))

        self.assertEqual("Claude", events[0].text)
        self.assertTrue(events[-1].partial)
        self.assertEqual(9000, client.messages.create.call_args.kwargs["max_tokens"])

    def test_ollama_done_reason_and_transport_failure_both_have_terminal_events(self):
        response = MagicMock()
        response.iter_lines.return_value = [b'{"response":"Local"}', b'{"done":true,"done_reason":"stop"}']
        with patch("api.ai_api.requests.post", return_value=response):
            events = self._events("Ollama")
        self.assertEqual([AIStreamEvent.text_chunk("Local"), AIStreamEvent.final("stop")], events)
        response.close.assert_called_once()

        with patch("api.ai_api.requests.post", side_effect=TimeoutError("timeout")):
            failed_events = self._events("Ollama")
        self.assertEqual("error", failed_events[-1].reason)
        self.assertTrue(failed_events[-1].partial)
        self.assertIn("timeout", failed_events[-1].error)


if __name__ == "__main__":
    unittest.main()

import types
import unittest
from unittest.mock import MagicMock, call, patch

import requests

from api.ai_api import AIClient
from api.ai_prompts import AIStreamEvent
from core.operation import OperationCancelled


class TestAIStreamRetries(unittest.TestCase):
    def setUp(self):
        self.client = AIClient("OpenAI", "synthetic-key")

    def test_retries_initial_connection_failure_then_streams_once(self):
        stream_factory = MagicMock(
            side_effect=[
                requests.exceptions.ConnectionError("temporary network failure"),
                iter(["relatório"]),
            ]
        )

        with patch("api.ai_api.time.sleep") as sleep:
            events = list(
                self.client._stream_provider_events(
                    stream_factory,
                    lambda payload: (payload, None),
                )
            )

        self.assertEqual(
            events,
            [AIStreamEvent.text_chunk("relatório"), AIStreamEvent.final("stop")],
        )
        self.assertEqual(2, stream_factory.call_count)
        sleep.assert_called_once_with(1.0)

    def test_retry_after_header_overrides_backoff(self):
        response = MagicMock(status_code=429, headers={"Retry-After": "7"})
        rate_limited = requests.exceptions.HTTPError("too many requests", response=response)
        stream_factory = MagicMock(side_effect=[rate_limited, iter(["ok"])])

        with patch("api.ai_api.time.sleep") as sleep:
            events = list(
                self.client._stream_provider_events(
                    stream_factory,
                    lambda payload: (payload, None),
                )
            )

        self.assertEqual(
            events,
            [AIStreamEvent.text_chunk("ok"), AIStreamEvent.final("stop")],
        )
        sleep.assert_called_once_with(7.0)

    def test_transient_http_statuses_and_connection_are_retryable(self):
        for status_code in (408, 429, 500, 599):
            with self.subTest(status_code=status_code):
                response = MagicMock(status_code=status_code)
                error = requests.exceptions.HTTPError("temporary", response=response)
                self.assertTrue(self.client._is_retryable_error(error))

        self.assertTrue(
            self.client._is_retryable_error(requests.exceptions.ConnectionError("offline"))
        )

    def test_failure_after_text_is_partial_and_does_not_restart_or_duplicate(self):
        def interrupted_stream():
            yield "primeiro trecho"
            raise requests.exceptions.ConnectionError("stream interrupted")

        stream_factory = MagicMock(return_value=interrupted_stream())
        with patch("api.ai_api.time.sleep") as sleep:
            events = list(
                self.client._stream_provider_events(
                    stream_factory,
                    lambda payload: (payload, None),
                )
            )

        self.assertEqual([event.text for event in events if event.event_type == "text"], ["primeiro trecho"])
        self.assertEqual("error", events[-1].reason)
        self.assertTrue(events[-1].partial)
        self.assertEqual(1, stream_factory.call_count)
        sleep.assert_not_called()

    def test_retry_wait_honors_cancellation(self):
        stream_factory = MagicMock(
            side_effect=requests.exceptions.ConnectionError("offline")
        )
        is_cancelled = MagicMock(side_effect=[False, True])

        with patch("api.ai_api.time.sleep") as sleep:
            with self.assertRaises(OperationCancelled):
                list(
                    self.client._stream_provider_events(
                        stream_factory,
                        lambda payload: (payload, None),
                        is_cancelled=is_cancelled,
                    )
                )

        self.assertEqual(1, stream_factory.call_count)
        sleep.assert_not_called()

    def test_openai_and_anthropic_disable_their_sdk_retries(self):
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = [
            types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(content="OpenAI"),
                        finish_reason="stop",
                    )
                ]
            )
        ]
        with patch("api.ai_api.openai.OpenAI", return_value=openai_client) as factory:
            events = list(AIClient("OpenAI", "synthetic-key").generate_audit_report({}, "test"))
        self.assertEqual(AIStreamEvent.final("stop"), events[-1])
        self.assertEqual(0, factory.call_args.kwargs["max_retries"])

        anthropic_client = MagicMock()
        anthropic_client.messages.create.return_value = [
            types.SimpleNamespace(
                type="content_block_delta",
                delta=types.SimpleNamespace(text="Anthropic"),
            ),
            types.SimpleNamespace(
                type="message_delta",
                delta=types.SimpleNamespace(stop_reason="stop"),
            ),
        ]
        with patch("api.ai_api.anthropic.Anthropic", return_value=anthropic_client) as factory:
            events = list(AIClient("Anthropic", "synthetic-key").generate_audit_report({}, "test"))
        self.assertEqual(AIStreamEvent.final("stop"), events[-1])
        self.assertEqual(0, factory.call_args.kwargs["max_retries"])

    def test_gemini_and_ollama_use_the_same_initial_retry_policy(self):
        gemini_client = MagicMock()
        gemini_client.models.generate_content_stream.side_effect = [
            requests.exceptions.ConnectionError("offline"),
            [
                types.SimpleNamespace(
                    text="Gemini",
                    candidates=[types.SimpleNamespace(finish_reason="STOP")],
                )
            ],
        ]
        with (
            patch("api.ai_api.genai.Client", return_value=gemini_client) as factory,
            patch("api.ai_api.time.sleep") as sleep,
        ):
            events = list(AIClient("Google Gemini", "synthetic-key").generate_audit_report({}, "test"))
        self.assertEqual(
            events,
            [AIStreamEvent.text_chunk("Gemini"), AIStreamEvent.final("stop")],
        )
        self.assertEqual(2, factory.call_count)
        self.assertEqual(1, factory.call_args.kwargs["http_options"].retry_options.attempts)
        sleep.assert_called_once_with(1.0)

        rate_limit_response = MagicMock(status_code=429, headers={"Retry-After": "3"})
        rate_limited = requests.exceptions.HTTPError("busy", response=rate_limit_response)
        failed_response = MagicMock()
        failed_response.raise_for_status.side_effect = rate_limited
        successful_response = MagicMock()
        successful_response.iter_lines.return_value = [
            b'{"response":"Ollama"}',
            b'{"done":true,"done_reason":"stop"}',
        ]
        with (
            patch("api.ai_api.requests.post", side_effect=[failed_response, successful_response]) as post,
            patch("api.ai_api.time.sleep") as sleep,
        ):
            events = list(AIClient("Ollama", "http://localhost:11434").generate_audit_report({}, "test"))
        self.assertEqual(
            events,
            [AIStreamEvent.text_chunk("Ollama"), AIStreamEvent.final("stop")],
        )
        self.assertEqual(2, post.call_count)
        sleep.assert_has_calls([call(3.0)])


if __name__ == "__main__":
    unittest.main()

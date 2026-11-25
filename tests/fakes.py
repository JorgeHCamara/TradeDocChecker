"""Fake Anthropic API clients for tests: the real SDK with its network replaced."""

import json
from pathlib import Path

import anthropic
import httpx2

FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name: str) -> str:
    """A real API response saved in tests/fixtures/."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def replay_client(contract_json: str, invoice_json: str) -> anthropic.Anthropic:
    """Fake API that answers contract requests and invoice requests with the given JSON."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        prompt = json.loads(request.content)["messages"][0]["content"][1]["text"]
        text = contract_json if "contract" in prompt else invoice_json
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 5000, "output_tokens": 500},
            },
        )

    return anthropic.Anthropic(
        api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0
    )

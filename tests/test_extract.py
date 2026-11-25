"""Tests for checker/extract.py that run without an API key or network.

The real Anthropic SDK is used, but its HTTP transport is replaced with a fake
server, so these tests check the request we build and how we handle each kind
of response, at no cost.
"""

import json
from pathlib import Path

import anthropic
import httpx2
import pytest

from checker.extract import ExtractionError, extract
from checker.schemas import ContractExtraction

CASE = Path(__file__).parent.parent / "data" / "cases" / "case_001"


def fake_client(response_body: dict, captured: dict) -> anthropic.Anthropic:
    """An Anthropic client whose 'API' records the request and returns response_body."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = request.headers
        return httpx2.Response(200, json=response_body)

    transport = httpx2.MockTransport(handler)
    return anthropic.Anthropic(api_key="test", http_client=httpx2.Client(transport=transport), max_retries=0)


def api_response(text: str | None, stop_reason: str = "end_turn", **extra) -> dict:
    content = [{"type": "text", "text": text}] if text is not None else []
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 3000, "output_tokens": 500},
        **extra,
    }


def expected_contract_json() -> str:
    """The case_001 answer key in the shape the model returns."""
    values = json.loads((CASE / "expected.json").read_text(encoding="utf-8"))["contract"]
    return json.dumps({name: {"value": v, "source": str(v)} for name, v in values.items()})


def test_request_contains_pdf_schema_and_settings():
    captured = {}
    client = fake_client(api_response(expected_contract_json()), captured)

    extract(CASE / "contract.pdf", "contract", client=client, effort="low")

    body = captured["body"]
    document = body["messages"][0]["content"][0]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "application/pdf"
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "quantity_tolerance_percent" in json.dumps(body["output_config"]["format"]["schema"])
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in captured["headers"]["anthropic-beta"]


def test_valid_response_is_parsed():
    client = fake_client(api_response(expected_contract_json()), {})

    result = extract(CASE / "contract.pdf", "contract", client=client)

    assert isinstance(result.data, ContractExtraction)
    assert result.data.quantity.value == 60000
    assert result.data.incoterm.value == "FOB"
    # 3000 input tokens at $4/M + 500 output tokens at $20/M
    assert result.cost_usd == pytest.approx(0.022)


def test_refusal_raises():
    body = api_response(None, stop_reason="refusal", stop_details={"type": "refusal", "category": None, "explanation": None})
    client = fake_client(body, {})

    with pytest.raises(ExtractionError, match="declined"):
        extract(CASE / "contract.pdf", "contract", client=client)


def test_cut_off_response_raises():
    client = fake_client(api_response('{"contract_number": {"val', stop_reason="max_tokens"), {})

    with pytest.raises(ExtractionError):
        extract(CASE / "contract.pdf", "contract", client=client)


def test_response_not_matching_schema_raises():
    client = fake_client(api_response('{"unexpected": true}'), {})

    with pytest.raises(ExtractionError, match="schema"):
        extract(CASE / "contract.pdf", "contract", client=client)


def test_haiku_requests_have_no_fallback_setting():
    captured = {}
    body = api_response(expected_contract_json())
    body["model"] = "claude-haiku-5-5"
    client = fake_client(body, captured)

    result = extract(CASE / "contract.pdf", "contract", client=client, model="claude-haiku-5-5")

    assert "fallbacks" not in captured["body"]
    assert "server-side-fallback" not in captured["headers"].get("anthropic-beta", "")
    # 3000 input tokens at $0.10/M + 500 output tokens at $0.50/M
    assert result.cost_usd == pytest.approx(0.00055)

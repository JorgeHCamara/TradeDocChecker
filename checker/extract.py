"""Step 1 of the pipeline: read one PDF and return its fields as structured data.

The PDF goes straight to the Claude API (no text extraction on our side),
together with the schema for its document type. Structured outputs make the
API return JSON that matches the schema, and the SDK turns it into a
Pydantic object.

Run it on one file:
    python -m checker.extract data/cases/case_001/contract.pdf contract
"""

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, ValidationError

from checker.schemas import ContractExtraction, InvoiceExtraction

# Chosen with the eval (README, "Results"): Claude Haiku 5.5 at low effort scored
# the same as Claude Opus 5.5 at medium on all 30 cases, three runs in a row,
# at about 1/35th of the cost. Use --model / --effort to try other settings.
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "low"

DocType = Literal["contract", "invoice"]
SCHEMAS: dict[str, type[BaseModel]] = {
    "contract": ContractExtraction,
    "invoice": InvoiceExtraction,
}

# USD per million tokens (input, output). Check current prices before relying on these.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

SYSTEM_PROMPT = """\
You extract data from physical commodity trade documents (sales contracts and \
commercial invoices) into a fixed schema.

Rules:
- Extract only what is written in the document. Never guess, infer or calculate a value.
- If a field is not in the document, return null for both its value and its source.
- `source` must be the exact text from the document that the value was read from, \
copied character for character. Keep it short: just the words or number that hold the value.
- Numbers: plain numbers without thousands separators or currency symbols \
(e.g. "61,250.000" becomes 61250).
- Dates: YYYY-MM-DD (e.g. "22 April 2026" becomes 2026-04-22)."""


def fallback_settings(model: str) -> dict:
    """If the model declines a request, the API can retry it on a fallback model
    inside the same call. Claude Haiku models have no server-side fallback, so
    the setting is not sent to them."""
    if model.startswith("claude-haiku"):
        return {}
    return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


class ExtractionError(Exception):
    """The API answered, but not with a usable extraction."""


@dataclass
class ExtractionResult:
    data: BaseModel  # a ContractExtraction or InvoiceExtraction
    model: str  # the model that actually served the request
    input_tokens: int
    output_tokens: int
    cost_usd: float | None  # None if the model is not in PRICES
    seconds: float
    request_id: str | None  # include this when reporting API problems to Anthropic


def extract(
    pdf_path: str | Path,
    doc_type: DocType,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
) -> ExtractionResult:
    """Extract the fields of one document. Raises ExtractionError if the
    response can't be used; API errors (bad key, network) are raised as-is."""
    schema = SCHEMAS[doc_type]
    client = client or anthropic.Anthropic(max_retries=4)
    pdf_b64 = base64.standard_b64encode(Path(pdf_path).read_bytes()).decode("ascii")

    started = time.perf_counter()
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": f"Extract the fields of this {doc_type}."},
                    ],
                }
            ],
            output_format=schema,
            output_config={"effort": effort},
            **fallback_settings(model),
        )
    except ValidationError as e:
        raise ExtractionError(f"response did not match the {doc_type} schema: {e}") from e
    seconds = time.perf_counter() - started

    if response.stop_reason == "refusal":
        raise ExtractionError(f"the model declined the request ({response.stop_details})")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("the response was cut off at max_tokens")
    if response.parsed_output is None:
        raise ExtractionError("the response contained no structured output")

    usage = response.usage
    prices = PRICES.get(response.model)
    cost = (
        (usage.input_tokens * prices[0] + usage.output_tokens * prices[1]) / 1_000_000
        if prices
        else None
    )
    return ExtractionResult(
        data=response.parsed_output,
        model=response.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost,
        seconds=seconds,
        request_id=getattr(response, "_request_id", None),
    )


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()  # reads ANTHROPIC_API_KEY from .env

    parser = argparse.ArgumentParser(description="Extract fields from one trade document.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("doc_type", choices=list(SCHEMAS))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high"])
    args = parser.parse_args()

    try:
        result = extract(args.pdf, args.doc_type, model=args.model, effort=args.effort)
    except anthropic.AuthenticationError:
        print("API key rejected. Check ANTHROPIC_API_KEY in your .env file.", file=sys.stderr)
        return 1
    except (anthropic.APIError, ExtractionError) as e:
        print(f"Extraction failed: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result.data.model_dump(mode="json"), indent=2, ensure_ascii=False))
    cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "unknown"
    print(
        f"\nmodel={result.model}  tokens in/out={result.input_tokens}/{result.output_tokens}"
        f"  cost={cost}  time={result.seconds:.1f}s  request_id={result.request_id}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

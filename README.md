# Trade Document Checker

Checks a commodity trade's commercial invoice against its sales contract.
An LLM reads both PDFs and extracts the key fields; plain code then runs the
checks (quantity tolerance, price, parties, Incoterm, shipment dates) and
reports every mismatch with the text it was found in.

All documents in `data/` are fictional and were created for testing.

> Work in progress. Results, architecture and setup instructions will be added as the project develops.

## Project layout

```
checker/schemas.py      What the LLM must extract from each document type
checker/extract.py      Sends one PDF to the Claude API and returns the extracted fields
data/cases/case_NNN/    One test case: contract.pdf, invoice.pdf, expected.json (the answer key)
data/templates/         HTML sources used to generate the test PDFs
tests/                  Tests that run without API calls
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env             # then put your Anthropic API key in .env
```

## Usage

Extract the fields of one document:

```bash
python -m checker.extract data/cases/case_001/contract.pdf contract
python -m checker.extract data/cases/case_001/invoice.pdf invoice --model claude-haiku-5-5 --effort low
```

The JSON goes to stdout; model, token usage, cost and time go to stderr.

## Running the tests

```bash
pytest
```

The tests use a fake API server, so they need no API key and cost nothing.

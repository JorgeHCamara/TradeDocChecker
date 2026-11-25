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
data/cases/case_NNN/    One test case: contract.pdf, invoice.pdf, expected.json (the answer key)
data/templates/         HTML sources used to generate the test PDFs
tests/                  Tests that run without API calls
```

## Running the tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

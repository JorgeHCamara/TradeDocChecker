# Trade Document Checker

Checks a commodity trade's commercial invoice against its sales contract.
An LLM reads both PDFs and extracts the key fields; plain code then runs the
checks (quantity tolerance, price, parties, Incoterm, shipment dates) and
reports every mismatch with the text it was found in.

All documents in `data/` are fictional and were created for testing.

> Work in progress. Architecture notes and full eval results will be added as the project develops.

## How it works

```
contract.pdf ─┐
              ├─► extract (LLM, in parallel) ─► verify source quotes ─► 9 checks (code) ─► report
invoice.pdf ──┘
```

1. **Extract.** Each PDF goes to the Claude API with a schema for its document type.
   Structured outputs guarantee valid JSON. Every field comes back with the exact
   text it was read from.
2. **Verify sources.** Each quote is searched for in the PDF's own text. A value
   whose quote isn't there may be made up, so checks that use it ask for human review.
3. **Check.** Nine comparisons in plain Python: parties, commodity, contract
   reference, unit price, quantity within tolerance (with MT/KG/LB/bushel conversion),
   invoice arithmetic, Incoterm, and B/L date within the shipment period.
   Each returns PASS, FAIL or REVIEW with a one-line explanation.

Example output (case_002, where the invoiced quantity exceeds the contract tolerance):

```
PASS    seller_matches                  Cerrado Verde Grãos Ltda.
PASS    unit_price_matches              USD 412.50/MT
FAIL    quantity_within_tolerance       63,800 MT is 800 MT over the maximum. Allowed: 57,000–63,000 MT (60,000 MT ±5%)
PASS    total_is_correct                63,800 × 412.50 = 26,317,500
...
Result: ISSUES FOUND  (1 fail, 0 review, 8 pass)
```

## Early results

First live runs, Claude Opus 5.5 at effort `medium`, on the two initial test cases:

| Document | Fields correct | Source quotes found in PDF | Tokens in / out | Cost | Time |
|---|---|---|---|---|---|
| Contract (2 pages) | 14/14 | 14/14 | 6,839 / 500 | $0.037 | 9.9 s |
| Invoice (1 page) | 14/14 | 14/14 | 4,869 / 496 | $0.029 | 6.7 s |

About $0.07 per trade. The two extractions run in parallel, so a full check takes
roughly as long as the slower one. These two cases are clean and simple; the full
test set will add harder variations.

## Project layout

```
checker/schemas.py      What the LLM must extract from each document type
checker/extract.py      Sends one PDF to the Claude API and returns the extracted fields
checker/sources.py      Checks each extracted value's source quote is really in the PDF
checker/checks.py       The nine comparison checks (plain code)
checker/pipeline.py     Runs the whole check for one trade and prints the report
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

Check a trade (a folder with `contract.pdf` and `invoice.pdf`, or two files):

```bash
python -m checker.pipeline data/cases/case_002
python -m checker.pipeline --contract path/to/contract.pdf --invoice path/to/invoice.pdf
```

Extract the fields of one document:

```bash
python -m checker.extract data/cases/case_001/contract.pdf contract
python -m checker.extract data/cases/case_001/invoice.pdf invoice --model claude-haiku-5-5 --effort low
```

## Running the tests

```bash
pytest
```

The tests use a fake API server and recorded real responses (`tests/fixtures/`),
so they need no API key and cost nothing.

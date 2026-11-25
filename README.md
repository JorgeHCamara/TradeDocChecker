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
test set below adds harder variations.

## Test set

30 cases (`data/cases/`, listed in [`data/cases/INDEX.md`](data/cases/INDEX.md)):
7 trades in soybeans and corn, 3 contract layouts and 3 invoice layouts.

- **12 clean cases** that must pass. They vary the format: tolerance written as
  "+/- 10% MOLBO", dates as ISO, dd.mm.yyyy, "May 12, 2026" or "30-Oct-2026",
  Brazilian number format (65.410,750), quantities in bushels, a quantity exactly
  at the tolerance limit, company names printed differently.
- **16 cases with planted problems:** quantity over or under tolerance, wrong price,
  wrong total, wrong buyer, wrong contract reference, wrong Incoterm or port,
  wrong commodity, B/L date outside the shipment period, a contract with no
  tolerance clause, an invoice with no B/L date, and one case with two errors.

The expected check results are written by hand in each case definition, never
computed with the checks code, so a bug in the checks can't leak into the answer
keys. The generated cases found one on their first run: "Seoha Grain Corporation"
and "SEOHA GRAIN CORP." were treated as different companies.

### About the test data

Real trade documents are confidential, so the test set is synthetic: realistic
trade terms with problems planted on purpose. That is a sound way to start, and
synthetic cases stay useful for rare edge cases and as regression tests for bugs
already found. But they only test the situations someone thought of. They are
all digitally generated, with no scans, stamps, handwritten corrections,
multi-page annexes or contract addenda.

In a real deployment, the next steps would be:

1. **Real documents:** an eval set of 50–200 real contracts and invoices
   (anonymized where needed), with answers labeled by the customer's trade
   operations team.
2. **A feedback loop:** every result a user corrects, and every case the system
   sends to review, becomes a new test case. The test set then grows from real
   problems instead of guessed ones.

## Project layout

```
checker/schemas.py      What the LLM must extract from each document type
checker/extract.py      Sends one PDF to the Claude API and returns the extracted fields
checker/sources.py      Checks each extracted value's source quote is really in the PDF
checker/checks.py       The nine comparison checks (plain code)
checker/pipeline.py     Runs the whole check for one trade and prints the report
checker/evaluate.py     The eval: runs the test cases on the real API and scores them
checker/api.py          HTTP API used by the frontend (FastAPI)
frontend/               React + TypeScript web app (Vite)
data/cases/case_NNN/    One test case: contract.pdf, invoice.pdf, expected.json (the answer key)
data/cases/INDEX.md     What each test case tests
data/templates/         HTML layouts used to generate the test PDFs
scripts/generate_cases.py  Generates case_003 onward (PDFs + answer keys)
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

## Web app

A React frontend: pick one of the 30 test cases (its result is shown next to the
expected answer) or upload your own contract and invoice PDFs. The report shows
every check with its explanation, and every extracted field with the text it was
read from; values whose source couldn't be found in the PDF are flagged.

Development (two terminals):

```bash
uvicorn checker.api:app --reload          # API on http://localhost:8000
cd frontend && npm install && npm run dev  # app on http://localhost:5173
```

Production-style (one server): build the frontend once, and the API serves it.

```bash
cd frontend && npm install && npm run build && cd ..
uvicorn checker.api:app                    # app and API on http://localhost:8000
```

## Eval

The tests check the code with a fake API. The eval measures how well the whole
system performs: it runs the test cases through the real Claude API and compares
every extracted field and every check result with the answer keys.

```bash
python -m checker.evaluate --quick     # 6 hard cases, about $0.40: use while iterating
python -m checker.evaluate             # all 30 cases, about $2 on Claude Opus 5.5
python -m checker.evaluate --model claude-haiku-5-5 --effort low
python -m checker.evaluate --rescore results/<run folder>   # re-score saved outputs, free
```

Each run saves its settings (model, effort, a fingerprint of the prompt and
schemas, git commit), the raw output of every case and the scorecard to
`results/`. The most important number is **problems missed**: a planted
problem that came back PASS. A false alarm costs an analyst a few minutes; a
missed problem can mean paying for goods outside the contract.

## Running the tests

```bash
pytest
```

The tests use a fake API server and recorded real responses (`tests/fixtures/`),
so they need no API key and cost nothing.

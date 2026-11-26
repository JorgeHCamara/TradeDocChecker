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
   Scanned PDFs have no text layer, so their text is read with OCR (optional, see
   [Scanned documents](#scanned-documents)).
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

## Results

Eval on the 30 text-PDF test cases, case_001 to case_030 (see [Eval](#eval)):

| Run | Model | Effort | Fields correct | Problems caught | Missed | False alarms | Cost / trade | Full eval | Median time |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | Claude Opus 5.5 | medium | 840/840 | 19/19 | 0 | 0 of 251 | $0.057 | $1.72 | 4.7 s |
| Cheaper (run 1) | Claude Haiku 5.5 | low | 840/840 | 19/19 | 0 | 0 of 251 | $0.002 | $0.05 | 4.3 s |
| Cheaper (run 2) | Claude Haiku 5.5 | low | 840/840 | 19/19 | 0 | 0 of 251 | $0.002 | $0.05 | 4.2 s |
| Cheaper (run 3) | Claude Haiku 5.5 | low | 840/840 | 19/19 | 0 | 0 of 251 | $0.002 | $0.05 | 4.0 s |

Every field and every check matched the answer keys in every run, including the
three values that are absent from their documents: both models returned `null`
for the two missing tolerance clauses and the missing B/L date instead of
inventing them.

**Decision: Claude Haiku 5.5 at low effort is the default.** It matched Claude
Opus 5.5 in three runs out of three at about 1/35th of the cost: roughly $20
instead of $570 for 10,000 trades. Claude Sonnet 5.5 and lower-effort Opus runs
were skipped: they cost more than Haiku, and Haiku already scores perfectly, so
their results could not change the decision. Claude Opus 5.5 is still available
with `--model claude-opus-5-5`.

**Limit of this result:** both models scored 100%, so this test set cannot tell
them apart. The claim is "Haiku is as good as Opus on these documents", not
"Haiku is as good as Opus". The next step is harder documents (scans, stamps,
contract addenda; see [About the test data](#about-the-test-data)), which is
where a cheaper model would be expected to fall behind first. If it does, a
common pattern is to keep Haiku as the default and send only uncertain trades
(those that need review) to a stronger model.

On scanned invoices, see [Scanned documents](#scanned-documents): with OCR, all
planted problems are caught and nothing is missed; the remaining reviews are on
the poorest scans.

## Test set

36 cases (`data/cases/`, listed in [`data/cases/INDEX.md`](data/cases/INDEX.md)):
7 trades in soybeans and corn, 3 contract layouts and 3 invoice layouts.

- **12 clean cases** that must pass. They vary the format: tolerance written as
  "+/- 10% MOLBO", dates as ISO, dd.mm.yyyy, "May 12, 2026" or "30-Oct-2026",
  Brazilian number format (65.410,750), quantities in bushels, a quantity exactly
  at the tolerance limit, company names printed differently.
- **16 cases with planted problems:** quantity over or under tolerance, wrong price,
  wrong total, wrong buyer, wrong contract reference, wrong Incoterm or port,
  wrong commodity, B/L date outside the shipment period, a contract with no
  tolerance clause, an invoice with no B/L date, and one case with two errors.
- **6 scanned invoices** (case_031 to case_036, tagged `scanned`): image-only PDFs
  with no text layer, at three scan qualities: good (200 dpi), fair (150 dpi,
  tilted, JPEG) and poor (110 dpi, blurred, heavy compression). 3 are clean and 3
  have a planted numeric error (quantity, price, total), the kind of value a bad
  scan is most likely to garble.

The expected check results are written by hand in each case definition, never
computed with the checks code, so a bug in the checks can't leak into the answer
keys. The generated cases found one on their first run: "Seoha Grain Corporation"
and "SEOHA GRAIN CORP." were treated as different companies.

### About the test data

Real trade documents are confidential, so the test set is synthetic: realistic
trade terms with problems planted on purpose. That is a sound way to start, and
synthetic cases stay useful for rare edge cases and as regression tests for bugs
already found. But they only test the situations someone thought of. Apart from
six simulated scans they are digitally generated, with no real scans, stamps,
handwritten corrections, multi-page annexes or contract addenda.

In a real deployment, the next steps would be:

1. **Real documents:** an eval set of 50–200 real contracts and invoices
   (anonymized where needed), with answers labeled by the customer's trade
   operations team.
2. **A feedback loop:** every result a user corrects, and every case the system
   sends to review, becomes a new test case. The test set then grows from real
   problems instead of guessed ones.

## Scanned documents

A scanned invoice is a picture of a page: the PDF has no text layer. The model
can still read it, but the source-quote check needs the document's own text to
compare against. Without OCR, every quote on a scan is unverified and every
check that uses it goes to review: safe, but a person has to check everything.

With the `ocr` extra installed, scans are read with
[RapidOCR](https://github.com/RapidAI/RapidOCR) (pure `pip` install, no separate
program), in parallel with the API calls. Quotes are then matched on letters and
digits only, because OCR often drops spaces and accents ("22April 2026",
"Paranagua"). Numbers stay strict: every digit must match, a number can't match
inside a longer number, and a misread like 60,580 for 60,850 is rejected. A quote
that wraps inside a table cell may be found in up to three pieces, since OCR reads
a table row by row. On OCR text only, a quote of 10+ characters may also differ
from the page by a few letters (OCR read "Corn" as "Con", "USD/MT" as "USD/NT"),
as long as every number in it is identical.

### Results on the 6 scanned invoices

| Run | Model | Fields correct | Quotes verified (both documents) | Planted problems caught | Missed | Extra reviews (of 51 clean checks) |
|---|---|---|---|---|---|---|
| Before (no OCR) | Haiku 5.5, low | 168/168 | 84/168 | 0/3 (all 3 sent to review) | 0 | 51 |
| OCR, first version | Haiku 5.5, low | 168/168 | 159/168 | 3/3 | 0 | 12 |
| OCR, first version | Opus 5.5, medium | 168/168 | 156/168 | 2/3 (1 sent to review) | 0 | 13 |
| **OCR, current version** | Haiku 5.5, low | 168/168 | 160/168 | **3/3** | **0** | **6** |

With the current version, every good- and fair-quality scan comes out fully
correct, and all 6 remaining reviews are on the two poorest typewriter-font scans
(case_033, case_035), where OCR misreads digits. Those reviews are the system
working as intended: it can't confirm those numbers, so it hands them to a person
instead of guessing.

What these runs showed:

- **The models read the scans better than the OCR.** Both models extracted every
  field correctly, even on the poorest scans. Every review left after adding OCR
  came from the source check failing to confirm a value that was in fact correct.
  On scans, the weak part is the check, not the model.
- **Before OCR the system was safe but useless on scans:** nothing was missed, but
  every check needed a person.
- **The first OCR version still sent a good-quality scan to review.** The commodity
  description wrapped as "...in" / "bulk" (a last piece shorter than the minimum
  allowed), and on another scan OCR read "Corn" as "Con". The current version
  allows shorter pieces and a few misread letters on OCR text, with numbers still
  exact; tests cover both cases. Unnecessary reviews went from 51 (no OCR) to 12
  (first version) to 6.
- **Text PDFs were unaffected:** in the same full run, the 30 text-PDF cases still
  scored 840/840 fields, 19/19 problems and no extra reviews.

Known limits:

- On the poorest scans of the typewriter-font invoice layout (case_033, case_035),
  OCR reads some 0s as 8s and splits text into many fragments. Those values can't
  be verified, so their checks go to review. Rendering pages larger for OCR made no
  difference (24/30 key values read at 2×, 24/30 at 3×, 23/30 at 4×). The tests
  mark these as known failures.
- If the model and the OCR misread the same digit the same way, the wrong value
  would pass the source check. They read the page differently, so this is unlikely,
  but possible.
- OCR runs on the CPU and adds time: scanned cases took 10–18 s in the eval
  (several cases at once) against about 4.5 s for text PDFs.

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

To verify quotes on scanned PDFs, also install the OCR extra (about 200 MB):

```bash
pip install -e ".[dev,ocr]"
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
python -m checker.extract data/cases/case_001/invoice.pdf invoice --model claude-opus-5-5 --effort medium
```

## Web app

A React frontend: pick one of the test cases (its result is shown next to the
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
python -m checker.evaluate --quick     # 6 hard cases, about $0.01: use while iterating
python -m checker.evaluate             # all cases, about $0.002 per case on the default model
python -m checker.evaluate --tag scanned   # only the scanned invoices
python -m checker.evaluate --model claude-opus-5-5 --effort medium   # about $1.70
python -m checker.evaluate --rescore results/<run folder>   # re-score saved outputs, free
```

Each run saves its settings (model, effort, a fingerprint of the prompt and
schemas, git commit), the raw output of every case and the scorecard to
`results/`. When the cases have different tags (`text_pdf`, `scanned`), the
scorecard also shows each group separately. The most important number is **problems missed**: a planted
problem that came back PASS. A false alarm costs an analyst a few minutes; a
missed problem can mean paying for goods outside the contract.

## Running the tests

```bash
pytest
```

The tests use a fake API server and recorded real responses (`tests/fixtures/`),
so they need no API key and cost nothing.

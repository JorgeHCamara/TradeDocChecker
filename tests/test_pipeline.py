"""End-to-end tests: real PDFs and real recorded API responses, replayed
through a fake API server. Also tests the source-quote check."""

import json
from pathlib import Path

from checker.pipeline import check_trade, format_report
from checker.schemas import InvoiceExtraction
from checker.sources import pdf_text, unverified_fields
from tests.fakes import recorded, replay_client

CASE_002 = Path(__file__).parent.parent / "data" / "cases" / "case_002"


def test_case_002_end_to_end_catches_the_quantity_error():
    client = replay_client(recorded("recorded_contract.json"), recorded("recorded_invoice_case_002.json"))

    report = check_trade(CASE_002 / "contract.pdf", CASE_002 / "invoice.pdf", client=client)

    assert report.unverified == set()  # every recorded source quote is in the PDFs
    results = {c.name: c.status for c in report.checks}
    expected = json.loads((CASE_002 / "expected.json").read_text(encoding="utf-8"))["checks"]
    assert results == expected
    text = format_report(report, "case_002")
    assert "ISSUES FOUND  (1 fail, 0 review, 8 pass)" in text


def test_invented_source_is_caught():
    invoice = json.loads(recorded("recorded_invoice_case_002.json"))
    invoice["quantity"]["source"] = "62,000.000"  # not in the PDF
    extraction = InvoiceExtraction.model_validate(invoice)

    unverified = unverified_fields(extraction, pdf_text(CASE_002 / "invoice.pdf"))

    assert unverified == {"quantity"}


def test_source_quote_ignores_line_breaks():
    invoice = json.loads(recorded("recorded_invoice_case_002.json"))
    # The PDF wraps this cell across two lines; the quote has it on one.
    invoice["commodity"]["source"] = "Brazilian Yellow Soybeans, GMO, crop 2025/2026, in bulk"
    extraction = InvoiceExtraction.model_validate(invoice)

    assert unverified_fields(extraction, pdf_text(CASE_002 / "invoice.pdf")) == set()

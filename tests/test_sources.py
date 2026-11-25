"""Tests for the source-quote check: quote matching rules, text-layer vs scan
detection, and OCR on the scanned test cases. No API calls.

The OCR tests need the optional extra (pip install -e ".[ocr]") and are
skipped without it.
"""

import json
from pathlib import Path

import pytest

from checker import sources
from checker.schemas import InvoiceExtraction
from checker.sources import document_text, quote_in_text, squash, unverified_fields

CASES_DIR = Path(__file__).parent.parent / "data" / "cases"
SCANNED_CASES = ["case_031", "case_032", "case_033", "case_034", "case_035", "case_036"]


# --- Matching rules -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("22 April 2026", "22april2026"),
        ("Paranaguá, Brazil", "paranaguabrazil"),
        ("63,800.000 412.50 26,317,500.00", "63800000 41250 2631750000"),
        ("65.410,750", "65410750"),  # Brazilian number format
        ("CVG-SOY-2026-0147", "cvgsoy2026 0147"),
    ],
)
def test_squash(text, expected):
    assert squash(text) == expected


@pytest.mark.parametrize(
    "quote, document, found",
    [
        ("22 April 2026", "Invoice date:22April 2026", True),  # OCR dropped a space
        ("Cerrado Verde Grãos Ltda.", "CERRADO VERDE GRAOS LTDA", True),  # accent and case
        ("USD 26,317,500.00", "TOTAL USD26,317,500.00", True),
        ("412.50", "63,800.000 412.50 26,317,500.00", True),  # one cell of a table row
        ("63,800.000", "Quantity 63,600.000", False),  # a different digit
        ("63,800", "1,638,000", False),  # a number inside a longer number
        ("26,317,500.00", "26,317,500.001", False),
        ("21 April 2026", "Bill of Lading date 20 April 2026", False),
        ("", "anything", False),
        # A table cell that wraps: OCR puts the row's other cells in between.
        ("Brazilian Yellow Soybeans, GMO, crop 2025/2026, in bulk",
         "Brazilian Yellow Soybeans, GMO,crop\n60,850.000\n448.00\n2025/2026,inbulk", True),
        # Pieces must come in order...
        ("Brazilian Yellow Soybeans, GMO, crop 2025/2026, in bulk",
         "2025/2026,inbulk\n60,850.000\nBrazilian Yellow Soybeans, GMO,crop", False),
        # ...and a number is never assembled from pieces.
        ("60,850.000", "60,8 something else 50.000", False),
    ],
)
def test_quote_in_text(quote, document, found):
    assert quote_in_text(quote, squash(document)) is found


# --- Text layer vs scan ---------------------------------------------------------------


def test_typed_pdf_uses_its_text_layer():
    doc = document_text(CASES_DIR / "case_002" / "invoice.pdf")
    assert doc.method == "pdf_text"
    assert "63,800.000" in doc.text


def test_scan_without_ocr_has_no_text(monkeypatch):
    monkeypatch.setattr(sources, "ocr_available", lambda: False)
    doc = document_text(CASES_DIR / "case_034" / "invoice.pdf")
    assert doc.method == "none"
    assert doc.text.strip() == ""


# --- OCR on the scanned test cases ----------------------------------------------------


def realistic_invoice(case_id: str, sources_by_field: dict[str, str]) -> InvoiceExtraction:
    """The case's answer-key values with the given source quotes."""
    values = json.loads((CASES_DIR / case_id / "expected.json").read_text(encoding="utf-8"))["invoice"]
    return InvoiceExtraction.model_validate(
        {name: {"value": v, "source": sources_by_field.get(name)} for name, v in values.items()}
    )


# Known limit: on poor scans of the typewriter-font invoice layout, OCR reads
# some 0s as 8s ("51,330.580"). Those values can't be verified, so their checks
# go to review. strict=True: if OCR starts reading them, this test says so.
OCR_KNOWN_FAILURES = {"case_033", "case_035"}


@pytest.mark.parametrize(
    "case_id",
    [
        pytest.param(
            c,
            marks=pytest.mark.xfail(strict=True, reason="poor scan, typewriter font: OCR reads 0 as 8"),
        )
        if c in OCR_KNOWN_FAILURES
        else c
        for c in SCANNED_CASES
    ],
)
def test_ocr_reads_the_key_numbers_of_every_scan(case_id):
    pytest.importorskip("rapidocr_onnxruntime")
    invoice = json.loads((CASES_DIR / case_id / "expected.json").read_text(encoding="utf-8"))["invoice"]

    doc = document_text(CASES_DIR / case_id / "invoice.pdf")

    assert doc.method == "ocr"
    text = squash(doc.text)
    for printed in (
        invoice["invoice_number"],
        invoice["contract_reference"],
        f"{invoice['quantity']:,.3f}",
        f"{invoice['unit_price']:,.2f}",
        f"{invoice['total_amount']:,.2f}",
    ):
        assert quote_in_text(printed, text), f"OCR did not read {printed!r} in {case_id}"


def test_scanned_invoice_with_real_quotes_is_fully_verified():
    pytest.importorskip("rapidocr_onnxruntime")
    # The quotes a model would return for case_034, as printed on the invoice.
    invoice = realistic_invoice(
        "case_034",
        {
            "invoice_number": "RCA/INV/26/0132",
            "invoice_date": "14 June 2026",
            "contract_reference": "RCA-26-0412",
            "seller": "Rio Claro Agroexport S.A.",
            "buyer": "Seoha Grain Corporation",
            "commodity": "Brazilian Yellow Soybeans, GMO, crop 2025/2026, in bulk",
            "quantity": "60,850.000",
            "quantity_unit": "Quantity (MT)",
            "unit_price": "448.00",
            "currency": "Unit price (USD/MT)",
            "total_amount": "USD 27,260,800.00",
            "incoterm": "CFR Busan",
            "incoterm_place": "CFR Busan",
            "bill_of_lading_date": "11 June 2026",
        },
    )
    doc = document_text(CASES_DIR / "case_034" / "invoice.pdf")

    assert unverified_fields(invoice, doc.text) == set()


def test_misread_number_on_a_scan_is_not_verified():
    pytest.importorskip("rapidocr_onnxruntime")
    # As if the model had misread 60,850 as 60,580.
    invoice = realistic_invoice("case_034", {"quantity": "60,580.000", "invoice_number": "RCA/INV/26/0132"})
    doc = document_text(CASES_DIR / "case_034" / "invoice.pdf")

    unverified = unverified_fields(invoice, doc.text)

    assert "quantity" in unverified
    assert "invoice_number" not in unverified

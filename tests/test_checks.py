"""Tests for the comparison checks. Plain code, so no API involved."""

import json
from pathlib import Path

import pytest

from checker.checks import normalize_company, normalize_place, run_checks
from checker.schemas import ContractExtraction, InvoiceExtraction

CASES_DIR = Path(__file__).parent.parent / "data" / "cases"
CASE_DIRS = sorted(p for p in CASES_DIR.iterdir() if p.is_dir())


def load_expected(case: str = "case_001") -> dict:
    return json.loads((CASES_DIR / case / "expected.json").read_text(encoding="utf-8"))


def build(expected: dict, **changes) -> tuple[ContractExtraction, InvoiceExtraction]:
    """Extractions from an answer key, with optional changes such as invoice__quantity=63000."""
    values = {"contract": dict(expected["contract"]), "invoice": dict(expected["invoice"])}
    for key, value in changes.items():
        doc, field = key.split("__")
        values[doc][field] = value
    wrap = lambda v: {name: {"value": x, "source": None} for name, x in v.items()}
    return (
        ContractExtraction.model_validate(wrap(values["contract"])),
        InvoiceExtraction.model_validate(wrap(values["invoice"])),
    )


def statuses(contract, invoice, unverified=frozenset()) -> dict[str, str]:
    return {r.name: r.status for r in run_checks(contract, invoice, unverified)}


# --- Every answer key: the checks must give the expected results ---------------


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
def test_checks_match_answer_key(case_dir):
    expected = load_expected(case_dir.name)
    assert statuses(*build(expected)) == expected["checks"]


# --- Quantity tolerance ---------------------------------------------------------


@pytest.mark.parametrize(
    "invoice_qty, status",
    [
        (63000, "PASS"),  # exactly the maximum (60,000 +5%)
        (63000.5, "FAIL"),
        (57000, "PASS"),  # exactly the minimum (60,000 -5%)
        (56999.5, "FAIL"),
    ],
)
def test_tolerance_limits(invoice_qty, status):
    contract, invoice = build(load_expected(), invoice__quantity=invoice_qty)
    assert statuses(contract, invoice)["quantity_within_tolerance"] == status


def test_failure_message_explains_the_problem():
    contract, invoice = build(load_expected("case_002"))
    result = next(r for r in run_checks(contract, invoice) if r.name == "quantity_within_tolerance")
    assert result.message == (
        "63,800 MT is 800 MT over the maximum. Allowed: 57,000–63,000 MT (60,000 MT ±5%)"
    )


def test_invoice_in_bushels_is_converted():
    # 61,250 MT of soybeans in bushels (60 lb/bu), priced per bushel.
    mt_per_bushel = 60 * 0.45359237 / 1000
    bushels = 61250 / mt_per_bushel
    price_per_bushel = 412.50 * mt_per_bushel
    contract, invoice = build(
        load_expected(),
        invoice__quantity=bushels,
        invoice__quantity_unit="BU",
        invoice__unit_price=price_per_bushel,
        invoice__total_amount=bushels * price_per_bushel,
    )
    result = statuses(contract, invoice)
    assert result["quantity_within_tolerance"] == "PASS"
    assert result["unit_price_matches"] == "PASS"


def test_missing_tolerance_needs_review():
    contract, invoice = build(load_expected(), contract__quantity_tolerance_percent=None)
    assert statuses(contract, invoice)["quantity_within_tolerance"] == "REVIEW"


# --- Names, places, dates, totals -----------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("Cerrado Verde Grãos Ltda.", "CERRADO VERDE GRAOS LTDA"),
        ("Eastbridge Agri Trading Pte. Ltd.", "Eastbridge Agri Trading Pte Ltd"),
        ("Eastbridge Agri Trading Pte. Ltd.", "EASTBRIDGE AGRI TRADING"),
        ("Seoha Grain Corporation", "SEOHA GRAIN CORP."),  # found by case_030
    ],
)
def test_company_names_that_should_match(a, b):
    assert normalize_company(a) == normalize_company(b)


def test_different_buyer_fails():
    contract, invoice = build(load_expected(), invoice__buyer="Westgate Grain Pte. Ltd.")
    assert statuses(contract, invoice)["buyer_matches"] == "FAIL"


def test_place_variants_match():
    assert normalize_place("Paranaguá, Brazil") == normalize_place("PARANAGUA")


@pytest.mark.parametrize(
    "changes",
    [{"invoice__incoterm": "CIF"}, {"invoice__incoterm_place": "Santos"}],
)
def test_different_incoterm_fails(changes):
    contract, invoice = build(load_expected(), **changes)
    assert statuses(contract, invoice)["incoterm_matches"] == "FAIL"


@pytest.mark.parametrize(
    "bl_date, status",
    [("2026-04-30", "PASS"), ("2026-05-01", "FAIL"), ("2026-03-31", "FAIL")],
)
def test_bl_date(bl_date, status):
    contract, invoice = build(load_expected(), invoice__bill_of_lading_date=bl_date)
    assert statuses(contract, invoice)["bl_date_within_shipment_period"] == status


def test_wrong_total_fails():
    contract, invoice = build(load_expected(), invoice__total_amount=25265626.00)
    assert statuses(contract, invoice)["total_is_correct"] == "FAIL"


# --- Missing and unverified values ----------------------------------------------


def test_missing_value_needs_review():
    contract, invoice = build(load_expected(), invoice__seller=None)
    result = statuses(contract, invoice)
    assert result["seller_matches"] == "REVIEW"
    assert result["buyer_matches"] == "PASS"  # other checks are unaffected


def test_unverified_field_needs_review_only_where_used():
    contract, invoice = build(load_expected())
    result = statuses(contract, invoice, unverified={"invoice.quantity"})
    assert result["quantity_within_tolerance"] == "REVIEW"
    assert result["total_is_correct"] == "REVIEW"
    assert result["seller_matches"] == "PASS"

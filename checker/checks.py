"""Step 2 of the pipeline: compare the invoice against the contract.

Every check is plain code, not an LLM call, so the results are exact,
repeatable and explainable. Each check returns one of:

    PASS    the documents agree
    FAIL    the documents disagree (the message says how)
    REVIEW  a human must look: a value is missing, or its source quote was
            not found in the document (see checker/sources.py)
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Literal

from checker.schemas import CHECK_NAMES, ContractExtraction, InvoiceExtraction

Status = Literal["PASS", "FAIL", "REVIEW"]


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str


class NeedsReview(Exception):
    """Raised inside a check when it can't decide PASS or FAIL on its own."""


# --- Normalization helpers -----------------------------------------------------

# Legal-form words that don't distinguish one company from another.
COMPANY_SUFFIXES = {
    "ltda", "ltd", "limited", "pte", "plc", "inc", "incorporated", "llc",
    "corp", "corporation", "co", "company",
    "sa", "ag", "gmbh", "bv", "nv", "srl", "spa", "eireli",
}


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_company(name: str) -> str:
    """'Cerrado Verde Grãos Ltda.' and 'CERRADO VERDE GRAOS LTDA' both become 'cerrado verde graos'."""
    text = _strip_accents(name).lower().replace(".", "")
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join(w for w in words if w not in COMPANY_SUFFIXES)


def normalize_place(place: str) -> str:
    """'Paranaguá, Brazil' and 'PARANAGUA' both become 'paranagua' (the part before the first comma)."""
    return _strip_accents(place.split(",")[0]).strip().lower()


def normalize_id(identifier: str) -> str:
    return re.sub(r"\s+", "", identifier).upper()


# --- Units ---------------------------------------------------------------------

KG_PER_LB = 0.45359237
LB_PER_BUSHEL = {"soybeans": 60, "corn": 56}  # standard bushel weights


def metric_tons_per_unit(unit: str, commodity: str | None) -> float:
    if unit == "MT":
        return 1.0
    if unit == "KG":
        return 0.001
    if unit == "LB":
        return KG_PER_LB / 1000
    if unit == "BU":
        if commodity not in LB_PER_BUSHEL:
            raise NeedsReview(f"no bushel weight known for commodity '{commodity}'")
        return LB_PER_BUSHEL[commodity] * KG_PER_LB / 1000
    raise NeedsReview(f"unknown unit '{unit}'")


def fmt(number: float) -> str:
    """60000.0 -> '60,000'; 412.5 -> '412.50'; 63000.5 -> '63,000.5'"""
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.2f}" if round(number, 2) == number else f"{number:,.3f}"


# --- The checks ------------------------------------------------------------------
# Each takes (contract, invoice) and returns (status, message). The fields it
# reads are listed in CHECK_INPUTS below; run_checks() handles missing and
# unverified values before any check runs.

Outcome = tuple[Status, str]


def seller_matches(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    if normalize_company(c.seller.value) == normalize_company(i.seller.value):
        return "PASS", c.seller.value
    return "FAIL", f"Contract seller '{c.seller.value}' but invoice seller '{i.seller.value}'"


def buyer_matches(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    if normalize_company(c.buyer.value) == normalize_company(i.buyer.value):
        return "PASS", c.buyer.value
    return "FAIL", f"Contract buyer '{c.buyer.value}' but invoice buyer '{i.buyer.value}'"


def commodity_matches(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    if c.commodity.value == i.commodity.value:
        return "PASS", c.commodity.value
    return "FAIL", f"Contract is for {c.commodity.value} but invoice is for {i.commodity.value}"


def contract_reference_matches(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    if normalize_id(c.contract_number.value) == normalize_id(i.contract_reference.value):
        return "PASS", c.contract_number.value
    return (
        "FAIL",
        f"Invoice refers to contract '{i.contract_reference.value}' "
        f"but the contract number is '{c.contract_number.value}'",
    )


def unit_price_matches(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    if c.currency.value.upper() != i.currency.value.upper():
        return "FAIL", f"Contract currency {c.currency.value} but invoice currency {i.currency.value}"
    # Prices are per unit of quantity; compare them per metric ton.
    c_per_mt = c.unit_price.value / metric_tons_per_unit(c.quantity_unit.value, c.commodity.value)
    i_per_mt = i.unit_price.value / metric_tons_per_unit(i.quantity_unit.value, i.commodity.value)
    if abs(c_per_mt - i_per_mt) < 0.005:
        return "PASS", f"{c.currency.value} {fmt(c.unit_price.value)}/{c.quantity_unit.value}"
    return (
        "FAIL",
        f"Contract price {c.currency.value} {fmt(c.unit_price.value)}/{c.quantity_unit.value} "
        f"but invoice price {i.currency.value} {fmt(i.unit_price.value)}/{i.quantity_unit.value}",
    )


def quantity_within_tolerance(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    tolerance = c.quantity_tolerance_percent.value / 100
    contract_mt = c.quantity.value * metric_tons_per_unit(c.quantity_unit.value, c.commodity.value)
    invoice_mt = i.quantity.value * metric_tons_per_unit(i.quantity_unit.value, i.commodity.value)
    low, high = contract_mt * (1 - tolerance), contract_mt * (1 + tolerance)
    margin = 1e-6 * contract_mt  # absorbs floating-point noise at the exact limit

    shown = f"{fmt(i.quantity.value)} {i.quantity_unit.value}"
    if i.quantity_unit.value != "MT":
        shown += f" ({fmt(round(invoice_mt, 3))} MT)"
    allowed = (
        f"{fmt(round(low, 3))}–{fmt(round(high, 3))} MT "
        f"({fmt(c.quantity.value)} {c.quantity_unit.value} ±{fmt(c.quantity_tolerance_percent.value)}%)"
    )
    if invoice_mt > high + margin:
        return "FAIL", f"{shown} is {fmt(round(invoice_mt - high, 3))} MT over the maximum. Allowed: {allowed}"
    if invoice_mt < low - margin:
        return "FAIL", f"{shown} is {fmt(round(low - invoice_mt, 3))} MT under the minimum. Allowed: {allowed}"
    return "PASS", f"{shown} is within {allowed}"


def total_is_correct(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    calculated = i.quantity.value * i.unit_price.value
    if abs(calculated - i.total_amount.value) <= 0.01:
        return "PASS", f"{fmt(i.quantity.value)} × {fmt(i.unit_price.value)} = {fmt(i.total_amount.value)}"
    return (
        "FAIL",
        f"Invoice total {fmt(i.total_amount.value)} but {fmt(i.quantity.value)} × "
        f"{fmt(i.unit_price.value)} = {fmt(round(calculated, 2))}",
    )


def incoterm_matches(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    contract_term = f"{c.incoterm.value} {c.incoterm_place.value}"
    invoice_term = f"{i.incoterm.value} {i.incoterm_place.value}"
    if c.incoterm.value == i.incoterm.value and normalize_place(c.incoterm_place.value) == normalize_place(
        i.incoterm_place.value
    ):
        return "PASS", contract_term
    return "FAIL", f"Contract terms '{contract_term}' but invoice terms '{invoice_term}'"


def bl_date_within_shipment_period(c: ContractExtraction, i: InvoiceExtraction) -> Outcome:
    bl, start, end = i.bill_of_lading_date.value, c.shipment_start.value, c.shipment_end.value
    period = f"{start:%d %b %Y} – {end:%d %b %Y}"
    if start <= bl <= end:
        return "PASS", f"B/L date {bl:%d %b %Y} is within the shipment period {period}"
    return "FAIL", f"B/L date {bl:%d %b %Y} is outside the shipment period {period}"


# Which fields each check reads. A missing or unverified value in any of
# them turns the check into REVIEW instead of guessing.
CHECKS: dict[str, tuple[Callable[[ContractExtraction, InvoiceExtraction], Outcome], list[str]]] = {
    "seller_matches": (seller_matches, ["contract.seller", "invoice.seller"]),
    "buyer_matches": (buyer_matches, ["contract.buyer", "invoice.buyer"]),
    "commodity_matches": (commodity_matches, ["contract.commodity", "invoice.commodity"]),
    "contract_reference_matches": (
        contract_reference_matches,
        ["contract.contract_number", "invoice.contract_reference"],
    ),
    "unit_price_matches": (
        unit_price_matches,
        [
            "contract.unit_price", "contract.currency", "contract.quantity_unit", "contract.commodity",
            "invoice.unit_price", "invoice.currency", "invoice.quantity_unit", "invoice.commodity",
        ],
    ),
    "quantity_within_tolerance": (
        quantity_within_tolerance,
        [
            "contract.quantity", "contract.quantity_tolerance_percent", "contract.quantity_unit", "contract.commodity",
            "invoice.quantity", "invoice.quantity_unit", "invoice.commodity",
        ],
    ),
    "total_is_correct": (
        total_is_correct,
        ["invoice.quantity", "invoice.unit_price", "invoice.total_amount"],
    ),
    "incoterm_matches": (
        incoterm_matches,
        ["contract.incoterm", "contract.incoterm_place", "invoice.incoterm", "invoice.incoterm_place"],
    ),
    "bl_date_within_shipment_period": (
        bl_date_within_shipment_period,
        ["contract.shipment_start", "contract.shipment_end", "invoice.bill_of_lading_date"],
    ),
}
assert list(CHECKS) == CHECK_NAMES, "CHECKS must cover every name in CHECK_NAMES, in order"


def run_checks(
    contract: ContractExtraction,
    invoice: InvoiceExtraction,
    unverified: set[str] = frozenset(),
) -> list[CheckResult]:
    """Run every check. `unverified` holds qualified field names such as
    'invoice.quantity' whose source quote was not found in the document."""
    docs = {"contract": contract, "invoice": invoice}

    results = []
    for name, (check, inputs) in CHECKS.items():
        missing = [f for f in inputs if getattr(docs[f.split(".")[0]], f.split(".")[1]).value is None]
        suspect = [f for f in inputs if f in unverified]
        if missing:
            results.append(CheckResult(name, "REVIEW", f"Missing: {', '.join(missing)}"))
        elif suspect:
            results.append(
                CheckResult(name, "REVIEW", f"Source text not found in the document for: {', '.join(suspect)}")
            )
        else:
            try:
                status, message = check(contract, invoice)
            except NeedsReview as e:
                status, message = "REVIEW", str(e)[0].upper() + str(e)[1:]
            results.append(CheckResult(name, status, message))
    return results

"""What the LLM must return for each document type.

These Pydantic models do two jobs:
1. They are sent to the Claude API as the structured-output schema, so the
   response is guaranteed to be valid JSON with exactly these fields.
2. The field descriptions are instructions: the model reads them, so they
   are part of the prompt.

Every field is wrapped with its `source`: the exact text the value was read
from. The UI shows it as evidence, and the validation step checks that the
quote really appears in the document (a cheap hallucination check).
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# --- Field wrappers: a value plus the text it came from ---------------------

SOURCE_DESCRIPTION = (
    "The exact text copied from the document that this value was read from, "
    "character for character. null if the value is not in the document."
)


class TextField(BaseModel):
    value: str | None
    source: str | None = Field(description=SOURCE_DESCRIPTION)


class NumberField(BaseModel):
    value: float | None
    source: str | None = Field(description=SOURCE_DESCRIPTION)


class DateField(BaseModel):
    value: date | None
    source: str | None = Field(description=SOURCE_DESCRIPTION)


class UnitField(BaseModel):
    value: Literal["MT", "KG", "LB", "BU"] | None = Field(
        description="MT = metric tons, KG = kilograms, LB = pounds, BU = bushels."
    )
    source: str | None = Field(description=SOURCE_DESCRIPTION)


class CommodityField(BaseModel):
    value: Literal["soybeans", "corn", "other"] | None = Field(
        description="The commodity category, whatever words the document uses for it."
    )
    source: str | None = Field(description=SOURCE_DESCRIPTION)


Incoterm = Literal["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"]


class IncotermField(BaseModel):
    value: Incoterm | None = Field(description="The Incoterms 2020 code only, e.g. FOB.")
    source: str | None = Field(description=SOURCE_DESCRIPTION)


# --- Document schemas ---------------------------------------------------------


class ContractExtraction(BaseModel):
    contract_number: TextField
    contract_date: DateField
    seller: TextField = Field(description="Seller's company name exactly as written.")
    buyer: TextField = Field(description="Buyer's company name exactly as written.")
    commodity: CommodityField
    quantity: NumberField = Field(description="The base contract quantity, without tolerance.")
    quantity_unit: UnitField
    quantity_tolerance_percent: NumberField = Field(
        description="The 'more or less' tolerance as a percentage, e.g. 5 for '5% more or less'."
    )
    unit_price: NumberField = Field(description="Price per unit of quantity.")
    currency: TextField = Field(description="ISO currency code, e.g. USD.")
    incoterm: IncotermField
    incoterm_place: TextField = Field(description="The port or place named with the Incoterm.")
    shipment_start: DateField = Field(description="First day of the shipment period.")
    shipment_end: DateField = Field(description="Last day of the shipment period.")


class InvoiceExtraction(BaseModel):
    invoice_number: TextField
    invoice_date: DateField
    contract_reference: TextField = Field(description="The contract number this invoice refers to.")
    seller: TextField = Field(description="Seller's company name exactly as written.")
    buyer: TextField = Field(description="Buyer's company name exactly as written.")
    commodity: CommodityField
    quantity: NumberField = Field(description="The quantity invoiced.")
    quantity_unit: UnitField
    unit_price: NumberField = Field(description="Price per unit of quantity.")
    currency: TextField = Field(description="ISO currency code, e.g. USD.")
    total_amount: NumberField = Field(description="The total amount due, as printed. Do not calculate it.")
    incoterm: IncotermField
    incoterm_place: TextField = Field(description="The port or place named with the Incoterm.")
    bill_of_lading_date: DateField


# The names of the checks, in the order the report shows them.
CHECK_NAMES = [
    "seller_matches",
    "buyer_matches",
    "commodity_matches",
    "contract_reference_matches",
    "unit_price_matches",
    "quantity_within_tolerance",
    "total_is_correct",
    "incoterm_matches",
    "bl_date_within_shipment_period",
]

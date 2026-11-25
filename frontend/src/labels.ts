// Human-readable names for the API's check and field names.

export const CHECK_LABELS: Record<string, string> = {
  seller_matches: "Seller matches",
  buyer_matches: "Buyer matches",
  commodity_matches: "Commodity matches",
  contract_reference_matches: "Invoice refers to this contract",
  unit_price_matches: "Unit price matches",
  quantity_within_tolerance: "Quantity within tolerance",
  total_is_correct: "Invoice total is correct",
  incoterm_matches: "Incoterm and place match",
  bl_date_within_shipment_period: "B/L date within shipment period",
};

export const FIELD_LABELS: Record<string, string> = {
  contract_number: "Contract number",
  contract_date: "Contract date",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  contract_reference: "Contract reference",
  seller: "Seller",
  buyer: "Buyer",
  commodity: "Commodity",
  quantity: "Quantity",
  quantity_unit: "Unit",
  quantity_tolerance_percent: "Tolerance (%)",
  unit_price: "Unit price",
  currency: "Currency",
  total_amount: "Total amount",
  incoterm: "Incoterm",
  incoterm_place: "Incoterm place",
  shipment_start: "Shipment from",
  shipment_end: "Shipment to",
  bill_of_lading_date: "B/L date",
};

export function formatValue(value: string | number | null): string {
  if (value === null) return "—";
  if (typeof value === "number") return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
  return value;
}

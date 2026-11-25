# Test cases

case_001 and case_002 were made by hand; case_003 onward by `scripts/generate_cases.py`.

| Case | Commodity | Contract layout | Invoice layout | What it tests | Expected non-PASS checks |
|---|---|---|---|---|---|
| case_001 | soybeans | a | a | Clean baseline. | – |
| case_002 | soybeans | a | a | 63,800 MT exceeds the maximum of 63,000 MT. | quantity_within_tolerance: FAIL |
| case_003 | soybeans | b | b | Clean. CFR contract in confirmation layout, tolerance written as '+/- 10% MOLBO'. | – |
| case_004 | soybeans | b | b | 61,200 MT exceeds the maximum of 60,500 MT (55,000 +10%). | quantity_within_tolerance: FAIL |
| case_005 | corn | c | c | Clean. Corn, letter-style contract, ISO dates, bilingual invoice. | – |
| case_006 | corn | c | a | B/L dated 03 Sep 2026, after the shipment period ends on 31 Aug 2026. | bl_date_within_shipment_period: FAIL |
| case_007 | corn | a | a | Clean. Invoice uses Brazilian number format (65.410,750). | – |
| case_008 | corn | a | b | Invoice price USD 213.75/MT, contract price USD 212.75/MT. | unit_price_matches: FAIL |
| case_009 | soybeans | b | c | Clean. Dates as dd.mm.yyyy; tolerance only 2%. | – |
| case_010 | soybeans | b | a | 29,150 MT is below the minimum of 29,400 MT (30,000 -2%). | quantity_within_tolerance: FAIL |
| case_011 | soybeans | c | b | Contract has no tolerance clause, so the quantity check needs review. | quantity_within_tolerance: REVIEW |
| case_012 | soybeans | c | a | Invoice made out to a different buyer (Westgate Grain); contract has no tolerance clause. | buyer_matches: FAIL, quantity_within_tolerance: REVIEW |
| case_013 | corn | a | c | Clean. Corn CFR, dd-Mon-yyyy dates, Brazilian number format. | – |
| case_014 | corn | a | a | Invoice says FOB Paranaguá; contract is CFR Busan. | incoterm_matches: FAIL |
| case_015 | soybeans | b | a | Clean. Seller name printed as 'CERRADO VERDE GRAOS LTDA' (same company, no accent). | – |
| case_016 | soybeans | b | b | Invoice refers to contract CVG-SOY-2026-0320 (digits swapped). | contract_reference_matches: FAIL |
| case_017 | soybeans | b | c | Invoice total has a typo: 30,000 more than quantity × price. | total_is_correct: FAIL |
| case_018 | corn | a | c | Invoice says FOB Paranaguá; contract is FOB Santos. | incoterm_matches: FAIL |
| case_019 | soybeans | b | a | B/L dated May 12, before the shipment period starts on May 15. US date format. | bl_date_within_shipment_period: FAIL |
| case_020 | corn | c | b | Invoice is for soybeans; the contract is for corn. | commodity_matches: FAIL |
| case_021 | soybeans | b | a | Clean. Invoice quantity and price in bushels (unit conversion test). | – |
| case_022 | soybeans | b | a | Invoice in bushels; equals 64,100 MT, over the maximum of 63,000 MT. | quantity_within_tolerance: FAIL |
| case_023 | corn | a | b | Two errors: price USD 248.00 vs 246.00, and 55,600 MT over the maximum of 55,000 MT. | unit_price_matches: FAIL, quantity_within_tolerance: FAIL |
| case_024 | corn | a | c | Invoice does not show the B/L date, so that check needs review. | bl_date_within_shipment_period: REVIEW |
| case_025 | soybeans | b | c | Clean. Bilingual invoice with Brazilian number format. | – |
| case_026 | corn | c | a | Clean. Quantity exactly at the maximum (45,000 +5% = 47,250 MT). | – |
| case_027 | corn | a | b | Clean. US date format. | – |
| case_028 | corn | c | c | Invoice total is 10.00 higher than quantity × price. | total_is_correct: FAIL |
| case_029 | soybeans | b | b | Clean. B/L on the last day of the shipment period. | – |
| case_030 | soybeans | b | a | Clean. Buyer printed as 'SEOHA GRAIN CORP.' (same company as Seoha Grain Corporation). | – |

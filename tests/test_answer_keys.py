"""Checks that every answer key is well-formed.

A typo in an answer key would silently corrupt every eval score, so each
expected.json must use exactly the schema's field names and valid values.
These tests make no API calls.
"""

import json
from pathlib import Path

import pytest

from checker.schemas import CHECK_NAMES, ContractExtraction, InvoiceExtraction

CASES_DIR = Path(__file__).parent.parent / "data" / "cases"
CASE_DIRS = sorted(p for p in CASES_DIR.iterdir() if p.is_dir())


def as_extraction(values: dict) -> dict:
    """Wrap plain answer-key values in the {value, source} shape the schemas use."""
    return {name: {"value": value, "source": None} for name, value in values.items()}


def test_cases_exist():
    assert CASE_DIRS, f"no test cases found in {CASES_DIR}"


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
def test_case_has_all_files(case_dir):
    for name in ("contract.pdf", "invoice.pdf", "expected.json"):
        assert (case_dir / name).is_file(), f"{case_dir.name} is missing {name}"


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
def test_answer_key_matches_schemas(case_dir):
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))

    assert expected["case_id"] == case_dir.name
    assert set(expected["contract"]) == set(ContractExtraction.model_fields)
    assert set(expected["invoice"]) == set(InvoiceExtraction.model_fields)

    # Raises if any value has the wrong type (e.g. a bad date or unit).
    ContractExtraction.model_validate(as_extraction(expected["contract"]))
    InvoiceExtraction.model_validate(as_extraction(expected["invoice"]))

    assert set(expected["checks"]) == set(CHECK_NAMES)
    assert set(expected["checks"].values()) <= {"PASS", "FAIL"}

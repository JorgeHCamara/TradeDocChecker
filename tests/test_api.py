"""Tests for the HTTP API, using a fake Claude client (no key, no cost)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from checker.api import app, get_client
from tests.fakes import recorded, replay_client

CASE_002 = Path(__file__).parent.parent / "data" / "cases" / "case_002"


@pytest.fixture
def api():
    fake = replay_client(recorded("recorded_contract.json"), recorded("recorded_invoice_case_002.json"))
    app.dependency_overrides[get_client] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_cases(api):
    cases = api.get("/api/cases").json()
    assert len(cases) == 30
    assert cases[1] == {
        "id": "case_002",
        "description": cases[1]["description"],
        "commodity": "soybeans",
        "expected_issues": 1,
    }


def test_check_case_returns_report_and_expected_results(api):
    body = api.post("/api/cases/case_002/check").json()

    assert body["verdict"] == "ISSUES FOUND"
    assert body["counts"] == {"FAIL": 1, "REVIEW": 0, "PASS": 8}
    failed = [c for c in body["checks"] if c["status"] == "FAIL"]
    assert [c["name"] for c in failed] == ["quantity_within_tolerance"]
    assert body["invoice"]["quantity"] == {"value": 63800.0, "source": "63,800.000", "verified": True}
    assert body["contract"]["shipment_start"]["value"] == "2026-04-01"
    assert body["expected"]["checks"]["quantity_within_tolerance"] == "FAIL"


def test_upload_check(api):
    files = {
        "contract": ("contract.pdf", (CASE_002 / "contract.pdf").read_bytes(), "application/pdf"),
        "invoice": ("invoice.pdf", (CASE_002 / "invoice.pdf").read_bytes(), "application/pdf"),
    }
    body = api.post("/api/check", files=files).json()

    assert body["verdict"] == "ISSUES FOUND"
    assert "expected" not in body


def test_upload_rejects_non_pdf(api):
    files = {
        "contract": ("contract.pdf", b"not a pdf", "application/pdf"),
        "invoice": ("invoice.pdf", (CASE_002 / "invoice.pdf").read_bytes(), "application/pdf"),
    }
    response = api.post("/api/check", files=files)

    assert response.status_code == 400
    assert "not a PDF" in response.json()["detail"]


@pytest.mark.parametrize("case_id", ["case_999", "../checker", "case_1"])
def test_unknown_case_is_404(api, case_id):
    assert api.post(f"/api/cases/{case_id}/check").status_code == 404


def test_case_pdf_is_served(api):
    response = api.get("/api/cases/case_002/invoice.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")

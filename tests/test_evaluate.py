"""Tests for the eval's scoring and its run/save/rescore flow. No real API calls."""

import json
from pathlib import Path

import pytest

from checker.evaluate import field_matches, run_eval, score_run, write_scores
from tests.fakes import recorded, replay_client

CASES_DIR = Path(__file__).parent.parent / "data" / "cases"


def expected_for(case_id: str) -> dict:
    return json.loads((CASES_DIR / case_id / "expected.json").read_text(encoding="utf-8"))


def perfect_output(case_id: str) -> dict:
    """A saved case output that matches the answer key exactly."""
    exp = expected_for(case_id)
    doc = lambda values: {n: {"value": v, "source": str(v), "verified": True} for n, v in values.items()}
    return {
        "case_id": case_id,
        "error": None,
        "report": {
            "verdict": "x",
            "contract": doc(exp["contract"]),
            "invoice": doc(exp["invoice"]),
            "checks": [{"name": n, "status": s, "message": ""} for n, s in exp["checks"].items()],
            "model": "claude-opus-5-5",
            "cost_usd": 0.07,
            "seconds": 10.0,
        },
    }


def save_run(tmp_path: Path, outputs: list[dict]) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "cases").mkdir(parents=True)
    for o in outputs:
        (run_dir / "cases" / f"{o['case_id']}.json").write_text(json.dumps(o), encoding="utf-8")
    config = {"model": "m", "effort": "medium", "cases": [o["case_id"] for o in outputs],
              "prompt_version": "p", "git_commit": "c"}
    (run_dir / "run.json").write_text(json.dumps(config), encoding="utf-8")
    return run_dir


def set_check(output: dict, name: str, status: str) -> None:
    next(c for c in output["report"]["checks"] if c["name"] == name)["status"] = status


# --- Field comparison rules -------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected, actual, ok",
    [
        ("quantity", 60000, 60000.0, True),
        ("quantity", 60000, 63000.0, False),
        ("quantity_tolerance_percent", None, None, True),
        ("quantity_tolerance_percent", None, 5.0, False),  # invented a tolerance
        ("incoterm_place", "Paranaguá", "Paranaguá, Brazil", True),
        ("buyer", "SEOHA GRAIN CORP.", "Seoha Grain Corp", True),
        ("buyer", "Eastbridge Agri Trading Pte. Ltd.", "Westgate Grain Pte. Ltd.", False),
        ("contract_reference", "PLN/C/2026/118", "PLN/C/2026/118 ", True),
        ("bill_of_lading_date", "2026-03-31", "2026-03-13", False),
        ("quantity_unit", "BU", "BU", True),
    ],
)
def test_field_matches(name, expected, actual, ok):
    assert field_matches(name, expected, actual) is ok


# --- Scoring ----------------------------------------------------------------------


def test_perfect_run_scores_perfectly(tmp_path):
    run = save_run(tmp_path, [perfect_output(c) for c in ("case_001", "case_002", "case_011")])
    s = score_run(run)
    assert s["fields"]["correct"] == s["fields"]["total"] == 84
    assert s["checks"]["problems_total"] == 2  # case_002 FAIL + case_011 REVIEW
    assert s["checks"]["problems_caught"] == 2
    assert s["checks"]["problems_missed"] == []
    assert s["cases_fully_correct"] == 3
    assert s["cost_usd_total"] == pytest.approx(0.21)


def test_problem_that_passes_counts_as_missed(tmp_path):
    out = perfect_output("case_002")
    set_check(out, "quantity_within_tolerance", "PASS")
    s = score_run(save_run(tmp_path, [out]))
    assert s["checks"]["problems_missed"] == [
        {"case": "case_002", "check": "quantity_within_tolerance", "expected": "FAIL", "got": "PASS"}
    ]


def test_review_instead_of_fail_is_flagged_not_missed(tmp_path):
    out = perfect_output("case_002")
    set_check(out, "quantity_within_tolerance", "REVIEW")
    s = score_run(save_run(tmp_path, [out]))
    assert s["checks"]["problems_missed"] == []
    assert len(s["checks"]["problems_flagged_differently"]) == 1


def test_false_alarm_and_extra_review(tmp_path):
    out = perfect_output("case_001")
    set_check(out, "seller_matches", "FAIL")
    set_check(out, "buyer_matches", "REVIEW")
    s = score_run(save_run(tmp_path, [out]))
    assert [d["check"] for d in s["checks"]["false_alarms"]] == ["seller_matches"]
    assert [d["check"] for d in s["checks"]["extra_reviews"]] == ["buyer_matches"]


def test_wrong_field_and_unverified_source_are_counted(tmp_path):
    out = perfect_output("case_001")
    out["report"]["invoice"]["quantity"] = {"value": 61520.0, "source": "61,520.000", "verified": False}
    s = score_run(save_run(tmp_path, [out]))
    assert s["fields"]["wrong"] == [
        {"case": "case_001", "field": "invoice.quantity", "expected": 61250, "got": 61520.0}
    ]
    assert s["fields"]["by_field"]["invoice.quantity"] == [0, 1]
    assert s["sources"]["verified"] == s["sources"]["total"] - 1


def test_errored_case_is_reported_not_scored(tmp_path):
    error = {"case_id": "case_003", "report": None, "error": "APIStatusError: overloaded"}
    s = score_run(save_run(tmp_path, [perfect_output("case_001"), error]))
    assert s["errors"] == {"case_003": "APIStatusError: overloaded"}
    assert s["cases_run"] == 1


# --- Full flow with a fake API: run, save, rescore --------------------------------


def test_run_eval_saves_outputs_and_rescore_matches(tmp_path):
    client = replay_client(recorded("recorded_contract.json"), recorded("recorded_invoice_case_002.json"))

    run_dir = run_eval(["case_002"], client=client, results_dir=tmp_path, workers=1)

    assert (run_dir / "cases" / "case_002.json").is_file()
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    assert scores["checks"]["problems_caught"] == 1
    assert scores["checks"]["problems_missed"] == []
    # The recorded contract says "Paranaguá, Brazil"; the answer key says "Paranaguá": still correct.
    assert scores["fields"]["wrong"] == []
    scorecard = (run_dir / "scorecard.txt").read_text(encoding="utf-8")
    assert "Problems MISSED         0" in scorecard

    # Rescoring the saved outputs gives the same result, with no API calls.
    assert write_scores(run_dir) + "\n" == scorecard

"""Eval: run the real system on the test cases and score it against the answer keys.

    python -m checker.evaluate                       # all cases (about $0.002 per case on the default, Claude Haiku 5.5)
    python -m checker.evaluate --quick               # 6 hard cases (about $0.01)
    python -m checker.evaluate --cases case_007 case_013
    python -m checker.evaluate --tag scanned                # only cases with that tag
    python -m checker.evaluate --model claude-opus-5-5 --effort medium   # about $1.70
    python -m checker.evaluate --rescore results/<run folder>   # score saved outputs again: no API calls

Every run is saved to results/<time>_<model>_<effort>/:
    run.json         settings: model, effort, cases, prompt version, git commit
    cases/*.json     the raw output for each case (what the API run cost money to get)
    scores.json      the scores
    scorecard.txt    the scorecard printed at the end

Unlike the tests in tests/, this makes real API calls and costs money.
"""

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic

from checker.checks import normalize_company, normalize_id, normalize_place
from checker.extract import DEFAULT_EFFORT, DEFAULT_MODEL, SYSTEM_PROMPT, ExtractionError
from checker.pipeline import check_trade, report_to_dict
from checker.schemas import ContractExtraction, InvoiceExtraction

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "data" / "cases"
RESULTS_DIR = ROOT / "results"

# Hard cases for quick iterations: Brazilian number format, no tolerance clause,
# dd-Mon-yyyy dates, bushels, two planted errors, a company name variant.
QUICK_CASES = ["case_007", "case_011", "case_013", "case_021", "case_023", "case_030"]


# --- Comparing one extracted field with the answer key ----------------------------


def field_matches(name: str, expected, actual) -> bool:
    """Is an extracted value correct? Exact for numbers, dates and codes; tolerant
    where two spellings mean the same thing (company names, places, IDs)."""
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and abs(expected - actual) <= 1e-6 * max(1.0, abs(expected))
    if name in ("seller", "buyer"):
        return normalize_company(actual) == normalize_company(expected)
    if name == "incoterm_place":
        return normalize_place(actual) == normalize_place(expected)
    if name in ("contract_number", "invoice_number", "contract_reference"):
        return normalize_id(actual) == normalize_id(expected)
    return str(actual).strip().casefold() == str(expected).strip().casefold()


# --- Scoring --------------------------------------------------------------------------


def score_case(expected: dict, report: dict) -> dict:
    """Compare one case's report with its answer key."""
    wrong_fields = []
    fields_total = sources_total = sources_verified = 0
    for doc in ("contract", "invoice"):
        for name, exp_value in expected[doc].items():
            got = report[doc][name]
            fields_total += 1
            if not field_matches(name, exp_value, got["value"]):
                wrong_fields.append({"field": f"{doc}.{name}", "expected": exp_value, "got": got["value"]})
            if got["value"] is not None:
                sources_total += 1
                sources_verified += got["verified"]

    actual = {c["name"]: c["status"] for c in report["checks"]}
    check_diffs = [
        {"check": name, "expected": exp, "got": actual[name]}
        for name, exp in expected["checks"].items()
        if actual[name] != exp
    ]
    return {
        "fields_total": fields_total,
        "wrong_fields": wrong_fields,
        "sources_total": sources_total,
        "sources_verified": sources_verified,
        "checks_total": len(expected["checks"]),
        "check_diffs": check_diffs,
        "problems": [name for name, exp in expected["checks"].items() if exp != "PASS"],
    }


def case_tags(case_id: str) -> list[str]:
    """A case's tags from its answer key; cases without tags are plain text PDFs."""
    expected = json.loads((CASES_DIR / case_id / "expected.json").read_text(encoding="utf-8"))
    return expected.get("tags") or ["text_pdf"]


def aggregate(per_case: dict[str, dict], costs: dict[str, float], seconds: dict[str, float]) -> dict:
    """Add up the per-case scores of a group of cases."""
    caught, flagged_differently, missed = [], [], []
    false_alarms, extra_reviews = [], []
    by_field: dict[str, list[int]] = {}
    for case_id, s in per_case.items():
        diffs = {d["check"]: d for d in s["check_diffs"]}
        # Planted problems: checks whose expected result is FAIL or REVIEW.
        for name in s["problems"]:
            if name not in diffs:
                caught.append(f"{case_id}.{name}")
            elif diffs[name]["got"] == "PASS":
                missed.append({"case": case_id, **diffs[name]})  # the dangerous outcome
            else:
                flagged_differently.append({"case": case_id, **diffs[name]})
        for d in s["check_diffs"]:
            if d["expected"] == "PASS" and d["got"] == "FAIL":
                false_alarms.append({"case": case_id, **d})
            elif d["expected"] == "PASS" and d["got"] == "REVIEW":
                extra_reviews.append({"case": case_id, **d})
        wrong = {w["field"] for w in s["wrong_fields"]}
        for doc, model in (("contract", ContractExtraction), ("invoice", InvoiceExtraction)):
            for name in model.model_fields:
                key = f"{doc}.{name}"
                counts = by_field.setdefault(key, [0, 0])
                counts[0] += key not in wrong
                counts[1] += 1

    case_costs = [costs[c] for c in per_case if c in costs]
    case_seconds = [seconds[c] for c in per_case if c in seconds]
    return {
        "cases_run": len(per_case),
        "cases_fully_correct": sum(1 for s in per_case.values() if not s["check_diffs"] and not s["wrong_fields"]),
        "fields": {
            "correct": sum(s["fields_total"] - len(s["wrong_fields"]) for s in per_case.values()),
            "total": sum(s["fields_total"] for s in per_case.values()),
            "by_field": by_field,
            "wrong": [{"case": c, **w} for c, s in per_case.items() for w in s["wrong_fields"]],
        },
        "sources": {
            "verified": sum(s["sources_verified"] for s in per_case.values()),
            "total": sum(s["sources_total"] for s in per_case.values()),
        },
        "checks": {
            "correct": sum(s["checks_total"] - len(s["check_diffs"]) for s in per_case.values()),
            "total": sum(s["checks_total"] for s in per_case.values()),
            "problems_total": sum(len(s["problems"]) for s in per_case.values()),
            "problems_caught": len(caught),
            "problems_flagged_differently": flagged_differently,
            "problems_missed": missed,
            "clean_checks_total": sum(s["checks_total"] - len(s["problems"]) for s in per_case.values()),
            "false_alarms": false_alarms,
            "extra_reviews": extra_reviews,
        },
        "cost_usd_total": round(sum(case_costs), 4) if case_costs else None,
        "cost_usd_per_trade": round(sum(case_costs) / len(case_costs), 4) if case_costs else None,
        "seconds_median": statistics.median(case_seconds) if case_seconds else None,
        "seconds_max": max(case_seconds) if case_seconds else None,
    }


def score_run(run_dir: Path) -> dict:
    """Score every saved case output in a run folder, overall and per tag
    (e.g. text_pdf vs scanned). Makes no API calls."""
    per_case, errors, costs, seconds = {}, {}, {}, {}
    for path in sorted((run_dir / "cases").glob("case_*.json")):
        output = json.loads(path.read_text(encoding="utf-8"))
        case_id = output["case_id"]
        if output["error"]:
            errors[case_id] = output["error"]
            continue
        expected = json.loads((CASES_DIR / case_id / "expected.json").read_text(encoding="utf-8"))
        per_case[case_id] = score_case(expected, output["report"])
        if output["report"]["cost_usd"] is not None:
            costs[case_id] = output["report"]["cost_usd"]
        seconds[case_id] = output["report"]["seconds"]

    groups: dict[str, dict] = {}
    for case_id, s in per_case.items():
        for tag in case_tags(case_id):
            groups.setdefault(tag, {})[case_id] = s
    return {
        **aggregate(per_case, costs, seconds),
        "errors": errors,
        "by_tag": {tag: aggregate(group, costs, seconds) for tag, group in sorted(groups.items())},
    }


def format_scorecard(scores: dict, config: dict) -> str:
    def pct(a: int, b: int) -> str:
        return f"{a}/{b} ({100 * a / b:.1f}%)" if b else "–"

    f, c, src = scores["fields"], scores["checks"], scores["sources"]
    lines = [
        f"Run: {config['model']}, effort {config['effort']}, {len(config['cases'])} cases, "
        f"prompt {config['prompt_version']}, commit {config['git_commit']}",
        "",
    ]
    if scores["errors"]:
        lines.append(f"ERRORS  {len(scores['errors'])} case(s) could not run (not scored below):")
        lines += [f"  {case}: {msg}" for case, msg in scores["errors"].items()]
        lines.append("")

    lines.append(f"Extraction        {pct(f['correct'], f['total'])} fields correct")
    weakest = sorted((v[0] / v[1], k, v) for k, v in f["by_field"].items() if v[0] < v[1])
    for _, key, (ok, total) in weakest[:5]:
        lines.append(f"  weak field      {key} {ok}/{total}")
    lines.append(f"Source quotes     {pct(src['verified'], src['total'])} found in the PDF")
    lines.append("")
    lines.append(f"Checks            {pct(c['correct'], c['total'])} match the answer key")
    lines.append(f"  Problems caught         {c['problems_caught']}/{c['problems_total']}")
    lines.append(f"  Problems MISSED         {len(c['problems_missed'])}    <- most important: should be 0")
    lines.append(f"  Flagged, other status   {len(c['problems_flagged_differently'])}    (e.g. REVIEW instead of FAIL: not missed)")
    lines.append(f"  False alarms (FAIL)     {len(c['false_alarms'])} of {c['clean_checks_total']} clean checks")
    lines.append(f"  Extra reviews           {len(c['extra_reviews'])} of {c['clean_checks_total']} clean checks")
    lines.append(f"Cases fully correct     {scores['cases_fully_correct']}/{scores['cases_run']}")
    lines.append("")
    cost = f"${scores['cost_usd_per_trade']:.3f} per trade, ${scores['cost_usd_total']:.2f} total" if scores["cost_usd_total"] is not None else "cost unknown"
    if scores["seconds_median"] is not None:
        lines.append(f"Cost  {cost}    Time  median {scores['seconds_median']:.1f}s, slowest {scores['seconds_max']:.1f}s")

    if len(scores["by_tag"]) > 1:
        lines += ["", "By tag              cases  fields      quotes      caught  missed  false alarms  extra reviews"]
        for tag, t in scores["by_tag"].items():
            tc = t["checks"]
            lines.append(
                f"  {tag:<17} {t['cases_run']:>5}  {t['fields']['correct']:>4}/{t['fields']['total']:<5}  "
                f"{t['sources']['verified']:>4}/{t['sources']['total']:<5}  "
                f"{tc['problems_caught']:>2}/{tc['problems_total']:<3}  {len(tc['problems_missed']):>6}  "
                f"{len(tc['false_alarms']):>12}  {len(tc['extra_reviews']):>13}"
            )

    details = []
    for d in c["problems_missed"]:
        details.append(f"  MISSED       {d['case']} {d['check']}: expected {d['expected']}, got PASS")
    for d in c["problems_flagged_differently"]:
        details.append(f"  other status {d['case']} {d['check']}: expected {d['expected']}, got {d['got']}")
    for d in c["false_alarms"] + c["extra_reviews"]:
        details.append(f"  not expected {d['case']} {d['check']}: expected PASS, got {d['got']}")
    for w in f["wrong"]:
        details.append(f"  wrong field  {w['case']} {w['field']}: expected {w['expected']!r}, got {w['got']!r}")
    if details:
        lines += ["", "Details:"] + details
    return "\n".join(lines)


# --- Running --------------------------------------------------------------------------


def prompt_version() -> str:
    """A short fingerprint of the prompt and schemas, so every result can be traced
    to exactly what produced it. It changes whenever either one changes."""
    text = SYSTEM_PROMPT + json.dumps(ContractExtraction.model_json_schema()) + json.dumps(
        InvoiceExtraction.model_json_schema()
    )
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_case(case_id: str, client: anthropic.Anthropic, model: str, effort: str) -> dict:
    case = CASES_DIR / case_id
    try:
        report = check_trade(case / "contract.pdf", case / "invoice.pdf", client=client, model=model, effort=effort)
        return {"case_id": case_id, "report": report_to_dict(report), "error": None}
    except anthropic.AuthenticationError:
        raise  # a bad key fails every case: stop the run instead of paying for nothing
    except (anthropic.APIError, ExtractionError) as e:
        return {"case_id": case_id, "report": None, "error": f"{type(e).__name__}: {e}"}


def run_eval(
    case_ids: list[str],
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    client: anthropic.Anthropic | None = None,
    results_dir: Path = RESULTS_DIR,
    label: str = "",
    workers: int = 3,
) -> Path:
    """Run the cases, save every output, score the run. Returns the run folder."""
    client = client or anthropic.Anthropic(max_retries=6)
    started = datetime.now()
    run_dir = results_dir / f"{started:%Y%m%d-%H%M%S}_{model}_{effort}{label}"
    (run_dir / "cases").mkdir(parents=True)
    config = {
        "model": model,
        "effort": effort,
        "cases": case_ids,
        "started_at": started.isoformat(timespec="seconds"),
        "prompt_version": prompt_version(),
        "git_commit": git_commit(),
    }
    (run_dir / "run.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # A few cases at a time (each case already makes 2 calls in parallel).
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(run_case, cid, client, model, effort): cid for cid in case_ids}
        for done, job in enumerate(as_completed(jobs), start=1):
            output = job.result()
            path = run_dir / "cases" / f"{output['case_id']}.json"
            path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if output["error"]:
                status = f"ERROR {output['error'][:80]}"
            else:
                r = output["report"]
                cost = f"${r['cost_usd']:.3f}" if r["cost_usd"] is not None else "$?"
                status = f"{r['verdict']:<17} {cost}  {r['seconds']:.1f}s"
            print(f"[{done:>2}/{len(case_ids)}] {output['case_id']}  {status}", flush=True)

    write_scores(run_dir)
    return run_dir


def write_scores(run_dir: Path) -> str:
    config = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    scores = score_run(run_dir)
    scorecard = format_scorecard(scores, config)
    (run_dir / "scores.json").write_text(json.dumps(scores, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "scorecard.txt").write_text(scorecard + "\n", encoding="utf-8")
    return scorecard


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Run and score the eval on the test cases.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high"])
    parser.add_argument("--quick", action="store_true", help=f"only the {len(QUICK_CASES)} hard cases")
    parser.add_argument("--cases", nargs="+", metavar="CASE_ID", help="only these cases")
    parser.add_argument("--tag", help="only cases with this tag, e.g. scanned or text_pdf")
    parser.add_argument("--rescore", type=Path, metavar="RUN_DIR", help="score a saved run again (no API calls)")
    parser.add_argument("--workers", type=int, default=3, help="cases run at the same time (default 3)")
    args = parser.parse_args()

    if args.rescore:
        print(write_scores(args.rescore))
        return 0

    all_cases = sorted(p.name for p in CASES_DIR.iterdir() if p.is_dir())
    case_ids = args.cases or (QUICK_CASES if args.quick else all_cases)
    if args.tag:
        case_ids = [c for c in case_ids if args.tag in case_tags(c)]
        if not case_ids:
            parser.error(f"no cases have the tag {args.tag!r}")
    unknown = set(case_ids) - set(all_cases)
    if unknown:
        parser.error(f"unknown case(s): {', '.join(sorted(unknown))}")

    print(f"Running {len(case_ids)} cases on {args.model} (effort {args.effort}). This makes real API calls.\n")
    try:
        run_dir = run_eval(
            case_ids,
            args.model,
            args.effort,
            label=f"_{args.tag}" if args.tag else "_quick" if args.quick else "",
            workers=args.workers,
        )
    except anthropic.AuthenticationError:
        print("API key rejected. Check ANTHROPIC_API_KEY in your .env file.", file=sys.stderr)
        return 1
    print("\n" + (run_dir / "scorecard.txt").read_text(encoding="utf-8"))
    print(f"Saved to {run_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

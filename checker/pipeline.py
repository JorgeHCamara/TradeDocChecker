"""The full check for one trade: contract PDF + invoice PDF in, report out.

    extract both (in parallel) -> verify source quotes -> run checks -> report

Run it on a test case folder:
    python -m checker.pipeline data/cases/case_002
or on any two files:
    python -m checker.pipeline --contract path/to/contract.pdf --invoice path/to/invoice.pdf
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import anthropic

from checker.checks import CheckResult, run_checks
from checker.extract import DEFAULT_EFFORT, DEFAULT_MODEL, ExtractionError, ExtractionResult, extract
from checker.sources import pdf_text, unverified_fields


@dataclass
class TradeReport:
    contract: ExtractionResult
    invoice: ExtractionResult
    unverified: set[str]  # e.g. {"invoice.quantity"}
    checks: list[CheckResult]
    seconds: float  # wall-clock time for the whole check

    @property
    def cost_usd(self) -> float | None:
        if self.contract.cost_usd is None or self.invoice.cost_usd is None:
            return None
        return self.contract.cost_usd + self.invoice.cost_usd

    def count(self, status: str) -> int:
        return sum(1 for c in self.checks if c.status == status)

    @property
    def verdict(self) -> str:
        if self.count("FAIL"):
            return "ISSUES FOUND"
        if self.count("REVIEW"):
            return "NEEDS REVIEW"
        return "ALL CHECKS PASSED"


def check_trade(
    contract_pdf: str | Path,
    invoice_pdf: str | Path,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
) -> TradeReport:
    client = client or anthropic.Anthropic(max_retries=4)
    started = time.perf_counter()

    # The two extractions don't depend on each other, so run them at the same
    # time: the total wait is the slower call, not the sum of both.
    with ThreadPoolExecutor(max_workers=2) as pool:
        contract_job = pool.submit(extract, contract_pdf, "contract", client, model, effort)
        invoice_job = pool.submit(extract, invoice_pdf, "invoice", client, model, effort)
        contract, invoice = contract_job.result(), invoice_job.result()

    unverified = {f"contract.{f}" for f in unverified_fields(contract.data, pdf_text(contract_pdf))}
    unverified |= {f"invoice.{f}" for f in unverified_fields(invoice.data, pdf_text(invoice_pdf))}

    checks = run_checks(contract.data, invoice.data, unverified)
    return TradeReport(contract, invoice, unverified, checks, time.perf_counter() - started)


def report_to_dict(report: TradeReport) -> dict:
    """The report as plain JSON-ready data (used by the API and the eval)."""

    def document(doc: str, result) -> dict:
        values = result.data.model_dump(mode="json")  # dates become "YYYY-MM-DD"
        return {
            name: {**field, "verified": f"{doc}.{name}" not in report.unverified}
            for name, field in values.items()
        }

    return {
        "verdict": report.verdict,
        "counts": {status: report.count(status) for status in ("FAIL", "REVIEW", "PASS")},
        "checks": [{"name": c.name, "status": c.status, "message": c.message} for c in report.checks],
        "contract": document("contract", report.contract),
        "invoice": document("invoice", report.invoice),
        "model": report.contract.model,
        "cost_usd": report.cost_usd,
        "seconds": round(report.seconds, 1),
    }


def format_report(report: TradeReport, title: str) -> str:
    lines = [
        f"Trade check: {title}",
        f"Contract {report.contract.data.contract_number.value}  ·  "
        f"Invoice {report.invoice.data.invoice_number.value}",
        "",
    ]
    width = max(len(c.name) for c in report.checks)
    for c in report.checks:
        lines.append(f"{c.status:<7} {c.name:<{width}}  {c.message}")
    lines.append("")
    if report.unverified:
        lines.append(f"Unverified fields: {', '.join(sorted(report.unverified))}")
    lines.append(
        f"Result: {report.verdict}  ({report.count('FAIL')} fail, {report.count('REVIEW')} review, "
        f"{report.count('PASS')} pass)"
    )
    cost = f"${report.cost_usd:.4f}" if report.cost_usd is not None else "unknown"
    lines.append(f"Model {report.contract.model}  ·  cost {cost}  ·  time {report.seconds:.1f}s")
    return "\n".join(lines)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Check an invoice against its sales contract.")
    parser.add_argument("case_dir", nargs="?", type=Path, help="folder with contract.pdf and invoice.pdf")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--invoice", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high"])
    args = parser.parse_args()

    if args.case_dir:
        contract_pdf, invoice_pdf, title = args.case_dir / "contract.pdf", args.case_dir / "invoice.pdf", args.case_dir.name
    elif args.contract and args.invoice:
        contract_pdf, invoice_pdf, title = args.contract, args.invoice, args.invoice.name
    else:
        parser.error("give a case folder, or both --contract and --invoice")

    try:
        report = check_trade(contract_pdf, invoice_pdf, model=args.model, effort=args.effort)
    except anthropic.AuthenticationError:
        print("API key rejected. Check ANTHROPIC_API_KEY in your .env file.", file=sys.stderr)
        return 1
    except (anthropic.APIError, ExtractionError) as e:
        print(f"Check failed: {e}", file=sys.stderr)
        return 1

    print(format_report(report, title))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""HTTP API used by the React frontend.

Run it (with the API key in .env):
    uvicorn checker.api:app --reload

Endpoints:
    GET  /api/cases                       list the test cases (for the demo picker)
    GET  /api/cases/{case_id}/{doc}.pdf   one of a test case's PDFs (doc = contract | invoice)
    POST /api/cases/{case_id}/check       check a test case; the response includes its expected results
    POST /api/check                       upload a contract PDF and an invoice PDF and check them

After `npm run build` in frontend/, the built app is also served at /.
"""

import json
import re
import tempfile
from functools import lru_cache
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from checker.extract import ExtractionError
from checker.pipeline import check_trade, report_to_dict

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "data" / "cases"
FRONTEND_DIST = ROOT / "frontend" / "dist"
MAX_PDF_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Trade Document Checker")


@lru_cache
def get_client() -> anthropic.Anthropic:
    """One shared API client. Tests replace it with a fake (app.dependency_overrides)."""
    return anthropic.Anthropic(max_retries=4)


def run_check(contract_pdf: Path, invoice_pdf: Path, client: anthropic.Anthropic) -> dict:
    try:
        return report_to_dict(check_trade(contract_pdf, invoice_pdf, client=client))
    except anthropic.AuthenticationError:
        raise HTTPException(500, "The server's Anthropic API key is missing or invalid.")
    except ExtractionError as e:
        raise HTTPException(422, f"Could not read the documents: {e}")
    except anthropic.APIError as e:
        raise HTTPException(502, f"The Claude API returned an error: {e}")


def case_dir(case_id: str) -> Path:
    # Only names like case_007 are accepted, so a request can't reach other folders.
    path = CASES_DIR / case_id
    if not re.fullmatch(r"case_\d{3}", case_id) or not path.is_dir():
        raise HTTPException(404, f"No test case named {case_id}")
    return path


def load_expected(path: Path) -> dict:
    return json.loads((path / "expected.json").read_text(encoding="utf-8"))


@app.get("/api/cases")
def list_cases() -> list[dict]:
    cases = []
    for path in sorted(p for p in CASES_DIR.iterdir() if p.is_dir()):
        expected = load_expected(path)
        cases.append(
            {
                "id": path.name,
                "description": expected["description"],
                "commodity": expected["contract"]["commodity"],
                "expected_issues": sum(1 for s in expected["checks"].values() if s != "PASS"),
            }
        )
    return cases


@app.get("/api/cases/{case_id}/{doc}.pdf")
def case_pdf(case_id: str, doc: str) -> FileResponse:
    if doc not in ("contract", "invoice"):
        raise HTTPException(404, "doc must be contract or invoice")
    return FileResponse(case_dir(case_id) / f"{doc}.pdf", media_type="application/pdf")


@app.post("/api/cases/{case_id}/check")
def check_case(case_id: str, client: anthropic.Anthropic = Depends(get_client)) -> dict:
    path = case_dir(case_id)
    result = run_check(path / "contract.pdf", path / "invoice.pdf", client)
    expected = load_expected(path)
    result["expected"] = {"description": expected["description"], "checks": expected["checks"]}
    return result


@app.post("/api/check")
async def check_upload(
    contract: UploadFile, invoice: UploadFile, client: anthropic.Anthropic = Depends(get_client)
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for name, upload in (("contract", contract), ("invoice", invoice)):
            data = await upload.read()
            if len(data) > MAX_PDF_BYTES:
                raise HTTPException(413, f"The {name} file is larger than 10 MB.")
            if not data.startswith(b"%PDF"):
                raise HTTPException(400, f"The {name} file is not a PDF.")
            paths[name] = Path(tmp) / f"{name}.pdf"
            paths[name].write_bytes(data)
        # check_trade blocks for ~10 s. This handler is async (to read the
        # uploads), so run the blocking call in a worker thread.
        return await run_in_threadpool(run_check, paths["contract"], paths["invoice"], client)


# Serve the built frontend, if there is one. Mounted last so /api routes win.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

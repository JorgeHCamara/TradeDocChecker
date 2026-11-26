"""Compare OCR engines on the scanned test invoices (case_031 to case_036).

For each engine and render size, every scan is read with OCR, and the script
checks whether six printed values can be confirmed in the OCR text using the
same matching rules as the app's source check (checker/sources.py):

    invoice number, contract reference, quantity, unit price, total,
    and the commodity description (a long text that often wraps)

So "values confirmed" means: would the source check have verified this value?
No API calls are made.

Engines (each is skipped if it isn't installed):
    rapidocr   pip install rapidocr-onnxruntime        (what the app uses)
    tesseract  pip install pytesseract, plus the Tesseract program
    easyocr    pip install easyocr                     (brings in PyTorch)

Usage:
    python scripts/ocr_benchmark.py
    python scripts/ocr_benchmark.py --engines rapidocr tesseract --scales 2 4
"""

import argparse
import json
import statistics
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checker.sources import quote_in_text, squash  # noqa: E402

CASES_DIR = ROOT / "data" / "cases"
RESULTS_DIR = ROOT / "results"
DESCRIPTIONS = {  # as printed by scripts/generate_cases.py
    "soybeans": "Brazilian Yellow Soybeans, GMO, crop 2025/2026, in bulk",
    "corn": "Brazilian Yellow Corn, GMO, crop 2026, in bulk",
}


# --- Engines: each returns (setup function, read function) --------------------------


def rapidocr_engine():
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()

    def read(image):
        result, _ = engine(np.array(image))
        return [text for _box, text, _confidence in result or []]

    return read


def tesseract_engine():
    import pytesseract

    pytesseract.get_tesseract_version()  # fails if the Tesseract program isn't installed

    def read(image):
        return pytesseract.image_to_string(image, lang="eng").splitlines()

    return read


def easyocr_engine():
    import numpy as np

    warnings.filterwarnings("ignore")  # PyTorch prints deprecation warnings on load
    import easyocr

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    def read(image):
        return reader.readtext(np.array(image), detail=0)

    return read


ENGINES = {"rapidocr": rapidocr_engine, "tesseract": tesseract_engine, "easyocr": easyocr_engine}


# --- Benchmark ---------------------------------------------------------------------------


def scanned_cases() -> list[tuple[str, dict]]:
    cases = []
    for path in sorted(CASES_DIR.glob("case_*")):
        expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
        if "scanned" in expected.get("tags", []):
            cases.append((path.name, expected))
    return cases


def printed_values(expected: dict) -> dict[str, str]:
    inv = expected["invoice"]
    return {
        "invoice_number": inv["invoice_number"],
        "contract_reference": inv["contract_reference"],
        "quantity": f"{inv['quantity']:,.3f}",
        "unit_price": f"{inv['unit_price']:,.2f}",
        "total_amount": f"{inv['total_amount']:,.2f}",
        "commodity": DESCRIPTIONS[inv["commodity"]],
    }


def render(case_id: str, scale: float):
    import pypdfium2 as pdfium

    return [page.render(scale=scale).to_pil().convert("RGB") for page in pdfium.PdfDocument(str(CASES_DIR / case_id / "invoice.pdf"))]


def run(engine_names: list[str], scales: list[float]) -> list[dict]:
    cases = scanned_cases()
    rows = []
    for name in engine_names:
        started = time.perf_counter()
        try:
            read = ENGINES[name]()
        except Exception as e:  # not installed, or its program is missing
            print(f"{name}: skipped ({type(e).__name__}: {e})")
            continue
        setup_seconds = time.perf_counter() - started
        for scale in scales:
            row = {"engine": name, "scale": scale, "setup_seconds": round(setup_seconds, 1),
                   "confirmed": 0, "total": 0, "by_quality": {}, "missed": [], "page_seconds": []}
            for case_id, expected in cases:
                quality = next(t for t in expected["tags"] if t.startswith("scan_"))[5:]
                lines = []
                for image in render(case_id, scale):
                    t = time.perf_counter()
                    lines += read(image)
                    row["page_seconds"].append(time.perf_counter() - t)
                text = squash("\n".join(lines))
                q = row["by_quality"].setdefault(quality, [0, 0])
                for field, printed in printed_values(expected).items():
                    ok = quote_in_text(printed, text, fuzzy=True)  # the app's rules for OCR text
                    row["confirmed"] += ok
                    row["total"] += 1
                    q[0] += ok
                    q[1] += 1
                    if not ok:
                        row["missed"].append(f"{case_id} ({quality}) {field}: {printed}")
            row["median_page_seconds"] = round(statistics.median(row["page_seconds"]), 2)
            del row["page_seconds"]
            rows.append(row)
            print(f"{name} at {scale}x: {row['confirmed']}/{row['total']} confirmed, "
                  f"{row['median_page_seconds']}s per page", flush=True)
    return rows


def format_table(rows: list[dict]) -> str:
    qualities = ["good", "fair", "poor"]
    lines = [
        "Engine     Scale  Confirmed   " + "  ".join(f"{q:>6}" for q in qualities) + "   s/page  setup s",
    ]
    for r in rows:
        by_q = "  ".join(f"{r['by_quality'].get(q, [0, 0])[0]:>3}/{r['by_quality'].get(q, [0, 0])[1]:<2}" for q in qualities)
        lines.append(
            f"{r['engine']:<10} {r['scale']:>4}x  {r['confirmed']:>3}/{r['total']:<3}     {by_q}   "
            f"{r['median_page_seconds']:>6}  {r['setup_seconds']:>7}"
        )
    lines.append("")
    for r in rows:
        if r["missed"]:
            lines.append(f"{r['engine']} at {r['scale']}x could not confirm:")
            lines += [f"  {m}" for m in r["missed"]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare OCR engines on the scanned test invoices.")
    parser.add_argument("--engines", nargs="+", choices=list(ENGINES), default=list(ENGINES))
    parser.add_argument("--scales", nargs="+", type=float, default=[2, 4], help="render sizes (2 = 144 dpi)")
    args = parser.parse_args()

    rows = run(args.engines, args.scales)
    table = format_table(rows)
    print("\n" + table)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"ocr_benchmark_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

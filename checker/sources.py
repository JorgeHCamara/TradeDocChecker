"""Hallucination check: is each `source` quote really in the document?

The model returns, for every field, the exact text it read the value from.
If that text can't be found in the PDF, the value may be made up, so the
field is marked unverified and any check that uses it asks for human review.

Where the document's text comes from:
- Typed or digitally generated PDFs have a text layer, read directly.
- Scanned PDFs are only images. Their text is read with OCR, an optional
  extra (pip install -e ".[ocr]", about 200 MB). Without it, a scan has no
  text to check against, so its quotes stay unverified and every check that
  uses them goes to review: safe, but a person has to check everything.

How quotes are matched: on letters and digits only. Spaces, punctuation,
accents and capitals are ignored, because OCR often drops spaces ("22April
2026") and accents ("Paranagua"). Numbers stay strict: every digit must
match, and a number can't match inside a longer number. A quote that wraps
inside a table cell may be found in up to three pieces, never split inside
a number.

Known limit: if the model and the OCR misread the same digit the same way,
the wrong value passes this check. They read the page differently, so this
is unlikely, but possible.
"""

import re
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfReader

# Fewer characters than this per page means the PDF is a scan (just images).
MIN_CHARS_PER_PAGE = 20

TextMethod = Literal["pdf_text", "ocr", "none"]


@dataclass
class DocumentText:
    text: str
    # pdf_text: the PDF's own text layer. ocr: read from the page images.
    # none: a scan, and OCR isn't installed, so there is no text.
    method: TextMethod


def pdf_text(pdf_path: str | Path) -> str:
    """All text in the PDF's text layer, pages joined in order."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)


def ocr_available() -> bool:
    try:
        import pypdfium2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()  # loads the OCR models once; reused for every page


_ocr_lock = threading.Lock()  # the pipeline reads two documents in parallel


def ocr_text(pdf_path: str | Path) -> str:
    """Read the text of a scanned PDF with OCR, one line per detected text box."""
    import numpy as np
    import pypdfium2 as pdfium

    lines = []
    for page in pdfium.PdfDocument(str(pdf_path)):
        image = page.render(scale=2).to_pil().convert("RGB")  # 144 dpi: enough for OCR
        with _ocr_lock:
            result, _ = _ocr_engine()(np.array(image))
        lines += [text for _box, text, _confidence in result or []]
    return "\n".join(lines)


def document_text(pdf_path: str | Path) -> DocumentText:
    """The document's text: from its text layer, or with OCR if it's a scan."""
    text = pdf_text(pdf_path)
    if len(text.strip()) >= MIN_CHARS_PER_PAGE * len(PdfReader(pdf_path).pages):
        return DocumentText(text, "pdf_text")
    if ocr_available():
        return DocumentText(ocr_text(pdf_path), "ocr")
    return DocumentText(text, "none")


def squash(text: str) -> str:
    """Reduce text to what matters for matching quotes:
    '22 April 2026' -> '22april2026', 'Paranaguá, Brazil' -> 'paranaguabrazil',
    '63,800.000 412.50' -> '63800000 41250'.
    A space is kept only between two numbers, so neighbouring table cells
    can't run together into one long number."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"(?<=\d)[.,'](?=\d)", "", text)  # 63,800.000 -> 63800000
    text = re.sub(r"[^0-9a-z]+", " ", text)  # punctuation and line breaks -> space
    text = re.sub(r"(?<!\d) | (?!\d)", "", text)  # drop spaces not between two digits
    return text.strip()


def _find(piece: str, text: str, start: int) -> int:
    """End position of the first match of `piece` in `text` at or after `start`
    where a number doesn't match inside a longer number; -1 if there is none."""
    for match in re.finditer(re.escape(piece), text[start:]):
        begin, end = start + match.start(), start + match.end()
        if piece[0].isdigit() and begin > 0 and text[begin - 1].isdigit():
            continue  # e.g. "63800" inside "1638000"
        if piece[-1].isdigit() and end < len(text) and text[end].isdigit():
            continue
        return end
    return -1


def _match_in_pieces(quote: str, text: str, start: int, pieces_left: int) -> bool:
    if _find(quote, text, start) >= 0:
        return True
    if pieces_left <= 1:
        return False
    # Try splitting off the longest possible first piece.
    for cut in range(len(quote) - MIN_PIECE, MIN_PIECE - 1, -1):
        if quote[cut - 1].isdigit() and quote[cut].isdigit():
            continue  # never split a number
        end = _find(quote[:cut], text, start)
        if end >= 0 and _match_in_pieces(quote[cut:], text, end, pieces_left - 1):
            return True
    return False


# Text that wraps inside a table cell can come out of OCR in pieces, with
# other cells of the same row in between ("...GMO, crop" / "60,850.000" /
# "448.00" / "2025/2026, in bulk"). So a quote may match in up to MAX_PIECES
# pieces, in order, each at least MIN_PIECE characters long, and never split
# inside a number.
MAX_PIECES = 3
MIN_PIECE = 6


def quote_in_text(quote: str, squashed_text: str) -> bool:
    """Is the quote in the (squashed) document text?"""
    q = squash(quote)
    if not q:
        return False
    return _match_in_pieces(q, squashed_text, 0, MAX_PIECES)


def unverified_fields(extraction: BaseModel, document_text: str) -> set[str]:
    """Names of the fields whose value is set but whose source isn't in the text."""
    haystack = squash(document_text)
    unverified = set()
    for name in type(extraction).model_fields:
        field = getattr(extraction, name)
        if field.value is None:
            continue  # nothing was extracted, so there is nothing to verify
        if not field.source or not quote_in_text(field.source, haystack):
            unverified.add(name)
    return unverified

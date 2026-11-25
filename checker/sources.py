"""Hallucination check: is each `source` quote really in the document?

The model returns, for every field, the exact text it read the value from.
If that text can't be found in the PDF, the value may be made up, so the
field is marked unverified and any check that uses it asks for human review.

This needs a PDF with a text layer (typed or digitally generated). Scanned
documents have no text layer and would need OCR first.
"""

import re
from pathlib import Path

from pydantic import BaseModel
from pypdf import PdfReader


def pdf_text(pdf_path: str | Path) -> str:
    """All text in the PDF, pages joined in order."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)


def _normalize(text: str) -> str:
    # PDF text extraction breaks lines and spaces differently from how the
    # page looks, so compare with all whitespace runs collapsed to one space.
    return re.sub(r"\s+", " ", text).strip()


def unverified_fields(extraction: BaseModel, document_text: str) -> set[str]:
    """Names of the fields whose value is set but whose source isn't in the text."""
    haystack = _normalize(document_text)
    unverified = set()
    for name in type(extraction).model_fields:
        field = getattr(extraction, name)
        if field.value is None:
            continue  # nothing was extracted, so there is nothing to verify
        if not field.source or _normalize(field.source) not in haystack:
            unverified.add(name)
    return unverified

"""Composite scoring for the research-reports library.

``composite_score`` = 0.5 × AI-relevance (normalized to 0-1) + 0.5 × length
(normalized character count). Reports whose body is missing/too short fall back
to reading their local PDF (via ``pypdf``) for a character count.

Standalone from the news pipeline: ``ReportFilter`` writes ``ai_relevance_score``
(1-5, or None when never evaluated) and this module derives the persisted
``composite_score`` used for frontend sorting.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from pypdf import PdfReader

from .models import Report

logger = logging.getLogger(__name__)

CONTENT_SHORT_THRESHOLD = 1000  # body shorter than this counts as "missing full text" → read PDF
FULL_LENGTH_CHARS = 15000       # character count that maps to a full length score
NEUTRAL_AI_SCORE = 3.0          # neutral 1-5 AI relevance when a report was never filter-scored
DEFAULT_PDF_OUTPUT_DIR = "data/reports_pdfs"


def content_length(report: Report, pdf_output_dir: str = DEFAULT_PDF_OUTPUT_DIR) -> int:
    """Character count for the report body, preferring clean text and falling
    back to the local PDF when the body is only summary-level (short).

    部分来源（如 aliyunreports）的 ``content_text`` 只是摘要（约 150-400 字符），
    完整内容在 PDF 中——正文过短时读 PDF 才能反映真实篇幅。
    """
    body = (report.content_text or "").strip()
    if len(body) >= CONTENT_SHORT_THRESHOLD:
        return len(body)
    return pdf_text_length(report, pdf_output_dir)


def _local_pdf_paths(report: Report, pdf_output_dir: str) -> List[Path]:
    """Resolve existing local PDF files for a report.

    ``pdf_urls`` entries carry a serveable ``local_path`` (``/api/reports/pdfs/
    {source}/{native_id}/{filename}.pdf``); strip that prefix and re-attach the
    configured on-disk root. Also glob the canonical ``{root}/{source}/{native_id}``
    directory as a fallback for older data. Returns deduplicated existing files.
    """
    root = Path(pdf_output_dir)
    candidates: List[Path] = []
    for entry in report.pdf_urls or []:
        lp = entry.get("local_path")
        if not lp:
            continue
        if lp.startswith("/api/reports/pdfs/"):
            rel = lp.removeprefix("/api/reports/pdfs/")
        elif lp.startswith("data/"):
            rel = lp.removeprefix("data/")
        else:
            continue
        candidates.append(root / rel)
    # 兜底：目录规则 {root}/{source}/{native_id}/*.pdf。
    candidates.extend((root / report.source / report.native_id).glob("*.pdf"))

    seen: set[Path] = set()
    out: List[Path] = []
    for p in candidates:
        if p.exists() and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def pdf_text_length(report: Report, pdf_output_dir: str) -> int:
    """Extract and sum character counts from local PDFs via pypdf.

    Scanned/image PDFs yield no extractable text — returns 0 (length score 0).
    """
    total = 0
    for path in _local_pdf_paths(report, pdf_output_dir):
        try:
            reader = PdfReader(str(path))
            total += sum(len(page.extract_text() or "") for page in reader.pages)
        except Exception:
            logger.debug(
                "PDF text extraction failed for %s", path, exc_info=True,
            )
    return total


def length_norm(char_count: int) -> float:
    """Linear normalization of character count to 0-1, capped at FULL_LENGTH_CHARS."""
    if char_count <= 0:
        return 0.0
    return min(1.0, char_count / FULL_LENGTH_CHARS)


def ai_relevance_norm(ai_relevance_score: Optional[float]) -> float:
    """Normalize the 1-5 AI relevance score to 0-1; missing → neutral 0.6."""
    score = ai_relevance_score if ai_relevance_score is not None else NEUTRAL_AI_SCORE
    return max(0.0, min(1.0, score / 5.0))


def compute_composite_score(report: Report, pdf_output_dir: str = DEFAULT_PDF_OUTPUT_DIR) -> Report:
    """Compute and write back ``report.composite_score`` (0-1)."""
    length = content_length(report, pdf_output_dir)
    composite = 0.5 * ai_relevance_norm(report.ai_relevance_score) + 0.5 * length_norm(length)
    report.composite_score = round(composite, 4)
    return report

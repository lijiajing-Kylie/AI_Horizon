"""Tests for composite scoring (src/reports/scoring.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.reports.models import Report
from src.reports.scoring import (
    compute_composite_score,
    content_length,
    length_norm,
    pdf_text_length,
)


def _report(**overrides) -> Report:
    defaults = dict(
        id="aliresearch:1",
        source="aliresearch",
        native_id="1",
        title="R",
        institution="阿里研究院",
        url="http://example.com/r",
        pdf_urls=[],
        content_text="",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Report(**defaults)


def _make_pdf(path: Path, text: str) -> None:
    """Write a minimal single-page PDF containing *text* (ASCII)."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = content
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    writer.write(str(path))


# ── length_norm ──────────────────────────────────────────────────────────────

def test_length_norm_boundaries():
    assert length_norm(0) == 0.0
    assert length_norm(7500) == pytest.approx(0.5)
    assert length_norm(15000) == 1.0
    assert length_norm(30000) == 1.0  # clamped


# ── content_length ───────────────────────────────────────────────────────────

def test_content_length_uses_body_when_long_enough(tmp_path):
    r = _report(content_text="x" * 1500)  # >= 1000 → 直接用正文
    assert content_length(r, str(tmp_path)) == 1500


def test_content_length_falls_back_to_pdf(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    report_dir = pdf_dir / "aliresearch" / "1"
    report_dir.mkdir(parents=True)
    _make_pdf(report_dir / "report.pdf", "Hello report body")  # 17 chars
    r = _report(
        content_text="短正文",  # < 100 → 读 PDF
        pdf_urls=[{
            "name": "report.pdf",
            "url": "http://x/report.pdf",
            "local_path": "/api/reports/pdfs/aliresearch/1/report.pdf",
        }],
    )
    assert content_length(r, str(pdf_dir)) == 17


def test_content_length_short_body_no_pdf(tmp_path):
    r = _report(content_text="短正文", pdf_urls=[])
    assert content_length(r, str(tmp_path)) == 0


def test_pdf_text_length_broken_pdf_returns_zero(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    report_dir = pdf_dir / "aliresearch" / "1"
    report_dir.mkdir(parents=True)
    (report_dir / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    r = _report(
        content_text="",
        pdf_urls=[{
            "name": "broken.pdf",
            "url": "http://x/broken.pdf",
            "local_path": "/api/reports/pdfs/aliresearch/1/broken.pdf",
        }],
    )
    assert pdf_text_length(r, str(pdf_dir)) == 0


# ── compute_composite_score ──────────────────────────────────────────────────

def test_composite_with_ai_score_and_full_length():
    r = _report(ai_relevance_score=4.0, content_text="x" * 15000)
    compute_composite_score(r, "data/reports_pdfs")
    # 0.5×(4/5) + 0.5×min(1, 15000/15000)
    assert r.composite_score == pytest.approx(0.5 * 0.8 + 0.5 * 1.0)


def test_composite_neutral_ai_when_missing_and_no_length(tmp_path):
    r = _report(ai_relevance_score=None, content_text="")  # 无正文无 PDF → length 0
    compute_composite_score(r, str(tmp_path))
    # 0.5×(3/5) + 0.5×0
    assert r.composite_score == pytest.approx(0.5 * 0.6)

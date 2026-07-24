"""Universal HTTP-based PDF downloader for the reports library.

Downloads PDF files via direct HTTP (``httpx.AsyncClient``), independent of
Playwright browser sessions. Handles the common case where report PDFs are
served from public CDN URLs or directly accessible endpoints.

Sources that already handle their own PDF download (e.g. ``aliyunreports``
via Playwright click/fetch) store ``local_path`` themselves — this module
skips entries that already have one.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from ..models import ReportsConfig
from .models import Report
from .pdf import sanitize_filename

logger = logging.getLogger(__name__)


async def download_report_pdfs(
    report: Report,
    config: ReportsConfig,
    client: httpx.AsyncClient,
) -> Report:
    """Download all PDF URLs for *report* that lack a local copy.

    Iterates ``report.pdf_urls``, downloads each entry's ``url`` via HTTP GET,
    and stores the resulting file under ``{pdf_output_dir}/{source}/{native_id}/``.
    Sets the entry's ``local_path`` key to the serveable URL path (usable
    behind a ``/api/reports/pdfs/`` ``StaticFiles`` mount).

    Entries that already have a ``local_path`` key (e.g. from AliyunReports'
    own Playwright-based download) are skipped.  Entries whose download fails
    keep their remote ``url`` as a fallback — the caller's frontend should
    prefer ``local_path`` over ``url``.
    """
    pdf_output_dir = Path(config.pdf_output_dir)

    for entry in report.pdf_urls:
        # Already has a local copy — skip.
        if entry.get("local_path"):
            continue

        url = entry.get("url")
        if not url:
            continue

        # Skip entries explicitly marked as non-PDF (e.g. web readers).
        if entry.get("type") == "reader":
            logger.debug("Skipping reader-type entry: %s", url)
            continue

        # Skip URLs that don't look like PDF links at all.
        if not re.search(r'\.pdf([?#]|$)', url):
            logger.debug("URL doesn't look like a PDF link, skipping: %s", url)
            continue

        # Derive a safe filename.
        name = entry.get("name") or report.native_id
        safe_name = sanitize_filename(name)

        output_dir = pdf_output_dir / report.source / report.native_id
        output_path = output_dir / f"{safe_name}.pdf"

        # Already on disk from a previous run.
        if output_path.exists():
            entry["local_path"] = _serveable_path(
                config.pdf_output_dir, report.source, report.native_id, f"{safe_name}.pdf"
            )
            logger.info("PDF already exists, reusing: %s", output_path)
            continue

        try:
            resp = await client.get(url, follow_redirects=True, timeout=30.0)
            resp.raise_for_status()
            body = resp.content

            # Guard against empty / error-page bodies.
            if len(body) < 1000:
                logger.warning(
                    "Too small (%d bytes) at %s — not a real PDF; skipped",
                    len(body),
                    url,
                )
                continue

            # Validate that the response is actually a PDF by checking the
            # magic bytes.  PDF files always start with ``%PDF``.
            if not body.startswith(b"%PDF"):
                logger.warning(
                    "Response from %s does not start with %%PDF headers "
                    "(got %.40r…) — not a PDF; skipped",
                    url,
                    body[:40],
                )
                continue

            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(body)

            entry["local_path"] = _serveable_path(
                config.pdf_output_dir, report.source, report.native_id, f"{safe_name}.pdf"
            )
            logger.info("Downloaded PDF (%d bytes) from %s -> %s", len(body), url, output_path)

        except Exception as exc:
            logger.warning("Failed to download PDF from %s: %s", url, exc)
            # Keep the remote url as fallback — do not mutate entry.

    return report


def _serveable_path(
    pdf_output_dir: str, source: str, native_id: str, filename: str
) -> str:
    """Build the URL path for a PDF served behind the ``/api/reports/pdfs`` mount.

    The ``StaticFiles`` mount in ``api/server.py`` serves files from
    ``data/reports_pdfs/`` at ``/api/reports/pdfs/``.  Example:

        _serveable_path("data/reports_pdfs", "aliresearch", "123", "report.pdf")
        # →  "/api/reports/pdfs/aliresearch/123/report.pdf"
    """
    return f"/api/reports/pdfs/{source}/{native_id}/{filename}"

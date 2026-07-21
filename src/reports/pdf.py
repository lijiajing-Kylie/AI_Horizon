"""PDF download utilities for the reports library.

Handles downloading PDFs through Playwright browser sessions (preserving
cookies/CSRF tokens) and sanitising filenames for local storage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from playwright.async_api import Page

# Characters that are problematic in filenames across OSes.
_FILENAME_INVALID_TRANS = str.maketrans({
    '/': '_', '\\': '_', ':': '_', '*': '_', '?': '_',
    '"': '_', '<': '_', '>': '_', '|': '_', '\0': '',
    '\n': ' ', '\r': ' ',
})


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Remove or replace characters that are illegal in filenames.

    Also strips leading/trailing whitespace and dots, collapses
    multiple spaces, truncates to *max_len* characters preserving
    the extension if one is present.
    """
    cleaned = name.translate(_FILENAME_INVALID_TRANS).strip().strip('.')
    # Collapse multiple spaces.
    cleaned = ' '.join(cleaned.split())
    if not cleaned:
        cleaned = "report"
    # Truncate preserving extension.
    if len(cleaned) > max_len:
        stem, _, ext = cleaned.rpartition(".")
        if ext and len(ext) <= 5:
            cleaned = stem[:max_len - len(ext) - 1] + "." + ext
        else:
            cleaned = cleaned[:max_len]
    return cleaned


async def download_pdf_via_click(
    page: "Page",
    trigger_selector: str,
    output_dir: Path,
    filename: str,
    *,
    timeout_ms: int = 30000,
) -> Optional[Path]:
    """Click a download trigger on *page*, capture the PDF, and save locally.

    Uses Playwright's :meth:`page.expect_download` to intercept the
    browser's download event, which preserves session cookies and
    CSRF tokens.

    Returns the local ``Path`` on success, ``None`` on failure.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = sanitize_filename(filename)
        output_path = output_dir / f"{safe_name}.pdf"

        # If the file already exists, skip re-downloading.
        if output_path.exists():
            logger.info("PDF already exists, skipping: %s", output_path)
            return output_path

        async with page.expect_download(timeout=timeout_ms) as download_info:
            await page.click(trigger_selector)

        download = await download_info.value
        await download.save_as(str(output_path))
        logger.info("Downloaded PDF (%s) to %s", download.suggested_filename, output_path)
        return output_path

    except Exception as exc:
        logger.warning("Failed to download PDF via click %r: %s", trigger_selector, exc)
        return None


async def download_pdf_via_fetch(
    page: "Page",
    url: str,
    output_dir: Path,
    filename: str,
) -> Optional[Path]:
    """Download a PDF from *url* using the browser's ``fetch()`` API.

    Uses ``page.evaluate()`` to call ``fetch()`` inside the browser
    (preserving cookies/session), transfers the bytes via base64 to
    Python, and writes them to disk.

    Returns the local ``Path`` on success, ``None`` on failure.
    """
    import base64

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = sanitize_filename(filename)
        output_path = output_dir / f"{safe_name}.pdf"

        if output_path.exists():
            logger.info("PDF already exists, skipping: %s", output_path)
            return output_path

        result: Optional[str] = await page.evaluate(f"""
            async () => {{
                try {{
                    const resp = await fetch({url!r});
                    if (!resp.ok) return null;
                    const blob = await resp.blob();
                    const buffer = await blob.arrayBuffer();
                    const bytes = new Uint8Array(buffer);
                    let binary = '';
                    for (let i = 0; i < bytes.length; i++) {{
                        binary += String.fromCharCode(bytes[i]);
                    }}
                    return btoa(binary);
                }} catch (e) {{
                    return null;
                }}
            }}
        """)

        if not result:
            logger.warning("Browser fetch returned empty for %s", url)
            return None

        pdf_bytes = base64.b64decode(result)
        output_path.write_bytes(pdf_bytes)
        logger.info("Downloaded PDF (%d bytes) to %s", len(pdf_bytes), output_path)
        return output_path

    except Exception as exc:
        logger.warning("Failed to download PDF via fetch %s: %s", url, exc)
        return None

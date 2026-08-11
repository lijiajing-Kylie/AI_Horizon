"""Data model for the standalone research-reports library.

Deliberately independent of `src.models.ContentItem` and `src.papers.models.Paper`
— reports come from arbitrary institution websites (each with its own ID scheme),
and are keyed by a source-namespaced id so multiple sources can never collide.
Reports carry only a light AI relevance score (from the AI filter) and a derived
composite score used for frontend sorting — they never go through the news
pipeline's full analyzer/enricher.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class Report(BaseModel):
    """A single research report from one configured source."""

    id: str             # f"{source}:{native_id}", e.g. "aliresearch:591792162400768000"
    source: str          # short source key, e.g. "aliresearch"
    native_id: str        # the source's own id (used to re-fetch/detail against that source)
    title: str
    institution: str      # publishing org, e.g. "阿里研究院" — generic across sources
    author: Optional[str] = None
    url: str
    pdf_urls: List[dict] = []   # [{"name": str, "url": str}], direct links only, not downloaded
    summary: Optional[str] = None
    content_text: str      # cleaned plain text of the report body
    raw_html: Optional[str] = None  # original HTML as fetched (e.g. WeChat MP article body), not cleaned
    categories: List[str] = []
    keywords: List[str] = []   # AI-extracted keywords (5-8), bilingual
    published_at: datetime
    updated_at: datetime
    view_count: Optional[int] = None
    download_count: Optional[int] = None
    fetched_at: datetime
    skip_ai_filter: bool = False  # set True for already-curated sources (e.g. featured articles)
    ai_relevance_score: Optional[float] = None  # 1-5 from the AI filter; None = not evaluated (scored as neutral)
    composite_score: Optional[float] = None  # 0-1, 0.5×ai_norm + 0.5×length_norm — used for frontend sorting

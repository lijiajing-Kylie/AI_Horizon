"""Cross-source URL dedup, AI semantic topic dedup, and source-provenance aggregation.

These are the algorithms behind identifying and merging ``ContentItem``s that
refer to the same underlying story, whether discovered via an exact
normalized-URL match (:func:`merge_cross_source_duplicates`) or via AI
semantic matching (:func:`merge_topic_duplicates`). :func:`build_source_attribution`
aggregates the provenance data both of those write into a unified,
display-ready structure.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urlparse

from rich.console import Console

from .ai.client import create_ai_client
from .ai.prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
from .ai.utils import parse_json_response
from .models import (
    AIConfig,
    ContentItem,
    SOURCE_ROLE_PRIORITY,
    SourceRole,
    classify_url_role,
    sub_source_label,
)

_MAX_MERGED_IMAGES = 20


def merge_item_images(primary: ContentItem, other: ContentItem) -> None:
    """Fold ``other``'s cover image / image list into ``primary``, in place.

    Used when duplicate items are merged (cross-source URL dedup, AI topic
    dedup) so an image found via a secondary source isn't lost just because
    that item wasn't picked as primary.
    """
    if not primary.cover_image and other.cover_image:
        primary.cover_image = other.cover_image

    if other.images and len(primary.images) < _MAX_MERGED_IMAGES:
        seen = {img.get("url") for img in primary.images}
        for img in other.images:
            if len(primary.images) >= _MAX_MERGED_IMAGES:
                break
            if img.get("url") not in seen:
                primary.images.append(img)
                seen.add(img.get("url"))


_EXTRACTION_FIELDS = (
    "raw_content", "raw_html", "display_html", "content_source",
    "extraction_status", "extraction_error", "http_status",
    "final_url", "text_length", "extracted_at", "extractor_version",
)


def merge_extraction_fields(primary: ContentItem, other: ContentItem) -> None:
    """Promote ``other``'s full-content extraction result onto ``primary``, in place.

    Mirrors ``merge_item_images``: cross-source URL dedup picks ``primary``
    by raw ``content`` length, which has nothing to do with whether that
    item's own extraction succeeded. If ``primary``'s extraction failed
    while a same-URL duplicate's succeeded, without this the good
    raw_content/raw_html/display_html would simply be discarded.
    """
    if primary.extraction_status == "success":
        return
    if other.extraction_status != "success":
        return
    for field_name in _EXTRACTION_FIELDS:
        setattr(primary, field_name, getattr(other, field_name))
    primary.content = primary.raw_content  # keep legacy alias consistent


def build_source_attribution(items: List[ContentItem]) -> None:
    """Build unified source provenance and backward-compatible source attribution.

    Aggregates sources from:
    1. URL dedup (``_cross_source_provenance`` set by
       :func:`merge_cross_source_duplicates`)
    2. Semantic topic dedup (``_topic_provenance_groups`` set by
       :func:`merge_topic_duplicates`)
    3. The item itself (standalone source)

    Writes two metadata keys:

    * ``source_provenance`` — canonical structure with primary_source and
      full sources list
    * ``source_attribution`` — legacy compact structure for backward compat
    """
    for item in items:
        # ── Phase A: gather all rich source entries ──────────────────
        all_sources: list[dict] = []

        # 1. Cross-source URL dedup provenance
        cross_prov = item.metadata.pop("_cross_source_provenance", None)
        if isinstance(cross_prov, dict):
            all_sources.extend(cross_prov.get("sources", []))

        # 2. Topic dedup provenance (may have multiple groups)
        topic_groups = item.metadata.pop("_topic_provenance_groups", None) or []
        for group in topic_groups:
            if isinstance(group, dict):
                all_sources.extend(group.get("sources", []))

        # 3. The item itself (always included)
        own_entry: dict = {
            "source_name": sub_source_label(item),
            "source_url": str(item.url),
            "source_type": item.source_type.value,
            "role": classify_url_role(str(item.url)).value,
            "title": item.title,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "is_primary": True,
            "discovered_via": "standalone",
            "confidence": 1.0,
        }
        all_sources.append(own_entry)

        # ── Phase B: deduplicate by source_url ───────────────────────
        seen_urls: set[str] = set()
        unique_sources: list[dict] = []
        for s in all_sources:
            url = s.get("source_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_sources.append(s)

        # ── Phase C: select primary by provenance priority ───────────
        unique_sources.sort(
            key=lambda e: SOURCE_ROLE_PRIORITY.get(
                SourceRole(e.get("role", "unknown")), 10
            )
        )
        if unique_sources:
            best = unique_sources[0]
            for s in unique_sources:
                s["is_primary"] = s["source_url"] == best["source_url"]

        # ── Phase D: write source_provenance ─────────────────────────
        if len(unique_sources) >= 1:
            best = unique_sources[0]
            item.metadata["source_provenance"] = {
                "primary_source_name": best.get("source_name", ""),
                "primary_source_url": best.get("source_url", ""),
                "primary_source_type": best.get("role", "unknown"),
                "source_count": len(unique_sources),
                "sources": unique_sources,
            }

        # ── Phase E: backward-compatible source_attribution ──────────
        detail: list[dict] = []
        for s in unique_sources:
            title = s.get("title", "")
            if len(title) > 60:
                title = title[:57] + "..."
            detail.append({
                "label": s.get("source_name", ""),
                "title": title,
                "url": s.get("source_url", ""),
            })

        if len(detail) <= 1:
            continue

        item.metadata["source_attribution"] = {
            "count": len(detail),
            "labels": [d["label"] for d in detail],
            "detail": detail,
        }


def merge_cross_source_duplicates(items: List[ContentItem]) -> List[ContentItem]:
    """Merge items that point to the same URL from different sources.

    This is a stable stage helper for integrations such as MCP.

    Keeps the item with the richest content (or most authoritative URL) and
    combines metadata.  Stores full source provenance records for later
    aggregation by :func:`build_source_attribution`.

    Args:
        items: Items to deduplicate

    Returns:
        List[ContentItem]: Deduplicated items
    """
    def normalize_url(url: str) -> str:
        parsed = urlparse(str(url))
        # Strip www prefix, trailing slashes, and fragments
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/")
        return f"{host}{path}"

    def _build_source_entry(item: ContentItem, discovered_via: str = "url_dedup", confidence: float = 1.0) -> dict:
        """Build a single source provenance entry for a ContentItem."""
        return {
            "source_name": sub_source_label(item),
            "source_url": str(item.url),
            "source_type": item.source_type.value,
            "role": classify_url_role(str(item.url)).value,
            "title": item.title,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "is_primary": False,
            "discovered_via": discovered_via,
            "confidence": confidence,
        }

    # Group by normalized URL
    url_groups: Dict[str, List[ContentItem]] = {}
    for item in items:
        key = normalize_url(str(item.url))
        url_groups.setdefault(key, []).append(item)

    merged = []
    for key, group in url_groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Pick the item with the richest content as initial primary
        primary = max(group, key=lambda x: len(x.content or ""))

        # Merge metadata and source info from other items
        all_sources_dicts: list[dict] = []           # backward-compat
        provenance_entries: list[dict] = []           # new rich structure
        for item in group:
            # Backward-compatible record
            all_sources_dicts.append({
                "source_type": item.source_type.value,
                "label": sub_source_label(item),
            })
            # Rich provenance entry
            entry = _build_source_entry(item)
            entry["is_primary"] = (item is primary)
            provenance_entries.append(entry)

            # Merge metadata (engagement, discussion, etc.)
            for mk, mv in item.metadata.items():
                if mk not in primary.metadata or not primary.metadata[mk]:
                    primary.metadata[mk] = mv

            if item is not primary:
                # Promote a successful extraction found on a duplicate
                # before the content-append below, so primary.content
                # ends up as (promoted raw_content) + appended comments
                # rather than the promotion clobbering the append.
                merge_extraction_fields(primary, item)

            # Append content (e.g., comments from another source)
            if item is not primary and item.content:
                if primary.content and item.content not in primary.content:
                    primary.content = (primary.content or "") + f"\n\n--- From {item.source_type.value} ---\n" + item.content
            if item is not primary:
                merge_item_images(primary, item)

        # --- Select primary by provenance priority (not just content length) ---
        # Sort by SOURCE_ROLE_PRIORITY ascending (lower = more authoritative)
        provenance_entries.sort(
            key=lambda e: SOURCE_ROLE_PRIORITY.get(
                SourceRole(e.get("role", "unknown")), 10
            )
        )
        best = provenance_entries[0]
        # Mark the priority-selected entry as primary
        for entry in provenance_entries:
            is_primary = entry["source_url"] == best["source_url"]
            entry["is_primary"] = is_primary
        # Also update the backward-compat label list to mark primary
        for sd in all_sources_dicts:
            sd["is_primary"] = (
                best.get("source_name") == sd.get("label")
            )

        primary.metadata["merged_sources"] = all_sources_dicts
        # Store rich provenance for later aggregation by build_source_attribution
        primary.metadata["_cross_source_provenance"] = {
            "sources": provenance_entries,
        }
        merged.append(primary)

    return merged


async def merge_topic_duplicates(
    items: List[ContentItem], ai_config: AIConfig, console: Optional[Console] = None
) -> List[ContentItem]:
    """Merge items covering the same topic using AI semantic deduplication.

    This is a stable stage helper for integrations such as MCP.

    Sends all item titles, tags, and summaries to AI in a single call.
    Items must already be sorted by ai_score descending so that the first
    item in each duplicate group is always the highest-scored one.
    Content (comments) from duplicate items is merged into the primary.

    Parses the AI response for ``source_provenance`` to build rich source
    records.  Falls back to returning items unchanged if the AI call fails.
    """
    if len(items) <= 1:
        return items

    # Build the item list for the prompt — include URL so the AI can classify
    lines = []
    for i, item in enumerate(items):
        tags = ", ".join(item.ai_tags) if item.ai_tags else "—"
        summary = item.ai_summary or "—"
        lines.append(
            f"[{i}] {item.title}\n"
            f"    URL: {item.url}\n"
            f"    Tags: {tags}\n"
            f"    Summary: {summary}"
        )
    items_text = "\n\n".join(lines)

    try:
        ai_client = create_ai_client(ai_config)
        response = await ai_client.complete(
            system=TOPIC_DEDUP_SYSTEM,
            user=TOPIC_DEDUP_USER.format(items=items_text),
        )
        result = parse_json_response(response)
        if result is None:
            if console:
                console.print("[yellow]  dedup: could not parse AI response, skipping[/yellow]")
            return items

        duplicate_groups = result.get("duplicates", [])
        source_provenance_raw = result.get("source_provenance", {})
    except Exception as e:
        if console:
            console.print(f"[yellow]  dedup: AI call failed ({e}), skipping[/yellow]")
        return items

    if not duplicate_groups:
        return items

    def _build_topic_source_entry(item: ContentItem, discovered_via: str = "ai_topic_dedup", confidence: float = 0.85) -> dict:
        """Build a single source provenance entry for a topic-dedup item."""
        return {
            "source_name": sub_source_label(item),
            "source_url": str(item.url),
            "source_type": item.source_type.value,
            "role": classify_url_role(str(item.url)).value,
            "title": item.title,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "is_primary": False,
            "discovered_via": discovered_via,
            "confidence": confidence,
        }

    # Build a set of indices to drop (all non-primary duplicates)
    drop_indices: set[int] = set()
    for group in duplicate_groups:
        if not isinstance(group, list) or len(group) < 2:
            continue
        primary_idx = group[0]
        if primary_idx < 0 or primary_idx >= len(items):
            continue
        primary = items[primary_idx]
        primary_topic_sources: list[dict] = primary.metadata.setdefault("topic_coverage", [])

        # --- Collect source provenance for this group ---
        group_provenance: list[dict] = []
        # Primary item
        primary_entry = _build_topic_source_entry(primary)
        group_provenance.append(primary_entry)

        # Parse AI-provided provenance for this group if available
        ai_prov = source_provenance_raw.get(str(primary_idx))
        if isinstance(ai_prov, dict):
            # Apply AI-determined primary_source
            ai_primary = ai_prov.get("primary_source")
            if isinstance(ai_primary, dict):
                for entry in group_provenance:
                    if entry["source_url"] == ai_primary.get("url"):
                        entry["is_primary"] = True
                        entry["role"] = ai_primary.get("type", entry["role"])
            # Apply AI-classified source types
            ai_sources = ai_prov.get("sources", [])
            if isinstance(ai_sources, list):
                for ai_s in ai_sources:
                    if not isinstance(ai_s, dict):
                        continue
                    ai_url = ai_s.get("url", "")
                    for entry in group_provenance:
                        if entry["source_url"] == ai_url:
                            if ai_s.get("type"):
                                entry["role"] = ai_s["type"]
                            if ai_s.get("is_primary"):
                                entry["is_primary"] = True
                            break

            # Store merged_facts if provided
            merged_facts = ai_prov.get("merged_facts")
            if isinstance(merged_facts, list):
                existing = primary.metadata.setdefault("merged_facts", [])
                existing.extend(merged_facts)

        for dup_idx in group[1:]:
            if not isinstance(dup_idx, int) or dup_idx < 0 or dup_idx >= len(items):
                continue
            if dup_idx == primary_idx:
                continue
            dup = items[dup_idx]
            # Merge comments/content from the duplicate into the primary
            if dup.content:
                if not primary.content or dup.content not in primary.content:
                    label = dup.source_type.value
                    primary.content = (primary.content or "") + f"\n\n--- From {label} ---\n{dup.content}"
            merge_item_images(primary, dup)
            # Record source attribution for the dropped item (backward-compat)
            primary_topic_sources.append({
                "source_type": dup.source_type.value,
                "label": sub_source_label(dup),
                "title": dup.title,
                "url": str(dup.url),
            })
            # Rich provenance entry for duplicate
            dup_entry = _build_topic_source_entry(dup)
            group_provenance.append(dup_entry)
            if console:
                console.print(
                    f"   [dim]dedup: keep [{primary_idx}] {primary.title}[/dim]\n"
                    f"   [dim]       drop [{dup_idx}] {dup.title}[/dim]"
                )
            drop_indices.add(dup_idx)

        # --- Ensure primary_source is correctly identified by priority ---
        # Sort by provenance priority (lower = more authoritative)
        group_provenance.sort(
            key=lambda e: SOURCE_ROLE_PRIORITY.get(
                SourceRole(e.get("role", "unknown")), 10
            )
        )
        best_entry = group_provenance[0]
        for entry in group_provenance:
            entry["is_primary"] = entry["source_url"] == best_entry["source_url"]

        # Store for later aggregation
        topic_prov_groups: list[dict] = primary.metadata.setdefault(
            "_topic_provenance_groups", []
        )
        topic_prov_groups.append({
            "primary_source_name": best_entry["source_name"],
            "primary_source_url": best_entry["source_url"],
            "primary_source_type": best_entry["role"],
            "sources": group_provenance,
        })

    return [item for i, item in enumerate(items) if i not in drop_indices]

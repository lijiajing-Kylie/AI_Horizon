"""Per-category quota and global item-cap filtering for the final digest."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rich.console import Console

from .models import ContentItem, FilteringConfig


@dataclass
class BalancedDigestResult:
    """Items and selection statistics from balanced digest filtering."""

    items: List[ContentItem]
    enabled: bool = False
    group_counts: Dict[str, int] = field(default_factory=dict)
    group_limits: Dict[str, Optional[int]] = field(default_factory=dict)
    duplicate_categories: List[str] = field(default_factory=list)


def apply_balanced_digest(
    items: List[ContentItem],
    filtering: FilteringConfig,
    *,
    console: Optional[Console] = None,
    log: bool = True,
) -> BalancedDigestResult:
    """Apply configured category quotas and the final item cap.

    Categories are read from ``item.metadata["category"]``. If a category
    appears in more than one configured group, the first group in config
    order wins.
    """
    groups = filtering.category_groups
    max_items = filtering.max_items

    if not groups and max_items is None:
        return BalancedDigestResult(items=items)

    sorted_items = sorted(
        items,
        key=lambda item: item.ai_score or 0,
        reverse=True,
    )

    category_to_group: Dict[str, str] = {}
    duplicate_categories: List[str] = []
    for group_key, group in groups.items():
        for category in group.categories:
            if category in category_to_group:
                if category_to_group[category] != group_key:
                    duplicate_categories.append(category)
                continue
            category_to_group[category] = group_key

    if log and console:
        for category in sorted(set(duplicate_categories)):
            first_group = category_to_group[category]
            console.print(
                f"[yellow]Warning: category '{category}' is configured in multiple "
                f"groups; using '{first_group}'.[/yellow]"
            )

    selected: List[tuple[ContentItem, str]] = []
    group_counts: Dict[str, int] = defaultdict(int)
    default_group = filtering.default_group

    for item in sorted_items:
        category = item.metadata.get("category")
        group_key = (
            category_to_group.get(category, default_group)
            if isinstance(category, str)
            else default_group
        )

        if group_key in groups:
            limit = groups[group_key].limit
        else:
            limit = filtering.default_group_limit

        if limit is not None and group_counts[group_key] >= limit:
            continue

        selected.append((item, group_key))
        group_counts[group_key] += 1

    if max_items is not None:
        selected = selected[:max_items]

    final_counts: Dict[str, int] = defaultdict(int)
    for _, group_key in selected:
        final_counts[group_key] += 1

    group_limits: Dict[str, Optional[int]] = {
        group_key: group.limit for group_key, group in groups.items()
    }
    group_limits.setdefault(default_group, filtering.default_group_limit)

    if log and console:
        console.print(
            f"⚖️ Balanced digest selected {len(selected)}/{len(items)} items"
        )
        for group_key, group in groups.items():
            label = group.name or group_key
            console.print(
                f"      • {label}: {final_counts.get(group_key, 0)}/{group.limit}"
            )
        if (
            final_counts.get(default_group, 0)
            or filtering.default_group_limit is not None
        ):
            limit_label = (
                str(filtering.default_group_limit)
                if filtering.default_group_limit is not None
                else "unlimited"
            )
            console.print(
                f"      • {default_group}: "
                f"{final_counts.get(default_group, 0)}/{limit_label}"
            )
        console.print("")

    return BalancedDigestResult(
        items=[item for item, _ in selected],
        enabled=True,
        group_counts=dict(final_counts),
        group_limits=group_limits,
        duplicate_categories=sorted(set(duplicate_categories)),
    )

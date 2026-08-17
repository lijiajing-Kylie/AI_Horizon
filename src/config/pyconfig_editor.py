"""Surgical editor for ``data/config.py`` — updates ``sources['wxmp']`` in place.

Uses AST **only to locate** source ranges, then rewrites just the target
dict/list slices so comments and formatting everywhere else are preserved.
Never uses ``ast.unparse()`` on the whole file (it would drop comments).

Used by ``horizon-wxmp subscribe`` / ``migrate`` to write ``weread_mp_id``
into feeds and to toggle ``enabled``.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigEditError(ValueError):
    """Raised when the config structure cannot be located or edited safely."""


def _is_const_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant)


def _find_wxmp_dict(tree: ast.Module) -> ast.Dict:
    """Locate the ``sources['wxmp']`` dict node."""
    sources_assign = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "sources" for t in n.targets)
            and isinstance(n.value, ast.Dict)
        ),
        None,
    )
    if sources_assign is None:
        raise ConfigEditError("config 里没有顶层 `sources = {...}`")
    sources = sources_assign.value
    for k, v in zip(sources.keys, sources.values):
        if _is_const_literal(k) and getattr(k, "value", None) == "wxmp":
            if not isinstance(v, ast.Dict):
                raise ConfigEditError("sources['wxmp'] 不是 dict 字面量")
            return v
    raise ConfigEditError("config 里没有 sources['wxmp']")


def _find_feeds_list(wxmp: ast.Dict) -> ast.List:
    for k, v in zip(wxmp.keys, wxmp.values):
        if _is_const_literal(k) and getattr(k, "value", None) == "feeds":
            if not isinstance(v, ast.List):
                raise ConfigEditError("sources['wxmp']['feeds'] 不是 list")
            return v
    raise ConfigEditError("sources['wxmp'] 里没有 feeds 列表")


def _dict_fields(node: ast.Dict) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    for k, v in zip(node.keys, node.values):
        if not _is_const_literal(k):
            continue
        key = k.value
        try:
            fields[key] = ast.literal_eval(v)
        except (ValueError, TypeError):
            fields[key] = None
    return fields


def _feed_literal(fields: Dict[str, Any]) -> str:
    """Render a feed dict as a single-line literal matching the config style."""
    return json.dumps(fields, ensure_ascii=False)


def _element_indent(node: ast.AST) -> str:
    """Spaces matching a node's source column offset (for new lines)."""
    return " " * max(0, getattr(node, "col_offset", 0))


def _backup_and_write(path: Path, new_text: str) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    path.write_text(new_text, encoding="utf-8")


def update_wxmp_feed(
    config_path: Path | str,
    *,
    name: str,
    weread_mp_id: str,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Add or update one feed in ``sources['wxmp']['feeds']``.

    An existing feed is matched by ``name`` (case-insensitive); its other
    fields are preserved and ``weread_mp_id`` is set/updated. Otherwise a new
    entry is appended. Backs up to ``<config>.bak`` first.
    """
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    feeds = _find_feeds_list(_find_wxmp_dict(tree))

    # ── existing feed by name ────────────────────────────────────────────────
    for elt in feeds.elts:
        if not isinstance(elt, ast.Dict):
            continue
        fields = _dict_fields(elt)
        if str(fields.get("name", "")).lower() != name.lower():
            continue
        fields["weread_mp_id"] = weread_mp_id
        if category is not None:
            fields["category"] = category
        new_literal = _feed_literal(fields)
        seg = ast.get_source_segment(text, elt)
        if seg is None:
            raise ConfigEditError(f"无法定位 feed {name!r} 的源码片段")
        _backup_and_write(path, text.replace(seg, new_literal, 1))
        return fields

    # ── append new feed before the closing bracket ───────────────────────────
    indent = _element_indent(feeds.elts[0]) if feeds.elts else "            "
    new_literal = _feed_literal(
        {
            "name": name,
            "weread_mp_id": weread_mp_id,
            **({"category": category} if category is not None else {}),
        }
    )
    lines = text.splitlines(keepends=True)
    insert_idx = feeds.end_lineno - 1  # 0-based index of the ']' line
    if not (0 <= insert_idx < len(lines)):
        raise ConfigEditError("feeds 列表结束行定位失败")
    lines.insert(insert_idx, f"{indent}{new_literal},\n")
    _backup_and_write(path, "".join(lines))
    return {"name": name, "weread_mp_id": weread_mp_id}


def remove_wxmp_feed(config_path: Path | str, *, name: str) -> bool:
    """Remove a feed by ``name`` (case-insensitive) from ``feeds``.

    Returns True if removed, False if no matching feed was found. Backs up to
    ``<config>.bak`` first. The feed is a single-line dict literal in the
    config's style, so removal is a clean line deletion; the Python list stays
    valid (a preceding trailing comma is allowed by the grammar).
    """
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    feeds = _find_feeds_list(_find_wxmp_dict(tree))

    target = next(
        (elt for elt in feeds.elts if isinstance(elt, ast.Dict)
         and str(_dict_fields(elt).get("name", "")).lower() == name.lower()),
        None,
    )
    if target is None:
        return False

    lines = text.splitlines(keepends=True)
    del lines[target.lineno - 1 : target.end_lineno]
    _backup_and_write(path, "".join(lines))
    return True


def set_wxmp_enabled(config_path: Path | str, enabled: bool) -> None:
    """Set ``sources['wxmp']['enabled']`` to ``enabled`` in place.

    Replaces the ``"enabled": …`` value on the line INSIDE the wxmp dict's
    source range — a bare ``str.replace("False", …)`` would hit the first
    ``False`` anywhere in the file (e.g. another source's flag).
    """
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    wxmp = _find_wxmp_dict(tree)
    value = "True" if enabled else "False"
    lines = text.splitlines(keepends=True)
    for i in range(wxmp.lineno - 1, wxmp.end_lineno):
        if '"enabled"' not in lines[i]:
            continue
        new_line = re.sub(r'("enabled"\s*:\s*)(True|False)', rf"\g<1>{value}", lines[i])
        if new_line == lines[i]:
            raise ConfigEditError(f"无法替换 wxmp enabled 值（行 {i + 1}）")
        lines[i] = new_line
        _backup_and_write(path, "".join(lines))
        return
    raise ConfigEditError("sources['wxmp'] 里没有 enabled 字段")


def list_wxmp_feeds(config_path: Path | str) -> List[Dict[str, Any]]:
    """Return the current feeds as plain dicts (for status / migrate reconcile)."""
    path = Path(config_path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    feeds = _find_feeds_list(_find_wxmp_dict(tree))
    return [_dict_fields(elt) for elt in feeds.elts if isinstance(elt, ast.Dict)]

"""Sprint 9: ABICC-compatible HTML report generator.

Generates a self-contained HTML report that mirrors the structure of
abi-compliance-checker (ABICC) reports:

  - Verdict banner (BREAKING / COMPATIBLE / NO_CHANGE)
  - Binary Compatibility % metric (based on old exported symbol count)
  - Summary table: changes by category (functions, variables, types, enums, ELF)
  - Sectioned changes: Removed | Changed | Added (with anchored navigation)
  - Suppressed changes section (if any)
  - Demangled symbol names as display text, mangled as tooltip

No external CSS/JS dependencies — fully self-contained single HTML file.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING

from .checker import _BREAKING_KINDS as _CHECKER_BREAKING_KINDS_ENUM

if TYPE_CHECKING:
    from .checker import DiffResult

# ---------------------------------------------------------------------------
# Verdict styling — matches ABICC's visual palette
# ---------------------------------------------------------------------------

_VERDICT_STYLE: dict[str, tuple[str, str]] = {
    "BREAKING": ("#b71c1c", "#ffcdd2"),
    "COMPATIBLE": ("#1b5e20", "#c8e6c9"),
    "NO_CHANGE": ("#0d47a1", "#bbdefb"),
    "SOURCE_BREAK": ("#e65100", "#ffe0b2"),
}

# ---------------------------------------------------------------------------
# Change-kind classification helpers
# ---------------------------------------------------------------------------

#: Kinds that count as "removed" in the ABICC sense (symbol no longer available).
_REMOVED_KINDS: frozenset[str] = frozenset({
    "func_removed", "var_removed", "type_removed", "typedef_removed",
    "union_field_removed",
    "enum_member_removed",  # removing an enum member is ABI-breaking (callers rely on value)
})

#: Kinds that count as "added" (new API surface — compatible).
_ADDED_KINDS: frozenset[str] = frozenset({
    "func_added", "var_added", "type_added", "func_virtual_added",
    "enum_member_added", "union_field_added", "type_field_added",
    "type_field_added_compatible",
})

#: Kinds that are breaking but neither a simple removal nor addition.
_CHANGED_BREAKING_KINDS: frozenset[str] = frozenset({
    "func_params_changed", "func_return_changed",
    "func_virtual_removed", "func_virtual_became_pure",
    "func_pure_virtual_added", "func_static_changed", "func_cv_changed",
    "var_type_changed",
    "type_size_changed", "type_alignment_changed",
    "type_field_removed", "type_field_offset_changed", "type_field_type_changed",
    "type_base_changed", "type_vtable_changed",
    "enum_member_value_changed", "enum_last_member_value_changed",
    "enum_underlying_size_changed",
    "struct_size_changed", "struct_field_offset_changed", "struct_field_removed",
    "struct_field_type_changed", "struct_alignment_changed",
    "field_bitfield_changed",
    "calling_convention_changed", "struct_packing_changed",
    "func_visibility_changed",  # public→hidden: symbol removed from ABI
    "typedef_base_changed",
    "union_field_type_changed",
    "type_visibility_changed",
    # ELF-layer
    "soname_changed", "symbol_type_changed",
    "symbol_size_changed", "symbol_version_defined_removed",
})

#: Canonical breaking kinds imported from checker — single source of truth.
#: Converted to frozenset[str] (kind.value) so kind_str lookups work without
#: importing ChangeKind enum in this module.
_BREAKING_KINDS: frozenset[str] = frozenset(k.value for k in _CHECKER_BREAKING_KINDS_ENUM)

#: Category buckets for the summary table — mirrors ABICC section headers.
_CATEGORY_PREFIXES: list[tuple[str, tuple[str, ...]]] = [
    ("Functions",  ("func_",)),
    ("Variables",  ("var_",)),
    ("Types",      ("type_", "struct_", "union_", "field_", "typedef_")),
    ("Enums",      ("enum_",)),
    ("ELF / DWARF", ("soname_", "symbol_", "needed_", "rpath_", "runpath_",
                     "ifunc_", "common_", "dwarf_")),
]


def _category(kind_str: str) -> str:
    for label, prefixes in _CATEGORY_PREFIXES:
        if any(kind_str.startswith(p) for p in prefixes):
            return label
    return "Other"


def _is_breaking(change: object) -> bool:
    kind = getattr(change, "kind", None)
    kind_str = kind.value if kind is not None and hasattr(kind, "value") else str(kind)
    return kind_str in _BREAKING_KINDS


def _kind_str(change: object) -> str:
    kind = getattr(change, "kind", None)
    return kind.value if kind is not None and hasattr(kind, "value") else str(kind)


def _change_bucket(change: object) -> str:
    """Classify a change into 'removed', 'added', or 'changed'."""
    ks = _kind_str(change)
    if ks in _REMOVED_KINDS:
        return "removed"
    if ks in _ADDED_KINDS:
        return "added"
    return "changed"


# ---------------------------------------------------------------------------
# CSS — ABICC visual style, no external deps
# ---------------------------------------------------------------------------

_CSS = """\
*, *::before, *::after { box-sizing: border-box; }
body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f5f5f5; color: #212121; }

/* ---- header ---- */
.header { padding: 20px 32px; background: #263238; color: #fff; }
.header h1 { margin: 0 0 4px; font-size: 1.4em; letter-spacing: .02em; }
.header .meta { font-size: 0.88em; color: #b0bec5; }

/* ---- verdict banner ---- */
.verdict-box { margin: 20px 32px 0; padding: 14px 22px; border-radius: 6px; }
.verdict-box h2 { margin: 0 0 6px; font-size: 1.2em; }
.bc-metric { font-size: 1em; margin-top: 4px; }
.bc-metric strong { font-size: 1.1em; }

/* ---- nav bar ---- */
.nav { margin: 14px 32px 0; display: flex; gap: 8px; flex-wrap: wrap; }
.nav a { display: inline-block; padding: 5px 12px; border-radius: 4px;
          background: #eceff1; color: #37474f; font-size: 0.85em;
          text-decoration: none; border: 1px solid #cfd8dc; }
.nav a:hover { background: #cfd8dc; }
.nav a.breaking { background: #ffcdd2; border-color: #e57373; color: #b71c1c; }
.nav a.added    { background: #c8e6c9; border-color: #81c784; color: #1b5e20; }

/* ---- summary table ---- */
.summary-section { margin: 20px 32px 0; background: #fff; border-radius: 6px;
                   box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow: hidden; }
.summary-section h3 { margin: 0; padding: 10px 16px; background: #eceff1;
                      font-size: .95em; border-bottom: 1px solid #cfd8dc; }
.summary-table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
.summary-table th { background: #f5f5f5; padding: 7px 12px; text-align: left;
                    border-bottom: 2px solid #e0e0e0; }
.summary-table td { padding: 6px 12px; border-bottom: 1px solid #eeeeee; }
.summary-table tr:last-child td { border-bottom: none; }
.num { font-weight: bold; font-family: monospace; }
.num-red  { color: #b71c1c; }
.num-green { color: #1b5e20; }
.num-blue  { color: #1565c0; }

/* ---- change sections ---- */
.section { margin: 16px 32px 0; background: #fff; border-radius: 6px;
           box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow: hidden; }
.section h3 { margin: 0; padding: 10px 16px; font-size: .95em;
              border-bottom: 1px solid #cfd8dc; }
.section-removed h3 { background: #ffebee; color: #b71c1c; }
.section-changed h3 { background: #fff8e1; color: #e65100; }
.section-added   h3 { background: #e8f5e9; color: #1b5e20; }
.section-suppressed h3 { background: #f3e5f5; color: #6a1b9a; }

/* ---- changes table ---- */
table.changes { width: 100%; border-collapse: collapse; font-size: 0.87em; }
table.changes th { background: #fafafa; padding: 7px 12px; text-align: left;
                   border-bottom: 2px solid #e0e0e0; white-space: nowrap; }
table.changes td { padding: 7px 12px; border-bottom: 1px solid #eeeeee; vertical-align: top; }
table.changes tr:last-child td { border-bottom: none; }
.kind-badge { font-family: monospace; font-size: 0.82em; color: #37474f;
              background: #eceff1; padding: 2px 6px; border-radius: 3px;
              white-space: nowrap; }
.sym { font-family: monospace; font-size: 0.85em; }
.sym abbr { text-decoration: underline dotted #9e9e9e; cursor: help; }
.empty { padding: 14px 16px; color: #9e9e9e; font-style: italic; font-size: 0.88em; }
.cat-badge { font-size: 0.78em; background: #e3f2fd; color: #1565c0;
             padding: 1px 5px; border-radius: 3px; white-space: nowrap; }

/* ---- footer ---- */
footer { margin: 20px 32px 32px; padding: 12px 16px; font-size: 0.8em;
         color: #9e9e9e; border-top: 1px solid #e0e0e0; }
"""

# ---------------------------------------------------------------------------
# HTML generation helpers
# ---------------------------------------------------------------------------


def _symbol_cell(change: object) -> str:
    """Render symbol name: demangled text with mangled name as tooltip."""
    h = html.escape
    mangled = h(getattr(change, "symbol", "") or "")
    demangled = h(getattr(change, "demangled_symbol", "") or mangled)
    if demangled and demangled != mangled and mangled:
        return f"<abbr title='{mangled}'>{demangled}</abbr>"
    return demangled or mangled


def _changes_table(changes: list[object]) -> str:
    if not changes:
        return "<p class='empty'>No changes in this category.</p>"

    rows = []
    for ch in changes:
        ks = _kind_str(ch)
        cat = _category(ks)
        desc = html.escape(getattr(ch, "description", "") or "")
        old_val = html.escape(str(getattr(ch, "old_value", "") or ""))
        new_val = html.escape(str(getattr(ch, "new_value", "") or ""))
        sym_cell = _symbol_cell(ch)
        rows.append(
            f"<tr>"
            f"<td><span class='kind-badge'>{html.escape(ks)}</span></td>"
            f"<td class='sym'>{sym_cell}</td>"
            f"<td><span class='cat-badge'>{html.escape(cat)}</span></td>"
            f"<td>{desc}</td>"
            f"<td>{old_val}</td>"
            f"<td>{new_val}</td>"
            f"</tr>"
        )

    body = "\n".join(rows)
    return f"""<table class='changes'>
  <thead>
    <tr>
      <th>Kind</th><th>Symbol</th><th>Category</th>
      <th>Description</th><th>Old&nbsp;value</th><th>New&nbsp;value</th>
    </tr>
  </thead>
  <tbody>
    {body}
  </tbody>
</table>"""


def _summary_table(
    removed: list[object], changed: list[object], added: list[object], suppressed_count: int
) -> str:
    """Build category-level summary table (mirrors ABICC's overview section)."""

    # Count by category
    cats: dict[str, dict[str, int]] = {}
    for label, _ in _CATEGORY_PREFIXES:
        cats[label] = {"removed": 0, "changed": 0, "added": 0}
    cats["Other"] = {"removed": 0, "changed": 0, "added": 0}

    for ch in removed:
        cats[_category(_kind_str(ch))]["removed"] += 1
    for ch in changed:
        cats[_category(_kind_str(ch))]["changed"] += 1
    for ch in added:
        cats[_category(_kind_str(ch))]["added"] += 1

    rows = []
    for label in [lbl for lbl, _ in _CATEGORY_PREFIXES] + ["Other"]:
        c = cats[label]
        if c["removed"] == 0 and c["changed"] == 0 and c["added"] == 0:
            continue
        r = f"<span class='num num-red'>{c['removed']}</span>" if c["removed"] else "—"
        ch_n = f"<span class='num num-blue'>{c['changed']}</span>" if c["changed"] else "—"
        a = f"<span class='num num-green'>{c['added']}</span>" if c["added"] else "—"
        rows.append(f"<tr><td>{html.escape(label)}</td><td>{r}</td><td>{ch_n}</td><td>{a}</td></tr>")

    total_r = f"<span class='num num-red'>{len(removed)}</span>"
    total_ch = f"<span class='num num-blue'>{len(changed)}</span>"
    total_a = f"<span class='num num-green'>{len(added)}</span>"
    rows.append(
        f"<tr style='border-top:2px solid #e0e0e0; font-weight:bold;'>"
        f"<td>Total</td><td>{total_r}</td><td>{total_ch}</td><td>{total_a}</td></tr>"
    )

    if suppressed_count:
        rows.append(
            f"<tr><td colspan='4' style='color:#6a1b9a; font-size:0.85em; padding:6px 12px;'>"
            f"ℹ️ {suppressed_count} change(s) suppressed by suppression file</td></tr>"
        )

    body = "\n".join(rows)
    return f"""<div class='summary-section'>
  <h3>📊 Change Summary</h3>
  <table class='summary-table'>
    <thead>
      <tr><th>Category</th><th>Removed</th><th>Changed</th><th>Added</th></tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</div>"""


def _nav_bar(removed: list[object], changed: list[object], added: list[object], suppressed_count: int) -> str:
    links = []
    if removed:
        links.append(f"<a href='#removed' class='breaking'>⛔ Removed ({len(removed)})</a>")
    if changed:
        links.append(f"<a href='#changed' class='breaking'>⚠️ Changed ({len(changed)})</a>")
    if added:
        links.append(f"<a href='#added' class='added'>✅ Added ({len(added)})</a>")
    if suppressed_count:
        links.append(f"<a href='#suppressed'>🔕 Suppressed ({suppressed_count})</a>")
    if not links:
        return ""
    return "<div class='nav'>" + "".join(links) + "</div>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_html_report(
    result: DiffResult,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
    old_symbol_count: int | None = None,
) -> str:
    """Generate a standalone ABICC-compatible HTML ABI report.

    Args:
        result: DiffResult from checker.compare().
        lib_name: Library name for the report header.
        old_version: Old library version string.
        new_version: New library version string.
        old_symbol_count: Total exported public symbol count in the old library.
            Used to compute Binary Compatibility %. If None, approximated from
            changes (legacy behaviour).

    Returns:
        Complete self-contained HTML document as a string.
    """
    verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
    fg, bg = _VERDICT_STYLE.get(verdict, ("#212121", "#f5f5f5"))

    changes: list[object] = list(getattr(result, "changes", None) or [])
    suppressed: list[object] = list(getattr(result, "suppressed_changes", None) or [])
    suppressed_count: int = getattr(result, "suppressed_count", len(suppressed))

    # Split changes into buckets
    removed = [ch for ch in changes if _change_bucket(ch) == "removed"]
    added   = [ch for ch in changes if _change_bucket(ch) == "added"]
    changed = [ch for ch in changes if _change_bucket(ch) == "changed"]

    # Binary Compatibility %
    breaking_count = sum(1 for ch in changes if _is_breaking(ch))
    if breaking_count == 0:
        bc_pct = 100.0
    elif old_symbol_count is not None and old_symbol_count > 0:
        # ABICC-style: (total_old - breaking) / total_old * 100
        # Clamp to 0% if breaking exceeds symbol count (stale snapshot edge case)
        bc_pct = max(0.0, (old_symbol_count - breaking_count) / old_symbol_count * 100)
    else:
        # old_symbol_count is None or 0 — fall back to change-ratio approximation
        total = len(changes)
        bc_pct = max(0.0, (total - breaking_count) / total * 100) if total > 0 else 0.0

    h = html.escape
    lib_display  = h(lib_name)  if lib_name  else "library"
    old_display  = h(old_version) if old_version else "old"
    new_display  = h(new_version) if new_version else "new"

    # Verdict icon
    verdict_icon = {"BREAKING": "🔴", "COMPATIBLE": "🟢",
                    "NO_CHANGE": "🔵", "SOURCE_BREAK": "🟠"}.get(verdict, "⚪")

    summary_html = _summary_table(removed, changed, added, suppressed_count)
    nav_html     = _nav_bar(removed, changed, added, suppressed_count)

    def _section(title: str, anchor: str, css_class: str, items: list[object]) -> str:
        count = len(items)
        tbl = _changes_table(items)
        return (
            f"<div class='section {css_class}' id='{anchor}'>"
            f"<h3>{title} ({count})</h3>"
            f"{tbl}"
            f"</div>"
        )

    sections = []
    if removed:
        sections.append(_section("⛔ Removed Symbols", "removed", "section-removed", removed))
    if changed:
        sections.append(_section("⚠️ Changed Symbols", "changed", "section-changed", changed))
    if added:
        sections.append(_section("✅ Added Symbols", "added", "section-added", added))
    if suppressed:
        sections.append(_section("🔕 Suppressed Changes", "suppressed",
                                  "section-suppressed", suppressed))
    elif suppressed_count and not suppressed:
        # Count known but details not stored
        sections.append(
            f"<div class='section section-suppressed' id='suppressed'>"
            f"<h3>🔕 Suppressed Changes ({suppressed_count})</h3>"
            f"<p class='empty'>Details not available (suppressed_changes list is empty).</p>"
            f"</div>"
        )

    if not sections:
        sections.append(
            "<div class='section'><p class='empty'>"
            "No ABI changes detected between the two versions."
            "</p></div>"
        )

    sections_html = "\n".join(sections)

    symbol_count_note = ""
    if old_symbol_count:
        symbol_count_note = (
            f" / {old_symbol_count} exported symbols"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ABI Report: {lib_display} {old_display} → {new_display}</title>
  <style>{_CSS}</style>
</head>
<body>

<div class="header">
  <h1>ABI Compatibility Report — {lib_display}</h1>
  <div class="meta">
    {old_display} → {new_display} &nbsp;|&nbsp;
    Generated by <strong>abicheck</strong> (ABICC-compatible)
  </div>
</div>

<div class="verdict-box" style="background:{bg}; color:{fg}; border-left:6px solid {fg};">
  <h2>{verdict_icon} Verdict: {h(verdict)}</h2>
  <div class="bc-metric">
    Binary Compatibility: <strong>{bc_pct:.1f}%</strong>
    <span style="font-size:0.82em; opacity:0.75">
      ({breaking_count} breaking change(s){symbol_count_note})
    </span>
    &nbsp;&nbsp;
    <span style="font-size:0.85em;">
      Removed: <strong>{len(removed)}</strong>
      &nbsp;|&nbsp; Changed: <strong>{len(changed)}</strong>
      &nbsp;|&nbsp; Added: <strong>{len(added)}</strong>
    </span>
  </div>
</div>

{nav_html}
{summary_html}
{sections_html}

<footer>
  Generated by <strong>abicheck</strong> · ABICC-compatible report format ·
  <a href="https://github.com/napetrov/abicheck" style="color:#9e9e9e;">napetrov/abicheck</a>
</footer>

</body>
</html>
"""


def write_html_report(
    result: DiffResult,
    output_path: Path,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
    old_symbol_count: int | None = None,
) -> None:
    """Write HTML report to *output_path*, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html_report(
        result,
        lib_name=lib_name,
        old_version=old_version,
        new_version=new_version,
        old_symbol_count=old_symbol_count,
    )
    output_path.write_text(content, encoding="utf-8")

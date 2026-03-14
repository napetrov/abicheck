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
from typing import TYPE_CHECKING, cast

from .checker import _BREAKING_KINDS as _CHECKER_BREAKING_KINDS_ENUM
from .checker_policy import HasKind
from .report_summary import compatibility_metrics

if TYPE_CHECKING:
    from .checker import DiffResult

# ---------------------------------------------------------------------------
# Verdict styling — matches ABICC's visual palette
# ---------------------------------------------------------------------------

_VERDICT_STYLE: dict[str, tuple[str, str]] = {
    "BREAKING": ("#b71c1c", "#ffcdd2"),
    "COMPATIBLE_WITH_RISK": ("#e65100", "#fff3e0"),  # orange — deployment caution
    "COMPATIBLE": ("#1b5e20", "#c8e6c9"),
    "NO_CHANGE": ("#0d47a1", "#bbdefb"),
    "API_BREAK": ("#e65100", "#ffe0b2"),
}

# ---------------------------------------------------------------------------
# Change-kind classification helpers
# ---------------------------------------------------------------------------

#: Kinds that count as "removed" in the ABICC sense (symbol no longer available).
_REMOVED_KINDS: frozenset[str] = frozenset(
    {
        "func_removed",
        "var_removed",
        "type_removed",
        "typedef_removed",
        "union_field_removed",
        "enum_member_removed",  # removing an enum member is ABI-breaking (callers rely on value)
    }
)

#: Kinds that count as "added" (new API surface — compatible).
_ADDED_KINDS: frozenset[str] = frozenset(
    {
        "func_added",
        "var_added",
        "type_added",
        "func_virtual_added",
        "enum_member_added",
        "union_field_added",
        "type_field_added",
        "type_field_added_compatible",
    }
)

#: Kinds that are breaking but neither a simple removal nor addition.
_CHANGED_BREAKING_KINDS: frozenset[str] = frozenset(
    {
        "func_params_changed",
        "func_return_changed",
        "func_virtual_removed",
        "func_virtual_became_pure",
        "func_pure_virtual_added",
        "func_static_changed",
        "func_cv_changed",
        "var_type_changed",
        "type_size_changed",
        "type_alignment_changed",
        "type_field_removed",
        "type_field_offset_changed",
        "type_field_type_changed",
        "type_base_changed",
        "type_vtable_changed",
        "enum_member_value_changed",
        "enum_last_member_value_changed",
        "enum_underlying_size_changed",
        "struct_size_changed",
        "struct_field_offset_changed",
        "struct_field_removed",
        "struct_field_type_changed",
        "struct_alignment_changed",
        "field_bitfield_changed",
        "calling_convention_changed",
        "struct_packing_changed",
        "func_visibility_changed",  # public→hidden: symbol removed from ABI
        "typedef_base_changed",
        "union_field_type_changed",
        "type_visibility_changed",
        # ELF-layer
        "soname_changed",
        "symbol_type_changed",
        "symbol_size_changed",
        "symbol_version_defined_removed",
    }
)

#: Canonical breaking kinds imported from checker — single source of truth.
#: Converted to frozenset[str] (kind.value) so kind_str lookups work without
#: importing ChangeKind enum in this module.
_BREAKING_KINDS: frozenset[str] = frozenset(
    k.value for k in _CHECKER_BREAKING_KINDS_ENUM
)

#: Category buckets for the summary table — mirrors ABICC section headers.
_CATEGORY_PREFIXES: list[tuple[str, tuple[str, ...]]] = [
    ("Functions", ("func_",)),
    ("Variables", ("var_",)),
    ("Types", ("type_", "struct_", "union_", "field_", "typedef_")),
    ("Enums", ("enum_",)),
    (
        "ELF / DWARF",
        (
            "soname_",
            "symbol_",
            "needed_",
            "rpath_",
            "runpath_",
            "ifunc_",
            "common_",
            "dwarf_",
        ),
    ),
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


def _file_metadata_html(result: object) -> str:
    """Render library file metadata (path, SHA-256, size) as an HTML table."""
    old_meta = getattr(result, "old_metadata", None)
    new_meta = getattr(result, "new_metadata", None)
    if not old_meta and not new_meta:
        return ""
    h = html.escape

    def _row(label: str, old_val: str, new_val: str) -> str:
        return f"<tr><th>{label}</th><td>{h(old_val)}</td><td>{h(new_val)}</td></tr>"

    old_path = getattr(old_meta, "path", "—") if old_meta else "—"
    new_path = getattr(new_meta, "path", "—") if new_meta else "—"
    old_sha = getattr(old_meta, "sha256", "—") if old_meta else "—"
    new_sha = getattr(new_meta, "sha256", "—") if new_meta else "—"
    old_size = str(getattr(old_meta, "size_bytes", 0)) if old_meta else "—"
    new_size = str(getattr(new_meta, "size_bytes", 0)) if new_meta else "—"

    return f"""<div class='summary-section'>
  <h3>Library Files</h3>
  <table class='summary-table'>
    <thead><tr><th></th><th>Old</th><th>New</th></tr></thead>
    <tbody>
      {_row("Path", old_path, new_path)}
      {_row("SHA-256", old_sha[:16] + "…", new_sha[:16] + "…")}
      {_row("Size (bytes)", old_size, new_size)}
    </tbody>
  </table>
</div>"""


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

    from .checker_policy import impact_for as _impact_for

    rows = []
    for ch in changes:
        ks = _kind_str(ch)
        cat = _category(ks)
        desc = html.escape(getattr(ch, "description", "") or "")
        old_val = html.escape(str(getattr(ch, "old_value", "") or ""))
        new_val = html.escape(str(getattr(ch, "new_value", "") or ""))
        sym_cell = _symbol_cell(ch)
        loc = getattr(ch, "source_location", None)
        affected = getattr(ch, "affected_symbols", None)

        # Build extended description with impact + affected + location
        desc_parts = [desc]
        kind = getattr(ch, "kind", None)
        if kind:
            impact = _impact_for(kind)
            if impact:
                desc_parts.append(
                    f"<div style='font-size:0.85em; color:#666; margin-top:3px;'>"
                    f"💡 {html.escape(impact)}</div>"
                )
        if affected:
            names = ", ".join(html.escape(s) for s in affected[:5])
            suffix = f" (+{len(affected) - 5} more)" if len(affected) > 5 else ""
            desc_parts.append(
                f"<div style='font-size:0.82em; color:#1565c0; margin-top:2px;'>"
                f"📎 Affected: <code>{names}</code>{suffix}</div>"
            )
        if loc:
            desc_parts.append(
                f"<div style='font-size:0.82em; color:#999; margin-top:2px;'>"
                f"📍 {html.escape(loc)}</div>"
            )
        full_desc = "".join(desc_parts)

        rows.append(
            f"<tr>"
            f"<td><span class='kind-badge'>{html.escape(ks)}</span></td>"
            f"<td class='sym'>{sym_cell}</td>"
            f"<td><span class='cat-badge'>{html.escape(cat)}</span></td>"
            f"<td>{full_desc}</td>"
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
    removed: list[object],
    changed: list[object],
    added: list[object],
    suppressed_count: int,
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
        ch_n = (
            f"<span class='num num-blue'>{c['changed']}</span>" if c["changed"] else "—"
        )
        a = f"<span class='num num-green'>{c['added']}</span>" if c["added"] else "—"
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td>{r}</td><td>{ch_n}</td><td>{a}</td></tr>"
        )

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


def _nav_bar(
    removed: list[object],
    changed: list[object],
    added: list[object],
    suppressed_count: int,
) -> str:
    links = []
    if removed:
        links.append(
            f"<a href='#removed' class='breaking'>⛔ Removed ({len(removed)})</a>"
        )
    if changed:
        links.append(
            f"<a href='#changed' class='breaking'>⚠️ Changed ({len(changed)})</a>"
        )
    if added:
        links.append(f"<a href='#added' class='added'>✅ Added ({len(added)})</a>")
    if suppressed_count:
        links.append(f"<a href='#suppressed'>🔕 Suppressed ({suppressed_count})</a>")
    if not links:
        return ""
    return "<div class='nav'>" + "".join(links) + "</div>"


# ---------------------------------------------------------------------------
# ABICC severity classification (imported from xml_report for consistency)
# ---------------------------------------------------------------------------

_HIGH_SEVERITY_KINDS: frozenset[str] = frozenset(
    {
        "func_removed",
        "var_removed",
        "type_removed",
        "typedef_removed",
        "type_size_changed",
        "type_vtable_changed",
        "type_base_changed",
        "struct_size_changed",
        "func_virtual_removed",
        "func_pure_virtual_added",
        "func_virtual_became_pure",
        "base_class_position_changed",
        "base_class_virtual_changed",
        "type_kind_changed",
        "func_deleted",
    }
)

_MEDIUM_SEVERITY_KINDS: frozenset[str] = frozenset(
    {
        "func_return_changed",
        "func_params_changed",
        "type_field_offset_changed",
        "type_field_type_changed",
        "type_field_removed",
        "type_alignment_changed",
        "struct_field_offset_changed",
        "struct_field_removed",
        "struct_field_type_changed",
        "struct_alignment_changed",
        "var_type_changed",
        "calling_convention_changed",
        "soname_changed",
        "symbol_type_changed",
        "symbol_version_defined_removed",
        "return_pointer_level_changed",
        "param_pointer_level_changed",
        "union_field_removed",
        "union_field_type_changed",
        "typedef_base_changed",
        "struct_packing_changed",
    }
)


def _severity(kind_str: str) -> str:
    if kind_str in _HIGH_SEVERITY_KINDS:
        return "High"
    if kind_str in _MEDIUM_SEVERITY_KINDS:
        return "Medium"
    return "Low"


def _is_type_problem(kind_str: str) -> bool:
    return any(
        kind_str.startswith(p)
        for p in (
            "type_",
            "struct_",
            "union_",
            "field_",
            "typedef_",
            "enum_",
            "base_class_",
        )
    )


def _is_symbol_problem(kind_str: str) -> bool:
    return any(kind_str.startswith(p) for p in ("func_", "var_"))


# ---------------------------------------------------------------------------
# ABICC-compatible HTML (compat_html mode)
# ---------------------------------------------------------------------------

_COMPAT_CSS = """\
body { font-family: Arial, sans-serif; margin: 0; padding: 20px; color: #333; }
h1 { font-size: 1.6em; }
h2 { font-size: 1.2em; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 24px; }
table.summary { border-collapse: collapse; margin: 8px 0; }
table.summary td, table.summary th { padding: 4px 12px; border: 1px solid #ddd; }
table.summary th { background: #f5f5f5; text-align: left; }
td.compatible { color: #1b5e20; font-weight: bold; }
td.incompatible { color: #b71c1c; font-weight: bold; }
td.warning { color: #e65100; font-weight: bold; }
table.problem { border-collapse: collapse; width: 100%; margin: 8px 0; }
table.problem td, table.problem th { padding: 4px 8px; border: 1px solid #ddd; vertical-align: top; }
table.problem th { background: #f5f5f5; text-align: left; }
.sym { font-family: monospace; font-size: 0.9em; }
"""


def _compat_changes_table(items: list[object], show_severity: bool = False) -> str:
    """Render a changes table in ABICC style."""
    if not items:
        return "<p>No changes.</p>"
    h = html.escape
    rows = []
    for ch in items:
        ks = _kind_str(ch)
        sym = h(getattr(ch, "symbol", "") or "")
        desc = h(getattr(ch, "description", "") or "")
        old_val = h(str(getattr(ch, "old_value", "") or ""))
        new_val = h(str(getattr(ch, "new_value", "") or ""))
        sev_cell = f"<td>{_severity(ks)}</td>" if show_severity else ""
        rows.append(
            f"<tr><td class='sym'>{sym}</td><td>{h(ks)}</td>"
            f"{sev_cell}<td>{desc}</td><td>{old_val}</td><td>{new_val}</td></tr>"
        )
    sev_hdr = "<th>Severity</th>" if show_severity else ""
    return (
        f"<table class='problem'><thead><tr>"
        f"<th>Symbol</th><th>Kind</th>{sev_hdr}"
        f"<th>Description</th><th>Old</th><th>New</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _generate_compat_html(
    result: object,
    changes: list[object],
    removed: list[object],
    changed: list[object],
    added: list[object],
    suppressed: list[object],
    suppressed_count: int,
    bc_pct: float,
    affected_pct: float,
    breaking_count: int,
    verdict: str,
    lib_display: str,
    old_display: str,
    new_display: str,
    old_symbol_count: int | None,
    title: str | None,
    report_kind: str = "binary",
) -> str:
    """Generate ABICC-compatible HTML with matching element IDs and structure.

    Produces HTML with the same DOM IDs and section structure that ABICC
    report parsers expect: #Title, #Summary, #Added, #Removed,
    #TypeProblems_High, etc.

    Also embeds the META_DATA comment that ABICC includes for machine parsing.

    Args:
        report_kind: "binary" or "source" — controls title, META_DATA kind, and
            section ID prefixes to match ABICC's per-kind report structure.
    """
    h = html.escape

    # Classify type vs symbol problems by severity
    type_problems: dict[str, list[object]] = {"High": [], "Medium": [], "Low": []}
    symbol_problems: dict[str, list[object]] = {"High": [], "Medium": [], "Low": []}
    for ch in changed:
        ks = _kind_str(ch)
        sev = _severity(ks)
        if _is_type_problem(ks):
            type_problems[sev].append(ch)
        else:
            symbol_problems[sev].append(ch)

    # Counts for META_DATA
    tp_high = len(type_problems["High"])
    tp_med = len(type_problems["Medium"])
    tp_low = len(type_problems["Low"])
    sp_high = len(symbol_problems["High"])
    sp_med = len(symbol_problems["Medium"])
    sp_low = len(symbol_problems["Low"])

    compat_verdict = (
        "incompatible" if verdict in ("BREAKING", "API_BREAK") else "compatible"
    )
    bc_css = (
        "incompatible" if bc_pct < 90 else ("warning" if bc_pct < 100 else "compatible")
    )
    affected_pct_label = f"{affected_pct:.1f}" if old_symbol_count else "0"

    kind_label = report_kind.capitalize()  # "Binary" or "Source"

    # META_DATA comment (semicolon-delimited, matches ABICC format)
    meta_data = (
        f"verdict:{compat_verdict};kind:{report_kind};"
        f"affected:{affected_pct_label};"
        f"added:{len(added)};removed:{len(removed)};"
        f"type_problems_high:{tp_high};"
        f"type_problems_medium:{tp_med};"
        f"type_problems_low:{tp_low};"
        f"interface_problems_high:{sp_high};"
        f"interface_problems_medium:{sp_med};"
        f"interface_problems_low:{sp_low};"
        f"changed_constants:0;"
        f"tool_version:abicheck"
    )

    # Build title matching ABICC convention
    abicc_title = (
        h(title)
        if title
        else f"{kind_label} compatibility report for the <b>{lib_display}</b> "
        f"library between <b>{old_display}</b> and <b>{new_display}</b> versions"
    )

    # Build sections
    sections_html = []

    # Problem Summary
    sections_html.append(f"""
<div id='Summary'>
<h2>Test Info</h2>
<table class='summary'>
<tr><th>Library Name</th><td>{lib_display}</td></tr>
<tr><th>Version #1</th><td>{old_display}</td></tr>
<tr><th>Version #2</th><td>{new_display}</td></tr>
</table>
{_file_metadata_html(result)}

<h2>Test Results</h2>
<table class='summary'>
<tr><th>Total Symbols</th><td>{old_symbol_count or "N/A"}</td></tr>
<tr><th>{kind_label} Compatibility</th><td class='{bc_css}'>{bc_pct:.1f}%</td></tr>
<tr><th>Verdict</th><td class='{bc_css}'>{compat_verdict}</td></tr>
</table>

<h2>Problem Summary</h2>
<table class='summary'>
<tr><th></th><th>High</th><th>Medium</th><th>Low</th></tr>
<tr><th>Type Problems</th><td>{tp_high}</td><td>{tp_med}</td><td>{tp_low}</td></tr>
<tr><th>Interface Problems</th><td>{sp_high}</td><td>{sp_med}</td><td>{sp_low}</td></tr>
<tr><th>Added Symbols</th><td colspan='3'>{len(added)}</td></tr>
<tr><th>Removed Symbols</th><td colspan='3'>{len(removed)}</td></tr>
</table>
</div>""")

    # Added symbols section
    if added:
        sections_html.append(f"""
<div id='Added'>
<h2>Added Symbols ({len(added)})</h2>
{_compat_changes_table(added)}
</div>""")

    # Removed symbols section
    if removed:
        sections_html.append(f"""
<div id='Removed'>
<h2>Removed Symbols ({len(removed)})</h2>
{_compat_changes_table(removed)}
</div>""")

    # Type problems by severity
    for sev in ("High", "Medium", "Low"):
        items = type_problems[sev]
        if items:
            sections_html.append(f"""
<div id='TypeProblems_{sev}'>
<h2>Problems with Data Types — {sev} Severity ({len(items)})</h2>
{_compat_changes_table(items, show_severity=True)}
</div>""")

    # Interface (symbol) problems by severity
    for sev in ("High", "Medium", "Low"):
        items = symbol_problems[sev]
        if items:
            sections_html.append(f"""
<div id='InterfaceProblems_{sev}'>
<h2>Problems with Symbols — {sev} Severity ({len(items)})</h2>
{_compat_changes_table(items, show_severity=True)}
</div>""")

    body_html = "\n".join(sections_html)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{kind_label} compatibility report for {lib_display} between {old_display} and {new_display}</title>
<style>{_COMPAT_CSS}</style>
</head>
<body>
<!-- {meta_data} -->
<div id='Title'>
<h1>{abicc_title}</h1>
</div>
{body_html}
<br/>
<hr/>
<p style="font-size:0.85em; color:#999;">
Generated by <b>abicheck</b> (ABICC-compatible mode)
</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_html_report(
    result: DiffResult,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
    old_symbol_count: int | None = None,
    title: str | None = None,
    compat_html: bool = False,
    report_kind: str = "binary",
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
    verdict = (
        result.verdict.value
        if hasattr(result.verdict, "value")
        else str(result.verdict)
    )
    fg, bg = _VERDICT_STYLE.get(verdict, ("#212121", "#f5f5f5"))

    changes: list[object] = list(getattr(result, "changes", None) or [])
    suppressed: list[object] = list(getattr(result, "suppressed_changes", None) or [])
    suppressed_count: int = getattr(result, "suppressed_count", len(suppressed))

    # Split changes into buckets
    removed = [ch for ch in changes if _change_bucket(ch) == "removed"]
    added = [ch for ch in changes if _change_bucket(ch) == "added"]
    changed = [ch for ch in changes if _change_bucket(ch) == "changed"]

    metrics = compatibility_metrics(cast(list[HasKind], changes), old_symbol_count)
    breaking_count = metrics.breaking_count
    bc_pct = metrics.binary_compatibility_pct
    affected_pct = metrics.affected_pct

    h = html.escape
    lib_display = h(lib_name) if lib_name else "library"
    old_display = h(old_version) if old_version else "old"
    new_display = h(new_version) if new_version else "new"

    if compat_html:
        return _generate_compat_html(
            result,
            changes,
            removed,
            changed,
            added,
            suppressed,
            suppressed_count,
            bc_pct,
            affected_pct,
            breaking_count,
            verdict,
            lib_display,
            old_display,
            new_display,
            old_symbol_count,
            title,
            report_kind=report_kind,
        )

    # Verdict icon
    verdict_icon = {
        "BREAKING": "🔴",
        "COMPATIBLE": "🟢",
        "NO_CHANGE": "🔵",
        "API_BREAK": "🟠",
    }.get(verdict, "⚪")

    summary_html = _summary_table(removed, changed, added, suppressed_count)
    nav_html = _nav_bar(removed, changed, added, suppressed_count)

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
        sections.append(
            _section("⛔ Removed Symbols", "removed", "section-removed", removed)
        )
    if changed:
        sections.append(
            _section("⚠️ Changed Symbols", "changed", "section-changed", changed)
        )
    if added:
        sections.append(_section("✅ Added Symbols", "added", "section-added", added))
    if suppressed:
        sections.append(
            _section(
                "🔕 Suppressed Changes", "suppressed", "section-suppressed", suppressed
            )
        )
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
        symbol_count_note = f" / {old_symbol_count} exported symbols"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title) if title else f"ABI Report: {lib_display} {old_display} → {new_display}"}</title>
  <style>{_CSS}</style>
</head>
<body>

<div class="header">
  <h1>{h(title) if title else f"ABI Compatibility Report — {lib_display}"}</h1>
  <div class="meta">
    {old_display} → {new_display} &nbsp;|&nbsp;
    Generated by <strong>abicheck</strong> (ABICC-compatible)
  </div>
  {_file_metadata_html(result)}
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
    title: str | None = None,
    compat_html: bool = False,
    report_kind: str = "binary",
) -> None:
    """Write HTML report to *output_path*, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html_report(
        result,
        lib_name=lib_name,
        old_version=old_version,
        new_version=new_version,
        old_symbol_count=old_symbol_count,
        title=title,
        compat_html=compat_html,
        report_kind=report_kind,
    )
    output_path.write_text(content, encoding="utf-8")

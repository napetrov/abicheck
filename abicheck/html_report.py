"""Sprint 5: HTML report generator for ABI comparison results.

Generates a self-contained HTML report (no external CSS/JS dependencies)
matching the structure of ABICC reports:
- Verdict banner (BREAKING / COMPATIBLE / NO_CHANGE)
- Binary Compatibility % metric
- Changes table (kind, symbol, description, old/new value)
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .checker import DiffResult as CompareResult

# Verdict colours matching ABICC's visual style
_VERDICT_STYLE: dict[str, tuple[str, str]] = {
    "BREAKING":   ("#b71c1c", "#ffcdd2"),
    "COMPATIBLE": ("#1b5e20", "#c8e6c9"),
    "NO_CHANGE":  ("#0d47a1", "#bbdefb"),
}

_CSS = """
body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
.header { padding: 24px 32px; background: #263238; color: #fff; }
.header h1 { margin: 0 0 4px; font-size: 1.5em; }
.header .meta { font-size: 0.9em; color: #b0bec5; }
.verdict-box { margin: 24px 32px; padding: 16px 24px; border-radius: 6px; }
.verdict-box h2 { margin: 0 0 4px; font-size: 1.3em; }
.bc-metric { font-size: 1.1em; margin-top: 8px; }
.section { margin: 0 32px 24px; background: #fff; border-radius: 6px;
           box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow: hidden; }
.section h3 { margin: 0; padding: 12px 16px; background: #eceff1;
              font-size: 1em; border-bottom: 1px solid #cfd8dc; }
table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
th { background: #f5f5f5; padding: 8px 12px; text-align: left;
     border-bottom: 2px solid #e0e0e0; }
td { padding: 8px 12px; border-bottom: 1px solid #eeeeee; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.kind { font-family: monospace; font-size: 0.85em; color: #37474f;
        background: #eceff1; padding: 2px 6px; border-radius: 3px; }
.breaking { color: #b71c1c; font-weight: bold; }
.compatible { color: #1b5e20; }
.sym { font-family: monospace; }
.empty { padding: 16px; color: #9e9e9e; font-style: italic; }
footer { padding: 16px 32px; font-size: 0.8em; color: #9e9e9e; }
"""


def generate_html_report(
    result: CompareResult,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
) -> str:
    """Generate a standalone HTML ABI comparison report.

    Args:
        result: CompareResult from checker.compare().
        lib_name: Library name for the report header.
        old_version: Old library version string.
        new_version: New library version string.

    Returns:
        Complete HTML document as a string.
    """
    verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
    fg, bg = _VERDICT_STYLE.get(verdict, ("#212121", "#f5f5f5"))
    changes = getattr(result, "changes", []) or []

    # Derive summary from changes list (DiffResult has no pre-computed summary field)
    breaking = sum(1 for ch in changes if _is_breaking(ch))
    compatible_add = sum(1 for ch in changes if not _is_breaking(ch))
    total = len(changes)

    # BC% = exported symbols with no breaking change / total exported
    # We approximate: if no breaking changes, 100%; otherwise use breaking count.
    if breaking == 0:
        bc_pct = 100.0
    elif total > 0:
        bc_pct = max(0.0, (total - breaking) / total * 100)
    else:
        bc_pct = 0.0

    h = html.escape
    lib_display = h(lib_name) if lib_name else "library"
    old_display = h(old_version) if old_version else "old"
    new_display = h(new_version) if new_version else "new"

    changes_rows = ""
    if changes:
        for ch in changes:
            kind = getattr(ch, "kind", None)
            kind_str = kind.value if kind is not None and hasattr(kind, "value") else str(kind)
            sym = h(getattr(ch, "symbol", "") or "")
            desc = h(getattr(ch, "description", "") or "")
            old_val = h(str(getattr(ch, "old_value", "") or ""))
            new_val = h(str(getattr(ch, "new_value", "") or ""))
            row_class = "breaking" if kind_str in _BREAKING_KINDS else "compatible"
            changes_rows += (
                f"<tr>"
                f"<td><span class='kind'>{h(kind_str)}</span></td>"
                f"<td class='sym {row_class}'>{sym}</td>"
                f"<td>{desc}</td>"
                f"<td>{old_val}</td>"
                f"<td>{new_val}</td>"
                f"</tr>\n"
            )
    else:
        changes_rows = "<tr><td colspan='5' class='empty'>No changes detected.</td></tr>"

    table = f"""
    <table>
      <thead>
        <tr>
          <th>Kind</th><th>Symbol</th><th>Description</th>
          <th>Old value</th><th>New value</th>
        </tr>
      </thead>
      <tbody>
        {changes_rows}
      </tbody>
    </table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ABI Report: {lib_display} {old_display} → {new_display}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <h1>ABI Compatibility Report</h1>
    <div class="meta">
      Library: <strong>{lib_display}</strong> &nbsp;|&nbsp;
      {old_display} → {new_display} &nbsp;|&nbsp;
      Generated by <strong>abicheck</strong>
    </div>
  </div>

  <div class="verdict-box" style="background:{bg}; color:{fg}; border-left: 6px solid {fg};">
    <h2>Verdict: {h(verdict)}</h2>
    <div class="bc-metric">
      Binary Compatibility: <strong>{bc_pct:.1f}%</strong> &nbsp;|&nbsp;
      Breaking: {breaking} &nbsp;|&nbsp;
      Compatible additions: {compatible_add} &nbsp;|&nbsp;
      Total changes: {total}
    </div>
  </div>

  <div class="section">
    <h3>Changes ({total})</h3>
    {table}
  </div>

  <footer>Generated by abicheck · ABICC-compatible report format</footer>
</body>
</html>
"""


def _is_breaking(change: object) -> bool:
    kind = getattr(change, "kind", None)
    kind_str = kind.value if kind is not None and hasattr(kind, "value") else str(kind)
    return kind_str in _BREAKING_KINDS


# Set of kind strings that are considered breaking (for row colouring)
_BREAKING_KINDS: frozenset[str] = frozenset({
    "func_removed", "func_params_changed", "func_return_changed",
    "func_noexcept_removed", "type_size_changed", "struct_size_changed",
    "struct_field_removed", "struct_field_offset_changed", "struct_field_type_changed",
    "struct_alignment_changed", "type_vtable_changed", "enum_underlying_size_changed",
    "enum_member_value_changed", "enum_member_removed", "calling_convention_changed",
    "struct_packing_changed", "type_visibility_changed", "qualifier_removed",
    "union_field_removed", "bitfield_size_changed",
})


def write_html_report(
    result: CompareResult,
    output_path: Path,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
) -> None:
    """Write HTML report to *output_path*, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html_report(result, lib_name=lib_name,
                                   old_version=old_version, new_version=new_version)
    output_path.write_text(content, encoding="utf-8")

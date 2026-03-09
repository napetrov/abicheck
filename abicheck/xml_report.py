"""ABICC-compatible XML report generator.

Produces XML reports that match the structure expected by abi-compliance-checker
consumers (abi-tracker, lvc-monitor, Fedora/openSUSE ABI infrastructure).

The ABICC XML report schema:

    <report version="1.2" library="LIBNAME" version1="V1" version2="V2">
      <binary>
        <compatible>XX.X</compatible>
        <problems_with_types>N</problems_with_types>
        <problems_with_symbols>N</problems_with_symbols>
        <problems_total>N</problems_total>
        <removed>N</removed>
        <added>N</added>
        <warnings>N</warnings>
        <affected>N</affected>
      </binary>
      <source>
        <compatible>XX.X</compatible>
        <problems_with_types>N</problems_with_types>
        <problems_with_symbols>N</problems_with_symbols>
        <problems_total>N</problems_total>
        <removed>N</removed>
        <added>N</added>
        <warnings>N</warnings>
        <affected>N</affected>
      </source>
    </report>
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

from .checker import _BREAKING_KINDS as _CHECKER_BREAKING_KINDS_ENUM

if TYPE_CHECKING:
    from .checker import DiffResult

# ABICC XML report version
_REPORT_VERSION = "1.2"

# ── Change-kind classification for ABICC XML report ─────────────────────────

#: Kinds involving type changes (problems_with_types).
_TYPE_PROBLEM_PREFIXES = (
    "type_", "struct_", "union_", "field_", "typedef_", "enum_",
)

#: Kinds involving symbol/interface changes (problems_with_symbols).
_SYMBOL_PROBLEM_PREFIXES = (
    "func_", "var_",
)

#: Kinds that count as "removed" in ABICC's XML report.
_REMOVED_KINDS: frozenset[str] = frozenset({
    "func_removed", "var_removed", "type_removed", "typedef_removed",
    "union_field_removed", "enum_member_removed",
})

#: Kinds that count as "added" in ABICC's XML report.
_ADDED_KINDS: frozenset[str] = frozenset({
    "func_added", "var_added", "type_added", "func_virtual_added",
    "enum_member_added", "union_field_added", "type_field_added",
    "type_field_added_compatible",
})

#: Binary-only kinds (excluded from source compatibility section).
_BINARY_ONLY_KINDS: frozenset[str] = frozenset({
    "soname_changed", "needed_added", "needed_removed",
    "rpath_changed", "runpath_changed",
    "symbol_binding_changed", "symbol_binding_strengthened",
    "symbol_type_changed", "symbol_size_changed",
    "ifunc_introduced", "ifunc_removed", "common_symbol_risk",
    "symbol_version_defined_removed",
    "symbol_version_required_added", "symbol_version_required_removed",
    "dwarf_info_missing", "toolchain_flag_drift",
})

#: Canonical breaking kinds from checker (single source of truth).
_BREAKING_KINDS: frozenset[str] = frozenset(k.value for k in _CHECKER_BREAKING_KINDS_ENUM)


def _kind_str(change: object) -> str:
    kind = getattr(change, "kind", None)
    return kind.value if kind is not None and hasattr(kind, "value") else str(kind)


def _is_breaking(change: object) -> bool:
    return _kind_str(change) in _BREAKING_KINDS


def _is_type_problem(kind_str: str) -> bool:
    return any(kind_str.startswith(p) for p in _TYPE_PROBLEM_PREFIXES)


def _is_symbol_problem(kind_str: str) -> bool:
    return any(kind_str.startswith(p) for p in _SYMBOL_PROBLEM_PREFIXES)


def _compute_section(
    changes: list[object],
    old_symbol_count: int | None,
    *,
    exclude_binary_only: bool = False,
) -> dict[str, str]:
    """Compute counts for one section (binary or source) of the XML report."""
    filtered = changes
    if exclude_binary_only:
        filtered = [c for c in changes if _kind_str(c) not in _BINARY_ONLY_KINDS]

    breaking = [c for c in filtered if _is_breaking(c)]
    removed = [c for c in filtered if _kind_str(c) in _REMOVED_KINDS]
    added = [c for c in filtered if _kind_str(c) in _ADDED_KINDS]
    # "problems" = breaking changes that are not simple removals/additions
    problems = [c for c in breaking if _kind_str(c) not in _REMOVED_KINDS]

    type_problems = sum(1 for c in problems if _is_type_problem(_kind_str(c)))
    symbol_problems = sum(1 for c in problems if _is_symbol_problem(_kind_str(c)))
    # Count remaining problems (ELF/DWARF-level) as symbol problems
    other_problems = len(problems) - type_problems - symbol_problems
    symbol_problems += other_problems

    breaking_count = len(breaking)
    if breaking_count == 0:
        bc_pct = 100.0
    elif old_symbol_count is not None and old_symbol_count > 0:
        bc_pct = max(0.0, (old_symbol_count - breaking_count) / old_symbol_count * 100)
    else:
        total = len(filtered)
        bc_pct = max(0.0, (total - breaking_count) / total * 100) if total > 0 else 0.0

    return {
        "compatible": f"{bc_pct:.1f}",
        "problems_with_types": str(type_problems),
        "problems_with_symbols": str(symbol_problems),
        "problems_total": str(type_problems + symbol_problems),
        "removed": str(len(removed)),
        "added": str(len(added)),
        "warnings": "0",
        "affected": str(len(filtered)),
    }


def generate_xml_report(
    result: DiffResult,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
    old_symbol_count: int | None = None,
) -> str:
    """Generate an ABICC-compatible XML ABI report.

    Args:
        result: DiffResult from checker.compare().
        lib_name: Library name for the report.
        old_version: Old library version string.
        new_version: New library version string.
        old_symbol_count: Total exported public symbol count in the old library.

    Returns:
        XML document as a string matching the ABICC report schema.
    """
    changes: list[object] = list(getattr(result, "changes", None) or [])

    root = ET.Element("report")
    root.set("version", _REPORT_VERSION)
    root.set("library", lib_name or "unknown")
    root.set("version1", old_version or "old")
    root.set("version2", new_version or "new")

    # Binary compatibility section (all changes)
    binary_data = _compute_section(changes, old_symbol_count, exclude_binary_only=False)
    binary_el = ET.SubElement(root, "binary")
    for key, val in binary_data.items():
        child = ET.SubElement(binary_el, key)
        child.text = val

    # Source compatibility section (exclude binary-only kinds)
    source_data = _compute_section(changes, old_symbol_count, exclude_binary_only=True)
    source_el = ET.SubElement(root, "source")
    for key, val in source_data.items():
        child = ET.SubElement(source_el, key)
        child.text = val

    ET.indent(root, space="  ")
    xml_str = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return xml_str


def write_xml_report(
    result: DiffResult,
    output_path: Path,
    lib_name: str = "",
    old_version: str = "",
    new_version: str = "",
    old_symbol_count: int | None = None,
) -> None:
    """Write ABICC-compatible XML report to *output_path*."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_xml_report(
        result,
        lib_name=lib_name,
        old_version=old_version,
        new_version=new_version,
        old_symbol_count=old_symbol_count,
    )
    output_path.write_text(content, encoding="utf-8")

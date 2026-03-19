# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reporter — DiffResult → JSON / Markdown / stat output."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .checker_policy import HasKind
    from .severity import SeverityConfig

from .checker import (
    Change,
    DiffResult,
    Verdict,
)
from .checker_policy import (
    ChangeKind,
    impact_for,
)
from .checker_policy import (
    policy_kind_sets as _policy_kind_sets,
)
from .report_summary import build_summary


def _kind_to_severity(kind: ChangeKind, policy: str) -> str:
    """Map a ChangeKind to its severity label under the given policy (FIX-G)."""
    breaking, api_break, compatible, risk = _policy_kind_sets(policy)
    if kind in breaking:
        return "breaking"
    if kind in api_break:
        return "api_break"
    if kind in risk:
        return "risk"
    if kind in compatible:
        return "compatible"
    return "unknown"

_VERDICT_EMOJI = {
    Verdict.NO_CHANGE: "✅",
    Verdict.COMPATIBLE: "✅",
    Verdict.COMPATIBLE_WITH_RISK: "⚠️",
    Verdict.API_BREAK: "⚠️",
    Verdict.BREAKING: "❌",
}

_VERDICT_LABEL = {
    Verdict.NO_CHANGE: "NO_CHANGE",
    Verdict.COMPATIBLE: "COMPATIBLE",
    Verdict.COMPATIBLE_WITH_RISK: "COMPATIBLE_WITH_RISK",
    Verdict.API_BREAK: "API_BREAK",
    Verdict.BREAKING: "BREAKING",
}


# ---------------------------------------------------------------------------
# Show-only filter
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShowOnlyFilter:
    """Parsed --show-only tokens.

    Tokens fall into three dimensions; within each dimension OR logic applies,
    across dimensions AND logic applies.
    """
    severities: frozenset[str]  # breaking, api-break, risk, compatible
    elements: frozenset[str]    # functions, variables, types, enums, elf
    actions: frozenset[str]     # added, removed, changed

    @classmethod
    def parse(cls, raw: str) -> ShowOnlyFilter:
        """Parse a comma-separated --show-only string into a filter."""
        severity_tokens = {"breaking", "api-break", "risk", "compatible"}
        element_tokens = {"functions", "variables", "types", "enums", "elf"}
        action_tokens = {"added", "removed", "changed"}

        severities: set[str] = set()
        elements: set[str] = set()
        actions: set[str] = set()

        for tok in raw.split(","):
            tok = tok.strip().lower()
            if not tok:
                continue
            if tok in severity_tokens:
                severities.add(tok)
            elif tok in element_tokens:
                elements.add(tok)
            elif tok in action_tokens:
                actions.add(tok)
            else:
                raise ValueError(f"Unknown --show-only token: {tok!r}")

        return cls(
            severities=frozenset(severities),
            elements=frozenset(elements),
            actions=frozenset(actions),
        )

    def matches(self, change: Change, policy: str = "strict_abi") -> bool:
        """Return True if *change* passes this filter."""
        kind_val = change.kind.value

        # Severity check
        if self.severities:
            breaking_set, api_break_set, compat_set, risk_set = _policy_kind_sets(policy)
            sev_ok = False
            if "breaking" in self.severities and change.kind in breaking_set:
                sev_ok = True
            if "api-break" in self.severities and change.kind in api_break_set:
                sev_ok = True
            if "risk" in self.severities and change.kind in risk_set:
                sev_ok = True
            if "compatible" in self.severities and change.kind in compat_set:
                sev_ok = True
            if not sev_ok:
                return False

        # Element check
        if self.elements:
            elem_ok = False
            if "functions" in self.elements and any(
                kind_val.startswith(p) for p in (
                    "func_", "param_", "method_", "base_class_",
                    "template_", "return_pointer_level_",
                )
            ) or "functions" in self.elements and kind_val in (
                "removed_const_overload", "anon_field_changed",
                "used_reserved_field", "frame_register_changed",
            ):
                elem_ok = True
            if "variables" in self.elements and any(
                kind_val.startswith(p) for p in ("var_", "constant_")
            ):
                elem_ok = True
            if "types" in self.elements and any(kind_val.startswith(p) for p in (
                "type_", "struct_", "union_", "field_", "typedef_",
            )):
                elem_ok = True
            if "enums" in self.elements and kind_val.startswith("enum_"):
                elem_ok = True
            if "elf" in self.elements and any(kind_val.startswith(p) for p in (
                "soname_", "needed_", "symbol_", "rpath_", "runpath_",
                "ifunc_", "common_", "dwarf_", "calling_convention_",
                "compat_version_", "visibility_",
            )) or "elf" in self.elements and kind_val in (
                "toolchain_flag_drift", "source_level_kind_changed",
                "value_abi_trait_changed",
            ):
                elem_ok = True
            if not elem_ok:
                return False

        # Action check
        if self.actions:
            act_ok = False
            if "added" in self.actions and (
                kind_val.endswith("_added")
                or kind_val.endswith("_added_compatible")
            ):
                act_ok = True
            if "removed" in self.actions and (
                kind_val.endswith("_removed")
                or kind_val.endswith("_deleted")
                or kind_val.endswith("_elf_only")
                or kind_val.endswith("_elf_fallback")
            ):
                act_ok = True
            if "changed" in self.actions and not (
                kind_val.endswith("_added") or kind_val.endswith("_added_compatible")
                or kind_val.endswith("_removed") or kind_val.endswith("_deleted")
                or kind_val.endswith("_elf_only") or kind_val.endswith("_elf_fallback")
            ):
                act_ok = True
            if not act_ok:
                return False

        return True


def apply_show_only(
    changes: Sequence[Change],
    show_only: str,
    policy: str = "strict_abi",
) -> list[Change]:
    """Filter changes according to a --show-only token string."""
    filt = ShowOnlyFilter.parse(show_only)
    return [c for c in changes if filt.matches(c, policy=policy)]


# ---------------------------------------------------------------------------
# Stat mode
# ---------------------------------------------------------------------------

def to_stat(result: DiffResult) -> str:
    """One-line summary for CI gates."""
    summary = build_summary(result)
    label = _VERDICT_LABEL[result.verdict]
    parts = []
    if summary.breaking:
        parts.append(f"{summary.breaking} breaking")
    if summary.source_breaks:
        parts.append(f"{summary.source_breaks} source-level breaks")
    if summary.risk_count:
        parts.append(f"{summary.risk_count} risk")
    if summary.compatible_additions:
        parts.append(f"{summary.compatible_additions} compatible")
    detail = ", ".join(parts) if parts else "no changes"
    redundant_note = ""
    if result.redundant_count > 0:
        redundant_note = f" [{result.redundant_count} redundant hidden]"
    return f"{label}: {detail} ({summary.total_changes} total){redundant_note}"


def to_stat_json(result: DiffResult, indent: int = 2) -> str:
    """JSON output for --stat mode: summary only, no changes array."""
    summary = build_summary(result)
    effective_policy = result.policy or "strict_abi"
    d: dict[str, object] = {
        "library": result.library,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "verdict": result.verdict.value,
        "policy": effective_policy,
        "summary": {
            "breaking": summary.breaking,
            "source_breaks": summary.source_breaks,
            "risk_changes": summary.risk_count,
            "compatible_additions": summary.compatible_additions,
            "total_changes": summary.total_changes,
            "binary_compatibility_pct": round(summary.binary_compatibility_pct, 1),
            "affected_pct": round(summary.affected_pct, 1),
        },
    }
    if result.redundant_count > 0:
        d["redundant_count"] = result.redundant_count
    return json.dumps(d, indent=indent)


# ---------------------------------------------------------------------------
# Impact summary
# ---------------------------------------------------------------------------

def _build_impact_table(
    result: DiffResult,
    displayed_changes: list[Change] | None = None,
) -> list[str]:
    """Build impact summary table rows.

    When *displayed_changes* is given (e.g. after ``--show-only`` filtering),
    only those changes are considered.  Interface counts use unique
    ``affected_symbols`` names; ``caused_count`` is shown separately to
    avoid double-counting.
    """
    from .checker import _ROOT_TYPE_CHANGE_KINDS

    changes = displayed_changes if displayed_changes is not None else list(result.changes)

    # Collect root type changes with their impact
    root_entries: list[tuple[str, str, int, int]] = []
    for c in changes:
        if c.kind in _ROOT_TYPE_CHANGE_KINDS:
            affected_count = len(c.affected_symbols) if c.affected_symbols else 0
            if affected_count > 0 or c.caused_count > 0:
                root_entries.append((c.symbol, c.kind.value, affected_count, c.caused_count))

    # Count non-type direct changes
    direct_removals = sum(
        1 for c in changes
        if c.kind.value.endswith("_removed") and c.kind not in _ROOT_TYPE_CHANGE_KINDS
    )

    if not root_entries and direct_removals == 0:
        return []

    lines = [
        "## Impact Summary",
        "",
        "| Root Change | Kind | Affected Interfaces | Derived |",
        "|-------------|------|---------------------|---------|",
    ]
    for symbol, kind, iface_count, caused in root_entries:
        iface_str = f"{iface_count} functions" if iface_count > 0 else "—"
        caused_str = f"+{caused} collapsed" if caused > 0 else "—"
        lines.append(f"| {symbol} | {kind} | {iface_str} | {caused_str} |")
    if direct_removals > 0:
        lines.append(f"| — | removals ({direct_removals}) | direct | — |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Leaf-change mode helpers
# ---------------------------------------------------------------------------

def _to_markdown_leaf(
    result: DiffResult,
    show_impact: bool = False,
    show_only: str | None = None,
) -> str:
    """Leaf-change mode: root type changes with affected interface lists."""
    from .checker import _ROOT_TYPE_CHANGE_KINDS

    v = result.verdict
    emoji = _VERDICT_EMOJI[v]
    label = _VERDICT_LABEL[v]

    lines: list[str] = [
        f"# ABI Report: {result.library} (leaf-change view)",
        "",
        "| | |",
        "|---|---|",
        f"| **Old version** | `{result.old_version}` |",
        f"| **New version** | `{result.new_version}` |",
        f"| **Verdict** | {emoji} `{label}` |",
        "",
    ]

    changes = list(result.changes)
    if show_only:
        changes = apply_show_only(changes, show_only, policy=result.policy)
        lines.append(f"> Filtered by: `--show-only {show_only}` ({len(changes)} of {len(result.changes)} changes shown)")
        lines.append("")

    # Group root type changes by severity
    type_changes = [c for c in changes if c.kind in _ROOT_TYPE_CHANGE_KINDS]
    non_type_changes = [c for c in changes if c.kind not in _ROOT_TYPE_CHANGE_KINDS]

    if type_changes:
        breaking_set, api_break_set, _, _ = _policy_kind_sets(result.policy)

        breaking_types = [c for c in type_changes if c.kind in breaking_set]
        api_break_types = [c for c in type_changes if c.kind in api_break_set]
        other_types = [c for c in type_changes if c.kind not in breaking_set and c.kind not in api_break_set]

        for section_label, section_changes in [
            ("## Breaking Type Changes", breaking_types),
            ("## Source-Level Type Breaks", api_break_types),
            ("## Other Type Changes", other_types),
        ]:
            if not section_changes:
                continue
            lines += [section_label, ""]
            for c in section_changes:
                lines.append(f"### {c.symbol} — {c.description}")
                if c.affected_symbols:
                    lines.append(f"\n**Affected interfaces ({len(c.affected_symbols)}):**")
                    for sym in c.affected_symbols[:10]:
                        lines.append(f"- `{sym}`")
                    if len(c.affected_symbols) > 10:
                        lines.append(f"- ... ({len(c.affected_symbols) - 10} more)")
                if c.caused_count > 0:
                    lines.append(f"\n> {c.caused_count} derived change(s) collapsed")
                lines.append("")

    if non_type_changes:
        lines += ["## Non-Type Changes", ""]
        for c in non_type_changes:
            lines.append(_format_change_md(c))
        lines.append("")

    if not changes:
        if show_only and result.changes:
            lines.append("_No changes match the current filter._")
        else:
            lines.append("_No ABI changes detected._")

    _append_redundancy_note(lines, result)
    _append_suppression_note(lines, result)

    if show_impact:
        lines += _build_impact_table(result, displayed_changes=changes)

    lines += _footer_lines()
    return "\n".join(lines)


def _to_json_leaf(
    result: DiffResult,
    indent: int = 2,
    show_only: str | None = None,
) -> str:
    """Leaf-change mode JSON output."""
    from .checker import _ROOT_TYPE_CHANGE_KINDS

    summary = build_summary(result)
    changes = list(result.changes)
    if show_only:
        changes = apply_show_only(changes, show_only, policy=result.policy)
    type_changes = [c for c in changes if c.kind in _ROOT_TYPE_CHANGE_KINDS]
    non_type_changes = [c for c in changes if c.kind not in _ROOT_TYPE_CHANGE_KINDS]

    effective_policy = result.policy or "strict_abi"

    leaf_changes_list = [
        {
            "kind": c.kind.value,
            "symbol": c.symbol,
            "description": c.description,
            "severity": _kind_to_severity(c.kind, effective_policy),
            "affected_count": len(c.affected_symbols) if c.affected_symbols else 0,
            "affected_symbols": c.affected_symbols or [],
            "caused_count": c.caused_count,
            "old_value": getattr(c, "old_value", None),
            "new_value": getattr(c, "new_value", None),
        }
        for c in type_changes
    ]
    non_type_list = [_change_to_dict(c, policy=effective_policy) for c in non_type_changes]

    d: dict[str, object] = {
        "library": result.library,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "verdict": result.verdict.value,
        "policy": effective_policy,
        "summary": {
            "breaking": summary.breaking,
            "source_breaks": summary.source_breaks,
            "risk_changes": summary.risk_count,
            "compatible_additions": summary.compatible_additions,
            "total_changes": summary.total_changes,
        },
        "leaf_changes": leaf_changes_list,
        "non_type_changes": non_type_list,
        # FIX-H: populate changes with union for backward-compat consumers
        "changes": leaf_changes_list + non_type_list,
    }
    if result.redundant_count > 0:
        d["redundant_count"] = result.redundant_count
    return json.dumps(d, indent=indent)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def _metadata_dict(meta: object | None) -> dict[str, object] | None:
    if meta is None:
        return None
    return {
        "path": getattr(meta, "path", ""),
        "sha256": getattr(meta, "sha256", ""),
        "size_bytes": getattr(meta, "size_bytes", 0),
    }


def to_json(
    result: DiffResult,
    indent: int = 2,
    *,
    show_only: str | None = None,
    report_mode: str = "full",
    show_impact: bool = False,
    stat: bool = False,
    severity_config: SeverityConfig | None = None,
) -> str:
    if stat:
        return to_stat_json(result, indent=indent)

    if report_mode == "leaf":
        return _to_json_leaf(result, indent=indent, show_only=show_only)

    changes = list(result.changes)
    if show_only:
        changes = apply_show_only(changes, show_only, policy=result.policy)

    summary = build_summary(result)
    d: dict[str, object] = {
        "library": result.library,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "verdict": result.verdict.value,
    }
    # Library file metadata (path, SHA-256, size) when available
    old_meta = _metadata_dict(getattr(result, "old_metadata", None))
    new_meta = _metadata_dict(getattr(result, "new_metadata", None))
    if old_meta:
        d["old_file"] = old_meta
    if new_meta:
        d["new_file"] = new_meta
    d["summary"] = {
        "breaking": summary.breaking,
        "source_breaks": summary.source_breaks,
        "risk_changes": summary.risk_count,
        "compatible_additions": summary.compatible_additions,
        "total_changes": summary.total_changes,
        "binary_compatibility_pct": round(summary.binary_compatibility_pct, 1),
        "affected_pct": round(summary.affected_pct, 1),
    }
    effective_policy = result.policy or "strict_abi"
    d["policy"] = effective_policy

    # Severity-categorized summary when severity config is provided
    if severity_config is not None:
        d["severity"] = _build_severity_json(
            changes, severity_config,
            all_changes=list(result.changes),
            policy=effective_policy,
        )

    d["changes"] = [_change_to_dict(c, policy=effective_policy) for c in changes]
    if result.redundant_count > 0:
        d["redundant_count"] = result.redundant_count
    d["suppression"] = {
        "file_provided": result.suppression_file_provided,
        "suppressed_count": result.suppressed_count,
        "suppressed_changes": [
            {
                "kind": c.kind.value,
                "symbol": c.symbol,
                "description": c.description,
            }
            for c in result.suppressed_changes
        ],
    }
    d["detectors"] = [
        {
            "name": det.name,
            "changes_count": det.changes_count,
            "enabled": det.enabled,
            "coverage_gap": det.coverage_gap,
        }
        for det in result.detector_results
        if det.changes_count > 0 or det.coverage_gap is not None
    ]
    if show_impact:
        d["show_only_applied"] = show_only is not None
    return json.dumps(d, indent=indent)


def _change_to_dict(c: object, *, policy: str = "strict_abi") -> dict[str, object]:
    """Convert a Change to a JSON-serializable dict with impact and metadata."""
    kind = getattr(c, "kind", None)
    d: dict[str, object] = {
        "kind": kind.value if kind else "",
        "symbol": getattr(c, "symbol", ""),
        "description": getattr(c, "description", ""),
        "old_value": getattr(c, "old_value", None),
        "new_value": getattr(c, "new_value", None),
        # FIX-G: materialize severity from active policy
        "severity": _kind_to_severity(kind, policy) if kind else "unknown",
    }
    # Impact explanation
    if kind:
        impact = impact_for(kind)
        if impact:
            d["impact"] = impact
    # Source location
    loc = getattr(c, "source_location", None)
    if loc:
        d["source_location"] = loc
    # Affected symbols
    affected = getattr(c, "affected_symbols", None)
    if affected:
        d["affected_symbols"] = affected
    # Redundancy annotation
    caused_by = getattr(c, "caused_by_type", None)
    if caused_by:
        d["caused_by_type"] = caused_by
    caused_count = getattr(c, "caused_count", 0)
    if caused_count > 0:
        d["caused_count"] = caused_count
    return d


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _fmt_size(size_bytes: int) -> str:
    """Format file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _append_redundancy_note(lines: list[str], result: DiffResult) -> None:
    if result.redundant_count > 0:
        lines.append("")
        lines.append(
            f"> ℹ️ {result.redundant_count} redundant change(s) hidden "
            "(derived from root type changes). Use `--show-redundant` to show all."
        )


def _append_suppression_note(lines: list[str], result: DiffResult) -> None:
    if result.suppression_file_provided:
        lines.append("")
        if result.suppressed_count == 0:
            lines.append(
                "> ℹ️ Suppression file active — 0 changes matched (nothing suppressed)"
            )
        else:
            lines.append(
                f"> ℹ️ {result.suppressed_count} change(s) suppressed via suppression file"
            )
            for sc in result.suppressed_changes:
                lines.append(f">   - `{sc.symbol}` — {sc.description}")


# ---------------------------------------------------------------------------
# Severity section helpers
# ---------------------------------------------------------------------------

_BREAKING_ICON = "\u274c"  # ❌
_SOURCE_BREAK_ICON = "\u26a0\ufe0f"  # ⚠️
_RISK_ICON = "\u26a0\ufe0f"  # ⚠️
_QUALITY_ICON = "\U0001f50d"  # 🔍
_ADDITION_ICON = "\u2705"  # ✅

_SEVERITY_EMOJI = {
    "error": "\u274c",  # ❌
    "warning": "\u26a0\ufe0f",  # ⚠️
    "info": "\u2139\ufe0f",  # ℹ️
}


def _section_severity_label(severity_config: SeverityConfig | None, category_attr: str) -> str:
    """Return a severity label suffix like ' [ERROR]' for a report section header."""
    if severity_config is None:
        return ""
    level = getattr(severity_config, category_attr, None)
    if level is None:
        return ""
    level_val = level.value if hasattr(level, "value") else str(level)
    emoji = _SEVERITY_EMOJI.get(level_val, "")
    return f" {emoji} `{level_val.upper()}`"


def _build_severity_summary_md(
    changes: list[Change],
    severity_config: SeverityConfig,
    *,
    policy: str | None = None,
) -> list[str]:
    """Build a severity configuration summary table for markdown output."""
    from .severity import SeverityLevel, categorize_changes

    categorized = categorize_changes(changes, policy=policy)
    lines = [
        "## Severity Configuration",
        "",
        "| Category | Severity | Count | Exit Impact |",
        "|----------|----------|-------|-------------|",
    ]

    _CATEGORY_INFO: list[tuple[str, str, list[HasKind]]] = [
        ("ABI/API Incompatibilities", "abi_breaking", categorized.abi_breaking),
        ("Potential Incompatibilities", "potential_breaking", categorized.potential_breaking),
        ("Quality Issues", "quality_issues", categorized.quality_issues),
        ("Additions", "addition", categorized.addition),
    ]

    for label, attr, cat_changes in _CATEGORY_INFO:
        level = getattr(severity_config, attr, SeverityLevel.INFO)
        level_val = level.value if hasattr(level, "value") else str(level)
        emoji = _SEVERITY_EMOJI.get(level_val, "")
        count = len(cat_changes)
        impact = "causes non-zero exit" if level_val == "error" and count > 0 else "no exit impact"
        lines.append(
            f"| {label} | {emoji} `{level_val.upper()}` | {count} | {impact} |"
        )

    lines.append("")
    return lines


def _build_severity_json(
    changes: list[Change],
    severity_config: SeverityConfig,
    *,
    all_changes: list[Change] | None = None,
    policy: str | None = None,
) -> dict[str, object]:
    """Build severity information for JSON output.

    *changes* are the (possibly filtered) changes for display counts.
    *all_changes*, when provided, is the unfiltered set used to compute
    the exit code so that ``--show-only`` does not affect the exit code.
    """
    from .severity import SeverityLevel, categorize_changes, compute_exit_code

    categorized = categorize_changes(changes, policy=policy)

    config_dict: dict[str, str] = {}
    for attr in ("abi_breaking", "potential_breaking", "quality_issues", "addition"):
        level = getattr(severity_config, attr, SeverityLevel.INFO)
        config_dict[attr] = level.value if hasattr(level, "value") else str(level)

    categories: dict[str, object] = {
        "abi_breaking": {
            "severity": config_dict["abi_breaking"],
            "count": len(categorized.abi_breaking),
        },
        "potential_breaking": {
            "severity": config_dict["potential_breaking"],
            "count": len(categorized.potential_breaking),
        },
        "quality_issues": {
            "severity": config_dict["quality_issues"],
            "count": len(categorized.quality_issues),
        },
        "addition": {
            "severity": config_dict["addition"],
            "count": len(categorized.addition),
        },
    }

    # Exit code uses the full unfiltered change set so --show-only
    # does not affect it.
    exit_changes = all_changes if all_changes is not None else changes
    exit_code = compute_exit_code(exit_changes, severity_config, policy=policy)

    return {
        "config": config_dict,
        "categories": categories,
        "exit_code": exit_code,
    }


def _footer_lines() -> list[str]:
    return [
        "---",
        "## Legend",
        "",
        "| Verdict | Meaning |",
        "|---------|---------|",
        "| ✅ NO_CHANGE | Identical ABI |",
        "| ✅ COMPATIBLE | Only additions (backward compatible) |",
        "| ⚠️ COMPATIBLE_WITH_RISK | Binary-compatible; verify target environment |",
        "| ⚠️ API_BREAK | Source-level API change — recompilation required |",
        "| ❌ BREAKING | Binary ABI break — recompilation required |",
        "",
        "_Generated by [abicheck](https://github.com/napetrov/abicheck)_",
    ]


def to_markdown(
    result: DiffResult,
    *,
    show_only: str | None = None,
    report_mode: str = "full",
    show_impact: bool = False,
    stat: bool = False,
    severity_config: SeverityConfig | None = None,
) -> str:
    if stat:
        return to_stat(result)

    if report_mode == "leaf":
        return _to_markdown_leaf(result, show_impact=show_impact, show_only=show_only)

    v = result.verdict
    emoji = _VERDICT_EMOJI[v]
    label = _VERDICT_LABEL[v]

    old_meta = getattr(result, "old_metadata", None)
    new_meta = getattr(result, "new_metadata", None)

    # Apply show-only filter if provided (display-only, does not affect verdict)
    changes = list(result.changes)
    if show_only:
        changes = apply_show_only(changes, show_only, policy=result.policy)

    # Classify filtered changes by severity
    breaking_set, api_break_set, compat_set, risk_set = _policy_kind_sets(result.policy)
    breaking = [c for c in changes if c.kind in breaking_set]
    source_breaks = [c for c in changes if c.kind in api_break_set]
    risk = [c for c in changes if c.kind in risk_set]
    compatible = [c for c in changes if c.kind in compat_set]

    lines: list[str] = [
        f"# ABI Report: {result.library}",
        "",
        "| | |",
        "|---|---|",
        f"| **Old version** | `{result.old_version}` |",
        f"| **New version** | `{result.new_version}` |",
        f"| **Verdict** | {emoji} `{label}` |",
        f"| Breaking changes | {len(result.breaking)} |",
        f"| Source-level breaks | {len(result.source_breaks)} |",
        f"| Deployment risk changes | {len(result.risk)} |",
        f"| Compatible changes | {len(result.compatible)} |",
        "",
    ]

    # Severity configuration summary when provided
    if severity_config is not None:
        lines += _build_severity_summary_md(
            changes, severity_config, policy=result.policy,
        )

    if show_only:
        lines.append(f"> Filtered by: `--show-only {show_only}` ({len(changes)} of {len(result.changes)} changes shown)")
        lines.append("")

    if old_meta or new_meta:
        lines += ["## Library Files", "", "| | Old | New |", "|---|---|---|"]
        old_path = getattr(old_meta, "path", "—") if old_meta else "—"
        new_path = getattr(new_meta, "path", "—") if new_meta else "—"
        old_sha = getattr(old_meta, "sha256", "—")[:12] if old_meta else "—"
        new_sha = getattr(new_meta, "sha256", "—")[:12] if new_meta else "—"
        old_size = _fmt_size(old_meta.size_bytes) if old_meta else "—"
        new_size = _fmt_size(new_meta.size_bytes) if new_meta else "—"
        lines += [
            f"| **Path** | `{old_path}` | `{new_path}` |",
            f"| **SHA-256** | `{old_sha}…` | `{new_sha}…` |",
            f"| **Size** | {old_size} | {new_size} |",
            "",
        ]

    if breaking:
        sev_label = _section_severity_label(severity_config, "abi_breaking")
        lines += [f"## {_BREAKING_ICON} Breaking Changes{sev_label}", ""]
        for c in breaking:
            lines.append(_format_change_md(c))
        lines.append("")

    if source_breaks:
        sev_label = _section_severity_label(severity_config, "potential_breaking")
        lines += [f"## {_SOURCE_BREAK_ICON} Source-Level Breaks{sev_label}", ""]
        for c in source_breaks:
            lines.append(_format_change_md(c))
        lines.append("")

    if risk:
        # Risk changes share the "potential_breaking" severity category with
        # source-level breaks (both are potential incompatibilities), so they
        # show the same severity badge in the report.
        sev_label = _section_severity_label(severity_config, "potential_breaking")
        lines += [f"## {_RISK_ICON} Deployment Risk Changes{sev_label}", ""]
        lines += [
            "> These changes are **binary-compatible** but may cause the library to fail",
            "> loading on older systems (e.g. a new GLIBC version requirement). Verify",
            "> your target environment before deploying.",
            "",
        ]
        for c in risk:
            lines.append(f"- **{c.kind.value}**: {c.description}")
        lines.append("")

    # Split compatible changes into quality/behavioral issues vs additions
    # using the canonical kind sets from checker_policy (single source of truth).
    if compatible:
        from .checker_policy import ADDITION_KINDS as _ADDITION_KINDS
        quality = [c for c in compatible if c.kind not in _ADDITION_KINDS]
        additions_list = [c for c in compatible if c.kind in _ADDITION_KINDS]
        if quality:
            sev_label = _section_severity_label(severity_config, "quality_issues")
            lines += [f"## {_QUALITY_ICON} Quality Issues{sev_label}", ""]
            for c in quality:
                lines.append(f"- **{c.kind.value}**: {c.description}")
            lines.append("")
        if additions_list:
            sev_label = _section_severity_label(severity_config, "addition")
            lines += [f"## {_ADDITION_ICON} Additions{sev_label}", ""]
            for c in additions_list:
                lines.append(f"- {c.description}")
            lines.append("")

    if not changes:
        if show_only and result.changes:
            lines.append("_No changes match the current filter._")
        else:
            lines.append("_No ABI changes detected._")

    _append_redundancy_note(lines, result)
    _append_suppression_note(lines, result)

    if show_impact:
        lines.append("")
        lines += _build_impact_table(result, displayed_changes=changes)

    lines += _footer_lines()
    return "\n".join(lines)


def _format_change_md(c: object) -> str:
    """Format a single change as a markdown list item with impact and metadata."""
    kind = getattr(c, "kind", None)
    kind_val = kind.value if kind else ""
    desc = getattr(c, "description", "")
    old_val = getattr(c, "old_value", None)
    new_val = getattr(c, "new_value", None)
    loc = getattr(c, "source_location", None)
    affected = getattr(c, "affected_symbols", None)
    caused_count = getattr(c, "caused_count", 0)

    # Base line
    old_new = ""
    if old_val is not None and new_val is not None:
        old_new = f" (`{old_val}` → `{new_val}`)"
    elif old_val is not None:
        old_new = f" (`{old_val}`)"
    elif new_val is not None:
        old_new = f" (`{new_val}`)"
    line = f"- **{kind_val}**: {desc}{old_new}"

    # Source location
    if loc:
        line += f" — `{loc}`"

    # Impact
    if kind:
        impact = impact_for(kind)
        if impact:
            line += f"\n  > {impact}"

    # Collapsed derived changes
    if caused_count > 0:
        line += f"\n  > {caused_count} derived change(s) collapsed"

    # Affected functions
    if affected:
        names = ", ".join(f"`{s}`" for s in affected[:5])
        suffix = f" (+{len(affected) - 5} more)" if len(affected) > 5 else ""
        line += f"\n  > Affected symbols: {names}{suffix}"

    return line


# ---------------------------------------------------------------------------
# Application compatibility reporters (ADR-005)
# ---------------------------------------------------------------------------

def appcompat_to_json(result: object, indent: int = 2) -> str:
    """Render an AppCompatResult as JSON."""
    import json as _json

    verdict = getattr(result, "verdict", None)
    full_diff = getattr(result, "full_diff", None)

    d: dict[str, object] = {
        "application": getattr(result, "app_path", ""),
        "old_library": getattr(result, "old_lib_path", ""),
        "new_library": getattr(result, "new_lib_path", ""),
        "verdict": verdict.value if verdict else "UNKNOWN",
        "symbol_coverage_pct": round(getattr(result, "symbol_coverage", 0.0), 1),
        "required_symbol_count": getattr(result, "required_symbol_count", 0),
    }

    missing = getattr(result, "missing_symbols", [])
    d["missing_symbols"] = list(missing)

    missing_ver = getattr(result, "missing_versions", [])
    d["missing_versions"] = list(missing_ver)

    breaking = getattr(result, "breaking_for_app", [])
    appcompat_policy = getattr(getattr(result, "full_diff", None), "policy", "strict_abi") or "strict_abi"
    d["relevant_changes"] = [_change_to_dict(c, policy=appcompat_policy) for c in breaking]
    d["relevant_change_count"] = len(breaking)

    irrelevant = getattr(result, "irrelevant_for_app", [])
    d["irrelevant_change_count"] = len(irrelevant)

    total = len(breaking) + len(irrelevant)
    d["total_library_changes"] = total

    if full_diff:
        d["full_library_verdict"] = full_diff.verdict.value

    return _json.dumps(d, indent=indent)


def appcompat_to_markdown(result: object, *, show_irrelevant: bool = False) -> str:
    """Render an AppCompatResult as Markdown."""
    verdict = getattr(result, "verdict", None)
    v_label = verdict.value if verdict else "UNKNOWN"
    v_emoji = _VERDICT_EMOJI.get(verdict, "?") if verdict else "?"

    app_path = getattr(result, "app_path", "")
    old_lib = getattr(result, "old_lib_path", "")
    new_lib = getattr(result, "new_lib_path", "")
    required_count = getattr(result, "required_symbol_count", 0)
    coverage = getattr(result, "symbol_coverage", 0.0)
    missing = getattr(result, "missing_symbols", [])
    missing_ver = getattr(result, "missing_versions", [])
    breaking = getattr(result, "breaking_for_app", [])
    irrelevant = getattr(result, "irrelevant_for_app", [])

    total_changes = len(breaking) + len(irrelevant)

    lines: list[str] = [
        "# Application Compatibility Report",
        "",
    ]

    if old_lib:
        lines += [
            f"**Application:** `{app_path}`",
            f"**Library:** `{old_lib}` → `{new_lib}`",
            f"**Verdict:** {v_emoji} `{v_label}`",
            "",
        ]
    else:
        # Weak mode
        lines += [
            f"**Application:** `{app_path}`",
            f"**Library:** `{new_lib}`",
            f"**Verdict:** {v_emoji} `{v_label}`",
            "",
        ]

    # Symbol coverage section
    lines += ["## Symbol Coverage", ""]
    lines.append(
        f"App requires **{required_count}** library symbols."
    )

    if missing:
        lines.append(
            f"**{len(missing)}** required symbol(s) missing from new version "
            f"({coverage:.0f}% coverage)."
        )
    elif required_count > 0:
        lines.append(
            f"All {required_count} required symbols present in new version "
            f"({coverage:.0f}% coverage)."
        )
    lines.append("")

    # Missing symbols
    if missing:
        lines += ["## Missing Symbols", ""]
        lines.append("These symbols are required by the application but absent from the new library:")
        lines.append("")
        for sym in missing:
            lines.append(f"- `{sym}`")
        lines.append("")

    # Missing versions
    if missing_ver:
        lines += ["## Missing Symbol Versions", ""]
        for ver in missing_ver:
            lines.append(f"- `{ver}`")
        lines.append("")

    # Relevant changes
    if breaking:
        lines += [
            f"## Relevant Changes ({len(breaking)} of {total_changes} total)",
            "",
            "These library changes affect symbols your application uses:",
            "",
            "| Kind | Symbol | Description |",
            "|------|--------|-------------|",
        ]
        for c in breaking:
            kind_val = c.kind.value if c.kind else ""
            lines.append(f"| `{kind_val}` | `{c.symbol}` | {c.description} |")
        lines.append("")
    elif total_changes > 0:
        lines += [
            f"## Relevant Changes (0 of {total_changes} total)",
            "",
            "None of the library's ABI changes affect your application.",
            "",
        ]

    # Irrelevant changes
    if irrelevant and not show_irrelevant:
        lines.append(
            f"_{len(irrelevant)} library ABI change(s) do NOT affect your application. "
            "Use `--show-irrelevant` to see them._"
        )
        lines.append("")
    elif irrelevant and show_irrelevant:
        lines += [
            f"## Irrelevant Changes ({len(irrelevant)})",
            "",
            "These library changes do NOT affect your application:",
            "",
        ]
        for c in irrelevant:
            kind_val = c.kind.value if c.kind else ""
            lines.append(f"- **{kind_val}**: {c.description}")
        lines.append("")

    lines += [
        "---",
        "_Generated by [abicheck](https://github.com/napetrov/abicheck)_",
    ]
    return "\n".join(lines)

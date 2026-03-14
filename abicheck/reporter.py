"""Reporter — DiffResult → JSON / Markdown."""

from __future__ import annotations

import json

from .checker import (
    DiffResult,
    Verdict,
)
from .checker_policy import impact_for
from .report_summary import build_summary

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


def _metadata_dict(meta: object | None) -> dict[str, object] | None:
    if meta is None:
        return None
    return {
        "path": getattr(meta, "path", ""),
        "sha256": getattr(meta, "sha256", ""),
        "size_bytes": getattr(meta, "size_bytes", 0),
    }


def to_json(result: DiffResult, indent: int = 2) -> str:
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
    d["changes"] = [_change_to_dict(c) for c in result.changes]
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
    return json.dumps(d, indent=indent)


def _change_to_dict(c: object) -> dict[str, object]:
    """Convert a Change to a JSON-serializable dict with impact and metadata."""
    kind = getattr(c, "kind", None)
    d: dict[str, object] = {
        "kind": kind.value if kind else "",
        "symbol": getattr(c, "symbol", ""),
        "description": getattr(c, "description", ""),
        "old_value": getattr(c, "old_value", None),
        "new_value": getattr(c, "new_value", None),
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
    return d


def _fmt_size(size_bytes: int) -> str:
    """Format file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def to_markdown(result: DiffResult) -> str:
    v = result.verdict
    emoji = _VERDICT_EMOJI[v]
    label = _VERDICT_LABEL[v]

    old_meta = getattr(result, "old_metadata", None)
    new_meta = getattr(result, "new_metadata", None)

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
        f"| Compatible additions | {len(result.compatible)} |",
        "",
    ]

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

    if result.breaking:
        lines += ["## ❌ Breaking Changes", ""]
        for c in result.breaking:
            lines.append(_format_change_md(c))
        lines.append("")

    if result.source_breaks:
        lines += ["## ⚠️ Source-Level Breaks", ""]
        for c in result.source_breaks:
            lines.append(_format_change_md(c))
        lines.append("")

    if result.risk:
        lines += ["## ⚠️ Deployment Risk Changes", ""]
        lines += [
            "> These changes are **binary-compatible** but may cause the library to fail",
            "> loading on older systems (e.g. a new GLIBC version requirement). Verify",
            "> your target environment before deploying.",
            "",
        ]
        for c in result.risk:
            lines.append(f"- **{c.kind.value}**: {c.description}")
        lines.append("")

    if result.compatible:
        lines += ["## ✅ Compatible Additions", ""]
        for c in result.compatible:
            lines.append(f"- {c.description}")
        lines.append("")

    if not result.changes:
        lines.append("_No ABI changes detected._")

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

    lines += [
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

    # Base line
    old_new = ""
    if old_val and new_val:
        old_new = f" (`{old_val}` → `{new_val}`)"
    elif old_val:
        old_new = f" (`{old_val}`)"
    line = f"- **{kind_val}**: {desc}{old_new}"

    # Source location
    if loc:
        line += f" — `{loc}`"

    # Impact
    if kind:
        impact = impact_for(kind)
        if impact:
            line += f"\n  > {impact}"

    # Affected functions
    if affected:
        names = ", ".join(f"`{s}`" for s in affected[:5])
        suffix = f" (+{len(affected) - 5} more)" if len(affected) > 5 else ""
        line += f"\n  > Affected symbols: {names}{suffix}"

    return line

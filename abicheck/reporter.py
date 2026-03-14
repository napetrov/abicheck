"""Reporter — DiffResult → JSON / Markdown."""

from __future__ import annotations

import json

from .checker import (
    DiffResult,
    Verdict,
)
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


def to_json(result: DiffResult, indent: int = 2) -> str:
    summary = build_summary(result)
    d = {
        "library": result.library,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "verdict": result.verdict.value,
        "summary": {
            "breaking": summary.breaking,
            "source_breaks": summary.source_breaks,
            "risk_changes": summary.risk_count,
            "compatible_additions": summary.compatible_additions,
            "total_changes": summary.total_changes,
            "binary_compatibility_pct": round(summary.binary_compatibility_pct, 1),
            "affected_pct": round(summary.affected_pct, 1),
        },
        "changes": [
            {
                "kind": c.kind.value,
                "symbol": c.symbol,
                "description": c.description,
                "old_value": c.old_value,
                "new_value": c.new_value,
            }
            for c in result.changes
        ],
        "suppression": {
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
        },
        "detectors": [
            {
                "name": d.name,
                "changes_count": d.changes_count,
                "enabled": d.enabled,
                "coverage_gap": d.coverage_gap,
            }
            for d in result.detector_results
        ],
    }
    return json.dumps(d, indent=indent)


def to_markdown(result: DiffResult) -> str:
    v = result.verdict
    emoji = _VERDICT_EMOJI[v]
    label = _VERDICT_LABEL[v]

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

    if result.breaking:
        lines += ["## ❌ Breaking Changes", ""]
        for c in result.breaking:
            old_new = ""
            if c.old_value and c.new_value:
                old_new = f" (`{c.old_value}` → `{c.new_value}`)"
            elif c.old_value:
                old_new = f" (`{c.old_value}`)"
            lines.append(f"- **{c.kind.value}**: {c.description}{old_new}")
        lines.append("")

    if result.source_breaks:
        lines += ["## ⚠️ Source-Level Breaks", ""]
        for c in result.source_breaks:
            lines.append(f"- **{c.kind.value}**: {c.description}")
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

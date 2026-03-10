"""Canonical summary metric computation for all report formats."""
from __future__ import annotations

from dataclasses import dataclass

from .checker import _BREAKING_KINDS
from .checker import DiffResult


@dataclass(frozen=True)
class ReportSummary:
    breaking: int
    source_breaks: int
    compatible_additions: int
    total_changes: int
    binary_compatibility_pct: float
    affected_pct: float


@dataclass(frozen=True)
class CompatibilityMetrics:
    breaking_count: int
    binary_compatibility_pct: float
    affected_pct: float


def compatibility_metrics(changes: list[object], old_symbol_count: int | None = None) -> CompatibilityMetrics:
    """Compute canonical ABICC-style binary compatibility counters/percentages."""
    breaking_count = sum(1 for c in changes if getattr(c, "kind", None) in _BREAKING_KINDS)

    if breaking_count == 0:
        bc_pct = 100.0
    elif old_symbol_count and old_symbol_count > 0:
        bc_pct = max(0.0, (old_symbol_count - breaking_count) / old_symbol_count * 100)
    else:
        total = len(changes)
        bc_pct = max(0.0, (total - breaking_count) / total * 100) if total > 0 else 0.0

    if old_symbol_count and old_symbol_count > 0:
        affected_pct = breaking_count / old_symbol_count * 100
    else:
        affected_pct = 0.0

    return CompatibilityMetrics(
        breaking_count=breaking_count,
        binary_compatibility_pct=bc_pct,
        affected_pct=affected_pct,
    )


def build_summary(result: DiffResult) -> ReportSummary:
    metrics = compatibility_metrics(result.changes)
    return ReportSummary(
        breaking=len(result.breaking),
        source_breaks=len(result.source_breaks),
        compatible_additions=len(result.compatible),
        total_changes=len(result.changes),
        binary_compatibility_pct=metrics.binary_compatibility_pct,
        affected_pct=metrics.affected_pct,
    )

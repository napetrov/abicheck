"""Canonical summary metric computation for all report formats."""
from __future__ import annotations

from dataclasses import dataclass

from .checker import DiffResult


@dataclass(frozen=True)
class ReportSummary:
    breaking: int
    source_breaks: int
    compatible_additions: int
    total_changes: int


def build_summary(result: DiffResult) -> ReportSummary:
    return ReportSummary(
        breaking=len(result.breaking),
        source_breaks=len(result.source_breaks),
        compatible_additions=len(result.compatible),
        total_changes=len(result.changes),
    )

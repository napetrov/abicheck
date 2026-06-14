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

"""A render-ready view of a comparison result (C2 — ADR-035).

Output formats used to each re-apply the ``show_only`` filter and re-derive the
verdict-axis buckets (breaking / source-break / risk / compatible) on their own.
:class:`ReportModel` computes those *once* from a :class:`DiffResult` so renderers
become thin projections over a single, canonical classification.

Canonical severity (ADR-035): the **verdict axis** — each finding's
``result._effective_verdict_for_change(c)`` (policy-file overrides + ADR-027 A4
per-finding modulation respected). This is the same partition that drives the
overall verdict and the process exit code, so the report can never disagree with
the gate. The ABICC-style display severity (HIGH/MEDIUM/LOW in
``report_classifications``) and the symbol-origin axis (rtti/internal/public in
``report_summary``) are *separate projections*, deliberately not collapsed into
this one — they answer different questions.

Cycle-safety: this module imports only ``checker_policy`` and ``report_summary``.
The ``show_only`` filter lives in ``reporter`` (``apply_show_only``); callers
apply it and pass the already-filtered change list in, so ``report_model`` never
imports ``reporter`` — ``reporter`` depends on this module one-directionally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .checker_policy import Verdict
from .report_summary import ReportSummary, build_summary

if TYPE_CHECKING:
    from .checker_types import Change, DiffResult


@dataclass(frozen=True)
class ReportModel:
    """Classified, filtered, summarised view of a :class:`DiffResult`.

    ``changes`` is the display set (after any ``show_only`` filter); the four
    bucket lists partition it by canonical verdict; ``summary`` is the headline
    metric roll-up. The verdict counts on ``result`` itself are unfiltered and
    remain the source of truth for the gate — the buckets here are the *display*
    partition of the (possibly filtered) change set.
    """

    result: DiffResult
    changes: list[Change]
    breaking: list[Change]
    source_breaks: list[Change]
    risk: list[Change]
    compatible: list[Change]
    summary: ReportSummary

    @staticmethod
    def classify(
        changes: list[Change],
        result: DiffResult,
    ) -> tuple[list[Change], list[Change], list[Change], list[Change]]:
        """Split *changes* into (breaking, source_breaks, risk, compatible) by the
        effective per-finding verdict (canonical severity, ADR-035)."""
        ev = result._effective_verdict_for_change
        breaking = [c for c in changes if ev(c) == Verdict.BREAKING]
        source_breaks = [c for c in changes if ev(c) == Verdict.API_BREAK]
        risk = [c for c in changes if ev(c) == Verdict.COMPATIBLE_WITH_RISK]
        compatible = [c for c in changes if ev(c) == Verdict.COMPATIBLE]
        return breaking, source_breaks, risk, compatible

    @classmethod
    def from_result(
        cls,
        result: DiffResult,
        *,
        changes: list[Change] | None = None,
    ) -> ReportModel:
        """Build the model and classify *changes* (defaults to all of
        ``result.changes``).

        The ``show_only`` display filter is applied by the caller (via
        ``reporter.apply_show_only``) and the filtered list passed in here, so
        this module stays free of any ``reporter`` import (no cycle).
        """
        if changes is None:
            changes = list(result.changes)
        breaking, source_breaks, risk, compatible = cls.classify(changes, result)
        return cls(
            result=result,
            changes=changes,
            breaking=breaking,
            source_breaks=source_breaks,
            risk=risk,
            compatible=compatible,
            summary=build_summary(result),
        )

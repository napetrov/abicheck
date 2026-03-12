"""PolicyResult — v0.2.

Split into per-change annotations (AnnotatedChange) + aggregate summary (PolicySummary).
v0.1 had only a summary, which made it impossible to trace which changes caused a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .change import Change, ChangeSeverity


class PolicyVerdict(str, Enum):
    """Final CI verdict for a policy evaluation."""

    PASS = "pass"  # no incompatible changes
    WARN = "warn"  # review-needed changes present, no hard breaks
    BLOCK = "block"  # incompatible changes detected
    ERROR = "error"  # evaluation failed (e.g. insufficient evidence)


@dataclass(slots=True)
class AnnotatedChange:
    """A Change decorated with its per-policy verdict."""

    change: Change
    verdict: PolicyVerdict


@dataclass(slots=True)
class PolicySummary:
    """Aggregate counts for the policy evaluation run.

    ``verdict`` is always derived from the counts — never set independently.
    - BLOCK:  incompatible_count > 0
    - WARN:   review_needed_count > 0 (and incompatible_count == 0)
    - PASS:   both counts are 0
    - ERROR:  pipeline failure (not a policy outcome; error_count > 0)
    """

    verdict: PolicyVerdict
    review_needed_count: int = 0
    incompatible_count: int = 0
    suppressed_count: int = 0
    compatible_extension_count: int = 0
    error_count: int = 0  # reserved: pipeline failures (insufficient evidence etc.)


@dataclass(slots=True)
class PolicyResult:
    """Full result of a policy evaluation.

    ``annotated_changes`` provides per-change traceability (replaces the v0.1 opaque summary).
    ``summary`` provides the CI-facing aggregate verdict and counts.

    Use ``PolicyResult.from_annotated()`` as the primary constructor — it derives
    the summary deterministically from the change list.

    Count semantics:
    - ``incompatible_count``  = number of AnnotatedChange with verdict == BLOCK
    - ``review_needed_count`` = number of AnnotatedChange with verdict == WARN
    - ``suppressed_count``    = number of Change with severity == SUPPRESSED
    - ``error_count``         = number of AnnotatedChange with verdict == ERROR

    Note on ERROR verdict: ``PolicyVerdict.ERROR`` is not producible via
    ``from_annotated`` in normal flow — it signals pipeline failure, not a policy
    outcome. Construct manually when the pipeline cannot complete analysis.
    """

    annotated_changes: list[AnnotatedChange] = field(default_factory=list)
    summary: PolicySummary = field(
        default_factory=lambda: PolicySummary(verdict=PolicyVerdict.PASS)
    )

    @classmethod
    def from_annotated(cls, changes: list[AnnotatedChange]) -> PolicyResult:
        """Build a PolicyResult from a list of AnnotatedChange, computing summary."""
        incompatible = sum(1 for ac in changes if ac.verdict == PolicyVerdict.BLOCK)
        review_needed = sum(1 for ac in changes if ac.verdict == PolicyVerdict.WARN)
        error_count = sum(1 for ac in changes if ac.verdict == PolicyVerdict.ERROR)
        suppressed = sum(
            1 for ac in changes
            if ac.change.severity == ChangeSeverity.SUPPRESSED
        )
        compatible_extension = sum(
            1 for ac in changes
            if ac.change.severity == ChangeSeverity.COMPATIBLE_EXTENSION
        )

        if error_count > 0:
            verdict = PolicyVerdict.ERROR
        elif incompatible > 0:
            verdict = PolicyVerdict.BLOCK
        elif review_needed > 0:
            verdict = PolicyVerdict.WARN
        else:
            verdict = PolicyVerdict.PASS

        annotated_changes = list(changes)  # defensive copy — caller mutation won't stale summary
        return cls(
            annotated_changes=annotated_changes,
            summary=PolicySummary(
                verdict=verdict,
                incompatible_count=incompatible,
                review_needed_count=review_needed,
                suppressed_count=suppressed,
                compatible_extension_count=compatible_extension,
                error_count=error_count,
            ),
        )

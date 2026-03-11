"""PolicyResult — v0.2.

Split into per-change annotations (AnnotatedChange) + aggregate summary (PolicySummary).
v0.1 had only a summary, which made it impossible to trace which changes caused a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .change import Change


class PolicyVerdict(str, Enum):
    """Final CI verdict for a policy evaluation."""
    PASS  = "pass"    # no incompatible changes
    WARN  = "warn"    # review-needed changes present, no hard breaks
    BLOCK = "block"   # incompatible changes detected
    ERROR = "error"   # evaluation failed (e.g. insufficient evidence)


@dataclass(slots=True)
class AnnotatedChange:
    """A Change decorated with its per-policy verdict."""
    change:  Change
    verdict: PolicyVerdict


@dataclass(slots=True)
class PolicySummary:
    """Aggregate counts for the policy evaluation run."""
    verdict:             PolicyVerdict
    review_needed_count: int = 0
    incompatible_count:  int = 0
    suppressed_count:    int = 0


@dataclass
class PolicyResult:
    """Full result of a policy evaluation.

    ``annotated_changes`` provides per-change traceability (replaces the v0.1 opaque summary).
    ``summary`` provides the CI-facing aggregate verdict and counts.
    """
    annotated_changes: list[AnnotatedChange] = field(default_factory=list)
    summary:           PolicySummary = field(
        default_factory=lambda: PolicySummary(verdict=PolicyVerdict.PASS)
    )

    @classmethod
    def from_annotated(cls, changes: list[AnnotatedChange]) -> PolicyResult:
        """Build a PolicyResult from a list of AnnotatedChange, computing summary."""
        from .change import ChangeSeverity

        incompatible = sum(
            1 for ac in changes if ac.verdict == PolicyVerdict.BLOCK
        )
        review_needed = sum(
            1 for ac in changes
            if ac.change.severity == ChangeSeverity.REVIEW_NEEDED
        )
        suppressed = sum(
            1 for ac in changes
            if ac.change.severity == ChangeSeverity.SUPPRESSED
        )

        if incompatible > 0:
            verdict = PolicyVerdict.BLOCK
        elif review_needed > 0:
            verdict = PolicyVerdict.WARN
        else:
            verdict = PolicyVerdict.PASS

        return cls(
            annotated_changes=changes,
            summary=PolicySummary(
                verdict=verdict,
                incompatible_count=incompatible,
                review_needed_count=review_needed,
                suppressed_count=suppressed,
            ),
        )

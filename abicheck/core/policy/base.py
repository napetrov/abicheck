"""Policy Engine base — v0.2.

Interface: (list[Change], suppressed: set) → PolicyResult

Each policy profile applies domain-specific rules to classify Changes
into PolicyVerdict (PASS/WARN/BLOCK/ERROR).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from abicheck.core.model import (
    AnnotatedChange,
    Change,
    ChangeSeverity,
    PolicyResult,
    PolicyVerdict,
)


class PolicyProfile(ABC):
    """Base class for policy profiles.

    Subclasses implement classify_change() to map a Change to a verdict.
    The base apply() method handles aggregation into PolicyResult.
    """

    profile_name: str = "base"
    profile_version: str = "0.2"

    def apply(
        self,
        changes: list[Change],
        suppressed_ids: frozenset[int] | None = None,
    ) -> PolicyResult:
        """Apply this policy to a list of Changes.

        Suppressed changes (severity == SUPPRESSED) are automatically annotated
        as PASS — they've been explicitly acknowledged by a suppression rule.

        suppressed_ids: deprecated parameter, kept for backward compat.
        Suppression is now determined by change.severity == SUPPRESSED.
        """
        annotated: list[AnnotatedChange] = []

        for change in changes:
            if change.severity == ChangeSeverity.SUPPRESSED:
                verdict = PolicyVerdict.PASS
            else:
                verdict = self.classify_change(change)
            annotated.append(AnnotatedChange(change=change, verdict=verdict))

        return PolicyResult.from_annotated(annotated)

    @abstractmethod
    def classify_change(self, change: Change) -> PolicyVerdict:
        """Classify a single Change into a PolicyVerdict."""
        ...

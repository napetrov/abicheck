"""Core model package — v0.2 data structures.

Public surface:
    Origin, ChangeSeverity, ChangeKind, SourceLocation, EntitySnapshot, Change
    PolicyVerdict, AnnotatedChange, PolicySummary, PolicyResult
"""
from __future__ import annotations

from .origin import Origin
from .change import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    SourceLocation,
)
from .policy_result import (
    AnnotatedChange,
    PolicyResult,
    PolicySummary,
    PolicyVerdict,
)

__all__ = [
    "Origin",
    "Change",
    "ChangeKind",
    "ChangeSeverity",
    "EntitySnapshot",
    "SourceLocation",
    "AnnotatedChange",
    "PolicyResult",
    "PolicySummary",
    "PolicyVerdict",
]

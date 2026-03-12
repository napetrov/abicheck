"""Suppressions package — Phase 2."""
from __future__ import annotations

from .engine import SuppressionEngine, SuppressionResult
from .rule import SuppressionRule, SuppressionScope, VersionRange

__all__ = [
    "SuppressionRule",
    "SuppressionScope",
    "VersionRange",
    "SuppressionEngine",
    "SuppressionResult",
]

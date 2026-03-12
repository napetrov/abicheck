"""Core package — v0.2 architecture."""
from __future__ import annotations

from .errors import (
    AbicheckError,
    SnapshotError,
    SuppressionError,
    ValidationError,
)

__all__ = [
    "AbicheckError",
    "ValidationError",
    "SnapshotError",
    "SuppressionError",
]

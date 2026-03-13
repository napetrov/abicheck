"""Structured error hierarchy for abicheck.

All public exceptions inherit from AbicheckError, which itself extends
the built-in Exception class for easy catch-all error handling.

SuppressionError inherits both AbicheckError and ValueError so that
existing code catching ValueError continues to work without changes.
"""
from __future__ import annotations


class AbicheckError(Exception):
    """Base exception for all abicheck-specific errors."""


class ValidationError(AbicheckError):
    """Raised when input data fails validation (schema, format, length limits)."""


class SnapshotError(AbicheckError):
    """Raised when an ABI snapshot cannot be loaded or parsed."""


class SuppressionError(AbicheckError, ValueError):
    """Raised for invalid suppression rules or patterns.

    Inherits ValueError for backward compatibility with existing code that
    catches ValueError from SuppressionEngine.
    """

"""Diff engine package — Phase 1b."""
from __future__ import annotations

from .symbol_diff import diff_symbols
from .type_layout_diff import diff_type_layouts

__all__ = ["diff_symbols", "diff_type_layouts"]

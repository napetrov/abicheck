"""P1: vtable reordering severity (abicc #66).

Explicit severity test: TYPE_VTABLE_CHANGED must be in BREAKING_KINDS.
Tests the relationship between vtable changes and BREAKING verdict.

This supplements the existing TestVtableReorderingSeverity in test_issues_e1_e4.py
with more granular severity-focused tests.
"""
from __future__ import annotations

import pytest

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.checker_policy import BREAKING_KINDS
from abicheck.model import AbiSnapshot, RecordType


def _snap(**kwargs: object) -> AbiSnapshot:
    defaults: dict[str, object] = dict(library="lib.so", version="1.0")
    defaults.update(kwargs)
    return AbiSnapshot(**defaults)  # type: ignore[arg-type]


class TestVtableSeverity:
    """TYPE_VTABLE_CHANGED must always be BREAKING (abicc #66)."""

    def test_type_vtable_changed_in_breaking_kinds(self) -> None:
        """TYPE_VTABLE_CHANGED must be in BREAKING_KINDS set."""
        assert ChangeKind.TYPE_VTABLE_CHANGED in BREAKING_KINDS

    def test_vtable_reorder_verdict_breaking(self) -> None:
        """Reordering vtable entries → BREAKING verdict."""
        old = _snap(types=[RecordType(
            name="Base", kind="class",
            vtable=["_ZN4Base4drawEv", "_ZN4Base6resizeEv"],
        )])
        new = _snap(types=[RecordType(
            name="Base", kind="class",
            vtable=["_ZN4Base6resizeEv", "_ZN4Base4drawEv"],
        )])
        result = compare(old, new)
        assert ChangeKind.TYPE_VTABLE_CHANGED in {c.kind for c in result.changes}
        assert result.verdict == Verdict.BREAKING

    def test_vtable_entry_removed_is_breaking(self) -> None:
        """Removing a vtable entry → BREAKING."""
        old = _snap(types=[RecordType(
            name="Widget", kind="class",
            vtable=["_ZN6Widget4drawEv", "_ZN6Widget5paintEv"],
        )])
        new = _snap(types=[RecordType(
            name="Widget", kind="class",
            vtable=["_ZN6Widget4drawEv"],
        )])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.TYPE_VTABLE_CHANGED in kinds
        assert result.verdict == Verdict.BREAKING

    def test_vtable_entry_added_is_breaking(self) -> None:
        """Adding a vtable entry shifts indices of subsequent entries → BREAKING."""
        old = _snap(types=[RecordType(
            name="Widget", kind="class",
            vtable=["_ZN6Widget4drawEv"],
        )])
        new = _snap(types=[RecordType(
            name="Widget", kind="class",
            vtable=["_ZN6Widget4drawEv", "_ZN6Widget5paintEv"],
        )])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.TYPE_VTABLE_CHANGED in kinds
        assert result.verdict == Verdict.BREAKING

    def test_vtable_unchanged_no_change(self) -> None:
        """Identical vtable → no TYPE_VTABLE_CHANGED emitted."""
        old = _snap(types=[RecordType(
            name="Engine", kind="class",
            vtable=["_ZN6Engine4initEv", "_ZN6Engine3runEv"],
        )])
        new = _snap(types=[RecordType(
            name="Engine", kind="class",
            vtable=["_ZN6Engine4initEv", "_ZN6Engine3runEv"],
        )])
        result = compare(old, new)
        assert not result.changes

    def test_vtable_change_kind_value(self) -> None:
        """TYPE_VTABLE_CHANGED enum value is 'type_vtable_changed'."""
        assert ChangeKind.TYPE_VTABLE_CHANGED.value == "type_vtable_changed"

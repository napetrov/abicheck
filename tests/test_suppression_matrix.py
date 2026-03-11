"""Matrix tests for suppression / filter scenarios.

Tests the Cartesian product of:
  - Suppression selector: symbol (exact), symbol_pattern (regex), type_pattern
  - Change kind: func_removed, type_size_changed, enum_member_removed
  - Combinations: added, removed, negative (no match expected)

If additional suppression APIs are unavailable, individual tests are
scaffolded with TODO markers and skip directives.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from abicheck.checker import Change, ChangeKind, compare
from abicheck.model import (
    AbiSnapshot,
    EnumMember,
    EnumType,
    Function,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)
from abicheck.suppression import Suppression, SuppressionList


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def _fn(name: str, mangled: str) -> Function:
    return Function(name=name, mangled=mangled, return_type="int", visibility=Visibility.PUBLIC)


def _snap(ver: str = "1.0", funcs=None, types=None, enums=None) -> AbiSnapshot:
    s = AbiSnapshot(library="libtest.so", version=ver)
    s.functions = funcs or []
    s.types = types or []
    s.enums = enums or []
    return s


def _suppression_from_yaml(tmp_path: Path, content: str) -> SuppressionList:
    p = tmp_path / "suppressions.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return SuppressionList.load(p)


def _make_removed_func_snaps(mangled: str = "_Z6helperi"):
    old = _snap("1.0", funcs=[_fn("compute", "_Z7computei"), _fn("helper", mangled)])
    new = _snap("2.0", funcs=[_fn("compute", "_Z7computei")])
    return old, new


def _make_struct_change_snaps():
    old = _snap("1.0", types=[RecordType(
        name="Packet", kind="struct", size_bits=64,
        fields=[TypeField("x", "int", 0), TypeField("y", "int", 32)],
    )])
    new = _snap("2.0", types=[RecordType(
        name="Packet", kind="struct", size_bits=96,
        fields=[TypeField("x", "int", 0), TypeField("y", "int", 32), TypeField("z", "int", 64)],
    )])
    return old, new


def _make_enum_change_snaps():
    old = _snap("1.0", enums=[EnumType(
        name="Status",
        members=[EnumMember("OK", 0), EnumMember("FAIL", 1), EnumMember("RETRY", 2)],
    )])
    new = _snap("2.0", enums=[EnumType(
        name="Status",
        members=[EnumMember("OK", 0), EnumMember("RETRY", 2)],  # FAIL removed
    )])
    return old, new


# ===========================================================================
# 1. symbol (exact match) suppression
# ===========================================================================

class TestSymbolExactSuppression:
    """Exact symbol name suppression."""

    def test_symbol_exact_suppresses_func_removed(self, tmp_path: Path) -> None:
        """Exact symbol match suppresses the targeted func_removed change."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z6helperi"
                change_kind: "func_removed"
                reason: "intentionally removed in v2"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 1
        assert result.verdict.value in ("NO_CHANGE", "COMPATIBLE"), (
            f"Expected suppression to eliminate break, got {result.verdict.value}"
        )

    def test_symbol_exact_no_match_different_symbol(self, tmp_path: Path) -> None:
        """Exact symbol mismatch → change is NOT suppressed."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z9otherFunci"
                change_kind: "func_removed"
                reason: "different symbol"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"

    def test_symbol_exact_without_change_kind_filter(self, tmp_path: Path) -> None:
        """Symbol exact without change_kind → matches any change for that symbol."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z6helperi"
                reason: "catch-all for helper"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 1

    def test_symbol_exact_wrong_change_kind_no_suppress(self, tmp_path: Path) -> None:
        """Symbol exact but wrong change_kind → NOT suppressed."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z6helperi"
                change_kind: "type_size_changed"
                reason: "wrong kind"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"


# ===========================================================================
# 2. symbol_pattern (regex) suppression
# ===========================================================================

class TestSymbolPatternSuppression:
    """Regex pattern suppression via symbol_pattern."""

    def test_pattern_suppresses_matching_symbol(self, tmp_path: Path) -> None:
        """Pattern matching the symbol mangled name suppresses the change."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: ".*helper.*"
                reason: "suppress all helper symbols"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 1

    def test_pattern_does_not_match_unrelated_symbol(self, tmp_path: Path) -> None:
        """Pattern that doesn't match → no suppression."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: ".*internal.*"
                reason: "only internal symbols"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"

    def test_pattern_fullmatch_semantics(self, tmp_path: Path) -> None:
        """symbol_pattern uses fullmatch — partial prefix does NOT match."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: "_Z6"
                reason: "prefix only — should NOT match (fullmatch semantics)"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 0

    def test_pattern_with_change_kind_filter(self, tmp_path: Path) -> None:
        """Pattern + change_kind: both must match."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: ".*helper.*"
                change_kind: "func_removed"
                reason: "helper func_removed only"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 1


# ===========================================================================
# 3. type_pattern suppression
# ===========================================================================

class TestTypePatternSuppression:
    """type_pattern only matches type-level change kinds."""

    def test_type_pattern_suppresses_struct_size_change(self, tmp_path: Path) -> None:
        """type_pattern matching struct name suppresses TYPE_SIZE_CHANGED."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - type_pattern: "Packet"
                reason: "Packet layout intentionally extended"
        """)
        old, new = _make_struct_change_snaps()
        result = compare(old, new, suppression=sl)
        # At least one type change suppressed
        assert result.suppressed_count > 0

    def test_type_pattern_does_not_suppress_func_removed(self, tmp_path: Path) -> None:
        """type_pattern does NOT suppress func_removed (symbol-level change)."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - type_pattern: ".*"
                reason: "wildcard type pattern"
        """)
        old, new = _make_removed_func_snaps()
        result = compare(old, new, suppression=sl)
        # func_removed is NOT a type change kind, should not be suppressed
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"

    def test_type_pattern_with_change_kind_filter(self, tmp_path: Path) -> None:
        """type_pattern + change_kind: both must match."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - type_pattern: "Packet"
                change_kind: "type_size_changed"
                reason: "only size change suppressed"
        """)
        old, new = _make_struct_change_snaps()
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count >= 1

    def test_type_pattern_enum_suppression(self, tmp_path: Path) -> None:
        """type_pattern matches enum changes (enum_member_removed)."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - type_pattern: "Status"
                reason: "Status enum member removed intentionally"
        """)
        old, new = _make_enum_change_snaps()
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count >= 1


# ===========================================================================
# 4. change-kind filter in isolation
# ===========================================================================

class TestChangeKindFilter:
    """change_kind as primary filter axis."""

    def test_change_kind_func_removed_matches_only_func_removed(self, tmp_path: Path) -> None:
        """change_kind: func_removed targets only func_removed changes."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: ".*"
                change_kind: "func_removed"
                reason: "all func_removed changes"
        """)
        old, new = _make_removed_func_snaps()
        result = compare(old, new, suppression=sl)
        # All func_removed changes suppressed by wildcard + change_kind filter
        assert all(
            c.kind != ChangeKind.FUNC_REMOVED for c in result.changes
        ), "func_removed changes should be suppressed"

    def test_change_kind_does_not_suppress_other_kinds(self, tmp_path: Path) -> None:
        """Suppression with change_kind=func_removed doesn't affect struct changes."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: ".*"
                change_kind: "func_removed"
                reason: "only func_removed"
        """)
        old, new = _make_struct_change_snaps()
        result = compare(old, new, suppression=sl)
        # Struct size changes are NOT func_removed → should remain
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"


# ===========================================================================
# 5. Multiple suppressions / added scenarios
# ===========================================================================

class TestMultipleSuppressionsAdded:
    """Multiple suppression rules and added-change scenarios."""

    def test_multiple_rules_each_match_once(self, tmp_path: Path) -> None:
        """Two rules each matching one symbol independently."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z6helperi"
                change_kind: "func_removed"
                reason: "helper removed"
              - symbol: "_Z7computei"
                change_kind: "func_removed"
                reason: "compute removed"
        """)
        old = _snap("1.0", funcs=[_fn("compute", "_Z7computei"), _fn("helper", "_Z6helperi")])
        new = _snap("2.0")  # both removed
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 2

    def test_suppressed_changes_audit_trail(self, tmp_path: Path) -> None:
        """Suppressed changes are recorded in suppressed_changes audit trail."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z6helperi"
                reason: "audit test"
        """)
        old, new = _make_removed_func_snaps()
        result = compare(old, new, suppression=sl)
        assert result.suppression_file_provided is True
        assert len(result.suppressed_changes) == result.suppressed_count


# ===========================================================================
# 6. Removed-change scenarios
# ===========================================================================

class TestRemovedChangeScenarios:
    """Suppression scenarios involving removed symbols / types."""

    def test_suppress_var_removed(self, tmp_path: Path) -> None:
        """Variable removal can be suppressed."""
        from abicheck.model import Variable
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_ZN3foo6g_varE"
                change_kind: "var_removed"
                reason: "global var intentionally removed"
        """)
        from abicheck.model import Variable
        old = _snap("1.0")
        old.variables.append(Variable(
            name="foo::g_var", mangled="_ZN3foo6g_varE", type="int",
            visibility=Visibility.PUBLIC,
        ))
        new = _snap("2.0")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 1

    def test_suppress_type_removed(self, tmp_path: Path) -> None:
        """Type removal can be suppressed with type_pattern."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - type_pattern: "OldConfig"
                reason: "OldConfig type removed intentionally"
        """)
        old = _snap("1.0", types=[RecordType(
            name="OldConfig", kind="struct", size_bits=32,
            fields=[TypeField("val", "int", 0)],
        )])
        new = _snap("2.0")
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count >= 1


# ===========================================================================
# 7. Negative scenarios — suppression should NOT match
# ===========================================================================

class TestNegativeSuppressionScenarios:
    """Ensure suppression rules do NOT over-suppress."""

    def test_no_suppression_different_change_kind(self, tmp_path: Path) -> None:
        """Suppression for wrong change_kind leaves change unsuppressed."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol: "_Z6helperi"
                change_kind: "func_params_changed"
                reason: "only for param changes, not removal"
        """)
        old, new = _make_removed_func_snaps()
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"

    def test_no_suppression_partial_pattern(self, tmp_path: Path) -> None:
        """Partial (non-fullmatch) pattern doesn't accidentally match."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions:
              - symbol_pattern: "helper"
                reason: "short pattern without anchors - fullmatch fails"
        """)
        old, new = _make_removed_func_snaps("_Z6helperi")
        result = compare(old, new, suppression=sl)
        # "helper" does not fullmatch "_Z6helperi"
        assert result.suppressed_count == 0

    def test_empty_suppression_list_no_effect(self, tmp_path: Path) -> None:
        """Empty suppression list → no changes suppressed."""
        sl = _suppression_from_yaml(tmp_path, """
            version: 1
            suppressions: []
        """)
        old, new = _make_removed_func_snaps()
        result = compare(old, new, suppression=sl)
        assert result.suppressed_count == 0
        assert result.verdict.value == "BREAKING"


# ===========================================================================
# 8. Scaffold / TODO — advanced suppression APIs (if not yet implemented)
# ===========================================================================

class TestAdvancedSuppressionScaffold:
    """Scaffold tests for suppression features that may not yet be implemented.

    These use pytest.skip with TODO markers. Remove skip when the feature
    is implemented.
    """

    @pytest.mark.skip(reason="TODO: label/tag-based suppression not yet implemented")
    def test_label_based_suppression(self) -> None:
        """TODO: suppress by label / tag annotation in suppression file."""
        # Implement when suppression supports label/group fields
        pass

    @pytest.mark.skip(reason="TODO: file-scoped suppression (by source_location) not yet implemented")
    def test_file_scoped_suppression(self) -> None:
        """TODO: suppress all changes in a specific header file."""
        # Implement when suppression supports source_location pattern
        pass

    @pytest.mark.skip(reason="TODO: suppression expiry date not yet implemented")
    def test_suppression_with_expiry_date(self) -> None:
        """TODO: suppression with 'expires' date field."""
        pass

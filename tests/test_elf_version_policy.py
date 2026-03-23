"""Tests for ELF symbol-version policy checks (diff_versioning.py).

Covers:
  - Version node removal detection
  - Symbol migration between version nodes
  - SONAME bump recommendation (breaking changes, no SONAME change)
  - SONAME bump unnecessary (no breaking changes, SONAME changed)
  - Version script missing detection
  - Integration with checker.compare()
"""
from __future__ import annotations

from abicheck.checker_policy import ChangeKind, Verdict
from abicheck.checker_types import Change
from abicheck.diff_versioning import (
    check_soname_bump_policy,
    detect_version_node_changes,
    detect_version_script_missing,
)
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sym(name: str, version: str = "", binding: SymbolBinding = SymbolBinding.GLOBAL) -> ElfSymbol:
    return ElfSymbol(
        name=name,
        binding=binding,
        sym_type=SymbolType.FUNC,
        size=8,
        version=version,
        is_default=True,
    )


def _breaking_change(symbol: str = "foo") -> Change:
    """Create a dummy BREAKING change for testing."""
    return Change(
        kind=ChangeKind.FUNC_REMOVED,
        symbol=symbol,
        description=f"Function removed: {symbol}",
    )


def _compatible_change(symbol: str = "bar") -> Change:
    """Create a dummy COMPATIBLE change for testing."""
    return Change(
        kind=ChangeKind.FUNC_ADDED,
        symbol=symbol,
        description=f"Function added: {symbol}",
    )


# ===========================================================================
# Version node removal
# ===========================================================================

class TestVersionNodeRemoved:
    def test_removed_version_node(self):
        """A version node entirely removed → SYMBOL_VERSION_NODE_REMOVED."""
        old = ElfMetadata(
            versions_defined=["LIBFOO_1.0", "LIBFOO_2.0"],
            symbols=[
                _sym("foo", "LIBFOO_1.0"),
                _sym("bar", "LIBFOO_1.0"),
                _sym("baz", "LIBFOO_2.0"),
            ],
        )
        new = ElfMetadata(
            versions_defined=["LIBFOO_2.0"],
            symbols=[
                _sym("baz", "LIBFOO_2.0"),
            ],
        )
        changes = detect_version_node_changes(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYMBOL_VERSION_NODE_REMOVED
        assert changes[0].symbol == "LIBFOO_1.0"
        assert "LIBFOO_1.0" in changes[0].description
        assert "bar" in changes[0].description or "foo" in changes[0].description

    def test_no_removed_nodes(self):
        """No nodes removed → no changes."""
        old = ElfMetadata(
            versions_defined=["LIBFOO_1.0"],
            symbols=[_sym("foo", "LIBFOO_1.0")],
        )
        new = ElfMetadata(
            versions_defined=["LIBFOO_1.0", "LIBFOO_2.0"],
            symbols=[
                _sym("foo", "LIBFOO_1.0"),
                _sym("bar", "LIBFOO_2.0"),
            ],
        )
        changes = detect_version_node_changes(old, new)
        node_removed = [c for c in changes if c.kind == ChangeKind.SYMBOL_VERSION_NODE_REMOVED]
        assert len(node_removed) == 0

    def test_empty_versions(self):
        """Both sides have no version definitions → no changes."""
        old = ElfMetadata(symbols=[_sym("foo")])
        new = ElfMetadata(symbols=[_sym("foo")])
        changes = detect_version_node_changes(old, new)
        assert changes == []


# ===========================================================================
# Symbol migration between version nodes
# ===========================================================================

class TestSymbolMovedVersionNode:
    def test_symbol_moved_between_nodes(self):
        """Symbol moves from one version node to another → SYMBOL_MOVED_VERSION_NODE."""
        old = ElfMetadata(
            versions_defined=["LIBFOO_1.0", "LIBFOO_2.0"],
            symbols=[
                _sym("foo", "LIBFOO_1.0"),
                _sym("bar", "LIBFOO_2.0"),
            ],
        )
        new = ElfMetadata(
            versions_defined=["LIBFOO_1.0", "LIBFOO_2.0"],
            symbols=[
                _sym("foo", "LIBFOO_2.0"),  # moved!
                _sym("bar", "LIBFOO_2.0"),
            ],
        )
        changes = detect_version_node_changes(old, new)
        moved = [c for c in changes if c.kind == ChangeKind.SYMBOL_MOVED_VERSION_NODE]
        assert len(moved) == 1
        assert moved[0].symbol == "foo"
        assert moved[0].old_value == "LIBFOO_1.0"
        assert moved[0].new_value == "LIBFOO_2.0"
        assert "LIBFOO_1.0" in moved[0].description
        assert "LIBFOO_2.0" in moved[0].description

    def test_symbol_stays_in_same_node(self):
        """Symbol remains in same version node → no change."""
        old = ElfMetadata(
            versions_defined=["LIBFOO_1.0"],
            symbols=[_sym("foo", "LIBFOO_1.0")],
        )
        new = ElfMetadata(
            versions_defined=["LIBFOO_1.0"],
            symbols=[_sym("foo", "LIBFOO_1.0")],
        )
        changes = detect_version_node_changes(old, new)
        moved = [c for c in changes if c.kind == ChangeKind.SYMBOL_MOVED_VERSION_NODE]
        assert len(moved) == 0


# ===========================================================================
# SONAME bump recommendation
# ===========================================================================

class TestSonameBumpRecommended:
    def test_breaking_changes_no_soname_bump(self):
        """Breaking changes but SONAME not bumped → SONAME_BUMP_RECOMMENDED."""
        old_elf = ElfMetadata(soname="libfoo.so.1")
        new_elf = ElfMetadata(soname="libfoo.so.1")
        changes = [_breaking_change("func1"), _breaking_change("func2")]

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert len(result) == 1
        assert result[0].kind == ChangeKind.SONAME_BUMP_RECOMMENDED
        assert "2 binary-incompatible" in result[0].description
        assert "libfoo.so.1" in result[0].description

    def test_breaking_changes_with_soname_bump(self):
        """Breaking changes AND SONAME bumped → no recommendation needed."""
        old_elf = ElfMetadata(soname="libfoo.so.1")
        new_elf = ElfMetadata(soname="libfoo.so.2")
        changes = [_breaking_change()]

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert result == []

    def test_no_breaking_no_soname_change(self):
        """No breaking changes, no SONAME change → nothing to report."""
        old_elf = ElfMetadata(soname="libfoo.so.1")
        new_elf = ElfMetadata(soname="libfoo.so.1")
        changes = [_compatible_change()]

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert result == []

    def test_no_soname_at_all(self):
        """No SONAME on either side → skip recommendation."""
        old_elf = ElfMetadata(soname="")
        new_elf = ElfMetadata(soname="")
        changes = [_breaking_change()]

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert result == []


# ===========================================================================
# SONAME bump unnecessary
# ===========================================================================

class TestSonameBumpUnnecessary:
    def test_soname_bumped_no_breaking(self):
        """SONAME bumped but no breaking changes → SONAME_BUMP_UNNECESSARY."""
        old_elf = ElfMetadata(soname="libfoo.so.1")
        new_elf = ElfMetadata(soname="libfoo.so.2")
        changes = [_compatible_change()]

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert len(result) == 1
        assert result[0].kind == ChangeKind.SONAME_BUMP_UNNECESSARY
        assert "libfoo.so.1" in result[0].description
        assert "libfoo.so.2" in result[0].description

    def test_soname_bumped_with_breaking(self):
        """SONAME bumped with breaking changes → no unnecessary warning."""
        old_elf = ElfMetadata(soname="libfoo.so.1")
        new_elf = ElfMetadata(soname="libfoo.so.2")
        changes = [_breaking_change()]

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert result == []

    def test_empty_changes_soname_bumped(self):
        """Empty change list but SONAME bumped → SONAME_BUMP_UNNECESSARY."""
        old_elf = ElfMetadata(soname="libfoo.so.1")
        new_elf = ElfMetadata(soname="libfoo.so.2")
        changes: list[Change] = []

        result = check_soname_bump_policy(changes, old_elf, new_elf)
        assert len(result) == 1
        assert result[0].kind == ChangeKind.SONAME_BUMP_UNNECESSARY


# ===========================================================================
# Version script missing
# ===========================================================================

class TestVersionScriptMissing:
    def test_library_without_version_script(self):
        """Library exports symbols without version script → VERSION_SCRIPT_MISSING."""
        old = ElfMetadata(
            symbols=[_sym("foo"), _sym("bar")],
            versions_defined=[],
        )
        new = ElfMetadata(
            symbols=[_sym("foo"), _sym("bar")],
            versions_defined=[],
        )
        changes = detect_version_script_missing(old, new)
        assert len(changes) == 2  # one for old, one for new
        assert all(c.kind == ChangeKind.VERSION_SCRIPT_MISSING for c in changes)

    def test_library_with_version_script(self):
        """Library has version definitions → no warning."""
        old = ElfMetadata(
            symbols=[_sym("foo", "LIBFOO_1.0")],
            versions_defined=["LIBFOO_1.0"],
        )
        new = ElfMetadata(
            symbols=[_sym("foo", "LIBFOO_1.0")],
            versions_defined=["LIBFOO_1.0"],
        )
        changes = detect_version_script_missing(old, new)
        assert changes == []

    def test_no_symbols_no_warning(self):
        """Library with no symbols → no warning (nothing to version)."""
        old = ElfMetadata(symbols=[], versions_defined=[])
        new = ElfMetadata(symbols=[], versions_defined=[])
        changes = detect_version_script_missing(old, new)
        assert changes == []

    def test_one_side_missing_version_script(self):
        """Only old side lacks version script → one warning."""
        old = ElfMetadata(
            symbols=[_sym("foo")],
            versions_defined=[],
        )
        new = ElfMetadata(
            symbols=[_sym("foo", "LIBFOO_1.0")],
            versions_defined=["LIBFOO_1.0"],
        )
        changes = detect_version_script_missing(old, new)
        assert len(changes) == 1
        assert "old" in changes[0].description


# ===========================================================================
# ChangeKind classification checks
# ===========================================================================

class TestChangeKindClassification:
    def test_symbol_version_node_removed_is_breaking(self):
        from abicheck.checker_policy import BREAKING_KINDS
        assert ChangeKind.SYMBOL_VERSION_NODE_REMOVED in BREAKING_KINDS

    def test_symbol_moved_version_node_is_risk(self):
        from abicheck.checker_policy import RISK_KINDS
        assert ChangeKind.SYMBOL_MOVED_VERSION_NODE in RISK_KINDS

    def test_soname_bump_recommended_is_compatible(self):
        from abicheck.checker_policy import COMPATIBLE_KINDS
        assert ChangeKind.SONAME_BUMP_RECOMMENDED in COMPATIBLE_KINDS

    def test_soname_bump_unnecessary_is_compatible(self):
        from abicheck.checker_policy import COMPATIBLE_KINDS
        assert ChangeKind.SONAME_BUMP_UNNECESSARY in COMPATIBLE_KINDS

    def test_version_script_missing_is_compatible(self):
        from abicheck.checker_policy import COMPATIBLE_KINDS
        assert ChangeKind.VERSION_SCRIPT_MISSING in COMPATIBLE_KINDS


# ===========================================================================
# Integration: checker.compare() picks up version policy changes
# ===========================================================================

class TestCheckerIntegration:
    def test_compare_detects_version_node_removal(self):
        """Full pipeline: version node removal is detected."""
        from abicheck.elf_metadata import ElfMetadata
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(
            library="libfoo.so.1",
            version="1.0",
            functions=[],
            variables=[],
            types=[],
            elf=ElfMetadata(
                soname="libfoo.so.1",
                versions_defined=["LIBFOO_1.0"],
                symbols=[_sym("foo", "LIBFOO_1.0")],
            ),
        )
        new = AbiSnapshot(
            library="libfoo.so.1",
            version="2.0",
            functions=[],
            variables=[],
            types=[],
            elf=ElfMetadata(
                soname="libfoo.so.1",
                versions_defined=[],
                symbols=[_sym("foo")],
            ),
        )
        from abicheck.checker import compare
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        # Should detect the version node removal and the defined version removal
        assert ChangeKind.SYMBOL_VERSION_NODE_REMOVED in kinds or \
            ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED in kinds

    def test_compare_soname_bump_recommended(self):
        """Full pipeline: SONAME bump recommendation fires when breaking + no bump."""
        from abicheck.model import AbiSnapshot, Function, Visibility

        old = AbiSnapshot(
            library="libfoo.so.1",
            version="1.0",
            functions=[
                Function(name="removed_func", mangled="removed_func",
                         return_type="void", params=[],
                         visibility=Visibility.PUBLIC),
            ],
            variables=[],
            types=[],
            elf=ElfMetadata(
                soname="libfoo.so.1",
                symbols=[_sym("removed_func")],
            ),
        )
        new = AbiSnapshot(
            library="libfoo.so.1",
            version="2.0",
            functions=[],
            variables=[],
            types=[],
            elf=ElfMetadata(
                soname="libfoo.so.1",
                symbols=[],
            ),
        )
        from abicheck.checker import compare
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        # The function removal is breaking; soname unchanged → recommendation
        assert ChangeKind.SONAME_BUMP_RECOMMENDED in kinds

    def test_compare_version_script_missing(self):
        """Full pipeline: version script missing warning."""
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(
            library="libfoo.so.1",
            version="1.0",
            functions=[],
            variables=[],
            types=[],
            elf=ElfMetadata(
                soname="libfoo.so.1",
                symbols=[_sym("foo")],
                versions_defined=[],
            ),
        )
        new = AbiSnapshot(
            library="libfoo.so.1",
            version="2.0",
            functions=[],
            variables=[],
            types=[],
            elf=ElfMetadata(
                soname="libfoo.so.1",
                symbols=[_sym("foo")],
                versions_defined=[],
            ),
        )
        from abicheck.checker import compare
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.VERSION_SCRIPT_MISSING in kinds

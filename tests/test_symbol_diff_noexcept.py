"""B9: symbol_diff.py NOEXCEPT path (QA gap from PR #87 review).

Tests for the noexcept change detection in diff_symbols().

In C++17, `noexcept` is part of the function type and affects mangling.
Both adding and removing noexcept are ABI-breaking changes.

This directly tests the `_diff_function_pair` logic in symbol_diff.py.
"""
from __future__ import annotations

from abicheck.core.corpus.normalizer import NormalizedSnapshot
from abicheck.core.diff.symbol_diff import diff_symbols
from abicheck.core.model import ChangeKind, ChangeSeverity
from abicheck.model import AbiSnapshot, Function, Visibility


def _snap_with_func(
    name: str,
    mangled: str,
    is_noexcept: bool,
    return_type: str = "void",
    version: str = "1.0",
) -> AbiSnapshot:
    return AbiSnapshot(
        library="lib.so",
        version=version,
        functions=[Function(
            name=name,
            mangled=mangled,
            return_type=return_type,
            visibility=Visibility.PUBLIC,
            is_noexcept=is_noexcept,
        )],
    )


def _normalized(snap: AbiSnapshot) -> NormalizedSnapshot:
    from abicheck.core.corpus.normalizer import Normalizer
    return Normalizer().normalize(snap)


class TestSymbolDiffNoexcept:
    """Direct tests of diff_symbols() for noexcept path."""

    def test_noexcept_removed_is_break(self) -> None:
        """noexcept=True → noexcept=False must emit a BREAK change.

        Removing noexcept widens the exception spec: callers that relied on
        std::terminate being called on exception now face undefined behavior.
        """
        old = _normalized(_snap_with_func("foo", "_Z3foov", is_noexcept=True))
        new = _normalized(_snap_with_func("foo", "_Z3foov", is_noexcept=False))

        changes = diff_symbols(old, new)
        noexcept_changes = [c for c in changes if c.change_kind == ChangeKind.SYMBOL
                            and c.entity_name == "foo"]
        assert noexcept_changes, "noexcept removed must emit a Change"
        # At least one change must be BREAK severity
        severities = {c.severity for c in noexcept_changes}
        assert ChangeSeverity.BREAK in severities

    def test_noexcept_added_is_break(self) -> None:
        """noexcept=False → noexcept=True must emit a BREAK change.

        In C++17, noexcept is part of the function type and mangled name.
        Callers compiled against old (non-noexcept) header get undefined symbol.
        """
        old = _normalized(_snap_with_func("bar", "_Z3barv", is_noexcept=False))
        new = _normalized(_snap_with_func("bar", "_Z3barv", is_noexcept=True))

        changes = diff_symbols(old, new)
        noexcept_changes = [c for c in changes if c.change_kind == ChangeKind.SYMBOL
                            and c.entity_name == "bar"]
        assert noexcept_changes, "noexcept added must emit a Change"
        severities = {c.severity for c in noexcept_changes}
        assert ChangeSeverity.BREAK in severities

    def test_noexcept_unchanged_no_extra_change(self) -> None:
        """noexcept=True in both → no noexcept-related change emitted."""
        old = _normalized(_snap_with_func("baz", "_Z3bazv", is_noexcept=True))
        new = _normalized(_snap_with_func("baz", "_Z3bazv", is_noexcept=True))

        changes = diff_symbols(old, new)
        # Identical functions → no changes
        assert not changes, f"Identical noexcept functions must not produce changes: {changes}"

    def test_noexcept_false_to_false_no_change(self) -> None:
        """noexcept=False in both → no noexcept-related change emitted."""
        old = _normalized(_snap_with_func("qux", "_Z3quxv", is_noexcept=False))
        new = _normalized(_snap_with_func("qux", "_Z3quxv", is_noexcept=False))

        changes = diff_symbols(old, new)
        assert not changes

    def test_noexcept_change_entity_name_matches(self) -> None:
        """Change entity_name must match the function name."""
        old = _normalized(_snap_with_func("Widget::init", "_ZN6Widget4initEv", is_noexcept=True))
        new = _normalized(_snap_with_func("Widget::init", "_ZN6Widget4initEv", is_noexcept=False))

        changes = diff_symbols(old, new)
        names = {c.entity_name for c in changes}
        assert "Widget::init" in names

    def test_noexcept_change_origin_castxml(self) -> None:
        """noexcept changes must have CASTXML origin (detected from header parsing)."""
        from abicheck.core.model import Origin

        old = _normalized(_snap_with_func("myFunc", "_ZmyFuncv", is_noexcept=True))
        new = _normalized(_snap_with_func("myFunc", "_ZmyFuncv", is_noexcept=False))

        changes = diff_symbols(old, new)
        noexcept_changes = [c for c in changes if c.entity_name == "myFunc"]
        assert noexcept_changes
        origins = {c.origin for c in noexcept_changes}
        assert Origin.CASTXML in origins

    def test_noexcept_removed_via_compare(self) -> None:
        """End-to-end: compare() reports FUNC_NOEXCEPT_REMOVED for noexcept removed."""
        from abicheck.checker import ChangeKind as CK
        from abicheck.checker import compare

        old = AbiSnapshot(library="lib.so", version="1.0", functions=[
            Function(name="process", mangled="_Zprocess", return_type="void",
                     visibility=Visibility.PUBLIC, is_noexcept=True),
        ])
        new = AbiSnapshot(library="lib.so", version="2.0", functions=[
            Function(name="process", mangled="_Zprocess", return_type="void",
                     visibility=Visibility.PUBLIC, is_noexcept=False),
        ])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert CK.FUNC_NOEXCEPT_REMOVED in kinds

    def test_noexcept_added_via_compare(self) -> None:
        """End-to-end: compare() reports FUNC_NOEXCEPT_ADDED for noexcept added."""
        from abicheck.checker import ChangeKind as CK
        from abicheck.checker import compare

        old = AbiSnapshot(library="lib.so", version="1.0", functions=[
            Function(name="compute", mangled="_Zcompute", return_type="int",
                     visibility=Visibility.PUBLIC, is_noexcept=False),
        ])
        new = AbiSnapshot(library="lib.so", version="2.0", functions=[
            Function(name="compute", mangled="_Zcompute", return_type="int",
                     visibility=Visibility.PUBLIC, is_noexcept=True),
        ])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert CK.FUNC_NOEXCEPT_ADDED in kinds

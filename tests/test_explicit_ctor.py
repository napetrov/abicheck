"""Tests for CTOR_EXPLICIT_ADDED / CTOR_EXPLICIT_REMOVED.

Synthetic snapshots — no compiler needed. Exercises the `is_explicit` flag
captured from DW_AT_explicit and the diff logic in diff_symbols.py.
"""

from abicheck.checker import compare
from abicheck.checker_policy import API_BREAK_KINDS, RISK_KINDS, ChangeKind, Verdict
from abicheck.model import AbiSnapshot, Function, Param, Visibility


def _snap(version: str, functions: list[Function]) -> AbiSnapshot:
    return AbiSnapshot(
        library="libtest.so.1",
        version=version,
        functions=functions,
        variables=[],
        types=[],
    )


def _ctor(mangled: str, is_explicit: bool) -> Function:
    return Function(
        name="Foo::Foo",
        mangled=mangled,
        return_type="void",
        params=[Param(name="x", type="int")],
        visibility=Visibility.PUBLIC,
        is_explicit=is_explicit,
    )


class TestExplicitCtor:
    def test_implicit_to_explicit_is_api_break(self) -> None:
        old = _snap("1.0", [_ctor("_ZN3FooC1Ei", is_explicit=False)])
        new = _snap("2.0", [_ctor("_ZN3FooC1Ei", is_explicit=True)])
        r = compare(old, new)
        assert r.verdict == Verdict.API_BREAK
        assert any(c.kind == ChangeKind.CTOR_EXPLICIT_ADDED for c in r.changes)
        assert ChangeKind.CTOR_EXPLICIT_ADDED in API_BREAK_KINDS

    def test_explicit_to_implicit_is_risk(self) -> None:
        old = _snap("1.0", [_ctor("_ZN3FooC1Ei", is_explicit=True)])
        new = _snap("2.0", [_ctor("_ZN3FooC1Ei", is_explicit=False)])
        r = compare(old, new)
        # COMPATIBLE_WITH_RISK is reported via verdict; the change itself is in RISK_KINDS
        assert any(c.kind == ChangeKind.CTOR_EXPLICIT_REMOVED for c in r.changes)
        assert ChangeKind.CTOR_EXPLICIT_REMOVED in RISK_KINDS

    def test_no_change_when_explicit_matches(self) -> None:
        old = _snap("1.0", [_ctor("_ZN3FooC1Ei", is_explicit=True)])
        new = _snap("2.0", [_ctor("_ZN3FooC1Ei", is_explicit=True)])
        r = compare(old, new)
        assert not any(
            c.kind in (ChangeKind.CTOR_EXPLICIT_ADDED, ChangeKind.CTOR_EXPLICIT_REMOVED)
            for c in r.changes
        )

    def test_mangled_name_unchanged(self) -> None:
        """The explicit specifier never changes the mangled name; both
        directions must rely on `is_explicit` rather than symbol churn."""
        old = _ctor("_ZN3FooC1Ei", is_explicit=False)
        new = _ctor("_ZN3FooC1Ei", is_explicit=True)
        assert old.mangled == new.mangled

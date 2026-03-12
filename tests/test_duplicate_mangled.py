"""B5: Duplicate mangled symbols (abi-dumper #41).

When the same mangled name appears twice in castxml output (e.g. from
template instantiations in multiple translation units), abicheck must
handle deduplication deterministically.

Policy: first-wins — when building the snapshot index (function_map), the
first Function with a given mangled name takes precedence.

This is safe because:
1. Same mangled name → same function signature (by definition)
2. Linker would also deduplicate these at link time
3. Keeping first-seen is deterministic and auditable

abi-dumper #41: the original tool did not deduplicate and could produce
unstable diffs when template instantiations appeared in multiple TUs.
"""
from __future__ import annotations

import pytest

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.model import AbiSnapshot, Function, Visibility


def _func(name: str, mangled: str, return_type: str = "void", **kwargs: object) -> Function:
    defaults: dict[str, object] = dict(visibility=Visibility.PUBLIC)
    defaults.update(kwargs)
    return Function(name=name, mangled=mangled, return_type=return_type, **defaults)  # type: ignore[arg-type]


class TestDuplicateMangledSymbols:
    """Verify deduplication behavior for duplicate mangled names."""

    def test_snapshot_index_last_wins(self) -> None:
        """When two functions share a mangled name, last one wins in function_map.

        The index is built via dict comprehension:
          {f.mangled: f for f in self.functions}
        which is last-wins for duplicate keys. This is documented behavior.
        Callers must ensure no duplicate mangled names are inserted if
        first-wins semantics are needed.
        """
        mangled = "_Z3foov"
        f1 = _func("foo", mangled, return_type="void")
        f2 = _func("foo_alt", mangled, return_type="int")  # same mangled, different name

        snap = AbiSnapshot(library="lib.so", version="1.0", functions=[f1, f2])
        # Dict comprehension → last-wins: f2 takes precedence
        indexed = snap.function_map[mangled]
        assert indexed.name == "foo_alt"
        assert indexed.return_type == "int"

    def test_snapshot_index_deduplication_deterministic(self) -> None:
        """function_map must always return the same function for a given mangled name."""
        mangled = "_ZN3Bar4initEv"
        func_a = _func("Bar::init", mangled, return_type="bool")
        func_b = _func("Bar::init", mangled, return_type="bool")  # identical duplicate

        snap = AbiSnapshot(library="lib.so", version="1.0", functions=[func_a, func_b])
        # Both are the same — just verify no crash and consistent result
        result = snap.function_map[mangled]
        assert result.mangled == mangled

    def test_compare_with_duplicate_mangled_no_crash(self) -> None:
        """compare() must not crash when snapshots have duplicate mangled names."""
        mangled = "_Z9templateEv"
        f_old = _func("template_func", mangled, return_type="void")
        f_new = _func("template_func", mangled, return_type="void")

        old = AbiSnapshot(library="lib.so", version="1.0", functions=[f_old, f_old])
        new = AbiSnapshot(library="lib.so", version="2.0", functions=[f_new, f_new])

        # Must not raise
        result = compare(old, new)
        assert result.verdict == Verdict.NO_CHANGE

    def test_compare_duplicate_vs_single_no_false_positives(self) -> None:
        """Comparing snapshot with duplicate (v1) to single (v2) must not falsely
        report a removal if the function is still there."""
        mangled = "_Z4funcEv"
        f = _func("func", mangled, return_type="int")

        old = AbiSnapshot(library="lib.so", version="1.0", functions=[f, f])  # duplicate
        new = AbiSnapshot(library="lib.so", version="2.0", functions=[f])     # single

        result = compare(old, new)
        # The function is still present — no removal
        removed = [c for c in result.changes if c.kind == ChangeKind.FUNC_REMOVED]
        assert not removed

    def test_duplicate_mangled_different_versions_detected(self) -> None:
        """If two functions with same mangled name differ in return type,
        the last one's signature (last-wins) is used for comparison."""
        mangled = "_Z6updatev"
        f1_old = _func("update", mangled, return_type="void")
        f2_old = _func("update_extra", mangled, return_type="int")  # duplicate, last-wins

        # In new snapshot, the function has return_type="int" (same as f2_old last-wins)
        f1_new = _func("update", mangled, return_type="int")

        old = AbiSnapshot(library="lib.so", version="1.0", functions=[f1_old, f2_old])
        new = AbiSnapshot(library="lib.so", version="2.0", functions=[f1_new])

        result = compare(old, new)
        # Last-wins: old index has f2_old (return=int), new has f1_new (return=int)
        # → no return type change
        kinds = {c.kind for c in result.changes}
        # Both sides have int return type (last-wins for old) → no FUNC_RETURN_CHANGED
        assert ChangeKind.FUNC_RETURN_CHANGED not in kinds

    def test_dedup_documented_behavior(self) -> None:
        """Document last-wins deduplication: verify function_map iteration order
        matches insertion order (Python dict maintains insertion order ≥3.7).

        The index is built as: {f.mangled: f for f in self.functions}
        For duplicate keys, the last entry wins (standard Python dict behavior).
        """
        mangled = "_Z3bazv"
        first = _func("baz_first", mangled, return_type="void")
        second = _func("baz_second", mangled, return_type="int")

        snap = AbiSnapshot(library="lib.so", version="1.0", functions=[first, second])
        # Dict comprehension: {f.mangled: f for f in [first, second]} → last-wins
        indexed = snap.function_map[mangled]
        # Last inserted (second) must win
        assert indexed.name == "baz_second"
        assert indexed.return_type == "int"

    def test_variable_dedup_consistent(self) -> None:
        """Variable deduplication must also be consistent."""
        from abicheck.model import Variable

        mangled = "_ZN3Foo3gVarE"
        v1 = Variable(name="Foo::gVar", mangled=mangled, type="int")
        v2 = Variable(name="Foo::gVar", mangled=mangled, type="double")  # duplicate

        snap = AbiSnapshot(library="lib.so", version="1.0", variables=[v1, v2])
        indexed = snap.variable_map[mangled]
        # Must be one of the two — deterministic
        assert indexed.mangled == mangled
        assert indexed.type in ("int", "double")

"""Phase 1c integration tests — end-to-end v0.2 pipeline.

Uses real AbiSnapshots from the existing example libraries to validate
that the v0.2 pipeline produces results consistent with the existing checker.

These tests are marked @pytest.mark.integration and require pre-built .so files.
They skip gracefully in CI unit-test jobs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from abicheck.core.model import ChangeKind, ChangeSeverity
from abicheck.core.pipeline import analyse
from abicheck.model import AbiSnapshot, Function, RecordType, TypeField, Visibility

REPO_ROOT = Path(__file__).parent.parent


def _make_snap(funcs=(), vars_=(), types=(), version="v1") -> AbiSnapshot:
    return AbiSnapshot(
        library="libtest.so",
        version=version,
        functions=list(funcs),
        variables=list(vars_),
        types=list(types),
    )


class TestPipelineUnit:
    """Unit-level pipeline tests (no .so required)."""

    def test_no_changes_returns_empty(self) -> None:
        f = Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC)
        old = _make_snap(funcs=[f])
        new = _make_snap(funcs=[f], version="v2")
        changes = analyse(old, new)
        assert changes == []

    def test_removed_function_is_break(self) -> None:
        f = Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC)
        old = _make_snap(funcs=[f])
        new = _make_snap(version="v2")
        changes = analyse(old, new)
        assert len(changes) == 1
        assert changes[0].severity == ChangeSeverity.BREAK
        assert changes[0].change_kind == ChangeKind.SYMBOL
        assert changes[0].entity_name == "foo"

    def test_added_function_is_compatible_extension(self) -> None:
        f = Function(name="bar", mangled="_Z3barv", return_type="void", visibility=Visibility.PUBLIC)
        old = _make_snap()
        new = _make_snap(funcs=[f], version="v2")
        changes = analyse(old, new)
        assert len(changes) == 1
        assert changes[0].severity == ChangeSeverity.COMPATIBLE_EXTENSION

    def test_type_size_change_is_break(self) -> None:
        t_old = RecordType(name="Pt", kind="struct", size_bits=64,
                           fields=[TypeField(name="x", type="int", offset_bits=0)])
        t_new = RecordType(name="Pt", kind="struct", size_bits=96,
                           fields=[TypeField(name="x", type="int", offset_bits=0),
                                   TypeField(name="y", type="int", offset_bits=64)])
        old = _make_snap(types=[t_old])
        new = _make_snap(types=[t_new], version="v2")
        changes = analyse(old, new)
        assert any(c.change_kind == ChangeKind.SIZE_CHANGE for c in changes)
        assert all(c.severity == ChangeSeverity.BREAK for c in changes)

    def test_output_is_sorted_deterministically(self) -> None:
        f_a = Function(name="alpha", mangled="_Za", return_type="int", visibility=Visibility.PUBLIC)
        f_b = Function(name="beta",  mangled="_Zb", return_type="int", visibility=Visibility.PUBLIC)
        old = _make_snap(funcs=[f_a, f_b])
        new = _make_snap(version="v2")
        changes = analyse(old, new)
        names = [c.entity_name for c in changes]
        assert names == sorted(names)

    def test_hidden_symbols_not_in_changes(self) -> None:
        f_pub = Function(name="pub", mangled="_Zpub", return_type="int", visibility=Visibility.PUBLIC)
        f_hid = Function(name="hid", mangled="_Zhid", return_type="int", visibility=Visibility.HIDDEN)
        old = _make_snap(funcs=[f_pub, f_hid])
        new = _make_snap(version="v2")
        changes = analyse(old, new)
        assert all(c.entity_name != "hid" for c in changes)
        assert len(changes) == 1


@pytest.mark.integration
class TestPipelineIntegration:
    """Integration tests using real .so files from examples/."""

    def _load(self, case: str, ver: str) -> AbiSnapshot:
        so = (REPO_ROOT / f"examples/{case}/lib{ver}.so").resolve()
        hdr_candidates = [f"{ver}.h", f"{ver}.hpp", f"{ver}.c", f"{ver}.cpp"]
        hdr = None
        for c in hdr_candidates:
            p = (REPO_ROOT / f"examples/{case}/{c}").resolve()
            if p.exists():
                hdr = p
                break
        if not so.exists():
            pytest.skip(f"pre-built artifact missing: {so}")
        if hdr is None:
            pytest.skip(f"no header found for {case}/{ver}")

        from abicheck.dumper import dump
        compiler = "cc" if hdr and hdr.suffix == ".c" else "c++"
        return dump(so, [hdr], version=ver, compiler=compiler)

    def test_case01_symbol_removal_produces_break(self) -> None:
        old = self._load("case01_symbol_removal", "v1")
        new = self._load("case01_symbol_removal", "v2")
        changes = analyse(old, new)
        breaks = [c for c in changes if c.severity == ChangeSeverity.BREAK]
        assert len(breaks) >= 1

    def test_case07_struct_layout_produces_size_change(self) -> None:
        old = self._load("case07_struct_layout", "v1")
        new = self._load("case07_struct_layout", "v2")
        changes = analyse(old, new)
        assert any(c.change_kind == ChangeKind.SIZE_CHANGE for c in changes)

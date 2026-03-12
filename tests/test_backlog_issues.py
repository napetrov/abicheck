"""Tests for backlog issues #66, #64, #70.

- #66: TYPE_VTABLE_CHANGED must include old_value/new_value with slot lists
- #64: detect_profile() ELF-only mode must return 'c' when no _Z prefix
- #70: extern "C" heuristic consistency — no false 'cpp' on C-only ELF libraries
"""
from __future__ import annotations

from typing import Any

from abicheck.checker import ChangeKind, compare
from abicheck.core.pipeline import detect_profile
from abicheck.model import AbiSnapshot, Function, RecordType, Visibility


def _snap_vtable(name: str, vtable: list[str]) -> AbiSnapshot:
    return AbiSnapshot(
        library="lib.so",
        version="1.0",
        types=[RecordType(name=name, kind="class", vtable=vtable)],
    )


def _func(name: str, mangled: str, *, is_extern_c: bool = False,
          vis: Visibility = Visibility.PUBLIC) -> Function:
    return Function(
        name=name, mangled=mangled, return_type="void",
        visibility=vis, is_extern_c=is_extern_c,
    )


# ── Issue #66: vtable old_value / new_value ─────────────────────────────────

class TestVtableOldNewValue:
    """TYPE_VTABLE_CHANGED must carry old_value and new_value with slot lists."""

    def test_vtable_reorder_has_old_new_value(self) -> None:
        """Pure reorder: old_value and new_value must be populated with correct order."""
        old = _snap_vtable("Foo", ["_ZN3Foo4drawEv", "_ZN3Foo6resizeEv"])
        new = _snap_vtable("Foo", ["_ZN3Foo6resizeEv", "_ZN3Foo4drawEv"])
        result = compare(old, new)
        change = next(c for c in result.changes
                      if c.kind == ChangeKind.TYPE_VTABLE_CHANGED)
        assert change.old_value is not None, "old_value must not be None"
        assert change.new_value is not None, "new_value must not be None"
        # Verify ordering, not just membership
        assert change.old_value.index("_ZN3Foo4drawEv") < change.old_value.index("_ZN3Foo6resizeEv"), (
            "old_value must preserve original vtable order: draw before resize"
        )
        assert change.new_value.index("_ZN3Foo6resizeEv") < change.new_value.index("_ZN3Foo4drawEv"), (
            "new_value must preserve new vtable order: resize before draw"
        )

    def test_vtable_entry_added_has_old_new_value(self) -> None:
        """Vtable entry added: old_value and new_value must reflect slot lists."""
        old = _snap_vtable("Bar", ["_ZN3Bar4drawEv"])
        new = _snap_vtable("Bar", ["_ZN3Bar4drawEv", "_ZN3Bar6updateEv"])
        result = compare(old, new)
        change = next(c for c in result.changes
                      if c.kind == ChangeKind.TYPE_VTABLE_CHANGED)
        assert "_ZN3Bar6updateEv" in change.new_value
        assert "_ZN3Bar6updateEv" not in change.old_value

    def test_vtable_no_change_no_event(self) -> None:
        """Identical vtable must not emit TYPE_VTABLE_CHANGED."""
        old = _snap_vtable("Baz", ["_ZN3Baz3fooEv"])
        new = _snap_vtable("Baz", ["_ZN3Baz3fooEv"])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.TYPE_VTABLE_CHANGED not in kinds


# ── Issue #64: detect_profile ELF-only ──────────────────────────────────────

class TestDetectProfileElfOnly:
    """detect_profile() must return 'c' for ELF-only snapshots with no _Z symbols."""

    def test_elf_only_no_z_prefix_returns_c(self) -> None:
        """Pure C library in ELF-only mode: profile must be 'c', not None."""
        snap = AbiSnapshot(
            library="libc_lib.so", version="1.0",
            functions=[
                _func("init_ctx", "init_ctx", vis=Visibility.ELF_ONLY),
                _func("process", "process", vis=Visibility.ELF_ONLY),
            ],
            elf_only_mode=True,
        )
        profile = detect_profile(snap)
        assert profile == "c", (
            f"ELF-only C library must detect as 'c', got {profile!r}"
        )

    def test_elf_only_with_z_prefix_returns_cpp(self) -> None:
        """ELF-only C++ library (has _Z symbols) must still detect as 'cpp'."""
        snap = AbiSnapshot(
            library="libcpp.so", version="1.0",
            functions=[
                _func("Foo::bar", "_ZN3Foo3barEv", vis=Visibility.ELF_ONLY),
            ],
            elf_only_mode=True,
        )
        profile = detect_profile(snap)
        assert profile == "cpp"

    def test_castxml_c_mode_no_extern_attr_no_z(self) -> None:
        """castxml C-mode: no extern='1', mangled == plain name.
        Must not return 'cpp'."""
        snap = AbiSnapshot(
            library="lib.so", version="1.0",
            functions=[
                _func("foo", "foo", is_extern_c=False, vis=Visibility.PUBLIC),
            ],
        )
        profile = detect_profile(snap)
        assert profile in (None, "c"), (
            f"Without _Z prefix must not return 'cpp', got {profile!r}"
        )

    def test_elf_only_mode_sets_is_extern_c_for_non_z(self, tmp_path: Any, monkeypatch: Any) -> None:
        """ELF-only dump() must set is_extern_c=True for non-_Z symbols via the real code path."""
        import abicheck.dumper as _dumper

        symbols = {"init_ctx", "_ZN3FoobarEv", "process"}

        # Stub ELF symbol extraction
        monkeypatch.setattr(_dumper, "_pyelftools_exported_symbols",
                            lambda path: (symbols, symbols))
        # Stub metadata parsers to avoid real ELF parsing
        monkeypatch.setattr(
            "abicheck.elf_metadata.parse_elf_metadata", lambda *a, **kw: None,
            raising=False,
        )
        monkeypatch.setattr(
            "abicheck.dwarf_metadata.parse_dwarf_metadata", lambda *a, **kw: None,
            raising=False,
        )
        monkeypatch.setattr(
            "abicheck.dwarf_metadata.parse_dwarf_advanced", lambda *a, **kw: None,
            raising=False,
        )

        # Create a dummy .so that passes path existence checks
        dummy_so = tmp_path / "libtest.so"
        dummy_so.write_bytes(b"\x7fELF")

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from abicheck.dumper import dump
            snap = dump(dummy_so, headers=[], version="1.0")

        by_mangled = {f.mangled: f for f in snap.functions}
        assert by_mangled["init_ctx"].is_extern_c is True,        "init_ctx → C linkage"
        assert by_mangled["_ZN3FoobarEv"].is_extern_c is False,   "_Z → C++ linkage"
        assert by_mangled["process"].is_extern_c is True,         "process → C linkage"


# ── Issue #70: extern "C" edge cases ─────────────────────────────────────────

class TestExternCEdgeCases:
    """extern "C" detection robustness."""

    def test_mixed_c_cpp_returns_cpp(self) -> None:
        """Library with both extern C and _Z symbols → 'cpp' wins."""
        snap = AbiSnapshot(
            library="lib.so", version="1.0",
            functions=[
                _func("c_init", "c_init", is_extern_c=True, vis=Visibility.PUBLIC),
                _func("CppClass::method", "_ZN8CppClass6methodEv", vis=Visibility.PUBLIC),
            ],
        )
        profile = detect_profile(snap)
        assert profile == "cpp"

    def test_all_extern_c_returns_c(self) -> None:
        """All public functions are extern C → 'c'."""
        snap = AbiSnapshot(
            library="lib.so", version="1.0",
            functions=[
                _func("foo", "foo", is_extern_c=True, vis=Visibility.PUBLIC),
                _func("bar", "bar", is_extern_c=True, vis=Visibility.PUBLIC),
            ],
        )
        assert detect_profile(snap) == "c"

    def test_no_functions_returns_none(self) -> None:
        """Empty function list → None."""
        snap = AbiSnapshot(library="lib.so", version="1.0")
        assert detect_profile(snap) is None

    def test_explicit_profile_overrides_heuristic(self) -> None:
        """Explicit language_profile must always win over heuristic."""
        snap = AbiSnapshot(
            library="lib.so", version="1.0",
            language_profile="sycl",
            functions=[
                _func("foo", "_ZN3fooEv", vis=Visibility.PUBLIC),
            ],
        )
        assert detect_profile(snap) == "sycl"

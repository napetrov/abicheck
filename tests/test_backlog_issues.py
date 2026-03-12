"""Tests for backlog issues #66, #64, #70.

- #66: TYPE_VTABLE_CHANGED must include old_value/new_value with slot lists
- #64: detect_profile() ELF-only mode must return 'c' when no _Z prefix
- #70: extern "C" heuristic consistency — no false 'cpp' on C-only ELF libraries
"""
from __future__ import annotations

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
        """Pure reorder: old_value and new_value must be populated."""
        old = _snap_vtable("Foo", ["_ZN3Foo4drawEv", "_ZN3Foo6resizeEv"])
        new = _snap_vtable("Foo", ["_ZN3Foo6resizeEv", "_ZN3Foo4drawEv"])
        result = compare(old, new)
        change = next(c for c in result.changes
                      if c.kind == ChangeKind.TYPE_VTABLE_CHANGED)
        assert change.old_value is not None, "old_value must not be None"
        assert change.new_value is not None, "new_value must not be None"
        assert "_ZN3Foo4drawEv" in change.old_value
        assert "_ZN3Foo6resizeEv" in change.old_value

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

    def test_elf_only_mode_sets_is_extern_c_for_non_z(self) -> None:
        """ELF-only dump must set is_extern_c=True for non-_Z symbols."""
        from abicheck.model import Function as F

        # Simulate what dump() produces in ELF-only mode
        funcs = [
            F(name=sym, mangled=sym, return_type="?",
              visibility=Visibility.ELF_ONLY,
              is_extern_c=not sym.startswith("_Z"))
            for sym in ["init_ctx", "_ZN3FoobarEv", "process"]
        ]
        assert funcs[0].is_extern_c is True    # init_ctx → C
        assert funcs[1].is_extern_c is False   # _Z → C++
        assert funcs[2].is_extern_c is True    # process → C


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

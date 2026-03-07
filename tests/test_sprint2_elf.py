"""Sprint 2 ELF-only detector tests.

All tests build AbiSnapshot + ElfMetadata directly — no castxml, no readelf required.
"""
from __future__ import annotations

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType
from abicheck.model import AbiSnapshot


def _snap(elf: ElfMetadata | None = None, **kwargs: object) -> AbiSnapshot:
    defaults: dict[str, object] = dict(library="lib.so", version="1.0")
    defaults.update(kwargs)
    s = AbiSnapshot(**defaults)  # type: ignore[arg-type]
    s.elf = elf
    return s


def _elf(**kwargs: object) -> ElfMetadata:
    defaults: dict[str, object] = dict(soname="libfoo.so.1")
    defaults.update(kwargs)
    return ElfMetadata(**defaults)  # type: ignore[arg-type]


def _sym(name: str, **kwargs: object) -> ElfSymbol:
    defaults: dict[str, object] = dict(
        binding=SymbolBinding.GLOBAL, sym_type=SymbolType.FUNC, size=0
    )
    defaults.update(kwargs)
    return ElfSymbol(name=name, **defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dynamic section tests
# ---------------------------------------------------------------------------

def test_soname_changed() -> None:
    old = _snap(_elf(soname="libfoo.so.1"))
    new = _snap(_elf(soname="libfoo.so.2"))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SONAME_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


def test_needed_added() -> None:
    old = _snap(_elf(needed=["libc.so.6"]))
    new = _snap(_elf(needed=["libc.so.6", "libssl.so.3"]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.NEEDED_ADDED in kinds
    assert result.verdict == Verdict.BREAKING


def test_needed_removed() -> None:
    old = _snap(_elf(needed=["libc.so.6", "libm.so.6"]))
    new = _snap(_elf(needed=["libc.so.6"]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.NEEDED_REMOVED in kinds
    assert result.verdict == Verdict.COMPATIBLE  # NEEDED_REMOVED is compatible


def test_rpath_changed() -> None:
    old = _snap(_elf(rpath="/opt/old/lib"))
    new = _snap(_elf(rpath="/opt/new/lib"))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.RPATH_CHANGED in kinds


def test_runpath_changed() -> None:
    old = _snap(_elf(runpath="/opt/old/lib"))
    new = _snap(_elf(runpath=""))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.RUNPATH_CHANGED in kinds


# ---------------------------------------------------------------------------
# Symbol versioning tests
# ---------------------------------------------------------------------------

def test_symbol_version_defined_removed() -> None:
    old = _snap(_elf(versions_defined=["LIBFOO_1.0", "LIBFOO_2.0"]))
    new = _snap(_elf(versions_defined=["LIBFOO_2.0"]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED in kinds
    assert result.verdict == Verdict.BREAKING


def test_symbol_version_required_added() -> None:
    """New GLIBC_2.34 requirement = breaks on older distros."""
    old = _snap(_elf(versions_required={"libc.so.6": ["GLIBC_2.5"]}))
    new = _snap(_elf(versions_required={"libc.so.6": ["GLIBC_2.5", "GLIBC_2.34"]}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED in kinds
    assert result.verdict == Verdict.BREAKING


def test_symbol_version_required_removed() -> None:
    old = _snap(_elf(versions_required={"libc.so.6": ["GLIBC_2.5", "GLIBC_2.17"]}))
    new = _snap(_elf(versions_required={"libc.so.6": ["GLIBC_2.5"]}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SYMBOL_VERSION_REQUIRED_REMOVED in kinds


# ---------------------------------------------------------------------------
# Per-symbol metadata tests
# ---------------------------------------------------------------------------

def test_symbol_binding_global_to_weak() -> None:
    old = _snap(_elf(symbols=[_sym("foo", binding=SymbolBinding.GLOBAL)]))
    new = _snap(_elf(symbols=[_sym("foo", binding=SymbolBinding.WEAK)]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SYMBOL_BINDING_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


def test_symbol_type_func_to_object() -> None:
    old = _snap(_elf(symbols=[_sym("bar", sym_type=SymbolType.FUNC)]))
    new = _snap(_elf(symbols=[_sym("bar", sym_type=SymbolType.OBJECT)]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SYMBOL_TYPE_CHANGED in kinds


def test_ifunc_introduced() -> None:
    old = _snap(_elf(symbols=[_sym("dispatch", sym_type=SymbolType.FUNC)]))
    new = _snap(_elf(symbols=[_sym("dispatch", sym_type=SymbolType.IFUNC)]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.IFUNC_INTRODUCED in kinds
    assert result.verdict == Verdict.BREAKING


def test_ifunc_removed() -> None:
    old = _snap(_elf(symbols=[_sym("dispatch", sym_type=SymbolType.IFUNC)]))
    new = _snap(_elf(symbols=[_sym("dispatch", sym_type=SymbolType.FUNC)]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.IFUNC_REMOVED in kinds
    assert result.verdict == Verdict.BREAKING


def test_symbol_size_changed() -> None:
    old = _snap(_elf(symbols=[_sym("g_state", sym_type=SymbolType.OBJECT, size=8)]))
    new = _snap(_elf(symbols=[_sym("g_state", sym_type=SymbolType.OBJECT, size=16)]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.SYMBOL_SIZE_CHANGED in kinds


def test_common_symbol_risk() -> None:
    old = _snap(_elf(symbols=[]))
    new = _snap(_elf(symbols=[_sym("g_counter", sym_type=SymbolType.COMMON)]))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.COMMON_SYMBOL_RISK in kinds


# ---------------------------------------------------------------------------
# No-change negative tests
# ---------------------------------------------------------------------------

def test_no_elf_changes() -> None:
    """Identical ELF metadata → no ELF-related changes."""
    elf = _elf(
        needed=["libc.so.6"],
        versions_defined=["LIBFOO_1.0"],
        versions_required={"libc.so.6": ["GLIBC_2.5"]},
        symbols=[_sym("foo", binding=SymbolBinding.GLOBAL, sym_type=SymbolType.FUNC, size=32)],
    )
    old = _snap(elf)
    new = _snap(elf)
    result = compare(old, new)
    elf_kinds = {c.kind for c in result.changes if "elf" not in c.kind.value
                 and c.kind.value in {k.value for k in [
                     ChangeKind.SONAME_CHANGED, ChangeKind.NEEDED_ADDED,
                     ChangeKind.NEEDED_REMOVED, ChangeKind.RPATH_CHANGED,
                     ChangeKind.RUNPATH_CHANGED, ChangeKind.SYMBOL_BINDING_CHANGED,
                     ChangeKind.SYMBOL_TYPE_CHANGED, ChangeKind.SYMBOL_SIZE_CHANGED,
                     ChangeKind.IFUNC_INTRODUCED, ChangeKind.IFUNC_REMOVED,
                     ChangeKind.COMMON_SYMBOL_RISK,
                     ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED,
                     ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED,
                 ]}}
    assert elf_kinds == set()


# ---------------------------------------------------------------------------
# Verdict mapping checks
# ---------------------------------------------------------------------------

def test_elf_breaking_kinds_verdict() -> None:
    """All BREAKING ELF kinds produce BREAKING verdict."""
    breaking_cases = [
        _snap(_elf(soname="libfoo.so.1")),     # SONAME_CHANGED
        _snap(_elf(needed=["libc.so.6"])),      # NEEDED_ADDED
        _snap(_elf(versions_defined=["V1"])),   # SYMBOL_VERSION_DEFINED_REMOVED
        _snap(_elf(versions_required={"libc.so.6": ["GLIBC_2.5"]})),  # VER_REQ_ADDED
        _snap(_elf(symbols=[_sym("f", binding=SymbolBinding.GLOBAL)])),  # BINDING_CHANGED
        _snap(_elf(symbols=[_sym("f", sym_type=SymbolType.FUNC)])),  # TYPE_CHANGED
        _snap(_elf(symbols=[_sym("f", sym_type=SymbolType.IFUNC)])),  # IFUNC_INTRODUCED
    ]
    new_cases = [
        _snap(_elf(soname="libfoo.so.2")),
        _snap(_elf(needed=["libc.so.6", "libssl.so.3"])),
        _snap(_elf(versions_defined=[])),
        _snap(_elf(versions_required={"libc.so.6": ["GLIBC_2.5", "GLIBC_2.34"]})),
        _snap(_elf(symbols=[_sym("f", binding=SymbolBinding.WEAK)])),
        _snap(_elf(symbols=[_sym("f", sym_type=SymbolType.OBJECT)])),
        _snap(_elf(symbols=[_sym("f", sym_type=SymbolType.FUNC)])),
    ]
    for old, new in zip(breaking_cases, new_cases):
        result = compare(old, new)
        assert result.verdict == Verdict.BREAKING, (
            f"Expected BREAKING, got {result.verdict}: {[c.kind for c in result.changes]}"
        )

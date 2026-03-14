"""Tests for symbol origin detection and SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED.

Covers:
- _guess_symbol_origin() heuristic for each symbol category
- ElfSymbol.origin_lib field population
- SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED in RISK_KINDS (not BREAKING)
- Integration: leaked-dependency symbols produce COMPATIBLE_WITH_RISK verdict
"""
from __future__ import annotations

import pytest

from abicheck.checker_policy import (
    BREAKING_KINDS,
    COMPATIBLE_KINDS,
    API_BREAK_KINDS,
    RISK_KINDS,
    ChangeKind,
    Verdict,
    compute_verdict,
)
from abicheck.elf_metadata import ElfSymbol, SymbolBinding, SymbolType, _guess_symbol_origin


# ---------------------------------------------------------------------------
# Tests for _guess_symbol_origin
# ---------------------------------------------------------------------------

class TestGuessSymbolOrigin:
    """Test heuristic origin detection for symbol names."""

    def test_cxx_stdlib_prefix_ZNSt_returns_libstdcxx(self):
        """_ZNSt... → libstdc++.so.6 (std:: member function)."""
        result = _guess_symbol_origin("_ZNSt6thread8_M_startEv", [])
        assert result == "libstdc++.so.6"

    def test_cxx_stdlib_prefix_ZNKSt_returns_libstdcxx(self):
        """_ZNKSt... → libstdc++ (std:: const member function)."""
        result = _guess_symbol_origin("_ZNKSt3mapIiSsE4findERKi", [])
        assert result == "libstdc++.so.6"

    def test_cxx_stdlib_prefix_ZSt_returns_libstdcxx(self):
        """_ZSt... → libstdc++ (std namespace free function)."""
        result = _guess_symbol_origin("_ZSt9terminatev", [])
        assert result == "libstdc++.so.6"

    def test_cxx_stdlib_prefix_ZTI_returns_libstdcxx(self):
        """_ZTI... → libstdc++ (typeinfo)."""
        result = _guess_symbol_origin("_ZTISt9exception", [])
        assert result == "libstdc++.so.6"

    def test_cxx_stdlib_prefix_ZTS_returns_libstdcxx(self):
        """_ZTS... → libstdc++ (typeinfo string)."""
        result = _guess_symbol_origin("_ZTSSt11logic_error", [])
        assert result == "libstdc++.so.6"

    def test_cxx_abi_vtable_returns_libstdcxx(self):
        """_ZTVN10__cxxabiv... → libstdc++ (C++ ABI vtable)."""
        result = _guess_symbol_origin("_ZTVN10__cxxabiv117__class_type_infoE", [])
        assert result == "libstdc++.so.6"

    def test_cxx_stdlib_prefers_needed_libstdcxx(self):
        """If libstdc++.so.6 appears in DT_NEEDED, return that exact name."""
        result = _guess_symbol_origin("_ZNSt3mapC1Ev", ["libm.so.6", "libstdc++.so.6"])
        assert result == "libstdc++.so.6"

    def test_cxx_stdlib_prefers_needed_libcxx(self):
        """If libc++.so.1 appears in DT_NEEDED, return that exact name."""
        result = _guess_symbol_origin("_ZNSt3vecC1Ev", ["libc++.so.1"])
        assert result == "libc++.so.1"

    def test_cxx_stdlib_fallback_when_not_in_needed(self):
        """Falls back to 'libstdc++.so.6' when no matching lib in DT_NEEDED."""
        result = _guess_symbol_origin("_ZSt9terminatev", ["libm.so.6"])
        assert result == "libstdc++.so.6"

    def test_gcc_runtime_ix86(self):
        """ix86_... → libgcc_s.so.1."""
        result = _guess_symbol_origin("ix86_math_helper", [])
        assert result == "libgcc_s.so.1"

    def test_gcc_runtime_ZGV(self):
        """_ZGV... → libgcc_s.so.1 (SIMD vector variant)."""
        result = _guess_symbol_origin("_ZGVnN4v_sin", [])
        assert result == "libgcc_s.so.1"

    def test_gcc_runtime_cpu_model(self):
        """__cpu_model → libgcc_s.so.1."""
        result = _guess_symbol_origin("__cpu_model", [])
        assert result == "libgcc_s.so.1"

    def test_gcc_runtime_cpu_features(self):
        """__cpu_features_init → libgcc_s.so.1."""
        result = _guess_symbol_origin("__cpu_features_init", [])
        assert result == "libgcc_s.so.1"

    def test_gcc_runtime_svml(self):
        """__svml_sin4 → libgcc_s.so.1."""
        result = _guess_symbol_origin("__svml_sin4", [])
        assert result == "libgcc_s.so.1"

    def test_libc_prefix_libc(self):
        """__libc_start_main → libc.so.6."""
        result = _guess_symbol_origin("__libc_start_main", [])
        assert result == "libc.so.6"

    def test_libc_prefix_glibc(self):
        """__glibc_safe_len → libc.so.6."""
        result = _guess_symbol_origin("__glibc_safe_len", [])
        assert result == "libc.so.6"

    def test_native_symbol_returns_none(self):
        """Regular C symbol (not matching any known prefix) → None."""
        result = _guess_symbol_origin("my_lib_function", [])
        assert result is None

    def test_native_mangled_symbol_returns_none(self):
        """Mangled non-stdlib C++ symbol → None (native to this lib)."""
        result = _guess_symbol_origin("_ZN3Foo3barEv", [])
        assert result is None

    def test_empty_name_returns_none(self):
        """Empty symbol name → None (no prefix match)."""
        result = _guess_symbol_origin("", [])
        assert result is None


# ---------------------------------------------------------------------------
# Tests for ElfSymbol.origin_lib field
# ---------------------------------------------------------------------------

class TestElfSymbolOriginLib:
    """Test that ElfSymbol.origin_lib is populated correctly."""

    def test_origin_lib_default_is_none(self):
        """ElfSymbol without origin_lib defaults to None."""
        sym = ElfSymbol(name="my_func")
        assert sym.origin_lib is None

    def test_origin_lib_can_be_set(self):
        """ElfSymbol.origin_lib can be set to a library name."""
        sym = ElfSymbol(name="_ZNSt6thread8_M_startEv", origin_lib="libstdc++.so.6")
        assert sym.origin_lib == "libstdc++.so.6"

    def test_origin_lib_none_for_native(self):
        """ElfSymbol.origin_lib is None for native symbols."""
        sym = ElfSymbol(name="native_func", origin_lib=None)
        assert sym.origin_lib is None

    def test_elf_symbol_dataclass_fields(self):
        """ElfSymbol dataclass has all expected fields including origin_lib."""
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(ElfSymbol)}
        assert "origin_lib" in field_names


# ---------------------------------------------------------------------------
# Tests for SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED in RISK_KINDS
# ---------------------------------------------------------------------------

class TestSymbolLeakedFromDependencyPolicy:
    """Test policy classification of SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED."""

    def test_in_risk_kinds(self):
        """SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED must be in RISK_KINDS."""
        assert ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED in RISK_KINDS

    def test_not_in_breaking_kinds(self):
        """Must not be in BREAKING_KINDS."""
        assert ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED not in BREAKING_KINDS

    def test_not_in_compatible_kinds(self):
        """Must not be in COMPATIBLE_KINDS."""
        assert ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED not in COMPATIBLE_KINDS

    def test_not_in_api_break_kinds(self):
        """Must not be in API_BREAK_KINDS."""
        assert ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED not in API_BREAK_KINDS

    def test_verdict_is_compatible_with_risk(self):
        """A change list with only SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED → COMPATIBLE_WITH_RISK."""
        from abicheck.checker import Change

        changes = [
            Change(
                kind=ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED,
                symbol="_ZNSt6thread8_M_startEv",
                description="test",
            )
        ]
        verdict = compute_verdict(changes, policy="strict_abi")
        assert verdict == Verdict.COMPATIBLE_WITH_RISK

    def test_verdict_not_breaking_alone(self):
        """Alone it does not produce BREAKING verdict."""
        from abicheck.checker import Change

        changes = [
            Change(
                kind=ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED,
                symbol="_ZNSt6thread8_M_startEv",
                description="test",
            )
        ]
        verdict = compute_verdict(changes)
        assert verdict != Verdict.BREAKING

    def test_mixed_breaking_overrides(self):
        """When combined with a BREAKING change, verdict is BREAKING."""
        from abicheck.checker import Change

        changes = [
            Change(
                kind=ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED,
                symbol="_ZNSt6thread8_M_startEv",
                description="leaked dependency",
            ),
            Change(
                kind=ChangeKind.FUNC_REMOVED,
                symbol="my_func",
                description="public function removed",
            ),
        ]
        verdict = compute_verdict(changes)
        assert verdict == Verdict.BREAKING


# ---------------------------------------------------------------------------
# Integration: _diff_leaked_dependency_symbols detector
# ---------------------------------------------------------------------------

class TestDiffLeakedDependencySymbols:
    """Test that the detector in checker.py emits the correct Changes."""

    def _make_elf_meta(self, symbols: list[ElfSymbol]) -> object:
        """Build a minimal ElfMetadata-like object with a symbol_map."""
        from abicheck.elf_metadata import ElfMetadata
        meta = ElfMetadata()
        meta.symbols = symbols
        return meta

    def test_removed_leaked_symbol_emits_change(self):
        """A symbol with origin_lib removed from new ELF → Change emitted."""
        from abicheck.checker import _diff_leaked_dependency_symbols

        old_elf = self._make_elf_meta([
            ElfSymbol(
                name="_ZNSt6thread8_M_startEv",
                origin_lib="libstdc++.so.6",
            )
        ])
        new_elf = self._make_elf_meta([])  # symbol removed

        changes = _diff_leaked_dependency_symbols(old_elf, new_elf)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED
        assert "_ZNSt6thread8_M_startEv" in changes[0].symbol
        assert "libstdc++.so.6" in changes[0].description

    def test_native_symbol_removed_no_change(self):
        """A removed symbol with origin_lib=None → no LEAKED change emitted."""
        from abicheck.checker import _diff_leaked_dependency_symbols

        old_elf = self._make_elf_meta([
            ElfSymbol(name="my_native_func", origin_lib=None)
        ])
        new_elf = self._make_elf_meta([])

        changes = _diff_leaked_dependency_symbols(old_elf, new_elf)
        assert changes == []

    def test_added_leaked_symbol_emits_change(self):
        """A newly added symbol with origin_lib → Change emitted."""
        from abicheck.checker import _diff_leaked_dependency_symbols

        old_elf = self._make_elf_meta([])
        new_elf = self._make_elf_meta([
            ElfSymbol(
                name="_ZGVnN4v_sin",
                origin_lib="libgcc_s.so.1",
            )
        ])

        changes = _diff_leaked_dependency_symbols(old_elf, new_elf)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED
        assert "libgcc_s.so.1" in changes[0].description

    def test_changed_leaked_symbol_type_emits_change(self):
        """A leaked symbol that changed type → Change emitted."""
        from abicheck.checker import _diff_leaked_dependency_symbols

        old_elf = self._make_elf_meta([
            ElfSymbol(
                name="_ZNSt6locale5_Impl16_M_check_same_nameEPKc",
                sym_type=SymbolType.FUNC,
                origin_lib="libstdc++.so.6",
            )
        ])
        new_elf = self._make_elf_meta([
            ElfSymbol(
                name="_ZNSt6locale5_Impl16_M_check_same_nameEPKc",
                sym_type=SymbolType.OBJECT,  # type changed
                origin_lib="libstdc++.so.6",
            )
        ])

        changes = _diff_leaked_dependency_symbols(old_elf, new_elf)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED

    def test_unchanged_leaked_symbol_no_change(self):
        """A leaked symbol that did NOT change → no LEAKED change emitted."""
        from abicheck.checker import _diff_leaked_dependency_symbols

        sym = ElfSymbol(
            name="_ZNSt6thread8_M_startEv",
            sym_type=SymbolType.FUNC,
            binding=SymbolBinding.GLOBAL,
            size=0,
            origin_lib="libstdc++.so.6",
        )
        old_elf = self._make_elf_meta([sym])
        new_elf = self._make_elf_meta([sym])

        changes = _diff_leaked_dependency_symbols(old_elf, new_elf)
        assert changes == []

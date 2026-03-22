"""Tests for the 9 new ABI change detectors added in the gap analysis.

Covers:
- tls_checks (TLS_VAR_SIZE_CHANGED)
- protected_visibility (PROTECTED_VISIBILITY_CHANGED)
- symbol_version_alias (SYMBOL_VERSION_ALIAS_CHANGED)
- glibcxx_dual_abi (GLIBCXX_DUAL_ABI_FLIP_DETECTED)
- inline_namespace (INLINE_NAMESPACE_MOVED)
- vtable_identity (VTABLE_SYMBOL_IDENTITY_CHANGED)
- abi_surface (ABI_SURFACE_EXPLOSION)
- func_ref_qual_changed (inline in _check_function_signature)
- func_language_linkage_changed (inline in _check_function_signature)
"""
from __future__ import annotations

from abicheck.checker import ChangeKind, compare
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType
from abicheck.model import (
    AbiSnapshot,
    Function,
    Visibility,
)


def _snap(version="1.0", functions=None, variables=None, types=None,
          enums=None, typedefs=None, elf=None):
    return AbiSnapshot(
        library="libtest.so.1", version=version,
        functions=functions or [], variables=variables or [],
        types=types or [], enums=enums or [],
        typedefs=typedefs or {}, elf=elf,
    )


def _pub_func(name, mangled, ret="void", params=None, **kwargs):
    return Function(name=name, mangled=mangled, return_type=ret,
                    params=params or [], visibility=Visibility.PUBLIC, **kwargs)


def _elf_sym(name, sym_type=SymbolType.FUNC, size=0, visibility="default",
             binding=SymbolBinding.GLOBAL, version="", is_default=True):
    return ElfSymbol(name=name, sym_type=sym_type, size=size,
                     visibility=visibility, binding=binding,
                     version=version, is_default=is_default)


def _has_kind(result, kind):
    return any(c.kind == kind for c in result.changes)


def _changes_of_kind(result, kind):
    return [c for c in result.changes if c.kind == kind]


# ── TLS_VAR_SIZE_CHANGED ─────────────────────────────────────────────────────

class TestTlsChecks:
    def test_tls_size_change_detected(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("tls_var", sym_type=SymbolType.TLS, size=4),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("tls_var", sym_type=SymbolType.TLS, size=8),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.TLS_VAR_SIZE_CHANGED)

    def test_tls_same_size_no_change(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("tls_var", sym_type=SymbolType.TLS, size=4),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("tls_var", sym_type=SymbolType.TLS, size=4),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.TLS_VAR_SIZE_CHANGED)

    def test_tls_zero_size_ignored(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("tls_var", sym_type=SymbolType.TLS, size=0),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("tls_var", sym_type=SymbolType.TLS, size=8),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.TLS_VAR_SIZE_CHANGED)

    def test_non_tls_not_reported(self):
        """Non-TLS symbols should not trigger TLS_VAR_SIZE_CHANGED."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("data_var", sym_type=SymbolType.OBJECT, size=4),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("data_var", sym_type=SymbolType.OBJECT, size=8),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.TLS_VAR_SIZE_CHANGED)


# ── PROTECTED_VISIBILITY_CHANGED ──────────────────────────────────────────────

class TestProtectedVisibility:
    def test_data_default_to_protected(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("global_data", sym_type=SymbolType.OBJECT, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("global_data", sym_type=SymbolType.OBJECT, visibility="protected"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

    def test_data_protected_to_default(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("global_data", sym_type=SymbolType.OBJECT, visibility="protected"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("global_data", sym_type=SymbolType.OBJECT, visibility="default"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

    def test_func_not_reported(self):
        """Function DEFAULT↔PROTECTED is handled by FUNC_VISIBILITY_PROTECTED_CHANGED."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("func_sym", sym_type=SymbolType.FUNC, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("func_sym", sym_type=SymbolType.FUNC, visibility="protected"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

    def test_same_visibility_no_change(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("global_data", sym_type=SymbolType.OBJECT, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("global_data", sym_type=SymbolType.OBJECT, visibility="default"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)


# ── SYMBOL_VERSION_ALIAS_CHANGED ──────────────────────────────────────────────

class TestSymbolVersionAlias:
    def test_default_version_changed(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="VER_1.0", is_default=True),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="VER_2.0", is_default=True),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.SYMBOL_VERSION_ALIAS_CHANGED)

    def test_same_version_no_change(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="VER_1.0", is_default=True),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="VER_1.0", is_default=True),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.SYMBOL_VERSION_ALIAS_CHANGED)

    def test_no_versioned_symbols_no_change(self):
        old_elf = ElfMetadata(symbols=[_elf_sym("foo")])
        new_elf = ElfMetadata(symbols=[_elf_sym("foo")])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.SYMBOL_VERSION_ALIAS_CHANGED)


# ── GLIBCXX_DUAL_ABI_FLIP_DETECTED ───────────────────────────────────────────

class TestGlibcxxDualAbi:
    def _make_cxx11_funcs(self, prefix, count, vis=Visibility.PUBLIC):
        """Generate functions with __cxx11 in mangled name."""
        funcs = []
        for i in range(count):
            funcs.append(Function(
                name=f"{prefix}::std::__cxx11::basic_string::func{i}",
                mangled=f"_ZN{prefix}std__cxx11_func{i}Ev",
                return_type="void",
                visibility=vis,
            ))
        return funcs

    def _make_legacy_funcs(self, prefix, count, vis=Visibility.PUBLIC):
        """Generate functions without __cxx11 marker (legacy ABI)."""
        funcs = []
        for i in range(count):
            funcs.append(Function(
                name=f"{prefix}::std::basic_string::func{i}",
                mangled=f"_ZN{prefix}std_func{i}Ev",
                return_type="void",
                visibility=vis,
            ))
        return funcs

    def test_cxx11_to_legacy_detected(self):
        old_funcs = self._make_cxx11_funcs("lib", 10)
        new_funcs = self._make_legacy_funcs("lib", 10)
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.GLIBCXX_DUAL_ABI_FLIP_DETECTED)

    def test_legacy_to_cxx11_detected(self):
        old_funcs = self._make_legacy_funcs("lib", 10)
        new_funcs = self._make_cxx11_funcs("lib", 10)
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.GLIBCXX_DUAL_ABI_FLIP_DETECTED)

    def test_small_churn_not_detected(self):
        """Below threshold (< 5 removed + < 5 added) → no detection."""
        old_funcs = self._make_cxx11_funcs("lib", 3)
        new_funcs = self._make_legacy_funcs("lib", 3)
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert not _has_kind(r, ChangeKind.GLIBCXX_DUAL_ABI_FLIP_DETECTED)

    def test_no_markers_not_detected(self):
        """Churn without CXX11 markers → no detection."""
        old_funcs = [_pub_func(f"func{i}", f"_Zfunc{i}v") for i in range(10)]
        new_funcs = [_pub_func(f"other{i}", f"_Zother{i}v") for i in range(10)]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert not _has_kind(r, ChangeKind.GLIBCXX_DUAL_ABI_FLIP_DETECTED)


# ── INLINE_NAMESPACE_MOVED ────────────────────────────────────────────────────

class TestInlineNamespace:
    def test_v1_to_v2_move_detected(self):
        old_funcs = [
            _pub_func(f"ns::v1::func{i}", f"_ZN2ns2v1func{i}Ev")
            for i in range(5)
        ]
        new_funcs = [
            _pub_func(f"ns::v2::func{i}", f"_ZN2ns2v2func{i}Ev")
            for i in range(5)
        ]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.INLINE_NAMESPACE_MOVED)

    def test_single_symbol_not_detected(self):
        """Need >= 2 matched symbols for detection."""
        old_funcs = [_pub_func("ns::v1::func0", "_ZN2ns2v1func0Ev")]
        new_funcs = [_pub_func("ns::v2::func0", "_ZN2ns2v2func0Ev")]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert not _has_kind(r, ChangeKind.INLINE_NAMESPACE_MOVED)

    def test_no_namespace_version_no_detection(self):
        """Functions without versioned namespaces should not trigger."""
        old_funcs = [_pub_func(f"ns::func{i}", f"_ZN2nsfunc{i}Ev") for i in range(5)]
        new_funcs = [_pub_func(f"other::func{i}", f"_ZN5otherfunc{i}Ev") for i in range(5)]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert not _has_kind(r, ChangeKind.INLINE_NAMESPACE_MOVED)

    def test_regex_does_not_match_v_in_identifier(self):
        """v1 inside an identifier (not a namespace) should NOT match."""
        old_funcs = [
            _pub_func(f"convert_v1_data{i}", f"_Zconvert_v1_data{i}v")
            for i in range(5)
        ]
        new_funcs = [
            _pub_func(f"convert_v2_data{i}", f"_Zconvert_v2_data{i}v")
            for i in range(5)
        ]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert not _has_kind(r, ChangeKind.INLINE_NAMESPACE_MOVED)


# ── VTABLE_SYMBOL_IDENTITY_CHANGED ────────────────────────────────────────────

class TestVtableIdentity:
    def test_rtti_identity_change_same_type_key(self):
        """RTTI symbols removed and re-added with same type key but different prefix.

        E.g. old has _ZTV5MyObj (vtable), new has _ZTS5MyObj (typeinfo name) —
        both have type key '5MyObj', indicating RTTI identity changed.
        """
        old_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, size=24),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTS5MyObj", sym_type=SymbolType.OBJECT, size=16),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.VTABLE_SYMBOL_IDENTITY_CHANGED)

    def test_rtti_visibility_change(self):
        """RTTI symbol visibility change for existing symbols."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, visibility="default"),
            _elf_sym("_ZTI5MyObj", sym_type=SymbolType.OBJECT, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, visibility="protected"),
            _elf_sym("_ZTI5MyObj", sym_type=SymbolType.OBJECT, visibility="protected"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.VTABLE_SYMBOL_IDENTITY_CHANGED)

    def test_no_rtti_no_change(self):
        old_elf = ElfMetadata(symbols=[
            _elf_sym("regular_func", sym_type=SymbolType.FUNC),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("regular_func", sym_type=SymbolType.FUNC),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.VTABLE_SYMBOL_IDENTITY_CHANGED)


# ── ABI_SURFACE_EXPLOSION ────────────────────────────────────────────────────

class TestAbiSurface:
    def _make_elf(self, count):
        return ElfMetadata(symbols=[
            _elf_sym(f"sym_{i}", sym_type=SymbolType.FUNC) for i in range(count)
        ])

    def test_surface_doubled(self):
        """2x+ growth with 50+ delta → detected."""
        r = compare(_snap(elf=self._make_elf(100)), _snap(elf=self._make_elf(250)))
        assert _has_kind(r, ChangeKind.ABI_SURFACE_EXPLOSION)

    def test_surface_halved(self):
        """<0.5x shrinkage with 50+ delta → detected."""
        r = compare(_snap(elf=self._make_elf(200)), _snap(elf=self._make_elf(50)))
        assert _has_kind(r, ChangeKind.ABI_SURFACE_EXPLOSION)

    def test_small_growth_not_detected(self):
        """Growth below 2x → not detected."""
        r = compare(_snap(elf=self._make_elf(100)), _snap(elf=self._make_elf(180)))
        assert not _has_kind(r, ChangeKind.ABI_SURFACE_EXPLOSION)

    def test_small_base_not_detected(self):
        """Base < 10 symbols → not detected."""
        r = compare(_snap(elf=self._make_elf(5)), _snap(elf=self._make_elf(100)))
        assert not _has_kind(r, ChangeKind.ABI_SURFACE_EXPLOSION)

    def test_boundary_delta_below_50(self):
        """Even with >2x ratio, delta < 50 → not detected."""
        r = compare(_snap(elf=self._make_elf(20)), _snap(elf=self._make_elf(60)))
        assert not _has_kind(r, ChangeKind.ABI_SURFACE_EXPLOSION)


# ── FUNC_REF_QUAL_CHANGED ────────────────────────────────────────────────────

class TestFuncRefQualChanged:
    def test_ref_qualifier_added(self):
        f_old = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="")
        f_new = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="&")
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_REF_QUAL_CHANGED)

    def test_ref_qualifier_changed(self):
        f_old = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="&")
        f_new = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="&&")
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_REF_QUAL_CHANGED)

    def test_ref_qualifier_removed(self):
        f_old = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="&&")
        f_new = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="")
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_REF_QUAL_CHANGED)

    def test_same_ref_qualifier_no_change(self):
        f_old = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="&")
        f_new = _pub_func("Foo::bar", "_ZN3Foo3barEv", ref_qualifier="&")
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert not _has_kind(r, ChangeKind.FUNC_REF_QUAL_CHANGED)


# ── FUNC_LANGUAGE_LINKAGE_CHANGED ─────────────────────────────────────────────

class TestFuncLanguageLinkageChanged:
    def test_linkage_changed(self):
        f_old = _pub_func("c_func", "c_func", is_extern_c=True)
        f_new = _pub_func("c_func", "c_func", is_extern_c=False)
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_LANGUAGE_LINKAGE_CHANGED)

    def test_same_linkage_no_change(self):
        f_old = _pub_func("c_func", "c_func", is_extern_c=True)
        f_new = _pub_func("c_func", "c_func", is_extern_c=True)
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert not _has_kind(r, ChangeKind.FUNC_LANGUAGE_LINKAGE_CHANGED)

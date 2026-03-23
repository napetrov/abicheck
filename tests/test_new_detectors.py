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

    def test_tls_not_reported(self):
        """TLS symbols don't use copy relocations — DEFAULT↔PROTECTED is benign."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("tls_sym", sym_type=SymbolType.TLS, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("tls_sym", sym_type=SymbolType.TLS, visibility="protected"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

    def test_ifunc_not_reported(self):
        """IFUNC symbols should not trigger PROTECTED_VISIBILITY_CHANGED."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("ifunc_sym", sym_type=SymbolType.IFUNC, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("ifunc_sym", sym_type=SymbolType.IFUNC, visibility="protected"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

    def test_common_default_to_protected(self):
        """COMMON data symbols should also trigger PROTECTED_VISIBILITY_CHANGED."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("common_sym", sym_type=SymbolType.COMMON, visibility="default"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("common_sym", sym_type=SymbolType.COMMON, visibility="protected"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

    def test_common_protected_to_default(self):
        """COMMON data symbols: protected→default should also trigger."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("common_sym", sym_type=SymbolType.COMMON, visibility="protected"),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("common_sym", sym_type=SymbolType.COMMON, visibility="default"),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert _has_kind(r, ChangeKind.PROTECTED_VISIBILITY_CHANGED)

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

    def test_is_default_flip_same_version_no_change(self):
        """Same version string but is_default flips → not a version alias change.

        The detector tracks default *version string* changes, not default flag flips.
        When is_default goes True→False the symbol loses its default designation
        but the version string hasn't changed to a different value.
        """
        old_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="VER_1.0", is_default=True),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="VER_1.0", is_default=False),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        assert not _has_kind(r, ChangeKind.SYMBOL_VERSION_ALIAS_CHANGED)

    def test_unversioned_is_default_flip_no_change(self):
        """Non-versioned symbols flipping is_default → no change."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="", is_default=False),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("foo", version="", is_default=True),
        ])
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

    def test_exact_threshold_cxx11_to_legacy(self):
        """Exactly 5 removed + 5 added (threshold boundary) → detected."""
        old_funcs = self._make_cxx11_funcs("lib", 5)
        new_funcs = self._make_legacy_funcs("lib", 5)
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.GLIBCXX_DUAL_ABI_FLIP_DETECTED)

    def test_exact_threshold_legacy_to_cxx11(self):
        """Exactly 5 removed + 5 added (threshold boundary), reverse direction."""
        old_funcs = self._make_legacy_funcs("lib", 5)
        new_funcs = self._make_cxx11_funcs("lib", 5)
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.GLIBCXX_DUAL_ABI_FLIP_DETECTED)


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

    def test_libcxx_1_to_2_move_detected(self):
        """libc++ inline namespace ::__1:: → ::__2:: should be detected."""
        old_funcs = [
            _pub_func(f"std::__1::func{i}", f"_ZNSt3__1func{i}Ev")
            for i in range(5)
        ]
        new_funcs = [
            _pub_func(f"std::__2::func{i}", f"_ZNSt3__2func{i}Ev")
            for i in range(5)
        ]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.INLINE_NAMESPACE_MOVED)

    def test_unversioned_to_versioned_move_detected(self):
        """Unversioned → versioned namespace move should be detected."""
        old_funcs = [
            _pub_func(f"ns::func{i}", f"_ZN2nsfunc{i}Ev_old")
            for i in range(5)
        ]
        new_funcs = [
            _pub_func(f"ns::v2::func{i}", f"_ZN2ns2v2func{i}Ev_new")
            for i in range(5)
        ]
        r = compare(_snap(functions=old_funcs), _snap(functions=new_funcs))
        assert _has_kind(r, ChangeKind.INLINE_NAMESPACE_MOVED)


# ── VTABLE_SYMBOL_IDENTITY_CHANGED ────────────────────────────────────────────

class TestVtableIdentity:
    def test_cross_prefix_not_identity_change(self):
        """_ZTV→_ZTS for same type is NOT an identity change (different RTTI artefacts)."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, size=24),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTS5MyObj", sym_type=SymbolType.OBJECT, size=16),
        ])
        r = compare(_snap(elf=old_elf), _snap(elf=new_elf))
        # Different prefixes → not same RTTI artefact
        assert not _has_kind(r, ChangeKind.VTABLE_SYMBOL_IDENTITY_CHANGED)

    def test_same_prefix_identity_change(self):
        """Same RTTI prefix removed and re-added with different properties → identity change.

        Simulates version-script change: _ZTV5MyObj present in both old and new
        but with different versions (handled via common_rtti path).
        """
        old_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, version="VER_1", is_default=True),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, version="VER_2", is_default=True),
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

    def test_same_rtti_no_change(self):
        """Identical RTTI symbols should not trigger."""
        old_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, visibility="default",
                     version="VER_1", is_default=True),
        ])
        new_elf = ElfMetadata(symbols=[
            _elf_sym("_ZTV5MyObj", sym_type=SymbolType.OBJECT, visibility="default",
                     version="VER_1", is_default=True),
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

    def test_ref_qualifier_different_mangled(self):
        """Ref-qualifier change with different mangled names (real-world case).

        In Itanium ABI, &/&& ref-qualifiers change the mangled name, so the
        functions won't match by mangled name.  The method_qualifiers detector
        should still pair them by (name, params) and report the change.
        """
        f_old = _pub_func("Foo::bar", "_ZNR3Foo3barEv", ref_qualifier="&")
        f_new = _pub_func("Foo::bar", "_ZNO3Foo3barEv", ref_qualifier="&&")
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_REF_QUAL_CHANGED)


# ── FUNC_LANGUAGE_LINKAGE_CHANGED ─────────────────────────────────────────────

class TestFuncLanguageLinkageChanged:
    def test_linkage_changed_same_mangled(self):
        """Same mangled name, extern C flag flipped."""
        f_old = _pub_func("c_func", "c_func", is_extern_c=True)
        f_new = _pub_func("c_func", "c_func", is_extern_c=False)
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_LANGUAGE_LINKAGE_CHANGED)

    def test_extern_c_to_cpp_different_mangled(self):
        """extern "C" → C++ flip: mangled name changes (c_func → _Z6c_funcv).

        The fallback matcher should still pair them by plain name.
        """
        f_old = _pub_func("c_func", "c_func", is_extern_c=True)
        f_new = _pub_func("c_func", "_Z6c_funcv", is_extern_c=False)
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_LANGUAGE_LINKAGE_CHANGED)

    def test_cpp_to_extern_c_different_mangled(self):
        """C++ → extern "C" flip: mangled name changes (_Z6c_funcv → c_func).

        The reverse direction should also be detected.
        """
        f_old = _pub_func("c_func", "_Z6c_funcv", is_extern_c=False)
        f_new = _pub_func("c_func", "c_func", is_extern_c=True)
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert _has_kind(r, ChangeKind.FUNC_LANGUAGE_LINKAGE_CHANGED)

    def test_same_linkage_no_change(self):
        f_old = _pub_func("c_func", "c_func", is_extern_c=True)
        f_new = _pub_func("c_func", "c_func", is_extern_c=True)
        r = compare(_snap(functions=[f_old]), _snap(functions=[f_new]))
        assert not _has_kind(r, ChangeKind.FUNC_LANGUAGE_LINKAGE_CHANGED)

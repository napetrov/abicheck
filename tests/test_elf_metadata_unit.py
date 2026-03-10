"""Unit tests for elf_metadata — mock pyelftools to cover internal parsing.

These tests exercise _parse, _parse_dynamic, _parse_version_def,
_parse_version_need, _parse_dynsym, and parse_elf_metadata edge cases
without needing a real ELF binary or gcc.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from abicheck.elf_metadata import (
    _BINDING_MAP,
    _HIDDEN_VISIBILITIES,
    _TYPE_MAP,
    ElfMetadata,
    ElfSymbol,
    SymbolBinding,
    SymbolType,
    _parse,
    _parse_dynamic,
    _parse_dynsym,
    _parse_version_def,
    _parse_version_need,
    parse_elf_metadata,
)

# ── ElfMetadata.symbol_map ───────────────────────────────────────────────

class TestElfMetadataSymbolMap:
    def test_symbol_map_returns_name_to_symbol(self):
        s1 = ElfSymbol(name="foo")
        s2 = ElfSymbol(name="bar")
        meta = ElfMetadata(symbols=[s1, s2])
        assert meta.symbol_map == {"foo": s1, "bar": s2}

    def test_symbol_map_cached(self):
        meta = ElfMetadata(symbols=[ElfSymbol(name="x")])
        m1 = meta.symbol_map
        m2 = meta.symbol_map
        assert m1 is m2


# ── parse_elf_metadata error paths ──────────────────────────────────────

class TestParseElfMetadataEdgeCases:
    def test_nonexistent_file_returns_empty(self):
        meta = parse_elf_metadata(Path("/nonexistent/libfake.so"))
        assert isinstance(meta, ElfMetadata)
        assert meta.symbols == []

    def test_non_regular_file_returns_empty(self, tmp_path):
        """Directory (not a regular file) → empty metadata."""
        meta = parse_elf_metadata(tmp_path)
        assert isinstance(meta, ElfMetadata)
        assert meta.symbols == []

    def test_non_elf_file_returns_empty(self, tmp_path):
        """Text file → ELFError → empty metadata."""
        f = tmp_path / "bad.so"
        f.write_text("not an elf", encoding="utf-8")
        meta = parse_elf_metadata(f)
        assert isinstance(meta, ElfMetadata)
        assert meta.symbols == []


# ── _parse_dynamic ──────────────────────────────────────────────────────

class TestParseDynamic:
    def _make_tag(self, d_tag: str, **kwargs):
        tag = MagicMock()
        tag.entry = MagicMock()
        tag.entry.d_tag = d_tag
        for k, v in kwargs.items():
            setattr(tag, k, v)
        return tag

    def test_soname(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.iter_tags.return_value = [self._make_tag("DT_SONAME", soname="libfoo.so.1")]
        _parse_dynamic(section, meta)
        assert meta.soname == "libfoo.so.1"

    def test_needed(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.iter_tags.return_value = [
            self._make_tag("DT_NEEDED", needed="libc.so.6"),
            self._make_tag("DT_NEEDED", needed="libm.so.6"),
        ]
        _parse_dynamic(section, meta)
        assert meta.needed == ["libc.so.6", "libm.so.6"]

    def test_rpath(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.iter_tags.return_value = [self._make_tag("DT_RPATH", rpath="/usr/lib")]
        _parse_dynamic(section, meta)
        assert meta.rpath == "/usr/lib"

    def test_runpath(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.iter_tags.return_value = [self._make_tag("DT_RUNPATH", runpath="$ORIGIN")]
        _parse_dynamic(section, meta)
        assert meta.runpath == "$ORIGIN"


# ── _parse_version_def ──────────────────────────────────────────────────

class TestParseVersionDef:
    def _verdef(self, flags: int = 0):
        """Return a verdef mock (flags=0 = real version node, flags=1 = base)."""
        vd = MagicMock()
        vd.entry.vd_flags = flags
        return vd

    def test_version_defs_collected(self):
        meta = ElfMetadata()
        aux1 = MagicMock()
        aux1.name = "LIBFOO_1.0"
        aux2 = MagicMock()
        aux2.name = "LIBFOO_2.0"
        section = MagicMock()
        section.iter_versions.return_value = [
            (self._verdef(0), [aux1]),
            (self._verdef(0), [aux2]),
        ]
        _parse_version_def(section, meta)
        assert meta.versions_defined == ["LIBFOO_1.0", "LIBFOO_2.0"]

    def test_base_entry_skipped(self):
        """VER_FLG_BASE (flags=1) entries are the SONAME marker — skip them."""
        meta = ElfMetadata()
        aux = MagicMock()
        aux.name = "libfoo.so.1"
        section = MagicMock()
        section.iter_versions.return_value = [(self._verdef(flags=1), [aux])]
        _parse_version_def(section, meta)
        assert meta.versions_defined == []

    def test_duplicates_not_added(self):
        meta = ElfMetadata()
        aux = MagicMock()
        aux.name = "VER_1"
        section = MagicMock()
        section.iter_versions.return_value = [
            (self._verdef(0), [aux]),
            (self._verdef(0), [aux]),
        ]
        _parse_version_def(section, meta)
        assert meta.versions_defined == ["VER_1"]

    def test_empty_name_skipped(self):
        meta = ElfMetadata()
        aux = MagicMock()
        aux.name = ""
        section = MagicMock()
        section.iter_versions.return_value = [(self._verdef(0), [aux])]
        _parse_version_def(section, meta)
        assert meta.versions_defined == []


# ── _parse_version_need ─────────────────────────────────────────────────

class TestParseVersionNeed:
    def test_version_needs_collected(self):
        meta = ElfMetadata()
        verneed = MagicMock()
        verneed.name = "libc.so.6"
        vernaux = MagicMock()
        vernaux.name = "GLIBC_2.17"
        section = MagicMock()
        section.iter_versions.return_value = [(verneed, [vernaux])]
        _parse_version_need(section, meta)
        assert meta.versions_required == {"libc.so.6": ["GLIBC_2.17"]}

    def test_multiple_versions_same_lib(self):
        meta = ElfMetadata()
        verneed = MagicMock()
        verneed.name = "libc.so.6"
        v1 = MagicMock()
        v1.name = "GLIBC_2.17"
        v2 = MagicMock()
        v2.name = "GLIBC_2.34"
        section = MagicMock()
        section.iter_versions.return_value = [(verneed, [v1, v2])]
        _parse_version_need(section, meta)
        assert meta.versions_required["libc.so.6"] == ["GLIBC_2.17", "GLIBC_2.34"]

    def test_duplicate_version_not_added(self):
        meta = ElfMetadata()
        verneed = MagicMock()
        verneed.name = "libc.so.6"
        v1 = MagicMock()
        v1.name = "GLIBC_2.17"
        section = MagicMock()
        section.iter_versions.return_value = [
            (verneed, [v1]),
            (verneed, [v1]),
        ]
        _parse_version_need(section, meta)
        assert meta.versions_required["libc.so.6"] == ["GLIBC_2.17"]

    def test_empty_name_skipped(self):
        meta = ElfMetadata()
        verneed = MagicMock()
        verneed.name = "libc.so.6"
        v = MagicMock()
        v.name = ""
        section = MagicMock()
        section.iter_versions.return_value = [(verneed, [v])]
        _parse_version_need(section, meta)
        assert meta.versions_required == {"libc.so.6": []}


# ── _parse_dynsym ──────────────────────────────────────────────────────

class TestParseDynsym:
    def _make_sym(self, name: str, shndx="SHN_ABS",
                  bind="STB_GLOBAL", typ="STT_FUNC",
                  vis="STV_DEFAULT", size=16):
        sym = MagicMock()
        sym.name = name
        sym.entry.st_shndx = shndx
        sym.entry.st_info.bind = bind
        sym.entry.st_info.type = typ
        sym.entry.st_other.visibility = vis
        sym.entry.st_size = size
        return sym

    def test_exported_func(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("foo")]
        _parse_dynsym(section, meta)
        assert len(meta.symbols) == 1
        assert meta.symbols[0].name == "foo"
        assert meta.symbols[0].binding == SymbolBinding.GLOBAL
        assert meta.symbols[0].sym_type == SymbolType.FUNC
        assert meta.symbols[0].size == 16
        assert meta.symbols[0].visibility == "default"

    def test_undefined_sym_skipped(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("undef", shndx="SHN_UNDEF")]
        _parse_dynsym(section, meta)
        assert meta.symbols == []

    def test_local_sym_skipped(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("local_fn", bind="STB_LOCAL")]
        _parse_dynsym(section, meta)
        assert meta.symbols == []

    def test_hidden_sym_skipped(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("hidden_fn", vis="STV_HIDDEN")]
        _parse_dynsym(section, meta)
        assert meta.symbols == []

    def test_internal_sym_skipped(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("internal_fn", vis="STV_INTERNAL")]
        _parse_dynsym(section, meta)
        assert meta.symbols == []

    def test_weak_binding(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("weak_fn", bind="STB_WEAK")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].binding == SymbolBinding.WEAK

    def test_object_type(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("global_var", typ="STT_OBJECT")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].sym_type == SymbolType.OBJECT

    def test_tls_type(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("tls_var", typ="STT_TLS")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].sym_type == SymbolType.TLS

    def test_ifunc_type(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("ifunc_fn", typ="STT_GNU_IFUNC")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].sym_type == SymbolType.IFUNC

    def test_common_type(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("common_sym", typ="STT_COMMON")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].sym_type == SymbolType.COMMON

    def test_notype(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("notype_sym", typ="STT_NOTYPE")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].sym_type == SymbolType.NOTYPE

    def test_unknown_bind_maps_to_other(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("exotic", bind="STB_GNU_UNIQUE")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].binding == SymbolBinding.OTHER

    def test_unknown_type_maps_to_other(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("exotic", typ="STT_UNKNOWN")]
        _parse_dynsym(section, meta)
        assert meta.symbols[0].sym_type == SymbolType.OTHER

    def test_protected_visibility_included(self):
        meta = ElfMetadata()
        section = MagicMock()
        section.name = ".dynsym"
        section.iter_symbols.return_value = [self._make_sym("prot_fn", vis="STV_PROTECTED")]
        _parse_dynsym(section, meta)
        assert len(meta.symbols) == 1
        assert meta.symbols[0].visibility == "protected"


# ── _parse (full section dispatch) ──────────────────────────────────────

class TestParseFull:
    def test_dispatches_to_all_section_types(self):
        """Mock ELFFile with all four section types → all parse methods called."""
        from elftools.elf.dynamic import DynamicSection
        from elftools.elf.gnuversions import GNUVerDefSection, GNUVerNeedSection
        from elftools.elf.sections import SymbolTableSection

        dyn = MagicMock(spec=DynamicSection)
        dyn.iter_tags.return_value = [MagicMock(entry=MagicMock(d_tag="DT_SONAME"), soname="lib.so")]

        verdef_aux = MagicMock()
        verdef_aux.name = "VER_DEF_1"
        verdef = MagicMock(spec=GNUVerDefSection)
        verdef_vd = MagicMock(); verdef_vd.entry.vd_flags = 0; verdef.iter_versions.return_value = [(verdef_vd, [verdef_aux])]

        verneed_entry = MagicMock()
        verneed_entry.name = "libc.so.6"
        vernaux = MagicMock()
        vernaux.name = "GLIBC_2.17"
        verneed = MagicMock(spec=GNUVerNeedSection)
        verneed.iter_versions.return_value = [(verneed_entry, [vernaux])]

        sym = MagicMock()
        sym.name = "my_func"
        sym.entry.st_shndx = "SHN_ABS"
        sym.entry.st_info.bind = "STB_GLOBAL"
        sym.entry.st_info.type = "STT_FUNC"
        sym.entry.st_other.visibility = "STV_DEFAULT"
        sym.entry.st_size = 42
        dynsym = MagicMock(spec=SymbolTableSection)
        dynsym.name = ".dynsym"
        dynsym.iter_symbols.return_value = [sym]

        elf = MagicMock()
        elf.iter_sections.return_value = [dyn, verdef, verneed, dynsym]

        f = MagicMock()
        with patch("abicheck.elf_metadata.ELFFile", return_value=elf):
            meta = _parse(f, Path("test.so"))

        assert meta.soname == "lib.so"
        assert meta.versions_defined == ["VER_DEF_1"]
        assert meta.versions_required == {"libc.so.6": ["GLIBC_2.17"]}
        assert len(meta.symbols) == 1
        assert meta.symbols[0].name == "my_func"

    def test_malformed_section_logged_and_skipped(self):
        """If a section raises, other sections still parse."""
        from elftools.elf.dynamic import DynamicSection
        from elftools.elf.sections import SymbolTableSection

        bad_section = MagicMock(spec=DynamicSection)
        bad_section.name = ".dynamic"
        bad_section.iter_tags.side_effect = RuntimeError("corrupt section")

        good_sym = MagicMock(spec=SymbolTableSection)
        good_sym.name = ".dynsym"
        sym = MagicMock()
        sym.name = "good_fn"
        sym.entry.st_shndx = "SHN_ABS"
        sym.entry.st_info.bind = "STB_GLOBAL"
        sym.entry.st_info.type = "STT_FUNC"
        sym.entry.st_other.visibility = "STV_DEFAULT"
        sym.entry.st_size = 8
        good_sym.iter_symbols.return_value = [sym]

        elf = MagicMock()
        elf.iter_sections.return_value = [bad_section, good_sym]

        f = MagicMock()
        with patch("abicheck.elf_metadata.ELFFile", return_value=elf):
            meta = _parse(f, Path("test.so"))

        assert len(meta.symbols) == 1
        assert meta.symbols[0].name == "good_fn"

    def test_symtab_section_not_dynsym_ignored(self):
        """SymbolTableSection with name != '.dynsym' is not parsed."""
        from elftools.elf.sections import SymbolTableSection

        symtab = MagicMock(spec=SymbolTableSection)
        symtab.name = ".symtab"
        symtab.iter_symbols.return_value = []

        elf = MagicMock()
        elf.iter_sections.return_value = [symtab]

        f = MagicMock()
        with patch("abicheck.elf_metadata.ELFFile", return_value=elf):
            meta = _parse(f, Path("test.so"))

        symtab.iter_symbols.assert_not_called()
        assert meta.symbols == []


# ── Constant correctness ────────────────────────────────────────────────

class TestConstants:
    def test_binding_map_completeness(self):
        assert "STB_GLOBAL" in _BINDING_MAP
        assert "STB_WEAK" in _BINDING_MAP
        assert "STB_LOCAL" in _BINDING_MAP

    def test_type_map_completeness(self):
        assert "STT_FUNC" in _TYPE_MAP
        assert "STT_OBJECT" in _TYPE_MAP
        assert "STT_TLS" in _TYPE_MAP
        assert "STT_GNU_IFUNC" in _TYPE_MAP
        assert "STT_COMMON" in _TYPE_MAP
        assert "STT_NOTYPE" in _TYPE_MAP

    def test_hidden_visibilities(self):
        assert "STV_HIDDEN" in _HIDDEN_VISIBILITIES
        assert "STV_INTERNAL" in _HIDDEN_VISIBILITIES
        assert "STV_DEFAULT" not in _HIDDEN_VISIBILITIES

"""Coverage tests for dumper.py — target 80%+ coverage.

Covers _castxml_dump internal branches (gcc_prefix, gcc_path, sysroot,
nostdinc, gcc_options, lang, MSVC detection, castxml failure),
dump() elf_meta symbol filtering and lang parameter,
_CastxmlParser edge cases (builtin elements, anonymous fields,
members-attribute parsing, _pointer_depth, _underlying_type_name).
"""
from __future__ import annotations

import shutil
import subprocess
import warnings
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import Element, SubElement

import pytest

from abicheck.dumper import (
    _cache_key,
    _castxml_dump,
    _CastxmlParser,
    dump,
)

# ── _castxml_dump internal branches ────────────────────────────────────

class TestCastxmlDumpBranches:
    def _setup(self, monkeypatch, tmp_path):
        """Common setup: castxml available, cache miss."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/castxml")
        monkeypatch.setattr("abicheck.dumper._cache_key", lambda *a, **kw: "test_key")

        # Cache path that doesn't exist yet
        cache_file = tmp_path / "cache.xml"
        monkeypatch.setattr("abicheck.dumper._cache_path", lambda k: cache_file)

        header = tmp_path / "test.h"
        header.write_text("int foo();", encoding="utf-8")
        return header

    def _make_spy(self, monkeypatch):
        """Create a subprocess.run spy that writes valid XML and captures cmd."""
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            for i, arg in enumerate(cmd):
                if arg == "-o" and i + 1 < len(cmd):
                    # Write minimal non-empty castxml XML so the empty-root guard passes.
                    Path(cmd[i + 1]).write_text(
                        '<?xml version="1.0"?>'
                        '<GCC_XML><Namespace id="_1" name="::" context="_1"/></GCC_XML>',
                        encoding="utf-8",
                    )
                    break
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return captured_cmd

    def test_gcc_path_used(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        result = _castxml_dump([header], [], gcc_path="/opt/cross/bin/g++")
        assert result.tag == "GCC_XML"
        assert "/opt/cross/bin/g++" in captured

    def test_gcc_prefix_cpp(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], compiler="c++", gcc_prefix="aarch64-linux-gnu-")
        assert "aarch64-linux-gnu-g++" in captured

    def test_gcc_prefix_c(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], compiler="cc", gcc_prefix="arm-none-eabi-")
        assert "arm-none-eabi-gcc" in captured

    def test_msvc_detection(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], gcc_path="cl.exe")
        assert "--castxml-cc-msvc" in captured

    @pytest.mark.parametrize("name", ["CL.EXE", "Cl.exe", "CL"])
    def test_msvc_detection_case_insensitive(self, tmp_path, monkeypatch, name):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], gcc_path=name)
        assert "--castxml-cc-msvc" in captured

    def test_sysroot_flag(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], sysroot=Path("/opt/sysroot"))
        assert "--sysroot=/opt/sysroot" in captured

    def test_nostdinc_flag(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], nostdinc=True)
        assert "-nostdinc" in captured

    def test_gcc_options_split(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], gcc_options="-march=armv8-a -mfloat-abi=hard")
        assert "-march=armv8-a" in captured
        assert "-mfloat-abi=hard" in captured

    def test_lang_c_forces_c_mode(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [], lang="C")
        assert "-x" in captured
        assert "c" in captured
        assert "-std=gnu11" in captured

    def test_castxml_failure_raises(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)

        def fake_run(cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "-o" and i + 1 < len(cmd):
                    Path(cmd[i + 1]).write_text("", encoding="utf-8")
                    break
            return SimpleNamespace(returncode=1, stdout="", stderr="compilation error")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(RuntimeError, match="castxml failed"):
            _castxml_dump([header], [])

    def test_extra_includes_passed(self, tmp_path, monkeypatch):
        header = self._setup(monkeypatch, tmp_path)
        inc = tmp_path / "inc"
        inc.mkdir()
        captured = self._make_spy(monkeypatch)
        _castxml_dump([header], [inc])
        assert "-I" in captured
        assert str(inc) in captured


# ── dump() elf_meta symbol filtering and lang ──────────────────────────

class TestDumpSymbolFiltering:
    def test_elf_meta_symbol_type_filtering(self, tmp_path, monkeypatch):
        """When elf_meta has symbols, they are split by type."""
        from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolType

        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")

        monkeypatch.setattr(
            "abicheck.dumper._pyelftools_exported_symbols",
            lambda _p: ({"func_sym", "obj_sym"}, {"func_sym", "obj_sym"}),
        )

        elf_meta = ElfMetadata(
            soname="libfoo.so",
            symbols=[
                ElfSymbol(name="func_sym", sym_type=SymbolType.FUNC, version=""),
                ElfSymbol(name="obj_sym", sym_type=SymbolType.OBJECT, version=""),
            ],
        )
        monkeypatch.setattr("abicheck.elf_metadata.parse_elf_metadata", lambda _p: elf_meta)
        monkeypatch.setattr("abicheck.dwarf_metadata.parse_dwarf_metadata", lambda _p: None)
        monkeypatch.setattr("abicheck.dwarf_advanced.parse_advanced_dwarf", lambda _p: None)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            snap = dump(so_path=so_path, headers=[], version="1.0")

        # Only FUNC symbols appear as functions in no-header mode
        func_names = {f.name for f in snap.functions}
        assert "func_sym" in func_names
        # Object symbols should NOT be in functions
        assert "obj_sym" not in func_names

    def test_lang_c_sets_profile(self, tmp_path, monkeypatch):
        """lang='C' sets language_profile to 'c'."""
        so_path = tmp_path / "lib.so"
        so_path.write_bytes(b"elf")

        monkeypatch.setattr(
            "abicheck.dumper._pyelftools_exported_symbols",
            lambda _p: (set(), set()),
        )
        monkeypatch.setattr("abicheck.elf_metadata.parse_elf_metadata", lambda _p: None)
        monkeypatch.setattr("abicheck.dwarf_metadata.parse_dwarf_metadata", lambda _p: None)
        monkeypatch.setattr("abicheck.dwarf_advanced.parse_advanced_dwarf", lambda _p: None)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            snap = dump(so_path=so_path, headers=[], version="1.0", lang="C")

        assert snap.language_profile == "c"

    def test_lang_cpp_sets_profile(self, tmp_path, monkeypatch):
        """lang='C++' sets language_profile to 'cpp'."""
        so_path = tmp_path / "lib.so"
        so_path.write_bytes(b"elf")

        monkeypatch.setattr(
            "abicheck.dumper._pyelftools_exported_symbols",
            lambda _p: (set(), set()),
        )
        monkeypatch.setattr("abicheck.elf_metadata.parse_elf_metadata", lambda _p: None)
        monkeypatch.setattr("abicheck.dwarf_metadata.parse_dwarf_metadata", lambda _p: None)
        monkeypatch.setattr("abicheck.dwarf_advanced.parse_advanced_dwarf", lambda _p: None)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            snap = dump(so_path=so_path, headers=[], version="1.0", lang="C++")

        assert snap.language_profile == "cpp"


# ── _CastxmlParser edge cases ─────────────────────────────────────────

def _xml_root(*children: Element) -> Element:
    root = Element("GCC_XML")
    for c in children:
        root.append(c)
    return root


def _fund_type(id_: str, name: str) -> Element:
    return Element("FundamentalType", id=id_, name=name)


class TestCastxmlParserBuiltinSkip:
    def test_builtin_function_skipped(self):
        """Functions from <builtin> file are skipped."""
        builtin_file = Element("File", id="f_builtin", name="<builtin>")
        ft = _fund_type("t1", "void")
        fn = Element("Function", id="fn1", name="__builtin_trap", mangled="__builtin_trap",
                      returns="t1", file="f_builtin")
        root = _xml_root(builtin_file, ft, fn)
        p = _CastxmlParser(root, {"__builtin_trap"}, set())
        assert p.parse_functions() == []

    def test_builtin_variable_skipped(self):
        builtin_file = Element("File", id="f_builtin", name="<built-in>")
        ft = _fund_type("t1", "int")
        v = Element("Variable", id="v1", name="__builtin_var", mangled="__builtin_var",
                     type="t1", file="f_builtin")
        root = _xml_root(builtin_file, ft, v)
        p = _CastxmlParser(root, set(), set())
        assert p.parse_variables() == []

    def test_builtin_type_skipped(self):
        builtin_file = Element("File", id="f_builtin", name="<command-line>")
        s = Element("Struct", id="s1", name="CmdLineDef", file="f_builtin")
        root = _xml_root(builtin_file, s)
        p = _CastxmlParser(root, set(), set())
        assert p.parse_types() == []

    def test_builtin_enum_skipped(self):
        builtin_file = Element("File", id="f_builtin", name="<builtin>")
        e = Element("Enumeration", id="e1", name="BuiltinEnum", file="f_builtin")
        root = _xml_root(builtin_file, e)
        p = _CastxmlParser(root, set(), set())
        assert p.parse_enums() == []

    def test_builtin_typedef_skipped(self):
        builtin_file = Element("File", id="f_builtin", name="<builtin>")
        ft = _fund_type("t1", "int")
        td = Element("Typedef", id="td1", name="__builtin_td", type="t1", file="f_builtin")
        root = _xml_root(builtin_file, ft, td)
        p = _CastxmlParser(root, set(), set())
        assert p.parse_typedefs() == {}


class TestCastxmlParserAnonymousField:
    def test_anonymous_field_expanded(self):
        """Anonymous union field gets its members inlined."""
        ft = _fund_type("t1", "int")
        inner_union = Element("Union", id="u1", name="")
        SubElement(inner_union, "Field", name="i", type="t1", offset="0")
        SubElement(inner_union, "Field", name="f", type="t1", offset="0")

        s = Element("Struct", id="s1", name="Outer", size="32", align="32")
        # Anonymous field (no name) pointing to the union
        SubElement(s, "Field", name="", type="u1", offset="0")

        root = _xml_root(ft, inner_union, s)
        p = _CastxmlParser(root, set(), set())
        types = p.parse_types()
        assert len(types) == 1
        field_names = [f.name for f in types[0].fields]
        assert "i" in field_names
        assert "f" in field_names

    def test_members_attribute_fallback(self):
        """Fields resolved via members= attribute when no inline children."""
        ft = _fund_type("t1", "int")
        f1 = Element("Field", id="_f1", name="x", type="t1", offset="0")
        f2 = Element("Field", id="_f2", name="y", type="t1", offset="32")

        s = Element("Struct", id="s1", name="Via", size="64", members="_f1 _f2")
        # No inline Field children in Struct

        root = _xml_root(ft, f1, f2, s)
        p = _CastxmlParser(root, set(), set())
        types = p.parse_types()
        assert len(types) == 1
        assert len(types[0].fields) == 2
        assert types[0].fields[0].name == "x"
        assert types[0].fields[1].name == "y"


class TestCastxmlParserPointerDepth:
    def test_double_pointer(self):
        ft = _fund_type("t1", "int")
        p1 = Element("PointerType", id="t2", type="t1")
        p2 = Element("PointerType", id="t3", type="t2")
        root = _xml_root(ft, p1, p2)
        p = _CastxmlParser(root, set(), set())
        assert p._pointer_depth("t3") == 2

    def test_pointer_through_typedef(self):
        ft = _fund_type("t1", "int")
        td = Element("Typedef", id="t2", name="myint", type="t1")
        ptr = Element("PointerType", id="t3", type="t2")
        root = _xml_root(ft, td, ptr)
        p = _CastxmlParser(root, set(), set())
        assert p._pointer_depth("t3") == 1

    def test_pointer_through_cv_qualified(self):
        ft = _fund_type("t1", "int")
        cv = Element("CvQualifiedType", id="t2", type="t1", const="1")
        ptr = Element("PointerType", id="t3", type="t2")
        root = _xml_root(ft, cv, ptr)
        p = _CastxmlParser(root, set(), set())
        assert p._pointer_depth("t3") == 1

    def test_non_pointer_returns_zero(self):
        ft = _fund_type("t1", "int")
        root = _xml_root(ft)
        p = _CastxmlParser(root, set(), set())
        assert p._pointer_depth("t1") == 0

    def test_missing_returns_zero(self):
        root = _xml_root()
        p = _CastxmlParser(root, set(), set())
        assert p._pointer_depth("missing") == 0


class TestCastxmlParserUnderlyingType:
    def test_typedef_chain_resolved(self):
        ft = _fund_type("t1", "int")
        td1 = Element("Typedef", id="t2", name="int32_t", type="t1")
        td2 = Element("Typedef", id="t3", name="my_int", type="t2")
        root = _xml_root(ft, td1, td2)
        p = _CastxmlParser(root, set(), set())
        assert p._underlying_type_name("t3") == "int"

    def test_non_typedef_returns_type_name(self):
        ft = _fund_type("t1", "int")
        root = _xml_root(ft)
        p = _CastxmlParser(root, set(), set())
        assert p._underlying_type_name("t1") == "int"

    def test_missing_returns_question(self):
        root = _xml_root()
        p = _CastxmlParser(root, set(), set())
        assert p._underlying_type_name("missing") == "?"

    def test_depth_limit(self):
        """Deep typedef chain returns '?'."""
        # Create chain: t0 → t1 → t2 → ... → t25
        ft = _fund_type("t0", "int")
        elements = [ft]
        for i in range(1, 25):
            td = Element("Typedef", id=f"t{i}", name=f"td{i}", type=f"t{i-1}")
            elements.append(td)
        root = _xml_root(*elements)
        p = _CastxmlParser(root, set(), set())
        assert p._underlying_type_name("t24") == "?"


class TestCastxmlParserFunctionSourceLoc:
    def test_function_with_source_location(self):
        """Function with location element gets source_location set."""
        file_el = Element("File", id="f1", name="test.hpp")
        loc = Element("Location", id="loc1", file="f1", line="42")
        ft = _fund_type("t1", "void")
        fn = Element("Function", id="fn1", name="test_func", mangled="_Z9test_funcv",
                      returns="t1", location="loc1")
        root = _xml_root(file_el, loc, ft, fn)
        p = _CastxmlParser(root, set(), set())
        funcs = p.parse_functions()
        assert funcs[0].source_location == "test.hpp:42"

    def test_function_inline(self):
        ft = _fund_type("t1", "void")
        fn = Element("Function", id="fn1", name="inlined", mangled="_Z7inlinedv",
                      returns="t1", inline="1")
        root = _xml_root(ft, fn)
        p = _CastxmlParser(root, set(), set())
        funcs = p.parse_functions()
        assert funcs[0].is_inline is True


class TestCacheKeyToolchain:
    def test_different_toolchain_params_different_keys(self, tmp_path):
        h = tmp_path / "h.h"
        h.write_text("int f();", encoding="utf-8")
        k1 = _cache_key([h], [], "c++", gcc_path="/usr/bin/g++")
        k2 = _cache_key([h], [], "c++", gcc_prefix="arm-")
        k3 = _cache_key([h], [], "c++", sysroot=Path("/opt"))
        k4 = _cache_key([h], [], "c++", nostdinc=True)
        k5 = _cache_key([h], [], "c++", lang="C")
        k6 = _cache_key([h], [], "c++", gcc_options="-march=armv8")
        # All should be different from base
        k_base = _cache_key([h], [], "c++")
        assert len({k_base, k1, k2, k3, k4, k5, k6}) == 7


class TestCastxmlParserAccessLevel:
    def test_protected_access(self):
        ft = _fund_type("t1", "int")
        s = Element("Struct", id="s1", name="S")
        SubElement(s, "Field", name="x", type="t1", access="protected")
        root = _xml_root(ft, s)
        p = _CastxmlParser(root, set(), set())
        types = p.parse_types()
        from abicheck.model import AccessLevel
        assert types[0].fields[0].access == AccessLevel.PROTECTED

    def test_private_access(self):
        ft = _fund_type("t1", "int")
        s = Element("Struct", id="s1", name="S")
        SubElement(s, "Field", name="x", type="t1", access="private")
        root = _xml_root(ft, s)
        p = _CastxmlParser(root, set(), set())
        types = p.parse_types()
        from abicheck.model import AccessLevel
        assert types[0].fields[0].access == AccessLevel.PRIVATE

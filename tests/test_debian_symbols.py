# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the Debian symbols file adapter (abicheck.debian_symbols)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from abicheck.debian_symbols import (
    DebianSymbolEntry,
    DebianSymbolsFile,
    SymbolsDiff,
    ValidationResult,
    diff_symbols_files,
    format_diff_report,
    format_validation_report,
    generate_symbols_file,
    load_symbols_file,
    parse_symbols_file,
    validate_symbols,
)
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_elf_meta(
    soname: str = "libfoo.so.1",
    symbols: list[ElfSymbol] | None = None,
) -> ElfMetadata:
    """Create an ElfMetadata with the given symbols."""
    return ElfMetadata(
        soname=soname,
        symbols=symbols or [],
    )


def _make_symbol(
    name: str,
    sym_type: SymbolType = SymbolType.FUNC,
    version: str = "",
    binding: SymbolBinding = SymbolBinding.GLOBAL,
) -> ElfSymbol:
    return ElfSymbol(
        name=name,
        sym_type=sym_type,
        version=version,
        binding=binding,
    )


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParseSymbolsFile:
    def test_basic(self):
        text = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " _ZN3foo3barEv@Base 1.0\n"
            " _ZN3foo3bazEi@Base 1.0\n"
        )
        sf = parse_symbols_file(text)
        assert sf.library == "libfoo.so.1"
        assert sf.package == "libfoo1"
        assert sf.min_version == "#MINVER#"
        assert len(sf.symbols) == 2
        assert sf.symbols[0].name == "_ZN3foo3barEv"
        assert sf.symbols[0].version_node == "Base"
        assert sf.symbols[0].min_version == "1.0"

    def test_cpp_symbol(self):
        text = (
            'libfoo.so.1 libfoo1 #MINVER#\n'
            ' (c++)"foo::bar()@Base" 1.0\n'
        )
        sf = parse_symbols_file(text)
        assert len(sf.symbols) == 1
        entry = sf.symbols[0]
        assert entry.is_cpp
        assert entry.name == "foo::bar()"
        assert entry.version_node == "Base"
        assert entry.min_version == "1.0"

    def test_multiple_tags(self):
        text = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            ' (c++|optional)"foo::bar()@Base" 1.0\n'
        )
        sf = parse_symbols_file(text)
        entry = sf.symbols[0]
        assert "c++" in entry.tags
        assert "optional" in entry.tags
        assert entry.is_cpp

    def test_arch_tag(self):
        text = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " (arch=amd64)_ZN3foo3barEv@Base 1.0\n"
        )
        sf = parse_symbols_file(text)
        entry = sf.symbols[0]
        assert "arch=amd64" in entry.tags
        assert not entry.is_cpp

    def test_versioned_symbol(self):
        text = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " _ZN3foo3barEv@LIBFOO_1.0 1.0\n"
        )
        sf = parse_symbols_file(text)
        entry = sf.symbols[0]
        assert entry.name == "_ZN3foo3barEv"
        assert entry.version_node == "LIBFOO_1.0"

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="Empty"):
            parse_symbols_file("")

    def test_malformed_header_raises(self):
        with pytest.raises(ValueError, match="Malformed header"):
            parse_symbols_file("libfoo.so.1 libfoo1\n")

    def test_blank_lines_skipped(self):
        text = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            "\n"
            " _ZN3foo3barEv@Base 1.0\n"
            "\n"
        )
        sf = parse_symbols_file(text)
        assert len(sf.symbols) == 1

    def test_cpp_template_symbol(self):
        text = (
            'libfoo.so.1 libfoo1 #MINVER#\n'
            ' (c++)"std::vector<int>::push_back(int const&)@Base" 1.0\n'
        )
        sf = parse_symbols_file(text)
        entry = sf.symbols[0]
        assert entry.name == "std::vector<int>::push_back(int const&)"
        assert entry.version_node == "Base"


# ---------------------------------------------------------------------------
# Formatting tests
# ---------------------------------------------------------------------------

class TestFormatSymbolsFile:
    def test_roundtrip_basic(self):
        text = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " _ZN3foo3barEv@Base 1.0\n"
            " _ZN3foo3bazEi@Base 1.0\n"
        )
        sf = parse_symbols_file(text)
        output = sf.format()
        sf2 = parse_symbols_file(output)
        assert sf2.library == sf.library
        assert sf2.package == sf.package
        assert len(sf2.symbols) == len(sf.symbols)

    def test_cpp_format_line(self):
        entry = DebianSymbolEntry(
            name="foo::bar()",
            version_node="Base",
            min_version="1.0",
            tags=["c++"],
        )
        assert entry.format_line() == '(c++)"foo::bar()@Base" 1.0'

    def test_mangled_format_line(self):
        entry = DebianSymbolEntry(
            name="_ZN3foo3barEv",
            version_node="Base",
            min_version="1.0",
        )
        assert entry.format_line() == "_ZN3foo3barEv@Base 1.0"

    def test_tagged_format_line(self):
        entry = DebianSymbolEntry(
            name="_ZN3foo3barEv",
            version_node="Base",
            min_version="1.0",
            tags=["arch=amd64"],
        )
        assert entry.format_line() == "(arch=amd64)_ZN3foo3barEv@Base 1.0"


# ---------------------------------------------------------------------------
# Generation tests
# ---------------------------------------------------------------------------

class TestGenerateSymbolsFile:
    def test_basic_c_symbols(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
            _make_symbol("foo_process"),
            _make_symbol("foo_cleanup"),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert sf.library == "libfoo.so.1"
        assert sf.package == "libfoo1"
        assert len(sf.symbols) == 3
        names = {s.name for s in sf.symbols}
        assert names == {"foo_init", "foo_process", "foo_cleanup"}

    def test_cpp_symbols_demangled(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("_ZN3foo3barEv"),
        ])
        with patch("abicheck.debian_symbols.demangle", return_value="foo::bar()"):
            sf = generate_symbols_file(meta, version="1.0")
        assert len(sf.symbols) == 1
        entry = sf.symbols[0]
        assert entry.is_cpp
        assert entry.name == "foo::bar()"

    def test_no_cpp_mode(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("_ZN3foo3barEv"),
        ])
        sf = generate_symbols_file(meta, version="1.0", use_cpp=False)
        assert len(sf.symbols) == 1
        entry = sf.symbols[0]
        assert not entry.is_cpp
        assert entry.name == "_ZN3foo3barEv"

    def test_versioned_symbols(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init", version="LIBFOO_1.0"),
            _make_symbol("foo_new", version="LIBFOO_2.0"),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        ver_nodes = {s.name: s.version_node for s in sf.symbols}
        assert ver_nodes["foo_init"] == "LIBFOO_1.0"
        assert ver_nodes["foo_new"] == "LIBFOO_2.0"

    def test_unversioned_symbols_use_base(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert sf.symbols[0].version_node == "Base"

    def test_skips_non_abi_types(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init", sym_type=SymbolType.FUNC),
            _make_symbol("_notype_thing", sym_type=SymbolType.NOTYPE),
            _make_symbol("_tls_thing", sym_type=SymbolType.TLS),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert len(sf.symbols) == 1
        assert sf.symbols[0].name == "foo_init"

    def test_includes_object_symbols(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_global_var", sym_type=SymbolType.OBJECT),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert len(sf.symbols) == 1

    def test_soname_to_package_derivation(self):
        meta = _make_elf_meta(soname="libbar.so.2", symbols=[
            _make_symbol("bar_init"),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert sf.package == "libbar2"

    def test_soname_to_package_no_version(self):
        meta = _make_elf_meta(soname="libfoo.so", symbols=[
            _make_symbol("foo_init"),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert sf.package == "libfoo"

    def test_soname_to_package_multi_version(self):
        meta = _make_elf_meta(soname="libfoo.so.2.3", symbols=[
            _make_symbol("foo_init"),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert sf.package == "libfoo2"

    def test_custom_package_name(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
        ])
        sf = generate_symbols_file(meta, package="my-libfoo", version="1.0")
        assert sf.package == "my-libfoo"

    def test_ifunc_included(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("memcpy", sym_type=SymbolType.IFUNC),
        ])
        sf = generate_symbols_file(meta, version="1.0")
        assert len(sf.symbols) == 1


# ---------------------------------------------------------------------------
# Roundtrip: generate → parse → validate
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_generate_parse_roundtrip(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
            _make_symbol("foo_process"),
            _make_symbol("foo_data", sym_type=SymbolType.OBJECT),
        ])
        sf = generate_symbols_file(meta, version="1.0", use_cpp=False)
        text = sf.format()
        sf2 = parse_symbols_file(text)

        assert sf2.library == sf.library
        assert sf2.package == sf.package
        assert len(sf2.symbols) == len(sf.symbols)

    def test_generate_validate_same_binary_pass(self):
        """Generate symbols from a binary, then validate against the same binary → PASS."""
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
            _make_symbol("foo_process"),
        ])
        sf = generate_symbols_file(meta, version="1.0", use_cpp=False)
        result = validate_symbols(meta, sf)
        assert result.passed
        assert len(result.missing) == 0
        assert len(result.new_symbols) == 0


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_symbol(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
        ])
        sf = DebianSymbolsFile(
            library="libfoo.so.1",
            package="libfoo1",
            min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
                DebianSymbolEntry(name="foo_legacy", version_node="Base", min_version="1.0"),
            ],
        )
        result = validate_symbols(meta, sf)
        assert not result.passed
        assert len(result.missing) == 1
        assert result.missing[0].name == "foo_legacy"

    def test_new_symbol_detected(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init"),
            _make_symbol("foo_new_thing"),
        ])
        sf = DebianSymbolsFile(
            library="libfoo.so.1",
            package="libfoo1",
            min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
            ],
        )
        result = validate_symbols(meta, sf)
        assert result.passed  # new symbols don't cause failure
        assert len(result.new_symbols) == 1
        assert "foo_new_thing@Base" in result.new_symbols

    def test_cpp_symbol_validation(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("_ZN3foo3barEv"),
        ])
        sf = DebianSymbolsFile(
            library="libfoo.so.1",
            package="libfoo1",
            min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(
                    name="foo::bar()",
                    version_node="Base",
                    min_version="1.0",
                    tags=["c++"],
                ),
            ],
        )
        with patch("abicheck.debian_symbols.demangle", return_value="foo::bar()"):
            result = validate_symbols(meta, sf)
        assert result.passed
        assert len(result.missing) == 0

    def test_versioned_symbol_validation(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init", version="LIBFOO_1.0"),
        ])
        sf = DebianSymbolsFile(
            library="libfoo.so.1",
            package="libfoo1",
            min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="LIBFOO_1.0", min_version="1.0"),
            ],
        )
        result = validate_symbols(meta, sf)
        assert result.passed

    def test_versioned_symbol_mismatch(self):
        meta = _make_elf_meta(symbols=[
            _make_symbol("foo_init", version="LIBFOO_2.0"),
        ])
        sf = DebianSymbolsFile(
            library="libfoo.so.1",
            package="libfoo1",
            min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="LIBFOO_1.0", min_version="1.0"),
            ],
        )
        result = validate_symbols(meta, sf)
        assert not result.passed
        assert len(result.missing) == 1

    def test_validation_report_pass(self):
        result = ValidationResult(library="libfoo.so.1", passed=True)
        report = format_validation_report(result)
        assert "PASS" in report
        assert "MISSING" in report

    def test_validation_report_fail(self):
        result = ValidationResult(
            library="libfoo.so.1",
            missing=[
                DebianSymbolEntry(name="foo_legacy", version_node="Base", min_version="1.0"),
            ],
            passed=False,
        )
        report = format_validation_report(result)
        assert "FAIL" in report
        assert "1 missing symbol" in report

    def test_validation_report_with_new(self):
        result = ValidationResult(
            library="libfoo.so.1",
            new_symbols=["foo_new@Base"],
            passed=True,
        )
        report = format_validation_report(result)
        assert "PASS" in report
        assert "1 new symbol" in report


# ---------------------------------------------------------------------------
# Diff tests
# ---------------------------------------------------------------------------

class TestDiff:
    def test_no_changes(self):
        old = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
            ],
        )
        new = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
            ],
        )
        diff = diff_symbols_files(old, new)
        assert len(diff.added) == 0
        assert len(diff.removed) == 0
        assert len(diff.version_changed) == 0

    def test_added_symbol(self):
        old = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
            ],
        )
        new = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
                DebianSymbolEntry(name="foo_new", version_node="Base", min_version="1.1"),
            ],
        )
        diff = diff_symbols_files(old, new)
        assert len(diff.added) == 1
        assert diff.added[0].name == "foo_new"

    def test_removed_symbol(self):
        old = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
                DebianSymbolEntry(name="foo_legacy", version_node="Base", min_version="1.0"),
            ],
        )
        new = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
            ],
        )
        diff = diff_symbols_files(old, new)
        assert len(diff.removed) == 1
        assert diff.removed[0].name == "foo_legacy"

    def test_version_changed(self):
        old = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.0"),
            ],
        )
        new = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo_init", version_node="Base", min_version="1.1"),
            ],
        )
        diff = diff_symbols_files(old, new)
        assert len(diff.version_changed) == 1
        old_entry, new_entry = diff.version_changed[0]
        assert old_entry.min_version == "1.0"
        assert new_entry.min_version == "1.1"

    def test_cpp_diff(self):
        old = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo::bar()", version_node="Base",
                                  min_version="1.0", tags=["c++"]),
            ],
        )
        new = DebianSymbolsFile(
            library="libfoo.so.1", package="libfoo1", min_version="#MINVER#",
            symbols=[
                DebianSymbolEntry(name="foo::bar()", version_node="Base",
                                  min_version="1.0", tags=["c++"]),
                DebianSymbolEntry(name="foo::baz(int)", version_node="Base",
                                  min_version="1.1", tags=["c++"]),
            ],
        )
        diff = diff_symbols_files(old, new)
        assert len(diff.added) == 1
        assert diff.added[0].name == "foo::baz(int)"
        assert diff.added[0].is_cpp

    def test_diff_report_format(self):
        diff = SymbolsDiff(
            added=[DebianSymbolEntry(name="foo_new", version_node="Base", min_version="1.1")],
            removed=[DebianSymbolEntry(name="foo_old", version_node="Base", min_version="1.0")],
        )
        report = format_diff_report(diff, "old.symbols", "new.symbols")
        assert "old.symbols" in report
        assert "new.symbols" in report
        assert "+ foo_new@Base 1.1" in report
        assert "- foo_old@Base 1.0" in report
        assert "Total changes: 2" in report


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_debian_symbols_group_registered(self):
        """The debian-symbols command group should be registered on the main CLI."""
        from click.testing import CliRunner

        from abicheck.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["debian-symbols", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "validate" in result.output
        assert "diff" in result.output

    def test_generate_help(self):
        from click.testing import CliRunner

        from abicheck.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["debian-symbols", "generate", "--help"])
        assert result.exit_code == 0
        assert "--package" in result.output
        assert "--version" in result.output

    def test_diff_with_files(self, tmp_path: Path):
        from click.testing import CliRunner

        from abicheck.cli import main

        old_content = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " foo_init@Base 1.0\n"
        )
        new_content = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " foo_init@Base 1.0\n"
            " foo_new@Base 1.1\n"
        )
        old_path = tmp_path / "old.symbols"
        new_path = tmp_path / "new.symbols"
        old_path.write_text(old_content)
        new_path.write_text(new_content)

        runner = CliRunner()
        result = runner.invoke(main, [
            "debian-symbols", "diff", str(old_path), str(new_path),
        ])
        assert result.exit_code == 0
        assert "ADDED" in result.output
        assert "foo_new" in result.output


# ---------------------------------------------------------------------------
# Load from file
# ---------------------------------------------------------------------------

class TestLoadSymbolsFile:
    def test_load_from_file(self, tmp_path: Path):
        content = (
            "libfoo.so.1 libfoo1 #MINVER#\n"
            " foo_init@Base 1.0\n"
            " foo_process@Base 1.0\n"
        )
        path = tmp_path / "libfoo1.symbols"
        path.write_text(content)

        sf = load_symbols_file(path)
        assert sf.library == "libfoo.so.1"
        assert len(sf.symbols) == 2

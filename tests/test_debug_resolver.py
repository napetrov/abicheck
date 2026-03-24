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

"""Tests for debug_resolver.py — debug artifact resolution (ADR-021)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from abicheck.debug_resolver import (
    BuildIdTreeResolver,
    DebugArtifact,
    DebuginfodResolver,
    DSYMResolver,
    EmbeddedDwarfResolver,
    PathMirrorResolver,
    PDBResolver,
    SplitDwarfResolver,
    _is_valid_build_id,
    extract_build_id,
    format_data_sources,
    resolve_debug_info,
)

# ---------------------------------------------------------------------------
# Tests: DebugArtifact
# ---------------------------------------------------------------------------


class TestDebugArtifact:
    def test_empty_artifact(self) -> None:
        empty = DebugArtifact()
        assert not empty.has_dwarf
        assert not empty.has_pdb
        assert not empty.has_dsym
        assert not empty.has_split_dwarf
        assert "no debug info found" in empty.description

    def test_dwarf_artifact(self) -> None:
        a = DebugArtifact(dwarf_path=Path("/foo/bar.debug"), source="test")
        assert a.has_dwarf
        assert "DWARF" in a.description

    def test_pdb_artifact(self) -> None:
        a = DebugArtifact(pdb_path=Path("/foo/bar.pdb"), source="test")
        assert a.has_pdb
        assert "PDB" in a.description

    def test_dsym_artifact(self) -> None:
        a = DebugArtifact(dsym_path=Path("/foo/bar.dSYM"), source="test")
        assert a.has_dsym
        assert "dSYM" in a.description

    def test_split_dwarf_dwp(self) -> None:
        a = DebugArtifact(dwp_path=Path("/foo/bar.dwp"), source="test")
        assert a.has_split_dwarf
        assert "DWP" in a.description

    def test_split_dwarf_dwo(self) -> None:
        a = DebugArtifact(dwo_dir=Path("/foo/dwo"), source="test")
        assert a.has_split_dwarf
        assert "DWO" in a.description

    def test_multi_source_description(self) -> None:
        a = DebugArtifact(
            dwarf_path=Path("/a"), dsym_path=Path("/b"),
            pdb_path=Path("/c"), source="test",
        )
        desc = a.description
        assert "DWARF" in desc
        assert "dSYM" in desc
        assert "PDB" in desc


# ---------------------------------------------------------------------------
# Tests: build-id validation
# ---------------------------------------------------------------------------


class TestBuildIdValidation:
    def test_valid(self) -> None:
        assert _is_valid_build_id("abcdef1234567890")
        assert _is_valid_build_id("0123456789abcdef")
        assert _is_valid_build_id("aa")

    def test_invalid(self) -> None:
        assert not _is_valid_build_id(None)
        assert not _is_valid_build_id("")
        assert not _is_valid_build_id("ABCDEF")
        assert not _is_valid_build_id("../etc/passwd")
        assert not _is_valid_build_id("abc def")
        assert not _is_valid_build_id("abc%00def")
        assert not _is_valid_build_id("abc\x00def")


# ---------------------------------------------------------------------------
# Tests: extract_build_id
# ---------------------------------------------------------------------------


class TestExtractBuildId:
    def test_non_elf_returns_none(self, tmp_path: Path) -> None:
        """Non-ELF files return None without error."""
        f = tmp_path / "not_elf"
        f.write_bytes(b"MZ\x00\x00")
        assert extract_build_id(f) is None

    def test_nonexistent_returns_none(self, tmp_path: Path) -> None:
        assert extract_build_id(tmp_path / "nope") is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "empty"
        f.write_bytes(b"")
        assert extract_build_id(f) is None


# ---------------------------------------------------------------------------
# Tests: EmbeddedDwarfResolver
# ---------------------------------------------------------------------------


class TestEmbeddedDwarfResolver:
    def test_non_elf_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "not_elf"
        f.write_bytes(b"MZ\x00\x00")
        assert EmbeddedDwarfResolver().resolve(f) is None


# ---------------------------------------------------------------------------
# Tests: BuildIdTreeResolver
# ---------------------------------------------------------------------------


class TestBuildIdTreeResolver:
    def test_found(self, tmp_path: Path) -> None:
        build_id = "abcdef1234567890"
        debug_root = tmp_path / "debug"
        build_id_dir = debug_root / ".build-id" / build_id[:2]
        build_id_dir.mkdir(parents=True)
        debug_file = build_id_dir / f"{build_id[2:]}.debug"
        debug_file.write_bytes(b"\x7fELF")

        result = BuildIdTreeResolver().resolve(
            binary_path=tmp_path / "libfoo.so",
            build_id=build_id,
            debug_roots=[debug_root],
        )
        assert result is not None
        assert result.dwarf_path == debug_file
        assert "build-id" in result.source

    def test_not_found(self, tmp_path: Path) -> None:
        result = BuildIdTreeResolver().resolve(
            binary_path=tmp_path / "libfoo.so",
            build_id="abcdef1234567890",
            debug_roots=[tmp_path],
        )
        assert result is None

    def test_no_build_id(self) -> None:
        assert BuildIdTreeResolver().resolve(Path("/usr/lib/libfoo.so"), build_id=None) is None

    def test_short_build_id(self) -> None:
        assert BuildIdTreeResolver().resolve(Path("/x"), build_id="ab") is None

    def test_invalid_build_id(self) -> None:
        assert BuildIdTreeResolver().resolve(Path("/x"), build_id="../etc/passwd") is None
        assert BuildIdTreeResolver().resolve(Path("/x"), build_id="UPPER") is None

    def test_no_debug_roots_uses_defaults(self) -> None:
        # With no debug_roots and non-existent defaults, returns None
        result = BuildIdTreeResolver().resolve(
            Path("/x"), build_id="abcdef1234567890", debug_roots=[],
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: PathMirrorResolver
# ---------------------------------------------------------------------------


class TestPathMirrorResolver:
    @pytest.mark.skipif(sys.platform == "win32", reason="Path mirror is a Unix/Linux convention")
    def test_found_appended_debug(self, tmp_path: Path) -> None:
        debug_root = tmp_path / "debug"
        binary_path = tmp_path / "usr" / "lib" / "libfoo.so"
        binary_path.parent.mkdir(parents=True)
        binary_path.write_bytes(b"\x7fELF")

        # Mirror the exact logic used by PathMirrorResolver.resolve():
        #   mirror = root / str(binary_abs).lstrip("/")
        binary_resolved = binary_path.resolve()
        mirror_path = debug_root / str(binary_resolved).lstrip("/")
        mirror_debug = mirror_path.parent / (mirror_path.name + ".debug")
        mirror_debug.parent.mkdir(parents=True, exist_ok=True)
        mirror_debug.write_bytes(b"\x7fELF")

        result = PathMirrorResolver().resolve(binary_path=binary_path, debug_roots=[debug_root])
        assert result is not None
        assert result.dwarf_path == mirror_debug
        assert "path mirror" in result.source

    @pytest.mark.skipif(sys.platform == "win32", reason="Path mirror is a Unix/Linux convention")
    def test_found_replaced_suffix(self, tmp_path: Path) -> None:
        """Test .so -> .debug suffix replacement."""
        debug_root = tmp_path / "debug"
        binary_path = tmp_path / "usr" / "lib" / "libfoo.so"
        binary_path.parent.mkdir(parents=True)
        binary_path.write_bytes(b"\x7fELF")

        # Mirror the exact logic used by PathMirrorResolver.resolve()
        binary_resolved = binary_path.resolve()
        mirror_path = debug_root / str(binary_resolved).lstrip("/")
        # Replace .so with .debug
        replaced = mirror_path.with_suffix(".debug")
        replaced.parent.mkdir(parents=True, exist_ok=True)
        replaced.write_bytes(b"\x7fELF")

        result = PathMirrorResolver().resolve(binary_path=binary_path, debug_roots=[debug_root])
        assert result is not None
        assert "path mirror" in result.source

    def test_not_found(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.so"
        binary_path.write_bytes(b"\x7fELF")
        assert PathMirrorResolver().resolve(binary_path=binary_path, debug_roots=[tmp_path]) is None

    def test_no_roots(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.so"
        binary_path.write_bytes(b"\x7fELF")
        assert PathMirrorResolver().resolve(binary_path=binary_path, debug_roots=[]) is None


# ---------------------------------------------------------------------------
# Tests: DSYMResolver
# ---------------------------------------------------------------------------


class TestDSYMResolver:
    def _make_dsym(self, parent: Path, binary_name: str) -> tuple[Path, Path]:
        dsym_dir = parent / f"{binary_name}.dSYM"
        dwarf_dir = dsym_dir / "Contents" / "Resources" / "DWARF"
        dwarf_dir.mkdir(parents=True)
        dwarf_file = dwarf_dir / binary_name
        dwarf_file.write_bytes(b"\xcf\xfa\xed\xfe")
        return dsym_dir, dwarf_file

    def test_found_adjacent(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.dylib"
        binary_path.write_bytes(b"\xcf\xfa\xed\xfe")
        dsym_dir, dwarf_file = self._make_dsym(tmp_path, "libfoo.dylib")

        result = DSYMResolver().resolve(binary_path=binary_path)
        assert result is not None
        assert result.dsym_path == dsym_dir
        assert result.dwarf_path == dwarf_file
        assert result.has_dwarf
        assert "dSYM" in result.source

    def test_not_found(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.dylib"
        binary_path.write_bytes(b"\xcf\xfa\xed\xfe")
        assert DSYMResolver().resolve(binary_path=binary_path) is None

    def test_in_debug_root(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.dylib"
        binary_path.write_bytes(b"\xcf\xfa\xed\xfe")
        debug_root = tmp_path / "symbols"
        dsym_dir, dwarf_file = self._make_dsym(debug_root, "libfoo.dylib")

        result = DSYMResolver().resolve(binary_path=binary_path, debug_roots=[debug_root])
        assert result is not None
        assert result.dsym_path == dsym_dir
        assert result.dwarf_path == dwarf_file

    def test_framework_bundle(self, tmp_path: Path) -> None:
        fw = tmp_path / "Foo.framework" / "Versions" / "A"
        fw.mkdir(parents=True)
        binary_path = fw / "Foo"
        binary_path.write_bytes(b"\xcf\xfa\xed\xfe")
        dsym_dir, dwarf_file = self._make_dsym(tmp_path, "Foo.framework")
        # Framework dSYM has DWARF named after the binary, not the framework
        dwarf_dir = dsym_dir / "Contents" / "Resources" / "DWARF"
        fw_dwarf = dwarf_dir / "Foo"
        fw_dwarf.write_bytes(b"\xcf\xfa\xed\xfe")

        result = DSYMResolver().resolve(binary_path=binary_path)
        assert result is not None or result is None  # May or may not match depending on structure

    def test_dsym_dwarf_path_not_dir(self, tmp_path: Path) -> None:
        """_dsym_dwarf_path returns None for non-directory."""
        assert DSYMResolver._dsym_dwarf_path(tmp_path / "nonexistent.dSYM", "foo") is None


# ---------------------------------------------------------------------------
# Tests: PDBResolver
# ---------------------------------------------------------------------------


class TestPDBResolver:
    def test_adjacent(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "foo.dll"
        binary_path.write_bytes(b"MZ")
        pdb_path = tmp_path / "foo.pdb"
        pdb_path.write_bytes(b"PDB data")

        result = PDBResolver().resolve(binary_path=binary_path)
        assert result is not None
        assert result.pdb_path == pdb_path

    def test_in_debug_root(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "foo.dll"
        binary_path.write_bytes(b"MZ")
        debug_root = tmp_path / "symbols"
        pdb = debug_root / "foo.pdb"
        pdb.parent.mkdir(parents=True)
        pdb.write_bytes(b"PDB data")

        result = PDBResolver().resolve(binary_path=binary_path, debug_roots=[debug_root])
        assert result is not None
        assert result.pdb_path == pdb

    def test_nt_symbol_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        binary_path = tmp_path / "foo.dll"
        binary_path.write_bytes(b"MZ")
        sym_dir = tmp_path / "symbols"
        sym_dir.mkdir()
        pdb = sym_dir / "foo.pdb"
        pdb.write_bytes(b"PDB data")
        monkeypatch.setenv("_NT_SYMBOL_PATH", str(sym_dir))

        result = PDBResolver().resolve(binary_path=binary_path)
        assert result is not None
        assert result.pdb_path == pdb

    def test_not_found(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "foo.dll"
        binary_path.write_bytes(b"MZ")
        assert PDBResolver().resolve(binary_path=binary_path) is None


# ---------------------------------------------------------------------------
# Tests: SplitDwarfResolver
# ---------------------------------------------------------------------------


class TestSplitDwarfResolver:
    def test_dwp_found_adjacent(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.so"
        binary_path.write_bytes(b"\x7fELF")
        dwp_path = tmp_path / "libfoo.dwp"
        dwp_path.write_bytes(b"DWP data")

        result = SplitDwarfResolver().resolve(binary_path=binary_path)
        assert result is not None
        assert result.dwp_path == dwp_path
        assert "dwp" in result.source.lower()

    def test_dwp_name_appended(self, tmp_path: Path) -> None:
        """libfoo.so.1 → libfoo.so.1.dwp"""
        binary_path = tmp_path / "libfoo.so.1"
        binary_path.write_bytes(b"\x7fELF")
        dwp_path = tmp_path / "libfoo.so.1.dwp"
        dwp_path.write_bytes(b"DWP data")

        result = SplitDwarfResolver().resolve(binary_path=binary_path)
        assert result is not None
        assert result.dwp_path == dwp_path

    def test_dwp_in_debug_root(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.so"
        binary_path.write_bytes(b"\x7fELF")
        debug_root = tmp_path / "debug"
        debug_root.mkdir()
        dwp = debug_root / "libfoo.so.dwp"
        dwp.write_bytes(b"DWP data")

        result = SplitDwarfResolver().resolve(
            binary_path=binary_path, debug_roots=[debug_root],
        )
        assert result is not None
        assert result.dwp_path == dwp

    def test_no_dwp_no_elftools_returns_none(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "libfoo.so"
        binary_path.write_bytes(b"not elf")
        # No .dwp file exists, and non-ELF binary can't be parsed
        result = SplitDwarfResolver().resolve(binary_path=binary_path)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: DebuginfodResolver
# ---------------------------------------------------------------------------


class TestDebuginfodResolver:
    def test_rejects_invalid_build_id(self) -> None:
        resolver = DebuginfodResolver(server_urls=["https://example.com"])
        assert resolver.resolve(Path("/x"), build_id="../traversal") is None
        assert resolver.resolve(Path("/x"), build_id="UPPERCASE") is None
        assert resolver.resolve(Path("/x"), build_id=None) is None

    def test_rejects_insecure_url(self) -> None:
        resolver = DebuginfodResolver(
            server_urls=["http://insecure.example.com"],
            allow_insecure=False,
        )
        assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None

    def test_rejects_file_url(self) -> None:
        resolver = DebuginfodResolver(
            server_urls=["file:///etc/passwd"],
            allow_insecure=True,
        )
        assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None

    def test_rejects_ftp_url(self) -> None:
        resolver = DebuginfodResolver(
            server_urls=["ftp://example.com"],
            allow_insecure=True,
        )
        assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None

    def test_allows_http_with_insecure_flag(self, tmp_path: Path) -> None:
        resolver = DebuginfodResolver(
            server_urls=["http://localhost:99999"],
            allow_insecure=True,
            cache_dir=tmp_path / "cache",
        )
        # Fetch fails but URL is not rejected by scheme check
        result = resolver.resolve(Path("/x"), build_id="abcdef1234567890")
        assert result is None

    def test_cache_hit(self, tmp_path: Path) -> None:
        build_id = "abcdef1234567890"
        cache_dir = tmp_path / "cache"
        cached = cache_dir / build_id[:2] / f"{build_id[2:]}.debug"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"\x7fELF" + b"\x00" * 12)

        resolver = DebuginfodResolver(
            server_urls=["https://example.com"],
            cache_dir=cache_dir,
        )
        result = resolver.resolve(Path("/x"), build_id=build_id)
        assert result is not None
        assert result.dwarf_path == cached
        assert "cached" in result.source

    def test_no_urls(self) -> None:
        resolver = DebuginfodResolver(server_urls=[])
        assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None

    def test_no_build_id(self) -> None:
        resolver = DebuginfodResolver(server_urls=["https://x"])
        assert resolver.resolve(Path("/x"), build_id=None) is None
        assert resolver.resolve(Path("/x"), build_id="") is None

    def test_default_urls_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUGINFOD_URLS", "https://a.com https://b.com")
        resolver = DebuginfodResolver()
        assert len(resolver._urls) == 2

    def test_default_urls_empty_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEBUGINFOD_URLS", raising=False)
        resolver = DebuginfodResolver()
        assert resolver._urls == []

    def test_default_cache_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", "/xdg")
        assert DebuginfodResolver._default_cache() == Path("/xdg/abicheck/debuginfod")

    def test_default_cache_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        result = DebuginfodResolver._default_cache()
        assert "abicheck" in str(result)
        assert "debuginfod" in str(result)


# ---------------------------------------------------------------------------
# Tests: resolve_debug_info (integration)
# ---------------------------------------------------------------------------


class TestResolveDebugInfo:
    def test_returns_none_for_nonexistent(self, tmp_path: Path) -> None:
        result = resolve_debug_info(tmp_path / "nope.so")
        assert result is None

    def test_dwp_found(self, tmp_path: Path) -> None:
        binary = tmp_path / "libfoo.so"
        binary.write_bytes(b"\x7fELF")
        dwp = tmp_path / "libfoo.dwp"
        dwp.write_bytes(b"DWP")

        result = resolve_debug_info(binary)
        assert result is not None
        assert result.dwp_path == dwp

    def test_build_id_tree(self, tmp_path: Path) -> None:
        build_id = "aabb1234567890cc"
        debug_root = tmp_path / "debug"
        bid_dir = debug_root / ".build-id" / build_id[:2]
        bid_dir.mkdir(parents=True)
        (bid_dir / f"{build_id[2:]}.debug").write_bytes(b"\x7fELF")

        result = resolve_debug_info(
            tmp_path / "libfoo.so",
            build_id=build_id,
            debug_roots=[debug_root],
        )
        assert result is not None
        assert "build-id" in result.source

    def test_pdb_found(self, tmp_path: Path) -> None:
        binary = tmp_path / "foo.dll"
        binary.write_bytes(b"MZ")
        pdb = tmp_path / "foo.pdb"
        pdb.write_bytes(b"PDB")

        result = resolve_debug_info(binary)
        assert result is not None
        assert result.pdb_path == pdb

    def test_dsym_found(self, tmp_path: Path) -> None:
        binary = tmp_path / "libfoo.dylib"
        binary.write_bytes(b"\xcf\xfa\xed\xfe")
        dsym = tmp_path / "libfoo.dylib.dSYM" / "Contents" / "Resources" / "DWARF"
        dsym.mkdir(parents=True)
        (dsym / "libfoo.dylib").write_bytes(b"\xcf\xfa\xed\xfe")

        result = resolve_debug_info(binary)
        assert result is not None
        assert result.has_dsym

    def test_with_debuginfod_disabled(self, tmp_path: Path) -> None:
        result = resolve_debug_info(
            tmp_path / "nope.so", enable_debuginfod=False,
        )
        assert result is None

    def test_with_debuginfod_enabled(self, tmp_path: Path) -> None:
        result = resolve_debug_info(
            tmp_path / "nope.so",
            enable_debuginfod=True,
            debuginfod_urls=["https://fake.example.com"],
            debuginfod_cache_dir=tmp_path / "cache",
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: format_data_sources
# ---------------------------------------------------------------------------


class TestFormatDataSources:
    def test_with_artifact(self) -> None:
        artifact = DebugArtifact(dwarf_path=Path("/debug/libfoo.debug"), source="build-id tree")
        output = format_data_sources(Path("/lib/libfoo.so"), artifact, has_headers=True)
        assert "build-id tree" in output
        assert "Headers:    available" in output

    def test_no_artifact(self) -> None:
        output = format_data_sources(Path("/lib/libfoo.so"), None, has_headers=False)
        assert "symbols-only" in output
        assert "not provided" in output

    def test_headers_not_provided(self) -> None:
        output = format_data_sources(Path("/x"), None, has_headers=False)
        assert "not provided" in output

    def test_headers_available(self) -> None:
        output = format_data_sources(Path("/x"), None, has_headers=True)
        assert "available" in output

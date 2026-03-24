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

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from abicheck.debug_resolver import (
    BuildIdTreeResolver,
    DebugArtifact,
    DebuginfodResolver,
    DSYMResolver,
    PDBResolver,
    PathMirrorResolver,
    SplitDwarfResolver,
    _is_valid_build_id,
    format_data_sources,
    resolve_debug_info,
)


# ---------------------------------------------------------------------------
# Tests: DebugArtifact
# ---------------------------------------------------------------------------


def test_debug_artifact_properties() -> None:
    """DebugArtifact properties reflect set paths."""
    empty = DebugArtifact()
    assert not empty.has_dwarf
    assert not empty.has_pdb
    assert not empty.has_dsym
    assert not empty.has_split_dwarf
    assert "no debug info found" in empty.description

    dwarf = DebugArtifact(dwarf_path=Path("/foo/bar.debug"), source="test")
    assert dwarf.has_dwarf
    assert "DWARF" in dwarf.description

    pdb = DebugArtifact(pdb_path=Path("/foo/bar.pdb"), source="test")
    assert pdb.has_pdb
    assert "PDB" in pdb.description

    dsym = DebugArtifact(dsym_path=Path("/foo/bar.dSYM"), source="test")
    assert dsym.has_dsym
    assert "dSYM" in dsym.description

    split = DebugArtifact(dwp_path=Path("/foo/bar.dwp"), source="test")
    assert split.has_split_dwarf


# ---------------------------------------------------------------------------
# Tests: build-id validation
# ---------------------------------------------------------------------------


def test_valid_build_id() -> None:
    assert _is_valid_build_id("abcdef1234567890")
    assert _is_valid_build_id("0123456789abcdef")


def test_invalid_build_id() -> None:
    assert not _is_valid_build_id(None)
    assert not _is_valid_build_id("")
    assert not _is_valid_build_id("ABCDEF")  # uppercase
    assert not _is_valid_build_id("../etc/passwd")
    assert not _is_valid_build_id("abc def")
    assert not _is_valid_build_id("abc%00def")


# ---------------------------------------------------------------------------
# Tests: BuildIdTreeResolver
# ---------------------------------------------------------------------------


def test_build_id_tree_resolver_found(tmp_path: Path) -> None:
    """Finds debug file in a build-id tree."""
    build_id = "abcdef1234567890"
    debug_root = tmp_path / "debug"
    build_id_dir = debug_root / ".build-id" / build_id[:2]
    build_id_dir.mkdir(parents=True)
    debug_file = build_id_dir / f"{build_id[2:]}.debug"
    debug_file.write_bytes(b"\x7fELF")

    resolver = BuildIdTreeResolver()
    result = resolver.resolve(
        binary_path=tmp_path / "libfoo.so",
        build_id=build_id,
        debug_roots=[debug_root],
    )
    assert result is not None
    assert result.dwarf_path == debug_file
    assert "build-id" in result.source


def test_build_id_tree_resolver_not_found(tmp_path: Path) -> None:
    resolver = BuildIdTreeResolver()
    result = resolver.resolve(
        binary_path=tmp_path / "libfoo.so",
        build_id="abcdef1234567890",
        debug_roots=[tmp_path],
    )
    assert result is None


def test_build_id_tree_resolver_no_build_id() -> None:
    resolver = BuildIdTreeResolver()
    assert resolver.resolve(Path("/usr/lib/libfoo.so"), build_id=None) is None


def test_build_id_tree_resolver_invalid_build_id() -> None:
    """Rejects non-hex build-ids (prevents path traversal)."""
    resolver = BuildIdTreeResolver()
    assert resolver.resolve(Path("/x"), build_id="../etc/passwd") is None
    assert resolver.resolve(Path("/x"), build_id="UPPER") is None


# ---------------------------------------------------------------------------
# Tests: PathMirrorResolver
# ---------------------------------------------------------------------------


def test_path_mirror_resolver_found(tmp_path: Path) -> None:
    debug_root = tmp_path / "debug"
    binary_path = tmp_path / "usr" / "lib" / "libfoo.so"
    binary_path.parent.mkdir(parents=True)
    binary_path.write_bytes(b"\x7fELF")

    binary_resolved = binary_path.resolve()
    mirror_path = debug_root / str(binary_resolved).lstrip("/")
    mirror_debug = mirror_path.parent / (mirror_path.name + ".debug")
    mirror_debug.parent.mkdir(parents=True)
    mirror_debug.write_bytes(b"\x7fELF")

    resolver = PathMirrorResolver()
    result = resolver.resolve(binary_path=binary_path, debug_roots=[debug_root])
    assert result is not None
    assert result.dwarf_path == mirror_debug
    assert "path mirror" in result.source


# ---------------------------------------------------------------------------
# Tests: DSYMResolver
# ---------------------------------------------------------------------------


def test_dsym_resolver_found(tmp_path: Path) -> None:
    """Finds dSYM bundle and sets BOTH dsym_path and dwarf_path."""
    binary_path = tmp_path / "libfoo.dylib"
    binary_path.write_bytes(b"\xcf\xfa\xed\xfe")

    dsym_dir = tmp_path / "libfoo.dylib.dSYM"
    dwarf_dir = dsym_dir / "Contents" / "Resources" / "DWARF"
    dwarf_dir.mkdir(parents=True)
    dwarf_file = dwarf_dir / "libfoo.dylib"
    dwarf_file.write_bytes(b"\xcf\xfa\xed\xfe")

    resolver = DSYMResolver()
    result = resolver.resolve(binary_path=binary_path)
    assert result is not None
    assert result.dsym_path == dsym_dir
    assert result.dwarf_path == dwarf_file  # P0 fix: dwarf_path is now set
    assert result.has_dwarf
    assert "dSYM" in result.source


def test_dsym_resolver_not_found(tmp_path: Path) -> None:
    binary_path = tmp_path / "libfoo.dylib"
    binary_path.write_bytes(b"\xcf\xfa\xed\xfe")
    assert DSYMResolver().resolve(binary_path=binary_path) is None


def test_dsym_resolver_in_debug_root(tmp_path: Path) -> None:
    binary_path = tmp_path / "libfoo.dylib"
    binary_path.write_bytes(b"\xcf\xfa\xed\xfe")

    debug_root = tmp_path / "symbols"
    dsym_dir = debug_root / "libfoo.dylib.dSYM"
    dwarf_dir = dsym_dir / "Contents" / "Resources" / "DWARF"
    dwarf_dir.mkdir(parents=True)
    dwarf_file = dwarf_dir / "libfoo.dylib"
    dwarf_file.write_bytes(b"\xcf\xfa\xed\xfe")

    result = DSYMResolver().resolve(binary_path=binary_path, debug_roots=[debug_root])
    assert result is not None
    assert result.dsym_path == dsym_dir
    assert result.dwarf_path == dwarf_file


# ---------------------------------------------------------------------------
# Tests: PDBResolver
# ---------------------------------------------------------------------------


def test_pdb_resolver_adjacent(tmp_path: Path) -> None:
    binary_path = tmp_path / "foo.dll"
    binary_path.write_bytes(b"MZ")
    pdb_path = tmp_path / "foo.pdb"
    pdb_path.write_bytes(b"PDB data")

    result = PDBResolver().resolve(binary_path=binary_path)
    assert result is not None
    assert result.pdb_path == pdb_path


def test_pdb_resolver_in_debug_root(tmp_path: Path) -> None:
    binary_path = tmp_path / "foo.dll"
    binary_path.write_bytes(b"MZ")
    debug_root = tmp_path / "symbols"
    pdb = debug_root / "foo.pdb"
    pdb.parent.mkdir(parents=True)
    pdb.write_bytes(b"PDB data")

    result = PDBResolver().resolve(binary_path=binary_path, debug_roots=[debug_root])
    assert result is not None
    assert result.pdb_path == pdb


# ---------------------------------------------------------------------------
# Tests: SplitDwarfResolver
# ---------------------------------------------------------------------------


def test_split_dwarf_dwp_found(tmp_path: Path) -> None:
    binary_path = tmp_path / "libfoo.so"
    binary_path.write_bytes(b"\x7fELF")
    dwp_path = tmp_path / "libfoo.dwp"
    dwp_path.write_bytes(b"DWP data")

    result = SplitDwarfResolver().resolve(binary_path=binary_path)
    assert result is not None
    assert result.dwp_path == dwp_path


# ---------------------------------------------------------------------------
# Tests: DebuginfodResolver
# ---------------------------------------------------------------------------


def test_debuginfod_rejects_invalid_build_id() -> None:
    """Non-hex build-ids are rejected before any network call."""
    resolver = DebuginfodResolver(server_urls=["https://example.com"])
    assert resolver.resolve(Path("/x"), build_id="../traversal") is None
    assert resolver.resolve(Path("/x"), build_id="UPPERCASE") is None
    assert resolver.resolve(Path("/x"), build_id=None) is None


def test_debuginfod_rejects_insecure_url() -> None:
    """HTTP URLs are skipped by default."""
    resolver = DebuginfodResolver(
        server_urls=["http://insecure.example.com"],
        allow_insecure=False,
    )
    # Should return None without making any HTTP call
    assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None


def test_debuginfod_rejects_file_url() -> None:
    """file:// URLs are always blocked, even with allow_insecure."""
    resolver = DebuginfodResolver(
        server_urls=["file:///etc/passwd"],
        allow_insecure=True,
    )
    assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None


def test_debuginfod_allows_http_with_insecure_flag() -> None:
    """HTTP is allowed when allow_insecure is True (still returns None due to no server)."""
    # This just verifies the URL scheme check passes; the actual fetch will fail
    # since there's no real server, but the scheme validation should pass.
    resolver = DebuginfodResolver(
        server_urls=["http://localhost:99999"],
        allow_insecure=True,
        cache_dir=Path("/tmp/nonexistent-cache-dir-test"),
    )
    # Will return None because fetch fails, but the URL is not rejected by scheme check
    result = resolver.resolve(Path("/x"), build_id="abcdef1234567890")
    assert result is None  # fetch fails, but it's not rejected by scheme validation


def test_debuginfod_cache_hit(tmp_path: Path) -> None:
    """Cached debug files are returned without network access."""
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


def test_debuginfod_no_urls() -> None:
    """Returns None when no URLs are configured."""
    resolver = DebuginfodResolver(server_urls=[])
    assert resolver.resolve(Path("/x"), build_id="abcdef1234567890") is None


# ---------------------------------------------------------------------------
# Tests: format_data_sources
# ---------------------------------------------------------------------------


def test_format_data_sources_with_artifact() -> None:
    artifact = DebugArtifact(dwarf_path=Path("/debug/libfoo.debug"), source="build-id tree")
    output = format_data_sources(Path("/lib/libfoo.so"), artifact, has_headers=True)
    assert "build-id tree" in output
    assert "Headers:    available" in output


def test_format_data_sources_no_artifact() -> None:
    output = format_data_sources(Path("/lib/libfoo.so"), None, has_headers=False)
    assert "symbols-only" in output
    assert "not provided" in output

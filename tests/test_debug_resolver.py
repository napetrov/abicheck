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

import pytest

from abicheck.debug_resolver import (
    BuildIdTreeResolver,
    DebugArtifact,
    DSYMResolver,
    PDBResolver,
    PathMirrorResolver,
    SplitDwarfResolver,
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
    """Returns None when build-id tree doesn't contain a match."""
    resolver = BuildIdTreeResolver()
    result = resolver.resolve(
        binary_path=tmp_path / "libfoo.so",
        build_id="abcdef1234567890",
        debug_roots=[tmp_path],
    )
    assert result is None


def test_build_id_tree_resolver_no_build_id() -> None:
    """Returns None when no build-id is provided."""
    resolver = BuildIdTreeResolver()
    result = resolver.resolve(
        binary_path=Path("/usr/lib/libfoo.so"),
        build_id=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Tests: PathMirrorResolver
# ---------------------------------------------------------------------------


def test_path_mirror_resolver_found(tmp_path: Path) -> None:
    """Finds debug file via path mirror convention."""
    debug_root = tmp_path / "debug"
    binary_path = tmp_path / "usr" / "lib" / "libfoo.so"
    binary_path.parent.mkdir(parents=True)
    binary_path.write_bytes(b"\x7fELF")

    # Create the mirrored debug file at debug_root + absolute_binary_path + .debug
    # The path mirror convention mirrors the full absolute path under the debug root
    binary_resolved = binary_path.resolve()
    mirror_path = debug_root / str(binary_resolved).lstrip("/")
    mirror_debug = mirror_path.parent / (mirror_path.name + ".debug")
    mirror_debug.parent.mkdir(parents=True)
    mirror_debug.write_bytes(b"\x7fELF")

    resolver = PathMirrorResolver()
    result = resolver.resolve(
        binary_path=binary_path,
        debug_roots=[debug_root],
    )
    assert result is not None
    assert result.dwarf_path == mirror_debug
    assert "path mirror" in result.source


# ---------------------------------------------------------------------------
# Tests: DSYMResolver
# ---------------------------------------------------------------------------


def test_dsym_resolver_found(tmp_path: Path) -> None:
    """Finds dSYM bundle adjacent to binary."""
    binary_path = tmp_path / "libfoo.dylib"
    binary_path.write_bytes(b"\xcf\xfa\xed\xfe")

    # Create dSYM bundle
    dsym_dir = tmp_path / "libfoo.dylib.dSYM"
    dwarf_dir = dsym_dir / "Contents" / "Resources" / "DWARF"
    dwarf_dir.mkdir(parents=True)
    (dwarf_dir / "libfoo.dylib").write_bytes(b"\xcf\xfa\xed\xfe")

    resolver = DSYMResolver()
    result = resolver.resolve(binary_path=binary_path)
    assert result is not None
    assert result.dsym_path == dsym_dir
    assert "dSYM" in result.source


def test_dsym_resolver_not_found(tmp_path: Path) -> None:
    """Returns None when no dSYM bundle exists."""
    binary_path = tmp_path / "libfoo.dylib"
    binary_path.write_bytes(b"\xcf\xfa\xed\xfe")

    resolver = DSYMResolver()
    result = resolver.resolve(binary_path=binary_path)
    assert result is None


def test_dsym_resolver_in_debug_root(tmp_path: Path) -> None:
    """Finds dSYM bundle in a debug root directory."""
    binary_path = tmp_path / "libfoo.dylib"
    binary_path.write_bytes(b"\xcf\xfa\xed\xfe")

    debug_root = tmp_path / "symbols"
    dsym_dir = debug_root / "libfoo.dylib.dSYM"
    dwarf_dir = dsym_dir / "Contents" / "Resources" / "DWARF"
    dwarf_dir.mkdir(parents=True)
    (dwarf_dir / "libfoo.dylib").write_bytes(b"\xcf\xfa\xed\xfe")

    resolver = DSYMResolver()
    result = resolver.resolve(
        binary_path=binary_path,
        debug_roots=[debug_root],
    )
    assert result is not None
    assert result.dsym_path == dsym_dir


# ---------------------------------------------------------------------------
# Tests: PDBResolver
# ---------------------------------------------------------------------------


def test_pdb_resolver_adjacent(tmp_path: Path) -> None:
    """Finds PDB adjacent to PE binary."""
    binary_path = tmp_path / "foo.dll"
    binary_path.write_bytes(b"MZ")

    pdb_path = tmp_path / "foo.pdb"
    pdb_path.write_bytes(b"PDB data")

    resolver = PDBResolver()
    result = resolver.resolve(binary_path=binary_path)
    assert result is not None
    assert result.pdb_path == pdb_path
    assert "adjacent" in result.source


def test_pdb_resolver_in_debug_root(tmp_path: Path) -> None:
    """Finds PDB in a debug root."""
    binary_path = tmp_path / "foo.dll"
    binary_path.write_bytes(b"MZ")

    debug_root = tmp_path / "symbols"
    pdb = debug_root / "foo.pdb"
    pdb.parent.mkdir(parents=True)
    pdb.write_bytes(b"PDB data")

    resolver = PDBResolver()
    result = resolver.resolve(
        binary_path=binary_path,
        debug_roots=[debug_root],
    )
    assert result is not None
    assert result.pdb_path == pdb


# ---------------------------------------------------------------------------
# Tests: SplitDwarfResolver
# ---------------------------------------------------------------------------


def test_split_dwarf_dwp_found(tmp_path: Path) -> None:
    """Finds .dwp file adjacent to binary."""
    binary_path = tmp_path / "libfoo.so"
    binary_path.write_bytes(b"\x7fELF")

    dwp_path = tmp_path / "libfoo.dwp"
    dwp_path.write_bytes(b"DWP data")

    resolver = SplitDwarfResolver()
    result = resolver.resolve(binary_path=binary_path)
    assert result is not None
    assert result.dwp_path == dwp_path
    assert "dwp" in result.source.lower()


# ---------------------------------------------------------------------------
# Tests: format_data_sources
# ---------------------------------------------------------------------------


def test_format_data_sources_with_artifact() -> None:
    """format_data_sources includes artifact info."""
    artifact = DebugArtifact(
        dwarf_path=Path("/debug/libfoo.debug"),
        source="build-id tree",
    )
    output = format_data_sources(Path("/lib/libfoo.so"), artifact, has_headers=True)
    assert "build-id tree" in output
    assert "Headers:    available" in output


def test_format_data_sources_no_artifact() -> None:
    """format_data_sources handles None artifact."""
    output = format_data_sources(Path("/lib/libfoo.so"), None, has_headers=False)
    assert "symbols-only" in output
    assert "not provided" in output

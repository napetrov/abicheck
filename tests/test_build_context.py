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

"""Tests for build_context.py — compile_commands.json ingestion (ADR-020)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abicheck.build_context import (
    BuildContext,
    CompileEntry,
    build_context_for_header,
    build_context_union_fallback,
    load_compile_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def compile_db_dir(tmp_path: Path) -> Path:
    """Create a minimal compile_commands.json in a tmp directory."""
    db = [
        {
            "directory": str(tmp_path / "build"),
            "file": "src/foo.cpp",
            "arguments": [
                "c++", "-std=c++17", "-DFOO_ENABLE_SSL=1",
                "-I/usr/include/openssl", "-Iinclude",
                "-fvisibility=hidden",
                "-c", "src/foo.cpp",
            ],
        },
        {
            "directory": str(tmp_path / "build"),
            "file": "src/bar.c",
            "command": "cc -std=c11 -DBAR_MODE=2 -Iinclude -c src/bar.c",
        },
    ]
    db_path = tmp_path / "build" / "compile_commands.json"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text(json.dumps(db))

    # Create source and header files for TU matching
    (tmp_path / "build" / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "build" / "src" / "foo.cpp").write_text(
        '#include "foo.h"\nvoid foo() {}\n'
    )
    (tmp_path / "build" / "src" / "bar.c").write_text(
        '#include "bar.h"\nvoid bar() {}\n'
    )
    (tmp_path / "build" / "include").mkdir(exist_ok=True)
    (tmp_path / "build" / "include" / "foo.h").write_text("void foo();\n")
    (tmp_path / "build" / "include" / "bar.h").write_text("void bar();\n")

    return tmp_path / "build"


# ---------------------------------------------------------------------------
# Tests: load_compile_db
# ---------------------------------------------------------------------------


def test_load_compile_db_from_dir(compile_db_dir: Path) -> None:
    """Loading from a directory finds compile_commands.json."""
    entries = load_compile_db(compile_db_dir)
    assert len(entries) == 2
    assert entries[0].arguments[0] == "c++"
    assert entries[1].file.name == "bar.c"


def test_load_compile_db_from_file(compile_db_dir: Path) -> None:
    """Loading from an explicit file path works."""
    entries = load_compile_db(compile_db_dir / "compile_commands.json")
    assert len(entries) == 2


def test_load_compile_db_missing(tmp_path: Path) -> None:
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_compile_db(tmp_path / "nonexistent")


def test_load_compile_db_invalid_json(tmp_path: Path) -> None:
    """Invalid JSON raises ValueError."""
    bad = tmp_path / "compile_commands.json"
    bad.write_text("not json")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_compile_db(bad)


def test_load_compile_db_not_array(tmp_path: Path) -> None:
    """Non-array JSON raises ValueError."""
    bad = tmp_path / "compile_commands.json"
    bad.write_text('{"key": "value"}')
    with pytest.raises(ValueError, match="JSON array"):
        load_compile_db(bad)


# ---------------------------------------------------------------------------
# Tests: CompileEntry
# ---------------------------------------------------------------------------


def test_compile_entry_arguments_form() -> None:
    """Entries with 'arguments' array parse correctly."""
    entry = CompileEntry.from_dict(
        {
            "directory": "/build",
            "file": "src/foo.cpp",
            "arguments": ["c++", "-std=c++17", "-DFOO=1", "-c", "src/foo.cpp"],
        },
        Path("/build"),
    )
    assert entry.file == Path("/build/src/foo.cpp").resolve()
    assert "-std=c++17" in entry.arguments


def test_compile_entry_command_form() -> None:
    """Entries with 'command' string are parsed via shlex."""
    entry = CompileEntry.from_dict(
        {
            "directory": "/build",
            "file": "src/bar.c",
            "command": "cc -std=c11 -DBAR=1 -c src/bar.c",
        },
        Path("/build"),
    )
    assert "-std=c11" in entry.arguments
    assert "-DBAR=1" in entry.arguments


# ---------------------------------------------------------------------------
# Tests: BuildContext flag extraction
# ---------------------------------------------------------------------------


def test_build_context_to_castxml_flags() -> None:
    """BuildContext generates correct CastXML flags."""
    ctx = BuildContext(
        defines={"FOO": "1", "BAR": None},
        include_paths=[Path("/usr/include")],
        system_includes=[Path("/usr/lib/include")],
        language_standard="c++17",
        target_triple="x86_64-linux-gnu",
        sysroot=Path("/sysroot"),
        extra_flags=["-fvisibility=hidden"],
    )
    flags = ctx.to_castxml_flags()
    assert "-std=c++17" in flags
    assert "--target=x86_64-linux-gnu" in flags
    assert "--sysroot=/sysroot" in flags
    assert "-DFOO=1" in flags
    assert "-DBAR" in flags
    assert "-fvisibility=hidden" in flags


def test_build_context_has_conflicts() -> None:
    """has_conflicts reflects conflict tracking."""
    ctx = BuildContext()
    assert not ctx.has_conflicts

    ctx.define_conflicts = {"FOO": ["1", "2"]}
    assert ctx.has_conflicts


# ---------------------------------------------------------------------------
# Tests: Union fallback
# ---------------------------------------------------------------------------


def test_union_fallback_merges_defines(compile_db_dir: Path) -> None:
    """Union fallback merges defines from all TUs."""
    entries = load_compile_db(compile_db_dir)
    ctx = build_context_union_fallback(entries)
    assert "FOO_ENABLE_SSL" in ctx.defines
    assert "BAR_MODE" in ctx.defines


def test_union_fallback_picks_highest_standard(compile_db_dir: Path) -> None:
    """Union fallback picks the highest C++ standard."""
    entries = load_compile_db(compile_db_dir)
    ctx = build_context_union_fallback(entries)
    # c++17 > c11, and c++17 is the highest C++ standard
    assert ctx.language_standard == "c++17"


def test_union_fallback_empty_entries() -> None:
    """Union fallback with no entries returns empty context."""
    ctx = build_context_union_fallback([])
    assert ctx.language_standard is None
    assert not ctx.defines


# ---------------------------------------------------------------------------
# Tests: Per-header TU matching
# ---------------------------------------------------------------------------


def test_per_header_matching(compile_db_dir: Path) -> None:
    """build_context_for_header matches foo.h to foo.cpp's TU."""
    entries = load_compile_db(compile_db_dir)
    header = compile_db_dir / "include" / "foo.h"
    ctx = build_context_for_header(entries, header)
    # Should get foo.cpp's defines (FOO_ENABLE_SSL) not bar.c's
    assert "FOO_ENABLE_SSL" in ctx.defines


def test_per_header_fallback_to_union(compile_db_dir: Path) -> None:
    """Unmatched header falls back to union strategy."""
    entries = load_compile_db(compile_db_dir)
    # Create a header that no TU includes
    unmatched = compile_db_dir / "include" / "baz.h"
    unmatched.write_text("void baz();\n")
    ctx = build_context_for_header(entries, unmatched)
    # Should have merged defines from both TUs
    assert "FOO_ENABLE_SSL" in ctx.defines
    assert "BAR_MODE" in ctx.defines


def test_source_filter(compile_db_dir: Path) -> None:
    """Source filter restricts which TUs are considered."""
    entries = load_compile_db(compile_db_dir)
    header = compile_db_dir / "include" / "bar.h"
    # Filter to only bar.c
    ctx = build_context_for_header(entries, header, source_filter="**/bar.c")
    assert "BAR_MODE" in ctx.defines

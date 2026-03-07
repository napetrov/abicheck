"""Integration tests for parse_elf_metadata() using real compiled .so files.

These tests compile minimal C shared libraries and verify the full
pyelftools parse round-trip: compile → parse_elf_metadata → assert fields.

Requires: gcc, available in CI.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from abicheck.elf_metadata import ElfMetadata, SymbolBinding, SymbolType, parse_elf_metadata

# ── helpers ────────────────────────────────────────────────────────────────

def _compile_so(src: str, name: str, tmp: Path, extra_flags: list[str] | None = None) -> Path:
    """Compile C source to a shared library; skip test if gcc unavailable."""
    gcc = ["gcc"] + (extra_flags or []) + ["-shared", "-fPIC", "-o", str(tmp / name), "-x", "c", "-"]
    result = subprocess.run(gcc, input=src.encode(), capture_output=True)
    if result.returncode != 0:
        pytest.skip(f"gcc failed: {result.stderr.decode()[:200]}")
    return tmp / name


# ── tests ──────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_parse_basic_so_symbols() -> None:
    """Real .so with two exported symbols → both appear in ElfMetadata.symbols."""
    src = """
    int foo(int x) { return x + 1; }
    int bar = 42;
    """
    with tempfile.TemporaryDirectory() as td:
        so = _compile_so(src, "libtest.so", Path(td))
        meta = parse_elf_metadata(so)

    assert isinstance(meta, ElfMetadata)
    names = {s.name for s in meta.symbols}
    assert "foo" in names, f"Expected 'foo' in symbols, got: {names}"
    assert "bar" in names, f"Expected 'bar' in symbols, got: {names}"

    # foo should be STT_FUNC
    foo_sym = next(s for s in meta.symbols if s.name == "foo")
    assert foo_sym.sym_type == SymbolType.FUNC
    assert foo_sym.binding == SymbolBinding.GLOBAL

    # bar should be STT_OBJECT
    bar_sym = next(s for s in meta.symbols if s.name == "bar")
    assert bar_sym.sym_type == SymbolType.OBJECT
    assert bar_sym.size > 0


@pytest.mark.integration
def test_parse_so_with_soname() -> None:
    """Library compiled with -soname → SONAME captured."""
    src = "int fn(void) { return 0; }"
    with tempfile.TemporaryDirectory() as td:
        so = _compile_so(src, "libsoname.so", Path(td),
                         extra_flags=["-Wl,-soname,libsoname.so.1"])
        meta = parse_elf_metadata(so)

    assert meta.soname == "libsoname.so.1", f"Expected soname, got: {meta.soname!r}"


@pytest.mark.integration
def test_parse_stripped_so_returns_metadata() -> None:
    """Stripped .so (no debug info) must still parse — no crash, symbols present."""
    src = "int stripped_fn(int x) { return x * 2; }"
    with tempfile.TemporaryDirectory() as td:
        so = _compile_so(src, "libstripped.so", Path(td))
        subprocess.run(["strip", str(so)], capture_output=True)  # strip debug info
        meta = parse_elf_metadata(so)

    assert isinstance(meta, ElfMetadata)
    # .dynsym survives strip; debug sections go away
    names = {s.name for s in meta.symbols}
    assert "stripped_fn" in names, f"Expected symbol after strip, got: {names}"


@pytest.mark.integration
def test_parse_so_with_needed() -> None:
    """Library with DT_NEEDED (linked against libc) → needed list non-empty."""
    src = "#include <stdlib.h>\nvoid* fn(size_t n) { return malloc(n); }"
    with tempfile.TemporaryDirectory() as td:
        so = _compile_so(src, "libneeded.so", Path(td), extra_flags=["-lc"])
        meta = parse_elf_metadata(so)

    # libc.so.6 (or similar) should appear in needed
    assert len(meta.needed) > 0, "Expected at least one DT_NEEDED entry"
    assert any("libc" in n for n in meta.needed), f"Expected libc in needed: {meta.needed}"


@pytest.mark.integration
def test_parse_hidden_symbols_excluded() -> None:
    """Hidden-visibility symbols must NOT appear in ElfMetadata.symbols."""
    src = """
    __attribute__((visibility("hidden"))) int hidden_fn(void) { return 1; }
    __attribute__((visibility("default"))) int public_fn(void) { return 2; }
    """
    with tempfile.TemporaryDirectory() as td:
        so = _compile_so(src, "libvisibility.so", Path(td))
        meta = parse_elf_metadata(so)

    names = {s.name for s in meta.symbols}
    assert "public_fn" in names, f"Expected public_fn, got: {names}"
    assert "hidden_fn" not in names, f"hidden_fn must be excluded, got: {names}"


@pytest.mark.integration
def test_parse_nonexistent_path_returns_empty() -> None:
    """Non-existent path → empty ElfMetadata, no exception."""
    meta = parse_elf_metadata(Path("/nonexistent/path/libfoo.so"))
    assert isinstance(meta, ElfMetadata)
    assert meta.symbols == []
    assert meta.soname == ""


@pytest.mark.integration
def test_parse_non_elf_file_returns_empty(tmp_path: Path) -> None:
    """Non-ELF file (plain text) → empty ElfMetadata, no exception."""
    bad = tmp_path / "notanelf.so"
    bad.write_text("this is not an ELF binary\n")
    meta = parse_elf_metadata(bad)
    assert isinstance(meta, ElfMetadata)
    assert meta.symbols == []

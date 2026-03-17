"""Tests for ADR-003 DwarfSnapshotBuilder and data source architecture."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from abicheck.dwarf_metadata import DwarfMetadata, EnumInfo, FieldInfo, StructLayout
from abicheck.dwarf_advanced import AdvancedDwarfMetadata
from abicheck.dwarf_snapshot import (
    _strip_type_decorators,
    build_snapshot_from_dwarf,
    show_data_sources,
)
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType
from abicheck.model import AbiSnapshot, Visibility


# ── helpers ──────────────────────────────────────────────────────────────────

def _elf_meta_with_symbols(names: list[str]) -> ElfMetadata:
    """Create ElfMetadata with exported symbols."""
    return ElfMetadata(
        soname="libtest.so.1",
        symbols=[
            ElfSymbol(
                name=name,
                binding=SymbolBinding.GLOBAL,
                sym_type=SymbolType.FUNC,
            )
            for name in names
        ],
    )


def _elf_meta_with_objects(func_names: list[str], obj_names: list[str]) -> ElfMetadata:
    """Create ElfMetadata with both function and object symbols."""
    symbols = [
        ElfSymbol(name=n, binding=SymbolBinding.GLOBAL, sym_type=SymbolType.FUNC)
        for n in func_names
    ] + [
        ElfSymbol(name=n, binding=SymbolBinding.GLOBAL, sym_type=SymbolType.OBJECT)
        for n in obj_names
    ]
    return ElfMetadata(soname="libtest.so.1", symbols=symbols)


def _dwarf_meta(**kwargs: object) -> DwarfMetadata:
    m = DwarfMetadata(has_dwarf=True)
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _dwarf_adv() -> AdvancedDwarfMetadata:
    return AdvancedDwarfMetadata(has_dwarf=True)


# ── _strip_type_decorators ──────────────────────────────────────────────────

class TestStripTypeDecorators:
    def test_pointer(self) -> None:
        assert _strip_type_decorators("int *") == "int"

    def test_double_pointer(self) -> None:
        assert _strip_type_decorators("char **") == "char"

    def test_reference(self) -> None:
        assert _strip_type_decorators("Foo &") == "Foo"

    def test_rvalue_ref(self) -> None:
        assert _strip_type_decorators("Foo &&") == "Foo"

    def test_const(self) -> None:
        assert _strip_type_decorators("const int") == "int"

    def test_volatile(self) -> None:
        assert _strip_type_decorators("volatile int") == "int"

    def test_array(self) -> None:
        assert _strip_type_decorators("int[]") == "int"

    def test_plain_type(self) -> None:
        assert _strip_type_decorators("MyStruct") == "MyStruct"

    def test_combined(self) -> None:
        assert _strip_type_decorators("const Foo *") == "Foo"


# ── show_data_sources ───────────────────────────────────────────────────────

class TestShowDataSources:
    def test_all_layers(self) -> None:
        elf = _elf_meta_with_symbols(["foo", "bar"])
        dwarf = _dwarf_meta(structs={"S": StructLayout("S", 8)})
        output = show_data_sources(Path("libtest.so"), elf, dwarf, has_headers=True)
        assert "L0 Binary metadata: ELF" in output
        assert "L1 Debug info:      DWARF" in output
        assert "L2 Header AST:      available" in output
        assert "Headers mode (30/30 detectors" in output

    def test_dwarf_only_mode(self) -> None:
        elf = _elf_meta_with_symbols(["foo"])
        dwarf = _dwarf_meta()
        output = show_data_sources(Path("libtest.so"), elf, dwarf, has_headers=False)
        assert "DWARF-only mode" in output
        assert "#define constants" in output

    def test_symbols_only_mode(self) -> None:
        elf = _elf_meta_with_symbols(["foo"])
        output = show_data_sources(Path("libtest.so"), elf, None, has_headers=False)
        assert "Symbols-only mode" in output

    def test_no_elf_meta(self) -> None:
        output = show_data_sources(Path("libtest.so"), None, None, has_headers=False)
        assert "not available" in output


# ── build_snapshot_from_dwarf (integration via real ELF) ────────────────────

# Helper to compile a minimal C shared library with debug info
_GCC = "gcc"


def _can_compile() -> bool:
    """Check if GCC is available for integration tests."""
    try:
        result = subprocess.run(
            [_GCC, "--version"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


_HAS_GCC = _can_compile()


@pytest.mark.skipif(not _HAS_GCC, reason="GCC not available")
class TestDwarfSnapshotIntegration:
    """Integration tests: compile real .so with debug info, build snapshot from DWARF."""

    @pytest.fixture()
    def simple_lib(self, tmp_path: Path) -> Path:
        """Compile a simple C library with exported function and struct."""
        c_src = tmp_path / "lib.c"
        c_src.write_text("""\
typedef struct {
    int x;
    int y;
} Point;

typedef enum {
    RED = 0,
    GREEN = 1,
    BLUE = 2,
} Color;

int global_var = 42;

int add(int a, int b) {
    return a + b;
}

Point make_point(int x, int y) {
    Point p = {x, y};
    return p;
}

Color get_color(int idx) {
    return (Color)idx;
}

static int internal_func(int x) {
    return x * 2;
}
""")
        so_path = tmp_path / "libtest.so"
        result = subprocess.run(
            [_GCC, "-shared", "-fPIC", "-g", "-o", str(so_path), str(c_src)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Compilation failed: {result.stderr}"
        return so_path

    def test_snapshot_has_functions(self, simple_lib: Path) -> None:
        """DWARF snapshot should contain exported functions."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        assert snap.elf_only_mode is False
        assert snap.platform == "elf"
        func_names = {f.name for f in snap.functions}
        # Exported functions should be present
        assert "add" in func_names
        assert "make_point" in func_names
        # Static/internal functions should NOT be present
        assert "internal_func" not in func_names

    def test_snapshot_has_types(self, simple_lib: Path) -> None:
        """DWARF snapshot should contain struct types."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        type_names = {t.name for t in snap.types}
        assert "Point" in type_names

    def test_snapshot_has_enums(self, simple_lib: Path) -> None:
        """DWARF snapshot should contain enum types."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        enum_names = {e.name for e in snap.enums}
        assert "Color" in enum_names
        color_enum = next(e for e in snap.enums if e.name == "Color")
        member_names = {m.name for m in color_enum.members}
        assert "RED" in member_names
        assert "GREEN" in member_names
        assert "BLUE" in member_names

    def test_snapshot_has_variables(self, simple_lib: Path) -> None:
        """DWARF snapshot should contain exported variables."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        var_names = {v.name for v in snap.variables}
        assert "global_var" in var_names

    def test_function_params(self, simple_lib: Path) -> None:
        """DWARF snapshot functions should have parameter information."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        add_func = next((f for f in snap.functions if f.name == "add"), None)
        assert add_func is not None
        assert add_func.return_type != "?"
        assert len(add_func.params) == 2

    def test_function_visibility_is_public(self, simple_lib: Path) -> None:
        """Exported functions should have PUBLIC visibility."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        for func in snap.functions:
            assert func.visibility == Visibility.PUBLIC

    def test_snapshot_json_roundtrip(self, simple_lib: Path, tmp_path: Path) -> None:
        """DWARF snapshot should serialize/deserialize via JSON."""
        from abicheck.dwarf_unified import parse_dwarf
        from abicheck.elf_metadata import parse_elf_metadata
        from abicheck.serialization import load_snapshot, snapshot_to_json

        elf_meta = parse_elf_metadata(simple_lib)
        dwarf_meta, dwarf_adv = parse_dwarf(simple_lib)

        snap = build_snapshot_from_dwarf(
            simple_lib, elf_meta, dwarf_meta, dwarf_adv,
        )

        json_path = tmp_path / "snap.json"
        json_path.write_text(snapshot_to_json(snap), encoding="utf-8")
        loaded = load_snapshot(json_path)
        assert loaded.library == snap.library
        assert len(loaded.functions) == len(snap.functions)


# ── Dumper fallback chain tests ─────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_GCC, reason="GCC not available")
class TestDumperFallbackChain:
    """Test the ADR-003 fallback chain in dumper.py."""

    @pytest.fixture()
    def debug_lib(self, tmp_path: Path) -> Path:
        """Compile a library WITH debug info (DWARF available)."""
        c_src = tmp_path / "lib.c"
        c_src.write_text("int exported_func(int x) { return x + 1; }\n")
        so_path = tmp_path / "libtest.so"
        subprocess.run(
            [_GCC, "-shared", "-fPIC", "-g", "-o", str(so_path), str(c_src)],
            capture_output=True, check=True, timeout=30,
        )
        return so_path

    @pytest.fixture()
    def stripped_lib(self, tmp_path: Path) -> Path:
        """Compile a library WITHOUT debug info (no DWARF)."""
        c_src = tmp_path / "lib.c"
        c_src.write_text("int exported_func(int x) { return x + 1; }\n")
        so_path = tmp_path / "libtest.so"
        # -g0 disables all debug info; -Wl,--build-id=none prevents build-id note
        subprocess.run(
            [_GCC, "-shared", "-fPIC", "-g0", "-o", str(so_path), str(c_src)],
            capture_output=True, check=True, timeout=30,
        )
        # Strip all sections including debug
        subprocess.run(
            ["strip", "--strip-all", "--remove-section=.debug*",
             "--remove-section=.note.gnu.build-id", str(so_path)],
            capture_output=True, timeout=10,
        )
        return so_path

    def test_no_headers_with_dwarf_uses_dwarf_mode(self, debug_lib: Path) -> None:
        """No headers + DWARF available → DWARF-only mode (elf_only_mode=False)."""
        from abicheck.dumper import dump

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            snap = dump(so_path=debug_lib, headers=[])

        assert snap.elf_only_mode is False
        assert snap.platform == "elf"
        # Should have extracted function info from DWARF
        func_names = {f.name for f in snap.functions}
        assert "exported_func" in func_names

    def test_no_headers_no_dwarf_uses_symbol_mode(self, stripped_lib: Path) -> None:
        """No headers + no DWARF → symbols-only mode (elf_only_mode=True)."""
        from abicheck.dumper import dump

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            snap = dump(so_path=stripped_lib, headers=[])

        assert snap.elf_only_mode is True

    def test_dwarf_only_flag(self, debug_lib: Path) -> None:
        """--dwarf-only flag forces DWARF mode even without headers."""
        from abicheck.dumper import dump

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            snap = dump(so_path=debug_lib, headers=[], dwarf_only=True)

        assert snap.elf_only_mode is False


# ── CLI tests ───────────────────────────────────────────────────────────────

class TestCLIDwarfFlags:
    """Test CLI --dwarf-only and --show-data-sources flags exist and are accepted."""

    def test_dump_help_shows_dwarf_only(self) -> None:
        """dump --help should mention --dwarf-only."""
        result = subprocess.run(
            [sys.executable, "-c", "from abicheck.cli import main; main()", "dump", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "--dwarf-only" in result.stdout

    def test_dump_help_shows_data_sources(self) -> None:
        """dump --help should mention --show-data-sources."""
        result = subprocess.run(
            [sys.executable, "-c", "from abicheck.cli import main; main()", "dump", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "--show-data-sources" in result.stdout

    def test_compare_help_shows_dwarf_only(self) -> None:
        """compare --help should mention --dwarf-only."""
        result = subprocess.run(
            [sys.executable, "-c", "from abicheck.cli import main; main()", "compare", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "--dwarf-only" in result.stdout

    @pytest.mark.skipif(not _HAS_GCC, reason="GCC not available")
    def test_show_data_sources_output(self, tmp_path: Path) -> None:
        """--show-data-sources should print diagnostic info and exit."""
        c_src = tmp_path / "lib.c"
        c_src.write_text("int foo(void) { return 0; }\n")
        so_path = tmp_path / "libtest.so"
        subprocess.run(
            [_GCC, "-shared", "-fPIC", "-g", "-o", str(so_path), str(c_src)],
            capture_output=True, check=True, timeout=30,
        )
        result = subprocess.run(
            [sys.executable, "-c", "from abicheck.cli import main; main()", "dump", str(so_path),
             "--show-data-sources"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "Data sources for" in result.stdout
        assert "L0 Binary metadata" in result.stdout

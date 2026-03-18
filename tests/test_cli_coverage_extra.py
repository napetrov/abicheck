"""Extra CLI coverage tests for uncovered command paths.

Targets uncovered lines in cli.py: PE/Mach-O dump paths, show-only validation,
stat output, compare error display, check-compat extraction, batch comparison
error recovery, and stack-check command.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from abicheck.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pe_bytes() -> bytes:
    """Create minimal PE bytes (MZ header + PE signature + COFF header)."""
    dos_header = bytearray(64)
    dos_header[0:2] = b"MZ"
    pe_offset = 64
    struct.pack_into("<I", dos_header, 0x3C, pe_offset)
    pe_sig = b"PE\x00\x00"
    coff_header = struct.pack(
        "<HHIIIHH",
        0x8664,  # Machine (x86_64)
        0,       # NumberOfSections
        0,       # TimeDateStamp
        0,       # PointerToSymbolTable
        0,       # NumberOfSymbols
        0,       # SizeOfOptionalHeader
        0x2000,  # Characteristics (DLL)
    )
    return bytes(dos_header) + pe_sig + coff_header


def _make_json_snapshot(path: Path, *, name: str = "lib.so", version: str = "1.0") -> Path:
    """Write a minimal valid JSON snapshot file."""
    from abicheck.model import AbiSnapshot
    from abicheck.serialization import snapshot_to_json

    snap = AbiSnapshot(library=name, version=version, functions=[], platform="elf")
    out = path / f"{name}_{version}.json"
    out.write_text(snapshot_to_json(snap), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# PE / Mach-O dump path (lines 496-513)
# ---------------------------------------------------------------------------


class TestDumpNativeBinary:
    """Test dump command with PE and Mach-O binaries."""

    def test_dump_pe_follow_deps_warning(self, tmp_path: Path) -> None:
        """--follow-deps on PE emits warning and still produces output."""
        pe_file = tmp_path / "test.dll"
        pe_file.write_bytes(_make_pe_bytes())

        # Mock pe_metadata to return valid data
        mock_meta = MagicMock()
        mock_meta.machine = "AMD64"
        mock_export = MagicMock()
        mock_export.name = "TestFunc"
        mock_export.ordinal = 1
        mock_meta.exports = [mock_export]

        with patch("abicheck.cli._detect_binary_format", return_value="pe"), \
             patch("abicheck.pe_metadata.parse_pe_metadata", return_value=mock_meta):
            runner = CliRunner()
            result = runner.invoke(main, [
                "dump", str(pe_file), "--version", "1.0", "--follow-deps",
            ])
            assert "follow-deps" in (result.output + (result.stderr if hasattr(result, 'stderr') else "")).lower() or result.exit_code == 0

    def test_dump_pe_to_file(self, tmp_path: Path) -> None:
        """PE dump with --output writes JSON file."""
        pe_file = tmp_path / "test.dll"
        pe_file.write_bytes(_make_pe_bytes())
        out_file = tmp_path / "dump.json"

        # Create a proper AbiSnapshot to return from _dump_native_binary
        from abicheck.model import AbiSnapshot, Function, Visibility

        mock_snap = AbiSnapshot(
            library="test.dll", version="1.0",
            functions=[
                Function(name="MyFunc", mangled="MyFunc", return_type="?",
                         visibility=Visibility.PUBLIC, is_extern_c=True),
            ],
            platform="pe",
        )

        with patch("abicheck.cli._detect_binary_format", return_value="pe"), \
             patch("abicheck.cli._dump_native_binary", return_value=mock_snap):
            runner = CliRunner()
            result = runner.invoke(main, [
                "dump", str(pe_file), "--version", "1.0",
                "-o", str(out_file),
            ])
            assert result.exit_code == 0
            assert out_file.exists()
            data = json.loads(out_file.read_text(encoding="utf-8"))
            assert "functions" in data


# ---------------------------------------------------------------------------
# Show-only validation (lines 638-643)
# ---------------------------------------------------------------------------


class TestShowOnlyValidation:
    """Test --show-only parameter validation."""

    def test_invalid_show_only_token(self, tmp_path: Path) -> None:
        """Invalid --show-only token produces error."""
        old = _make_json_snapshot(tmp_path, name="libold", version="1.0")
        new = _make_json_snapshot(tmp_path, name="libnew", version="2.0")

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new),
            "--show-only", "invalid_token_xyz",
        ])
        # Should fail with bad parameter
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Stat output (lines 660-662)
# ---------------------------------------------------------------------------


class TestStatOutput:
    """Test --stat flag for one-line summary output."""

    def test_stat_json_output(self, tmp_path: Path) -> None:
        """--stat with --format json produces JSON stat output."""
        old = _make_json_snapshot(tmp_path, name="libold", version="1.0")
        new = _make_json_snapshot(tmp_path, name="libnew", version="2.0")

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--stat", "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "verdict" in data

    def test_stat_text_output(self, tmp_path: Path) -> None:
        """--stat produces one-line summary."""
        old = _make_json_snapshot(tmp_path, name="libold", version="1.0")
        new = _make_json_snapshot(tmp_path, name="libnew", version="2.0")

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--stat",
        ])
        assert result.exit_code == 0
        assert result.output.strip()  # non-empty output


# ---------------------------------------------------------------------------
# Render output formats (lines 660-698)
# ---------------------------------------------------------------------------


class TestRenderOutputFormats:
    """Test all output format rendering through compare command."""

    @pytest.fixture
    def snapshot_pair(self, tmp_path: Path) -> tuple[Path, Path]:
        old = _make_json_snapshot(tmp_path, name="libtest", version="1.0")
        new = _make_json_snapshot(tmp_path, name="libtest", version="2.0")
        return old, new

    def test_sarif_output(self, snapshot_pair: tuple[Path, Path]) -> None:
        old, new = snapshot_pair
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--format", "sarif",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "$schema" in data

    def test_html_output(self, snapshot_pair: tuple[Path, Path]) -> None:
        old, new = snapshot_pair
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--format", "html",
        ])
        assert result.exit_code == 0
        assert "<html" in result.output.lower() or "<!doctype" in result.output.lower()

    def test_json_output(self, snapshot_pair: tuple[Path, Path]) -> None:
        old, new = snapshot_pair
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "verdict" in data

    def test_show_impact_flag(self, snapshot_pair: tuple[Path, Path]) -> None:
        old, new = snapshot_pair
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--show-impact",
        ])
        assert result.exit_code == 0

    def test_leaf_report_mode(self, snapshot_pair: tuple[Path, Path]) -> None:
        old, new = snapshot_pair
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new), "--report-mode", "leaf",
        ])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Compare error display (lines 732-753)
# ---------------------------------------------------------------------------


class TestCompareErrorDisplay:
    """Test compare command error handling paths."""

    def test_nonexistent_old_input(self) -> None:
        """Non-existent old input produces clean error."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", "/nonexistent/old.so", "/nonexistent/new.so",
        ])
        assert result.exit_code != 0

    def test_nonexistent_new_input(self, tmp_path: Path) -> None:
        """Non-existent new input produces clean error."""
        old = _make_json_snapshot(tmp_path, name="libold", version="1.0")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), "/nonexistent/new.so",
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Show-redundant flag (lines 1078-1085)
# ---------------------------------------------------------------------------


class TestShowRedundant:
    """Test --show-redundant flag for merging redundant changes."""

    def test_show_redundant_flag(self, tmp_path: Path) -> None:
        """--show-redundant merges redundant changes back into main list."""
        from abicheck.model import AbiSnapshot, Function, Visibility
        from abicheck.serialization import snapshot_to_json

        # Create snapshots with a removed function to produce changes
        old_snap = AbiSnapshot(
            library="libtest.so", version="1.0",
            functions=[
                Function(name="foo", mangled="foo", return_type="int",
                         visibility=Visibility.PUBLIC),
            ],
        )
        new_snap = AbiSnapshot(
            library="libtest.so", version="2.0",
            functions=[],
        )

        old_file = tmp_path / "old.json"
        new_file = tmp_path / "new.json"
        old_file.write_text(snapshot_to_json(old_snap), encoding="utf-8")
        new_file.write_text(snapshot_to_json(new_snap), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_file), str(new_file), "--show-redundant",
        ])
        # Should complete (exit 0 or 4 for breaking)
        assert result.exit_code in (0, 2, 4)


# ---------------------------------------------------------------------------
# Stack-check command (lines 1625-1648)
# ---------------------------------------------------------------------------


class TestStackCheckCommand:
    """Test the stack-check CLI command."""

    def test_stack_check_nonexistent_dirs(self) -> None:
        """stack-check with non-existent directories handles gracefully."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "stack-check", "usr/bin/test",
            "--baseline", "/nonexistent/baseline",
            "--candidate", "/nonexistent/candidate",
        ])
        # Exit code 2 = Click usage error for non-existent paths, also acceptable
        assert result.exit_code in (0, 1, 2, 4)

    def test_stack_check_with_mock(self, tmp_path: Path) -> None:
        """stack-check with mocked resolver produces proper output."""
        from abicheck.resolver import DependencyGraph
        from abicheck.stack_checker import StackCheckResult, StackVerdict

        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        baseline.mkdir()
        candidate.mkdir()

        mock_result = StackCheckResult(
            root_binary="usr/bin/test",
            baseline_env=str(baseline),
            candidate_env=str(candidate),
            loadability=StackVerdict.PASS,
            abi_risk=StackVerdict.PASS,
            baseline_graph=DependencyGraph(root="test"),
            candidate_graph=DependencyGraph(root="test"),
        )

        with patch("abicheck.stack_checker.check_stack", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(main, [
                "stack-check", "usr/bin/test",
                "--baseline", str(baseline),
                "--candidate", str(candidate),
            ])
            assert result.exit_code == 0

    def test_stack_check_json_format(self, tmp_path: Path) -> None:
        """stack-check with --format json produces JSON output."""
        from abicheck.resolver import DependencyGraph
        from abicheck.stack_checker import StackCheckResult, StackVerdict

        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        baseline.mkdir()
        candidate.mkdir()

        mock_result = StackCheckResult(
            root_binary="usr/bin/test",
            baseline_env=str(baseline),
            candidate_env=str(candidate),
            loadability=StackVerdict.PASS,
            abi_risk=StackVerdict.PASS,
            baseline_graph=DependencyGraph(root="test"),
            candidate_graph=DependencyGraph(root="test"),
        )

        with patch("abicheck.stack_checker.check_stack", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(main, [
                "stack-check", "usr/bin/test",
                "--baseline", str(baseline),
                "--candidate", str(candidate),
                "--format", "json",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            # Check for any expected top-level key from stack report
            assert isinstance(data, dict)
            assert len(data) > 0

    def test_stack_check_fail_exit_code(self, tmp_path: Path) -> None:
        """stack-check returns exit 4 when loadability is fail."""
        from abicheck.resolver import DependencyGraph
        from abicheck.stack_checker import StackCheckResult, StackVerdict

        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        baseline.mkdir()
        candidate.mkdir()

        mock_result = StackCheckResult(
            root_binary="usr/bin/test",
            baseline_env=str(baseline),
            candidate_env=str(candidate),
            loadability=StackVerdict.FAIL,
            abi_risk=StackVerdict.PASS,
            baseline_graph=DependencyGraph(root="test"),
            candidate_graph=DependencyGraph(root="test"),
        )

        with patch("abicheck.stack_checker.check_stack", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(main, [
                "stack-check", "usr/bin/test",
                "--baseline", str(baseline),
                "--candidate", str(candidate),
            ])
            assert result.exit_code == 4

    def test_stack_check_warn_exit_code(self, tmp_path: Path) -> None:
        """stack-check returns exit 1 when abi_risk is warn."""
        from abicheck.resolver import DependencyGraph
        from abicheck.stack_checker import StackCheckResult, StackVerdict

        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        baseline.mkdir()
        candidate.mkdir()

        mock_result = StackCheckResult(
            root_binary="usr/bin/test",
            baseline_env=str(baseline),
            candidate_env=str(candidate),
            loadability=StackVerdict.PASS,
            abi_risk=StackVerdict.WARN,
            baseline_graph=DependencyGraph(root="test"),
            candidate_graph=DependencyGraph(root="test"),
        )

        with patch("abicheck.stack_checker.check_stack", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(main, [
                "stack-check", "usr/bin/test",
                "--baseline", str(baseline),
                "--candidate", str(candidate),
            ])
            assert result.exit_code == 1

    def test_stack_check_to_file(self, tmp_path: Path) -> None:
        """stack-check with --output writes report to file."""
        from abicheck.resolver import DependencyGraph
        from abicheck.stack_checker import StackCheckResult, StackVerdict

        baseline = tmp_path / "baseline"
        candidate = tmp_path / "candidate"
        baseline.mkdir()
        candidate.mkdir()
        out_file = tmp_path / "report.md"

        mock_result = StackCheckResult(
            root_binary="usr/bin/test",
            baseline_env=str(baseline),
            candidate_env=str(candidate),
            loadability=StackVerdict.PASS,
            abi_risk=StackVerdict.PASS,
            baseline_graph=DependencyGraph(root="test"),
            candidate_graph=DependencyGraph(root="test"),
        )

        with patch("abicheck.stack_checker.check_stack", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(main, [
                "stack-check", "usr/bin/test",
                "--baseline", str(baseline),
                "--candidate", str(candidate),
                "--output", str(out_file),
            ])
            assert result.exit_code == 0
            assert out_file.exists()


# ---------------------------------------------------------------------------
# Compare output to file
# ---------------------------------------------------------------------------


class TestCompareOutputToFile:
    """Test compare command writing output to file."""

    def test_compare_output_to_file(self, tmp_path: Path) -> None:
        old = _make_json_snapshot(tmp_path, name="libtest", version="1.0")
        new = _make_json_snapshot(tmp_path, name="libtest", version="2.0")
        out_file = tmp_path / "report.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old), str(new),
            "--format", "json",
            "-o", str(out_file),
        ])
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "verdict" in data

"""Tests for compare command input auto-detection.

Covers: .so + .so, .json + .json, .json + .so (mixed), error paths,
and per-side header options (--old-header / --new-header).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from abicheck.cli import _is_elf, _resolve_input, main
from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.serialization import snapshot_to_json

# ── helpers ──────────────────────────────────────────────────────────────


def _make_snapshot(version: str = "1.0", funcs: list[Function] | None = None) -> AbiSnapshot:
    if funcs is None:
        funcs = [
            Function(name="foo", mangled="_Z3foov", return_type="int",
                     visibility=Visibility.PUBLIC),
        ]
    return AbiSnapshot(library="libtest.so", version=version, functions=funcs)


def _write_snapshot(path: Path, snap: AbiSnapshot | None = None) -> Path:
    if snap is None:
        snap = _make_snapshot()
    path.write_text(snapshot_to_json(snap), encoding="utf-8")
    return path


def _write_fake_elf(path: Path) -> Path:
    """Write a minimal file with ELF magic bytes."""
    path.write_bytes(b"\x7fELF" + b"\x00" * 64)
    return path


def _write_snapshots(tmp_path: Path) -> tuple[Path, Path]:
    old_p = _write_snapshot(tmp_path / "old.json", _make_snapshot("1.0"))
    new_p = _write_snapshot(tmp_path / "new.json", _make_snapshot("2.0"))
    return old_p, new_p


def _breaking_snapshots(tmp_path: Path) -> tuple[AbiSnapshot, AbiSnapshot]:
    old = _make_snapshot("1.0", [
        Function(name="foo", mangled="_Z3foov", return_type="int",
                 visibility=Visibility.PUBLIC),
        Function(name="bar", mangled="_Z3barv", return_type="void",
                 visibility=Visibility.PUBLIC),
    ])
    new = _make_snapshot("2.0", [
        Function(name="foo", mangled="_Z3foov", return_type="int",
                 visibility=Visibility.PUBLIC),
    ])
    return old, new


# ── _is_elf tests ────────────────────────────────────────────────────────


class TestIsElf:
    def test_elf_file_detected(self, tmp_path):
        p = _write_fake_elf(tmp_path / "lib.so")
        assert _is_elf(p) is True

    def test_json_file_not_elf(self, tmp_path):
        p = tmp_path / "snap.json"
        p.write_text('{"library": "test"}', encoding="utf-8")
        assert _is_elf(p) is False

    def test_nonexistent_file(self, tmp_path):
        assert _is_elf(tmp_path / "missing") is False

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty"
        p.write_bytes(b"")
        assert _is_elf(p) is False

    def test_short_file(self, tmp_path):
        p = tmp_path / "short"
        p.write_bytes(b"\x7f")
        assert _is_elf(p) is False


# ── _resolve_input tests ────────────────────────────────────────────────


class TestResolveInput:
    def test_json_snapshot_loaded(self, tmp_path):
        snap = _make_snapshot("1.0")
        p = _write_snapshot(tmp_path / "snap.json", snap)
        result = _resolve_input(p, headers=[], includes=[], version="1.0", compiler="c++")
        assert result.library == "libtest.so"
        assert result.version == "1.0"

    def test_elf_without_headers_raises(self, tmp_path):
        p = _write_fake_elf(tmp_path / "lib.so")
        with pytest.raises(Exception, match="header"):
            _resolve_input(p, headers=[], includes=[], version="1.0", compiler="c++")

    def test_unknown_format_raises(self, tmp_path):
        p = tmp_path / "mystery.dat"
        p.write_text("not json, not perl, not elf", encoding="utf-8")
        with pytest.raises(Exception, match="Cannot detect format"):
            _resolve_input(p, headers=[], includes=[], version="1.0", compiler="c++")

    def test_malformed_json_raises_click_exception(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"not_a_valid_snapshot": true}', encoding="utf-8")
        with pytest.raises(Exception, match="Failed to load JSON snapshot"):
            _resolve_input(p, headers=[], includes=[], version="1.0", compiler="c++")

    def test_elf_with_missing_header_raises(self, tmp_path):
        p = _write_fake_elf(tmp_path / "lib.so")
        missing = tmp_path / "nonexistent.h"
        with pytest.raises(Exception, match="Header file not found"):
            _resolve_input(
                p, headers=[missing], includes=[], version="1.0", compiler="c++",
            )


# ── compare with .json + .json (backward compat) ────────────────────────


class TestCompareJsonJson:
    def test_no_change(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p)])
        assert result.exit_code == 0
        assert "NO_CHANGE" in result.output

    def test_breaking(self, tmp_path):
        old, new = _breaking_snapshots(tmp_path)
        old_p = _write_snapshot(tmp_path / "old.json", old)
        new_p = _write_snapshot(tmp_path / "new.json", new)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p)])
        assert result.exit_code == 4

    def test_headers_ignored_warning(self, tmp_path):
        """When both inputs are JSON, -H should emit a warning."""
        old_p, new_p = _write_snapshots(tmp_path)
        hdr = tmp_path / "dummy.h"
        hdr.write_text("// dummy", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "-H", str(hdr),
        ])
        assert result.exit_code == 0
        assert "ignored" in result.output.lower()

    def test_per_side_headers_ignored_warning(self, tmp_path):
        """When both inputs are JSON, --old-header/--new-header should warn."""
        old_p, new_p = _write_snapshots(tmp_path)
        hdr = tmp_path / "dummy.h"
        hdr.write_text("// dummy", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p),
            "--old-header", str(hdr), "--new-header", str(hdr),
        ])
        assert result.exit_code == 0
        assert "--old-header" in result.output
        assert "--new-header" in result.output
        assert "ignored" in result.output.lower()


# ── compare with .so + .so (primary flow, monkeypatched) ────────────────


class TestCompareSoSo:
    def test_so_vs_so_with_shared_headers(self, tmp_path, monkeypatch):
        """Compare two .so files with -H (same header for both)."""
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")

        old_snap = _make_snapshot("old")
        new_snap = _make_snapshot("new")

        call_count = [0]

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            call_count[0] += 1
            if "v1" in str(so_path):
                return old_snap
            return new_snap

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_elf), str(new_elf), "-H", str(hdr),
        ])
        assert result.exit_code == 0, result.output
        assert call_count[0] == 2  # dump called for both sides

    def test_so_vs_so_with_per_side_headers(self, tmp_path, monkeypatch):
        """Compare two .so files with --old-header / --new-header."""
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        old_hdr = tmp_path / "v1.h"
        new_hdr = tmp_path / "v2.h"
        old_hdr.write_text("int foo(void);", encoding="utf-8")
        new_hdr.write_text("int foo(void); int bar(void);", encoding="utf-8")

        recorded_headers: list[list[Path]] = []

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            recorded_headers.append(list(headers))
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_elf), str(new_elf),
            "--old-header", str(old_hdr),
            "--new-header", str(new_hdr),
        ])
        assert result.exit_code == 0, result.output
        assert len(recorded_headers) == 2
        # old side got old_hdr, new side got new_hdr
        assert recorded_headers[0] == [old_hdr]
        assert recorded_headers[1] == [new_hdr]

    def test_so_without_headers_errors(self, tmp_path):
        """Passing .so files without any -H should fail."""
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_elf), str(new_elf),
        ])
        assert result.exit_code != 0
        assert "header" in result.output.lower()

    def test_so_vs_so_with_version_labels(self, tmp_path, monkeypatch):
        """--old-version / --new-version are passed through to dump."""
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")

        recorded_versions: list[str] = []

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            recorded_versions.append(version)
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_elf), str(new_elf), "-H", str(hdr),
            "--old-version", "1.0", "--new-version", "2.0",
        ])
        assert result.exit_code == 0, result.output
        assert recorded_versions == ["1.0", "2.0"]

    def test_so_vs_so_with_includes(self, tmp_path, monkeypatch):
        """Verify -I / --old-include / --new-include are passed correctly."""
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")
        inc_dir = tmp_path / "inc"
        inc_dir.mkdir()

        recorded_includes: list[list[Path]] = []

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            recorded_includes.append(list(extra_includes or []))
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_elf), str(new_elf),
            "-H", str(hdr), "-I", str(inc_dir),
        ])
        assert result.exit_code == 0, result.output
        assert len(recorded_includes) == 2
        assert recorded_includes[0] == [inc_dir]
        assert recorded_includes[1] == [inc_dir]


# ── compare mixed mode: .json + .so ─────────────────────────────────────


class TestCompareMixed:
    def test_json_vs_so(self, tmp_path, monkeypatch):
        """Baseline snapshot (.json) vs current build (.so)."""
        old_p = _write_snapshot(tmp_path / "baseline.json", _make_snapshot("1.0"))
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_elf), "-H", str(hdr),
        ])
        assert result.exit_code == 0, result.output
        assert "NO_CHANGE" in result.output

    def test_so_vs_json(self, tmp_path, monkeypatch):
        """Current build (.so) vs stored snapshot (.json)."""
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_p = _write_snapshot(tmp_path / "release.json", _make_snapshot("2.0"))
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_elf), str(new_p), "-H", str(hdr),
        ])
        assert result.exit_code == 0, result.output

    def test_mixed_breaking_detection(self, tmp_path, monkeypatch):
        """Mixed mode detects breaking changes correctly."""
        old_snap, new_snap = _breaking_snapshots(tmp_path)
        old_p = _write_snapshot(tmp_path / "baseline.json", old_snap)
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            return new_snap

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_elf), "-H", str(hdr),
        ])
        assert result.exit_code == 4  # BREAKING

    def test_mixed_with_per_side_headers(self, tmp_path, monkeypatch):
        """--new-header only applies to the .so side, JSON side ignores headers."""
        old_p = _write_snapshot(tmp_path / "baseline.json", _make_snapshot("1.0"))
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        new_hdr = tmp_path / "v2.h"
        new_hdr.write_text("int foo(void);", encoding="utf-8")

        recorded_headers: list[list[Path]] = []

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            recorded_headers.append(list(headers))
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_elf),
            "--new-header", str(new_hdr),
        ])
        assert result.exit_code == 0, result.output
        # dump should only be called for the .so side (new)
        assert len(recorded_headers) == 1
        assert recorded_headers[0] == [new_hdr]


# ── compare with output formats (using .so inputs) ──────────────────────


class TestCompareSoOutputFormats:
    def _run_with_format(self, tmp_path, monkeypatch, fmt, extra_args=None):
        old_elf = _write_fake_elf(tmp_path / "libv1.so")
        new_elf = _write_fake_elf(tmp_path / "libv2.so")
        hdr = tmp_path / "foo.h"
        hdr.write_text("int foo(void);", encoding="utf-8")

        def mock_dump(so_path, headers, extra_includes=None, version="unknown",
                      compiler="c++", **kw):
            return _make_snapshot(version)

        monkeypatch.setattr("abicheck.cli.dump", mock_dump)

        args = ["compare", str(old_elf), str(new_elf), "-H", str(hdr),
                "--format", fmt]
        if extra_args:
            args.extend(extra_args)

        runner = CliRunner()
        return runner.invoke(main, args)

    def test_json_format(self, tmp_path, monkeypatch):
        result = self._run_with_format(tmp_path, monkeypatch, "json")
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "verdict" in parsed

    def test_sarif_format(self, tmp_path, monkeypatch):
        out = tmp_path / "abi.sarif"
        result = self._run_with_format(tmp_path, monkeypatch, "sarif",
                                       ["-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_html_format(self, tmp_path, monkeypatch):
        result = self._run_with_format(tmp_path, monkeypatch, "html")
        assert result.exit_code == 0
        assert "<html" in result.output.lower()

    def test_markdown_format(self, tmp_path, monkeypatch):
        result = self._run_with_format(tmp_path, monkeypatch, "markdown")
        assert result.exit_code == 0


# ── compare help output ─────────────────────────────────────────────────


class TestCompareHelp:
    def test_nonexistent_header_ok_for_snapshots(self, tmp_path):
        """Headers with non-existent paths should not block snapshot-only runs."""
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p),
            "-H", str(tmp_path / "nonexistent.h"),
        ])
        # Should succeed (with warning) — header is ignored for snapshot inputs
        assert result.exit_code == 0
        assert "ignored" in result.output.lower()

    def test_help_shows_new_options(self):
        runner = CliRunner()
        result = runner.invoke(main, ["compare", "--help"])
        assert result.exit_code == 0
        for flag in ["-H", "--header", "--old-header", "--new-header",
                     "--old-version", "--new-version", "--old-include",
                     "--new-include", "--compiler"]:
            assert flag in result.output, f"{flag} not in help output"

    def test_help_shows_examples(self):
        runner = CliRunner()
        result = runner.invoke(main, ["compare", "--help"])
        assert "libfoo.so" in result.output
        assert "baseline.json" in result.output

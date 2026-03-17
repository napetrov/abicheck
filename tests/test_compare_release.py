"""Tests for the compare-release command (multi-binary directory comparison)."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from abicheck.cli import main
from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.serialization import snapshot_to_json

# ── helpers ──────────────────────────────────────────────────────────────────

def _snap(version: str = "1.0", funcs: list[Function] | None = None, library: str = "libfoo.so") -> AbiSnapshot:
    if funcs is None:
        funcs = [Function(name="foo", mangled="_Z3foov", return_type="int",
                          visibility=Visibility.PUBLIC)]
    return AbiSnapshot(library=library, version=version, functions=funcs)


def _write_snap(path: Path, snap: AbiSnapshot) -> Path:
    path.write_text(snapshot_to_json(snap), encoding="utf-8")
    return path


def _breaking_pair(lib: str = "libfoo.so") -> tuple[AbiSnapshot, AbiSnapshot]:
    old = _snap("1.0", [
        Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC),
        Function(name="bar", mangled="_Z3barv", return_type="void", visibility=Visibility.PUBLIC),
    ], library=lib)
    new = _snap("2.0", [
        Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC),
    ], library=lib)
    return old, new


def _invoke(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(main, list(args))
    return result.exit_code, result.output


# ── file vs file ─────────────────────────────────────────────────────────────

class TestFileVsFile:
    def test_no_change(self, tmp_path):
        snap = _snap()
        old_f = _write_snap(tmp_path / "libfoo.json", snap)
        new_f = _write_snap(tmp_path / "libfoo_new.json", snap)
        code, out = _invoke("compare-release", str(old_f), str(new_f))
        assert code == 0
        assert "NO_CHANGE" in out

    def test_breaking(self, tmp_path):
        old, new = _breaking_pair()
        old_f = _write_snap(tmp_path / "libfoo.json", old)
        new_f = _write_snap(tmp_path / "libfoo_new.json", new)
        code, out = _invoke("compare-release", str(old_f), str(new_f))
        assert code == 4

    def test_json_output(self, tmp_path):
        snap = _snap()
        old_f = _write_snap(tmp_path / "libfoo.json", snap)
        new_f = _write_snap(tmp_path / "libfoo2.json", snap)
        code, out = _invoke("compare-release", str(old_f), str(new_f), "--format", "json")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "NO_CHANGE"
        assert len(data["libraries"]) == 1


# ── dir vs dir ───────────────────────────────────────────────────────────────

class TestDirVsDir:
    def test_matching_by_name_no_change(self, tmp_path):
        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        snap = _snap()
        _write_snap(old_dir / "libfoo.json", snap)
        _write_snap(new_dir / "libfoo.json", snap)

        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0
        assert "NO_CHANGE" in out

    def test_matching_multi_library_all_ok(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        for name in ("libfoo.json", "libbar.json", "libbaz.json"):
            snap = _snap()
            _write_snap(old_dir / name, snap)
            _write_snap(new_dir / name, snap)

        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0

    def test_breaking_in_one_library(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        # libfoo: breaking
        old_foo, new_foo = _breaking_pair("libfoo.so")
        _write_snap(old_dir / "libfoo.json", old_foo)
        _write_snap(new_dir / "libfoo.json", new_foo)

        # libbar: no change
        _write_snap(old_dir / "libbar.json", _snap())
        _write_snap(new_dir / "libbar.json", _snap())

        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 4
        assert "BREAKING" in out

    def test_json_output_multi(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        for name in ("libfoo.json", "libbar.json"):
            snap = _snap()
            _write_snap(old_dir / name, snap)
            _write_snap(new_dir / name, snap)

        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "NO_CHANGE"
        assert len(data["libraries"]) == 2


# ── unmatched / missing ───────────────────────────────────────────────────────

class TestUnmatched:
    def test_removed_library_no_flag(self, tmp_path):
        """Removed library should warn but not fail by default."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(old_dir / "libbar.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())
        # libbar missing in new

        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0  # no --fail-on-removed-library
        # warning should be on stderr but click test merges stdout/stderr
        # at least the summary is ok

    def test_removed_library_with_flag(self, tmp_path):
        """--fail-on-removed-library should exit 8 when library disappears."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(old_dir / "libbar.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())

        code, _ = _invoke(
            "compare-release", str(old_dir), str(new_dir),
            "--fail-on-removed-library",
        )
        assert code == 8

    def test_added_library_ok(self, tmp_path):
        """New library in new_dir not in old_dir is fine (no flag needed)."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libbar.json", _snap())  # new lib

        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0

    def test_unmatched_reported_in_json(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(old_dir / "libremoved.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libadded.json", _snap())

        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0
        data = json.loads(out)
        assert "libremoved.json" in data["unmatched_old"]
        assert "libadded.json" in data["unmatched_new"]


# ── output-dir ────────────────────────────────────────────────────────────────

class TestOutputDir:
    def test_per_library_reports_written(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        out_dir = tmp_path / "reports"

        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())

        code, _ = _invoke(
            "compare-release", str(old_dir), str(new_dir),
            "--output-dir", str(out_dir),
        )
        assert code == 0
        assert (out_dir / "libfoo.json").exists()
        assert (out_dir / "summary.json").exists()

    def test_summary_json_structure(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        out_dir = tmp_path / "reports"

        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())

        _invoke("compare-release", str(old_dir), str(new_dir), "--output-dir", str(out_dir))
        summary = json.loads((out_dir / "summary.json").read_text())
        assert summary["verdict"] == "NO_CHANGE"
        assert len(summary["libraries"]) == 1


# ── mixed input (file vs file, different names, same stem) ───────────────────

class TestMixedInputs:
    def test_so_versioned_name_matching(self, tmp_path):
        """libfoo.so.1.2 in old should match libfoo.so.1.3 in new via stem."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        snap = _snap()
        _write_snap(old_dir / "libfoo.so.1.2.json", snap)
        _write_snap(new_dir / "libfoo.so.1.3.json", snap)

        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0
        data = json.loads(out)
        assert len(data["libraries"]) == 1
        assert data["verdict"] == "NO_CHANGE"

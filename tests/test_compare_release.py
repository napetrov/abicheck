"""Tests for the compare-release command (multi-binary directory comparison)."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from abicheck.cli import (
    _canonical_library_key,
    _is_supported_compare_input,
    _version_sort_key,
    main,
)
from abicheck.model import AbiSnapshot, Function, Param, Visibility
from abicheck.serialization import snapshot_to_json

# ── helpers ──────────────────────────────────────────────────────────────────

def _snap(
    version: str = "1.0",
    funcs: list[Function] | None = None,
    library: str = "libfoo.so",
) -> AbiSnapshot:
    if funcs is None:
        funcs = [Function(name="foo", mangled="_Z3foov", return_type="int",
                          visibility=Visibility.PUBLIC)]
    return AbiSnapshot(library=library, version=version, functions=funcs)


def _write_snap(path: Path, snap: AbiSnapshot) -> Path:
    path.write_text(snapshot_to_json(snap), encoding="utf-8")
    return path


def _breaking_pair(lib: str = "libfoo.so") -> tuple[AbiSnapshot, AbiSnapshot]:
    """Remove a function — always produces BREAKING verdict."""
    old = _snap("1.0", [
        Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC),
        Function(name="bar", mangled="_Z3barv", return_type="void", visibility=Visibility.PUBLIC),
    ], library=lib)
    new = _snap("2.0", [
        Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC),
    ], library=lib)
    return old, new


def _api_break_pair(lib: str = "libfoo.so") -> tuple[AbiSnapshot, AbiSnapshot]:
    """Signature change that requires recompilation but is not a binary break."""
    old = _snap("1.0", [
        Function(
            name="foo",
            mangled="_Z3foov",
            return_type="int",
            params=[Param(name="x", type="int", default="0")],
            visibility=Visibility.PUBLIC,
        ),
    ], library=lib)
    new = _snap("2.0", [
        Function(
            name="foo",
            mangled="_Z3foov",
            return_type="int",
            params=[Param(name="x", type="int")],
            visibility=Visibility.PUBLIC,
        ),
    ], library=lib)
    return old, new


def _invoke(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(main, list(args))
    return result.exit_code, result.output


# ── canonical key helpers ─────────────────────────────────────────────────────

class TestCanonicalLibraryKey:
    def test_so_versioned(self, tmp_path: Path) -> None:
        assert _canonical_library_key(Path("libfoo.so.1.2")) == "libfoo.so"

    def test_so_no_version(self, tmp_path: Path) -> None:
        assert _canonical_library_key(Path("libfoo.so")) == "libfoo.so"

    def test_json_snapshot(self, tmp_path: Path) -> None:
        # No .so in name — returns as-is
        assert _canonical_library_key(Path("libfoo.json")) == "libfoo.json"

    def test_so_json_snapshot(self, tmp_path: Path) -> None:
        # .so in name + .json suffix
        assert _canonical_library_key(Path("libfoo.so.1.2.json")) == "libfoo.so"

    def test_so_in_stem_not_confused(self, tmp_path: Path) -> None:
        # "libsome.so" — ".so" is real extension, not inside stem
        assert _canonical_library_key(Path("libsome.so")) == "libsome.so"

    def test_dll(self, tmp_path: Path) -> None:
        assert _canonical_library_key(Path("libfoo.dll")) == "libfoo.dll"


class TestVersionSortKey:
    def test_1_9_vs_1_10(self) -> None:
        k9 = _version_sort_key(Path("libfoo.so.1.9"), "libfoo.so")
        k10 = _version_sort_key(Path("libfoo.so.1.10"), "libfoo.so")
        assert k9 < k10, "1.10 should sort after 1.9"

    def test_1_2_vs_1_3(self) -> None:
        k2 = _version_sort_key(Path("libfoo.so.1.2"), "libfoo.so")
        k3 = _version_sort_key(Path("libfoo.so.1.3"), "libfoo.so")
        assert k2 < k3


# ── file vs file ─────────────────────────────────────────────────────────────

class TestFileVsFile:
    def test_no_change(self, tmp_path: Path) -> None:
        snap = _snap()
        old_f = _write_snap(tmp_path / "libfoo.json", snap)
        new_f = _write_snap(tmp_path / "libfoo_new.json", snap)
        code, out = _invoke("compare-release", str(old_f), str(new_f))
        assert code == 0
        assert "NO_CHANGE" in out

    def test_breaking(self, tmp_path: Path) -> None:
        old, new = _breaking_pair()
        old_f = _write_snap(tmp_path / "libfoo.json", old)
        new_f = _write_snap(tmp_path / "libfoo_new.json", new)
        code, out = _invoke("compare-release", str(old_f), str(new_f))
        assert code == 4
        assert "BREAKING" in out

    def test_api_break(self, tmp_path: Path) -> None:
        old, new = _api_break_pair()
        old_f = _write_snap(tmp_path / "libfoo.json", old)
        new_f = _write_snap(tmp_path / "libfoo_new.json", new)
        code, out = _invoke("compare-release", str(old_f), str(new_f))
        assert code == 2

    def test_json_output(self, tmp_path: Path) -> None:
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
    def test_matching_by_name_no_change(self, tmp_path: Path) -> None:
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

    def test_matching_multi_library_all_ok(self, tmp_path: Path) -> None:
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
        assert "NO_CHANGE" in out

    def test_breaking_in_one_library(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        old_foo, new_foo = _breaking_pair("libfoo.so")
        _write_snap(old_dir / "libfoo.json", old_foo)
        _write_snap(new_dir / "libfoo.json", new_foo)
        _write_snap(old_dir / "libbar.json", _snap())
        _write_snap(new_dir / "libbar.json", _snap())
        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 4
        assert "BREAKING" in out

    def test_api_break_in_one_library(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        old_foo, new_foo = _api_break_pair("libfoo.so")
        _write_snap(old_dir / "libfoo.json", old_foo)
        _write_snap(new_dir / "libfoo.json", new_foo)
        _write_snap(old_dir / "libbar.json", _snap())
        _write_snap(new_dir / "libbar.json", _snap())
        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 2

    def test_json_output_multi(self, tmp_path: Path) -> None:
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

    def test_breaking_overrides_api_break(self, tmp_path: Path) -> None:
        """Aggregate verdict is BREAKING even when another lib has API_BREAK."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        old_foo, new_foo = _breaking_pair("libfoo.so")
        old_bar, new_bar = _api_break_pair("libbar.so")
        _write_snap(old_dir / "libfoo.json", old_foo)
        _write_snap(new_dir / "libfoo.json", new_foo)
        _write_snap(old_dir / "libbar.json", old_bar)
        _write_snap(new_dir / "libbar.json", new_bar)
        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 4
        assert "BREAKING" in out

    def test_fully_disjoint_dirs_warns_and_exits_0(self, tmp_path: Path) -> None:
        """Dirs with no matching lib names: warn, empty libraries list, exit 0."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libbar.json", _snap())
        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0
        assert "no matching" in out.lower() or "warning" in out.lower()


# ── unmatched / missing ───────────────────────────────────────────────────────

class TestUnmatched:
    def test_removed_library_no_flag(self, tmp_path: Path) -> None:
        """Removed library warns but does not fail by default."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(old_dir / "libbar.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())
        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0

    def test_removed_library_with_flag(self, tmp_path: Path) -> None:
        """--fail-on-removed-library exits 8 when library disappears."""
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

    def test_removed_and_breaking_exits_4_not_8(self, tmp_path: Path) -> None:
        """BREAKING (4) takes priority over removed-library (8)."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        old_foo, new_foo = _breaking_pair("libfoo.so")
        _write_snap(old_dir / "libfoo.json", old_foo)
        _write_snap(new_dir / "libfoo.json", new_foo)
        _write_snap(old_dir / "libremoved.json", _snap())  # removed
        code, _ = _invoke(
            "compare-release", str(old_dir), str(new_dir),
            "--fail-on-removed-library",
        )
        assert code == 4

    def test_added_library_ok(self, tmp_path: Path) -> None:
        """New library in new_dir not in old_dir is fine."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libbar.json", _snap())
        code, out = _invoke("compare-release", str(old_dir), str(new_dir))
        assert code == 0

    def test_unmatched_reported_in_json(self, tmp_path: Path) -> None:
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
        assert isinstance(data["unmatched_old"], list)
        assert "libremoved.json" in data["unmatched_old"]
        assert isinstance(data["unmatched_new"], list)
        assert "libadded.json" in data["unmatched_new"]


# ── output-dir ────────────────────────────────────────────────────────────────

class TestOutputDir:
    def test_per_library_reports_written(self, tmp_path: Path) -> None:
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

    def test_summary_json_structure(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        out_dir = tmp_path / "reports"
        _write_snap(old_dir / "libfoo.json", _snap())
        _write_snap(new_dir / "libfoo.json", _snap())
        code, _ = _invoke("compare-release", str(old_dir), str(new_dir), "--output-dir", str(out_dir))
        assert code == 0
        summary = json.loads((out_dir / "summary.json").read_text())
        assert summary["verdict"] == "NO_CHANGE"
        assert len(summary["libraries"]) == 1


# ── version-aware name matching ───────────────────────────────────────────────

class TestMixedInputs:
    def test_so_versioned_name_matching(self, tmp_path: Path) -> None:
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

    def test_version_aware_picks_1_10_over_1_9(self, tmp_path: Path) -> None:
        """Version-aware sort must pick 1.10 as latest, not 1.9."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        # Two old candidates for same stem — 1.10 is newer
        snap = _snap()
        _write_snap(old_dir / "libfoo.so.1.9.json", snap)
        _write_snap(old_dir / "libfoo.so.1.10.json", snap)
        _write_snap(new_dir / "libfoo.so.2.0.json", snap)
        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0
        data = json.loads(out)
        # Only 1 comparison, and warnings should mention 1.10 as selected
        assert len(data["libraries"]) == 1
        assert any("1.10" in w for w in data.get("warnings", []))


class TestFilterOutNonABIFiles:
    """Regression tests for false-positive detection of non‑ABI files."""

    def test_ignore_json_without_library_key(self, tmp_path: Path) -> None:
        """JSON files without "library" field should be ignored, not cause ERROR."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        # Real ABI snapshot (accepted)
        snap = _snap()
        _write_snap(old_dir / "libfoo.so.json", snap)
        _write_snap(new_dir / "libfoo.so.json", snap)

        # False‑positive JSON files (should be ignored)
        (old_dir / "auditwheel.cdx.json").write_text(
            '{"bomFormat": "CycloneDX", "specVersion": "1.4", "metadata": {"component": {"type": "library"}}, "components": []}'
        )
        (new_dir / "auditwheel.cdx.json").write_text(
            '{"bomFormat": "CycloneDX", "specVersion": "1.4", "metadata": {"component": {"type": "library"}}, "components": []}'
        )
        (old_dir / "studentized_range_mpmath_ref.json").write_text(
            '{"data": [[1, 2, 3], [4, 5, 6]]}'
        )
        (new_dir / "studentized_range_mpmath_ref.json").write_text(
            '{"data": [[1, 2, 3], [4, 5, 6]]}'
        )
        # Template file that starts with '{' (Jinja, etc.)
        (old_dir / "html.tpl").write_text("{% extends 'base.tpl' %}\n{% block content %}\n...\n{% endblock %}")
        (new_dir / "html.tpl").write_text("{% extends 'base.tpl' %}\n{% block content %}\n...\n{% endblock %}")

        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0, f"Should pass (only one real library). Output: {out}"
        data = json.loads(out)
        # Only the real ABI snapshot is compared
        assert len(data["libraries"]) == 1
        assert data["libraries"][0]["library"] == "libfoo.so.json"
        assert data["libraries"][0]["verdict"] == "NO_CHANGE"
        # No ERROR verdict from the incidental JSON/template files
        assert not any(lib.get("verdict") == "ERROR" for lib in data["libraries"])

    def test_ignore_parquet_and_other_non_so_extensions(self, tmp_path: Path) -> None:
        """Files like *.parquet, *.csv, etc. should not be mistaken for .so candidates."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        # Real library (accepted)
        snap = _snap()
        _write_snap(old_dir / "libfoo.so.json", snap)
        _write_snap(new_dir / "libfoo.so.json", snap)

        # Files that contain the substring "so" but are not .so libraries
        (old_dir / "v0.7.1.some-named-index.parquet").write_bytes(b"PAR1" + b"fake data" * 100)
        (new_dir / "v0.7.1.some-named-index.parquet").write_bytes(b"PAR1" + b"fake data" * 100)
        (old_dir / "solution.json").write_text('{"answer": 42}')
        (new_dir / "solution.json").write_text('{"answer": 42}')
        (old_dir / "something.dll.txt").write_text("Not a DLL")
        (new_dir / "something.dll.txt").write_text("Not a DLL")

        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0, f"Should pass (only one real library). Output: {out}"
        data = json.loads(out)
        # Only the real ABI snapshot is compared
        assert len(data["libraries"]) == 1
        assert data["libraries"][0]["library"] == "libfoo.so.json"
        assert not any(lib.get("verdict") == "ERROR" for lib in data["libraries"])

    def test_accept_real_abi_snapshots(self, tmp_path: Path) -> None:
        """Legitimate ABI snapshots (JSON with "library" key) should still be accepted."""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        # ABI snapshot with "library" field
        snap1 = _snap("1.0", library="libfoo.so")
        snap2 = _snap("2.0", library="libfoo.so")
        _write_snap(old_dir / "libfoo.json", snap1)
        _write_snap(new_dir / "libfoo.json", snap2)

        code, out = _invoke("compare-release", str(old_dir), str(new_dir), "--format", "json")
        assert code == 0, f"Should compare the two snapshots. Output: {out}"
        data = json.loads(out)
        assert len(data["libraries"]) == 1
        assert data["libraries"][0]["library"] == "libfoo.json"
        assert data["libraries"][0]["verdict"] == "NO_CHANGE"

    def test_pyd_extension_accepted(self, tmp_path: Path) -> None:
        """Python Windows extension .pyd (a PE DLL) should be accepted."""
        pyd = tmp_path / "module.pyd"
        pyd.write_bytes(b"not-a-real-pe")
        assert _is_supported_compare_input(pyd)

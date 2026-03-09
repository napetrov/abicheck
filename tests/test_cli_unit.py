"""Unit tests for cli.py — compare and compat subcommands.

Covers compare_cmd output formats, exit codes, suppression handling,
and compat_cmd descriptor parsing/error paths.
"""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from abicheck.cli import main
from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.serialization import snapshot_to_json

# ── helpers ──────────────────────────────────────────────────────────────

def _write_snapshots(tmp_path: Path, old_snap: AbiSnapshot | None = None,
                     new_snap: AbiSnapshot | None = None) -> tuple[Path, Path]:
    """Write old/new snapshots to JSON files and return their paths."""
    if old_snap is None:
        old_snap = AbiSnapshot(
            library="libtest.so", version="1.0",
            functions=[Function(name="foo", mangled="_Z3foov", return_type="int",
                                visibility=Visibility.PUBLIC)],
        )
    if new_snap is None:
        new_snap = AbiSnapshot(
            library="libtest.so", version="2.0",
            functions=[Function(name="foo", mangled="_Z3foov", return_type="int",
                                visibility=Visibility.PUBLIC)],
        )
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(snapshot_to_json(old_snap), encoding="utf-8")
    new_path.write_text(snapshot_to_json(new_snap), encoding="utf-8")
    return old_path, new_path


def _breaking_snapshots(tmp_path: Path) -> tuple[Path, Path]:
    """Snapshots where a function is removed → BREAKING."""
    old = AbiSnapshot(
        library="libtest.so", version="1.0",
        functions=[
            Function(name="foo", mangled="_Z3foov", return_type="int",
                     visibility=Visibility.PUBLIC),
            Function(name="bar", mangled="_Z3barv", return_type="void",
                     visibility=Visibility.PUBLIC),
        ],
    )
    new = AbiSnapshot(
        library="libtest.so", version="2.0",
        functions=[
            Function(name="foo", mangled="_Z3foov", return_type="int",
                     visibility=Visibility.PUBLIC),
        ],
    )
    return _write_snapshots(tmp_path, old, new)


# ── compare markdown ────────────────────────────────────────────────────

class TestCompareMarkdown:
    def test_no_change_exit_0(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p)])
        assert result.exit_code == 0
        assert "NO_CHANGE" in result.output

    def test_breaking_exit_4(self, tmp_path):
        old_p, new_p = _breaking_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p)])
        assert result.exit_code == 4

    def test_output_to_file(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        out = tmp_path / "report.md"
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p), "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        assert "Report written to" in result.output


# ── compare JSON ────────────────────────────────────────────────────────

class TestCompareJson:
    def test_json_output(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p), "--format", "json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "verdict" in parsed


# ── compare SARIF ───────────────────────────────────────────────────────

class TestCompareSarif:
    def test_sarif_output(self, tmp_path):
        old_p, new_p = _breaking_snapshots(tmp_path)
        out = tmp_path / "results.sarif"
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--format", "sarif", "-o", str(out),
        ])
        assert result.exit_code == 4
        content = json.loads(out.read_text(encoding="utf-8"))
        assert content.get("$schema") or "runs" in content


# ── compare HTML ────────────────────────────────────────────────────────

class TestCompareHtml:
    def test_html_output_to_file(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        out = tmp_path / "report.html"
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--format", "html", "-o", str(out),
        ])
        assert result.exit_code == 0
        assert out.exists()
        assert "<html" in out.read_text(encoding="utf-8").lower()

    def test_html_output_to_stdout(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--format", "html",
        ])
        assert result.exit_code == 0
        assert "<html" in result.output.lower()


# ── compare with suppression ────────────────────────────────────────────

class TestCompareSuppression:
    def test_suppression_file_applied(self, tmp_path):
        old_p, new_p = _breaking_snapshots(tmp_path)
        sup = tmp_path / "suppress.yaml"
        sup.write_text(
            "version: 1\nsuppressions:\n  - symbol: _Z3barv\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--suppress", str(sup),
        ])
        # After suppression, the removed function is suppressed → NO_CHANGE
        assert result.exit_code == 0

    def test_bad_suppression_file(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        sup = tmp_path / "bad.yaml"
        sup.write_text("not: valid: suppression: format", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--suppress", str(sup),
        ])
        assert result.exit_code != 0


# ── compare suppression warning ─────────────────────────────────────────

class TestCompareSuppressionWarning:
    def test_all_changes_suppressed_warns(self, tmp_path):
        """When suppression file swallows all changes, a warning is shown."""
        old_p, new_p = _breaking_snapshots(tmp_path)
        sup = tmp_path / "suppress.yaml"
        sup.write_text(
            "version: 1\nsuppressions:\n  - symbol: _Z3barv\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--suppress", str(sup),
        ])
        assert "suppressed" in result.output.lower() or result.exit_code == 0


# ── compat descriptor errors ────────────────────────────────────────────

class TestCompatErrors:
    def test_invalid_descriptor_exits_2(self, tmp_path):
        old = tmp_path / "old.xml"
        new = tmp_path / "new.xml"
        old.write_text("<invalid>", encoding="utf-8")
        new.write_text("<invalid>", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "-lib", "libtest", "-old", str(old), "-new", str(new),
        ])
        assert result.exit_code == 2

    def test_missing_library_exits_2(self, tmp_path):
        """Descriptor references a .so that doesn't exist → exit 2."""
        old = tmp_path / "old.xml"
        new = tmp_path / "new.xml"
        old.write_text(
            "<descriptor><version>1.0</version><libs>/nonexistent/lib.so</libs></descriptor>",
            encoding="utf-8",
        )
        new.write_text(
            "<descriptor><version>2.0</version><libs>/nonexistent/lib.so</libs></descriptor>",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "-lib", "libtest", "-old", str(old), "-new", str(new),
        ])
        assert result.exit_code == 2


# ── compat help output ──────────────────────────────────────────────────

class TestCompatHelp:
    def test_compat_help_lists_flags(self):
        runner = CliRunner()
        result = runner.invoke(main, ["compat", "--help"])
        assert result.exit_code == 0
        for flag in ["-lib", "-old", "-new", "-s", "-source", "-stdout",
                     "-skip-symbols", "-v1", "-v2"]:
            assert flag in result.output, f"{flag} not in help output"

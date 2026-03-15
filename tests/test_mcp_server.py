"""Tests for abicheck.mcp_server — MCP tool functions.

These tests exercise the MCP tool functions directly (without running the MCP
protocol layer) to verify they produce correct structured JSON responses.
"""

import json
import tempfile
from pathlib import Path

import pytest

from abicheck.checker import ChangeKind, Verdict
from abicheck.model import AbiSnapshot, Function, Variable, Visibility

# Guard: skip entire module if the mcp package is not installed.
pytest.importorskip("mcp", reason="mcp package not installed")

from abicheck.mcp_server import (  # noqa: E402
    abi_compare,
    abi_dump,
    abi_explain_change,
    abi_list_changes,
    _impact_category,
    _resolve_input,
    _snapshot_summary,
)
from abicheck.serialization import snapshot_to_json  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_snapshot(
    version: str = "1.0",
    functions: list[Function] | None = None,
    variables: list[Variable] | None = None,
) -> AbiSnapshot:
    return AbiSnapshot(
        library="libtest.so.1",
        version=version,
        functions=functions or [],
        variables=variables or [],
    )


def _pub_func(name: str, mangled: str, ret: str = "void") -> Function:
    return Function(
        name=name, mangled=mangled, return_type=ret,
        visibility=Visibility.PUBLIC,
    )


def _pub_var(name: str, mangled: str, type_: str) -> Variable:
    return Variable(
        name=name, mangled=mangled, type=type_,
        visibility=Visibility.PUBLIC,
    )


@pytest.fixture
def snapshot_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Create two JSON snapshot files: old (with func) and new (func removed)."""
    old = _make_snapshot("1.0", functions=[_pub_func("init", "_Z4initv", "int")])
    new = _make_snapshot("2.0", functions=[])

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(snapshot_to_json(old), encoding="utf-8")
    new_path.write_text(snapshot_to_json(new), encoding="utf-8")
    return old_path, new_path


@pytest.fixture
def compatible_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Create two JSON snapshot files: old and new with a new function added."""
    f = _pub_func("init", "_Z4initv", "int")
    old = _make_snapshot("1.0", functions=[f])
    new = _make_snapshot("2.0", functions=[f, _pub_func("helper", "_Z6helperv")])

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(snapshot_to_json(old), encoding="utf-8")
    new_path.write_text(snapshot_to_json(new), encoding="utf-8")
    return old_path, new_path


# ---------------------------------------------------------------------------
# abi_list_changes
# ---------------------------------------------------------------------------

class TestAbiListChanges:
    def test_list_all(self):
        raw = abi_list_changes()
        data = json.loads(raw)
        assert "change_kinds" in data
        assert data["count"] > 50  # we have 85+ change kinds

    def test_filter_breaking(self):
        raw = abi_list_changes(impact="breaking")
        data = json.loads(raw)
        assert data["count"] > 0
        for entry in data["change_kinds"]:
            assert entry["impact"] == "breaking"

    def test_filter_compatible(self):
        raw = abi_list_changes(impact="compatible")
        data = json.loads(raw)
        assert data["count"] > 0
        for entry in data["change_kinds"]:
            assert entry["impact"] == "compatible"

    def test_filter_api_break(self):
        raw = abi_list_changes(impact="api_break")
        data = json.loads(raw)
        assert data["count"] > 0
        for entry in data["change_kinds"]:
            assert entry["impact"] == "api_break"

    def test_filter_risk(self):
        raw = abi_list_changes(impact="risk")
        data = json.loads(raw)
        assert data["count"] > 0
        for entry in data["change_kinds"]:
            assert entry["impact"] == "risk"

    def test_invalid_filter(self):
        raw = abi_list_changes(impact="bogus")
        data = json.loads(raw)
        assert "error" in data

    def test_each_entry_has_required_fields(self):
        raw = abi_list_changes()
        data = json.loads(raw)
        for entry in data["change_kinds"]:
            assert "kind" in entry
            assert "impact" in entry
            assert "default_verdict" in entry
            assert "description" in entry


# ---------------------------------------------------------------------------
# abi_explain_change
# ---------------------------------------------------------------------------

class TestAbiExplainChange:
    def test_known_kind(self):
        raw = abi_explain_change("func_removed")
        data = json.loads(raw)
        assert data["kind"] == "func_removed"
        assert data["impact"] == "breaking"
        assert data["default_verdict"] == "BREAKING"
        assert len(data["description"]) > 0
        assert "fix_guidance" in data

    def test_compatible_kind(self):
        raw = abi_explain_change("func_added")
        data = json.loads(raw)
        assert data["kind"] == "func_added"
        assert data["impact"] == "compatible"
        assert "backward-compatible" in data["fix_guidance"].lower() or "no action" in data["fix_guidance"].lower()

    def test_api_break_kind(self):
        raw = abi_explain_change("enum_member_renamed")
        data = json.loads(raw)
        assert data["kind"] == "enum_member_renamed"
        assert data["impact"] == "api_break"

    def test_unknown_kind(self):
        raw = abi_explain_change("totally_fake_kind")
        data = json.loads(raw)
        assert "error" in data

    def test_case_insensitive(self):
        raw = abi_explain_change("FUNC_REMOVED")
        data = json.loads(raw)
        assert data["kind"] == "func_removed"


# ---------------------------------------------------------------------------
# abi_compare
# ---------------------------------------------------------------------------

class TestAbiCompare:
    def test_breaking_change(self, snapshot_pair: tuple[Path, Path]):
        old_path, new_path = snapshot_pair
        raw = abi_compare(str(old_path), str(new_path))
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert data["verdict"] == "BREAKING"
        assert data["exit_code"] == 4
        assert data["summary"]["breaking"] > 0
        assert len(data["changes"]) > 0
        # Each change should have required fields
        for change in data["changes"]:
            assert "kind" in change
            assert "symbol" in change
            assert "description" in change
            assert "impact" in change

    def test_compatible_change(self, compatible_pair: tuple[Path, Path]):
        old_path, new_path = compatible_pair
        raw = abi_compare(str(old_path), str(new_path))
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert data["verdict"] == "COMPATIBLE"
        assert data["exit_code"] == 0
        assert data["summary"]["compatible"] > 0

    def test_no_change(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("init", "_Z4initv")])
        p = tmp_path / "snap.json"
        p.write_text(snapshot_to_json(snap), encoding="utf-8")
        raw = abi_compare(str(p), str(p))
        data = json.loads(raw)
        assert data["verdict"] == "NO_CHANGE"
        assert data["exit_code"] == 0
        assert data["summary"]["total_changes"] == 0

    def test_file_not_found(self, tmp_path: Path):
        raw = abi_compare(str(tmp_path / "nonexistent.json"), str(tmp_path / "also_gone.json"))
        data = json.loads(raw)
        assert "error" in data

    def test_report_included(self, snapshot_pair: tuple[Path, Path]):
        old_path, new_path = snapshot_pair
        raw = abi_compare(str(old_path), str(new_path), format="json")
        data = json.loads(raw)
        assert "report" in data
        # JSON report should be valid JSON
        report = json.loads(data["report"])
        assert "verdict" in report

    def test_markdown_format(self, snapshot_pair: tuple[Path, Path]):
        old_path, new_path = snapshot_pair
        raw = abi_compare(str(old_path), str(new_path), format="markdown")
        data = json.loads(raw)
        assert "report" in data
        assert "ABI Report" in data["report"]

    def test_suppressed_count(self, snapshot_pair: tuple[Path, Path]):
        old_path, new_path = snapshot_pair
        raw = abi_compare(str(old_path), str(new_path))
        data = json.loads(raw)
        assert "suppressed_count" in data


# ---------------------------------------------------------------------------
# abi_dump
# ---------------------------------------------------------------------------

class TestAbiDump:
    def test_dump_json_snapshot(self, tmp_path: Path):
        """Dump from an existing JSON snapshot (passthrough)."""
        snap = _make_snapshot("1.0", functions=[_pub_func("foo", "_Z3foov")])
        snap_path = tmp_path / "input.json"
        snap_path.write_text(snapshot_to_json(snap), encoding="utf-8")

        raw = abi_dump(str(snap_path))
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert "summary" in data
        assert data["summary"]["functions"] == 1

    def test_dump_to_file(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("foo", "_Z3foov")])
        snap_path = tmp_path / "input.json"
        snap_path.write_text(snapshot_to_json(snap), encoding="utf-8")
        out_path = tmp_path / "output.json"

        raw = abi_dump(str(snap_path), output_path=str(out_path))
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert data["output_path"] == str(out_path)
        assert out_path.exists()
        # Output should be valid JSON snapshot
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert "library" in loaded

    def test_dump_file_not_found(self):
        raw = abi_dump("/nonexistent/libfoo.so")
        data = json.loads(raw)
        assert "error" in data

    def test_dump_inline_snapshot(self, tmp_path: Path):
        """When no output_path, snapshot JSON is returned inline."""
        snap = _make_snapshot("2.0", variables=[_pub_var("counter", "counter", "int")])
        snap_path = tmp_path / "input.json"
        snap_path.write_text(snapshot_to_json(snap), encoding="utf-8")

        raw = abi_dump(str(snap_path))
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert "snapshot" in data
        assert data["summary"]["variables"] == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_impact_category_breaking(self):
        assert _impact_category(ChangeKind.FUNC_REMOVED) == "breaking"

    def test_impact_category_compatible(self):
        assert _impact_category(ChangeKind.FUNC_ADDED) == "compatible"

    def test_impact_category_api_break(self):
        assert _impact_category(ChangeKind.ENUM_MEMBER_RENAMED) == "api_break"

    def test_impact_category_risk(self):
        assert _impact_category(ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED) == "risk"

    def test_snapshot_summary(self):
        snap = _make_snapshot(
            "1.0",
            functions=[_pub_func("a", "_Z1av"), _pub_func("b", "_Z1bv")],
            variables=[_pub_var("x", "x", "int")],
        )
        summary = _snapshot_summary(snap)
        assert summary["functions"] == 2
        assert summary["variables"] == 1
        assert summary["library"] == "libtest.so.1"
        assert summary["version"] == "1.0"

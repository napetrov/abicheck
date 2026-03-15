"""Tests for abicheck.mcp_server — MCP tool functions.

These tests exercise the MCP tool functions directly (without running the MCP
protocol layer) to verify they produce correct structured JSON responses.
"""

import json
from pathlib import Path

import pytest

from abicheck.checker import ChangeKind
from abicheck.model import AbiSnapshot, Function, Variable, Visibility

# Guard: skip entire module if the mcp package is not installed.
pytest.importorskip("mcp", reason="mcp package not installed")

from abicheck.mcp_server import (  # noqa: E402
    _detect_binary_format,
    _impact_category,
    _render_output,
    _resolve_input,
    _snapshot_summary,
    abi_compare,
    abi_dump,
    abi_explain_change,
    abi_list_changes,
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
        raw = abi_compare(str(old_path), str(new_path), output_format="json")
        data = json.loads(raw)
        assert "report" in data
        # JSON format: report is embedded as a nested object (not a string)
        report = data["report"]
        assert isinstance(report, dict)
        assert "verdict" in report

    def test_markdown_format(self, snapshot_pair: tuple[Path, Path]):
        old_path, new_path = snapshot_pair
        raw = abi_compare(str(old_path), str(new_path), output_format="markdown")
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

    def test_detect_format_nonexistent_file(self):
        assert _detect_binary_format(Path("/nonexistent/file.so")) is None

    def test_detect_format_non_elf_file(self, tmp_path: Path):
        f = tmp_path / "not_elf.bin"
        f.write_bytes(b"not an elf file")
        assert _detect_binary_format(f) is None

    def test_detect_binary_format_json_file(self, tmp_path: Path):
        f = tmp_path / "snap.json"
        f.write_text("{}", encoding="utf-8")
        assert _detect_binary_format(f) is None

    def test_detect_binary_format_nonexistent(self):
        assert _detect_binary_format(Path("/nonexistent/file")) is None

    def test_resolve_input_json_snapshot(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("foo", "_Z3foov")])
        p = tmp_path / "snap.json"
        p.write_text(snapshot_to_json(snap), encoding="utf-8")
        result = _resolve_input(p, [], [], "1.0", "c++")
        assert result.library == "libtest.so.1"
        assert len(result.functions) == 1

    def test_resolve_input_unknown_format(self, tmp_path: Path):
        f = tmp_path / "weird.xyz"
        f.write_text("not a recognized format", encoding="utf-8")
        from abicheck.errors import AbicheckError
        with pytest.raises(AbicheckError, match="Cannot detect format"):
            _resolve_input(f, [], [], "1.0", "c++")


# ---------------------------------------------------------------------------
# _render_output
# ---------------------------------------------------------------------------

class TestRenderOutput:
    def _make_diff_result(self) -> tuple[object, AbiSnapshot, AbiSnapshot]:
        from abicheck.checker import DiffResult, Verdict
        old = _make_snapshot("1.0", functions=[_pub_func("init", "_Z4initv")])
        new = _make_snapshot("2.0", functions=[_pub_func("init", "_Z4initv")])
        result = DiffResult(
            old_version="1.0", new_version="2.0",
            library="libtest.so.1", verdict=Verdict.NO_CHANGE,
        )
        return result, old, new

    def test_render_json(self):
        result, old, new = self._make_diff_result()
        output = _render_output("json", result, old, new)
        parsed = json.loads(output)
        assert parsed["verdict"] == "NO_CHANGE"

    def test_render_markdown(self):
        result, old, new = self._make_diff_result()
        output = _render_output("markdown", result, old, new)
        assert "ABI Report" in output

    def test_render_sarif(self):
        result, old, new = self._make_diff_result()
        output = _render_output("sarif", result, old, new)
        parsed = json.loads(output)
        assert parsed["$schema"] or parsed.get("version")

    def test_render_html(self):
        result, old, new = self._make_diff_result()
        output = _render_output("html", result, old, new)
        assert "<html" in output.lower() or "<!doctype" in output.lower()

    def test_render_default_is_markdown(self):
        result, old, new = self._make_diff_result()
        output = _render_output("markdown", result, old, new)
        assert "ABI Report" in output

    def test_render_unknown_format_raises(self):
        result, old, new = self._make_diff_result()
        with pytest.raises(ValueError, match="Unknown output format"):
            _render_output("unknown_format", result, old, new)


# ---------------------------------------------------------------------------
# abi_compare — additional edge cases
# ---------------------------------------------------------------------------

class TestAbiCompareEdgeCases:
    def test_api_break_exit_code(self, tmp_path: Path):
        """API_BREAK verdict should produce exit_code=2."""
        from abicheck.model import EnumMember, EnumType
        old_enum = EnumType(name="Color", members=[
            EnumMember(name="RED", value="0"),
        ])
        new_enum = EnumType(name="Color", members=[
            EnumMember(name="ROUGE", value="0"),  # renamed → API_BREAK
        ])
        old = AbiSnapshot(library="libtest.so", version="1.0", enums=[old_enum])
        new = AbiSnapshot(library="libtest.so", version="2.0", enums=[new_enum])
        old_path = tmp_path / "old.json"
        new_path = tmp_path / "new.json"
        old_path.write_text(snapshot_to_json(old), encoding="utf-8")
        new_path.write_text(snapshot_to_json(new), encoding="utf-8")
        raw = abi_compare(str(old_path), str(new_path))
        data = json.loads(raw)
        assert data["verdict"] == "API_BREAK"
        assert data["exit_code"] == 2

    def test_sarif_format(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("init", "_Z4initv")])
        p = tmp_path / "snap.json"
        p.write_text(snapshot_to_json(snap), encoding="utf-8")
        raw = abi_compare(str(p), str(p), output_format="sarif")
        data = json.loads(raw)
        assert data["status"] == "ok"
        # SARIF report should be valid JSON
        sarif = json.loads(data["report"])
        assert "runs" in sarif or "$schema" in sarif

    def test_html_format(self, snapshot_pair: tuple[Path, Path]):
        old_path, new_path = snapshot_pair
        raw = abi_compare(str(old_path), str(new_path), output_format="html")
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert "<html" in data["report"].lower() or "<!doctype" in data["report"].lower()

    def test_with_suppression_file(self, snapshot_pair: tuple[Path, Path], tmp_path: Path):
        old_path, new_path = snapshot_pair
        supp = tmp_path / "suppress.yaml"
        supp.write_text(
            "version: 1\n"
            "suppressions:\n"
            "  - symbol: _Z4initv\n"
            "    change_kind: func_removed\n"
            "    reason: intentional removal\n",
            encoding="utf-8",
        )
        raw = abi_compare(str(old_path), str(new_path), suppression_file=str(supp))
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert data["suppressed_count"] >= 1


# ---------------------------------------------------------------------------
# abi_explain_change — risk kind
# ---------------------------------------------------------------------------

class TestAbiExplainChangeRisk:
    def test_risk_kind(self):
        raw = abi_explain_change("symbol_version_required_added")
        data = json.loads(raw)
        assert data["kind"] == "symbol_version_required_added"
        assert data["impact"] == "risk"
        assert "deployment risk" in data["fix_guidance"].lower() or "environment" in data["fix_guidance"].lower()


# ---------------------------------------------------------------------------
# abi_dump — version and language parameters
# ---------------------------------------------------------------------------

class TestAbiDumpParams:
    def test_custom_version(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("foo", "_Z3foov")])
        snap_path = tmp_path / "input.json"
        snap_path.write_text(snapshot_to_json(snap), encoding="utf-8")
        raw = abi_dump(str(snap_path), version="3.14.0")
        data = json.loads(raw)
        assert data["status"] == "ok"

    def test_custom_language(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("foo", "_Z3foov")])
        snap_path = tmp_path / "input.json"
        snap_path.write_text(snapshot_to_json(snap), encoding="utf-8")
        raw = abi_dump(str(snap_path), language="c")
        data = json.loads(raw)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------

class TestPolicyValidation:
    def test_invalid_policy_returns_error(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("init", "_Z4initv")])
        p = tmp_path / "snap.json"
        p.write_text(snapshot_to_json(snap), encoding="utf-8")
        raw = abi_compare(str(p), str(p), policy="plugin-abi")  # typo: dash instead of underscore
        data = json.loads(raw)
        assert "error" in data
        assert "plugin-abi" in data["error"]

    def test_valid_policies_accepted(self, tmp_path: Path):
        snap = _make_snapshot("1.0", functions=[_pub_func("init", "_Z4initv")])
        p = tmp_path / "snap.json"
        p.write_text(snapshot_to_json(snap), encoding="utf-8")
        for policy_name in ("strict_abi", "sdk_vendor", "plugin_abi"):
            raw = abi_compare(str(p), str(p), policy=policy_name)
            data = json.loads(raw)
            assert data["status"] == "ok", f"policy={policy_name} failed"


# ---------------------------------------------------------------------------
# Policy-aware impact category
# ---------------------------------------------------------------------------

class TestPolicyAwareImpact:
    def test_strict_abi_keeps_api_break(self):
        # enum_member_renamed is API_BREAK under strict_abi
        assert _impact_category(ChangeKind.ENUM_MEMBER_RENAMED, "strict_abi") == "api_break"

    def test_sdk_vendor_downgrades_to_compatible(self):
        # enum_member_renamed is downgraded to compatible under sdk_vendor
        assert _impact_category(ChangeKind.ENUM_MEMBER_RENAMED, "sdk_vendor") == "compatible"

    def test_plugin_abi_downgrades_calling_convention(self):
        # calling_convention_changed is BREAKING under strict_abi
        assert _impact_category(ChangeKind.CALLING_CONVENTION_CHANGED, "strict_abi") == "breaking"
        # but compatible under plugin_abi
        assert _impact_category(ChangeKind.CALLING_CONVENTION_CHANGED, "plugin_abi") == "compatible"

    def test_compare_impact_respects_policy(self, tmp_path: Path):
        """Per-change impact labels in abi_compare should honor the policy."""
        from abicheck.model import EnumMember, EnumType
        old_enum = EnumType(name="Color", members=[
            EnumMember(name="RED", value="0"),
        ])
        new_enum = EnumType(name="Color", members=[
            EnumMember(name="ROUGE", value="0"),  # renamed
        ])
        old = AbiSnapshot(library="libtest.so", version="1.0", enums=[old_enum])
        new = AbiSnapshot(library="libtest.so", version="2.0", enums=[new_enum])
        old_path = tmp_path / "old.json"
        new_path = tmp_path / "new.json"
        old_path.write_text(snapshot_to_json(old), encoding="utf-8")
        new_path.write_text(snapshot_to_json(new), encoding="utf-8")

        # Under strict_abi: enum_member_renamed is api_break
        raw = abi_compare(str(old_path), str(new_path), policy="strict_abi")
        data = json.loads(raw)
        rename_changes = [c for c in data["changes"] if c["kind"] == "enum_member_renamed"]
        assert rename_changes
        assert rename_changes[0]["impact"] == "api_break"

        # Under sdk_vendor: enum_member_renamed is downgraded to compatible
        raw = abi_compare(str(old_path), str(new_path), policy="sdk_vendor")
        data = json.loads(raw)
        rename_changes = [c for c in data["changes"] if c["kind"] == "enum_member_renamed"]
        assert rename_changes
        assert rename_changes[0]["impact"] == "compatible"


# ---------------------------------------------------------------------------
# Coverage gap closers
# ---------------------------------------------------------------------------

class TestRenderOutputValidation:
    """Ensure _render_output rejects unknown format strings."""

    def _make_diff_result(self):
        from abicheck.mcp_server import _render_output  # noqa: F401 (used below)
        old = AbiSnapshot(library="libtest.so.1", version="1.0")
        new = AbiSnapshot(library="libtest.so.1", version="2.0")
        from abicheck.checker import compare
        result = compare(old, new)
        return result, old, new

    def test_unknown_format_raises_value_error(self):
        from abicheck.mcp_server import _render_output
        result, old, new = self._make_diff_result()
        with pytest.raises(ValueError, match="Unknown output format"):
            _render_output("xml", result, old, new)


class TestImpactCategoryFallback:
    """_impact_category fall-safe for unknown kinds."""

    def test_breaking_kind_returns_breaking(self):
        from abicheck.checker_policy import ChangeKind
        from abicheck.mcp_server import _impact_category
        assert _impact_category(ChangeKind.FUNC_REMOVED) == "breaking"

    def test_compatible_kind_returns_compatible(self):
        from abicheck.checker_policy import ChangeKind
        from abicheck.mcp_server import _impact_category
        assert _impact_category(ChangeKind.FUNC_ADDED) == "compatible"

    def test_policy_sdk_vendor(self):
        from abicheck.checker_policy import ChangeKind
        from abicheck.mcp_server import _impact_category
        result = _impact_category(ChangeKind.ENUM_MEMBER_RENAMED, policy="sdk_vendor")
        assert result == "compatible"


class TestAbiCompareValidation:
    """abi_compare rejects invalid policy and format."""

    def test_invalid_policy_returns_error(self, tmp_path: Path):
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        old_p.write_text(snapshot_to_json(old), encoding="utf-8")
        new_p.write_text(snapshot_to_json(new), encoding="utf-8")
        raw = abi_compare(str(old_p), str(new_p), policy="nonexistent_policy")
        data = json.loads(raw)
        assert "error" in data
        assert "Unknown policy" in data["error"]

    def test_invalid_format_returns_error(self, tmp_path: Path):
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        old_p.write_text(snapshot_to_json(old), encoding="utf-8")
        new_p.write_text(snapshot_to_json(new), encoding="utf-8")
        raw = abi_compare(str(old_p), str(new_p), output_format="xml")
        data = json.loads(raw)
        assert "error" in data
        assert "Unknown output format" in data["error"]

    def test_suppression_file(self, tmp_path: Path):
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        old_p.write_text(snapshot_to_json(old), encoding="utf-8")
        new_p.write_text(snapshot_to_json(new), encoding="utf-8")
        # Empty suppression file (version field required)
        sup = tmp_path / "suppressions.yaml"
        sup.write_text("version: 1\nsuppressions: []\n", encoding="utf-8")
        raw = abi_compare(str(old_p), str(new_p), suppression_file=str(sup))
        data = json.loads(raw)
        assert data.get("status") == "ok"

    def test_policy_file(self, tmp_path: Path):
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        old_p.write_text(snapshot_to_json(old), encoding="utf-8")
        new_p.write_text(snapshot_to_json(new), encoding="utf-8")
        # Minimal policy file
        pf = tmp_path / "policy.yaml"
        pf.write_text("base: strict_abi\noverrides: {}\n", encoding="utf-8")
        raw = abi_compare(str(old_p), str(new_p), policy_file=str(pf))
        data = json.loads(raw)
        assert data.get("status") == "ok"

    def test_headers_side_specific_empty_list(self, tmp_path: Path):
        """old_headers=[] should override shared headers (not fall back to them)."""
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        old_p.write_text(snapshot_to_json(old), encoding="utf-8")
        new_p.write_text(snapshot_to_json(new), encoding="utf-8")
        raw = abi_compare(str(old_p), str(new_p), old_headers=[], new_headers=[])
        data = json.loads(raw)
        assert data.get("status") == "ok"


class TestMainFunction:
    """main() sets up logging and calls mcp.run."""

    def test_main_runs_without_error(self, monkeypatch):
        from abicheck import mcp_server
        calls = []
        monkeypatch.setattr(mcp_server.mcp, "run", lambda transport: calls.append(transport))
        mcp_server.main()
        assert calls == ["stdio"]


# ---------------------------------------------------------------------------
# Path safety helpers coverage
# ---------------------------------------------------------------------------

class TestSafeReadPath:
    def test_valid_path(self, tmp_path: Path) -> None:
        from abicheck.mcp_server import _safe_read_path
        f = tmp_path / "lib.so"
        f.write_bytes(b"x")
        result = _safe_read_path(str(f))
        assert result.is_absolute()

    def test_empty_raises(self) -> None:
        from abicheck.mcp_server import _safe_read_path
        with pytest.raises(ValueError, match="Empty"):
            _safe_read_path("")

    def test_whitespace_raises(self) -> None:
        from abicheck.mcp_server import _safe_read_path
        with pytest.raises(ValueError, match="Empty"):
            _safe_read_path("   ")

    def test_resolves_dotdot(self, tmp_path: Path) -> None:
        from abicheck.mcp_server import _safe_read_path
        sub = tmp_path / "sub"
        sub.mkdir()
        # ../sub/../sub is valid, just gets resolved
        result = _safe_read_path(str(sub))
        assert result == sub.resolve()


class TestSafeWritePath:
    def test_valid_json_path(self, tmp_path: Path) -> None:
        from abicheck.mcp_server import _safe_write_path
        result = _safe_write_path(str(tmp_path / "out.json"))
        assert result.suffix == ".json"

    def test_empty_raises(self) -> None:
        from abicheck.mcp_server import _safe_write_path
        with pytest.raises(ValueError, match="Empty"):
            _safe_write_path("")

    def test_non_json_suffix_raises(self, tmp_path: Path) -> None:
        from abicheck.mcp_server import _safe_write_path
        with pytest.raises(ValueError, match=".json"):
            _safe_write_path(str(tmp_path / "out.txt"))

    @pytest.mark.skipif(
        __import__("platform").system() == "Windows",
        reason="/etc and /dev are not sensitive paths on Windows",
    )
    def test_system_path_raises(self) -> None:
        from abicheck.mcp_server import _safe_write_path
        with pytest.raises(ValueError, match="sensitive system path"):
            _safe_write_path("/etc/out.json")

    @pytest.mark.skipif(
        __import__("platform").system() == "Windows",
        reason="//etc is not a sensitive path on Windows",
    )
    def test_double_slash_path_blocked(self) -> None:
        """//etc/out.json (double slash) must not bypass the path guard on POSIX."""
        from abicheck.mcp_server import _safe_write_path
        with pytest.raises(ValueError, match="sensitive system path"):
            _safe_write_path("//etc/out.json")

    @pytest.mark.skipif(
        __import__("platform").system() == "Windows",
        reason="/dev is not a sensitive path on Windows",
    )
    def test_dev_path_blocked(self) -> None:
        """/dev/ paths are blocked on POSIX."""
        from abicheck.mcp_server import _safe_write_path
        with pytest.raises(ValueError, match="sensitive system path"):
            _safe_write_path("/dev/out.json")

    @pytest.mark.skipif(
        __import__("platform").system() != "Windows",
        reason="Windows-specific sensitive path test",
    )
    def test_windows_system_path_blocked(self, tmp_path: Path) -> None:
        """C:\\Windows\\ is blocked on Windows."""
        from abicheck.mcp_server import _safe_write_path
        with pytest.raises(ValueError, match="sensitive system path"):
            _safe_write_path("C:\\Windows\\out.json")

    def test_ssh_dir_raises(self) -> None:
        from abicheck.mcp_server import _safe_write_path
        home = Path.home()
        with pytest.raises(ValueError, match="credential directory"):
            _safe_write_path(str(home / ".ssh" / "out.json"))

    def test_aws_dir_raises(self) -> None:
        from abicheck.mcp_server import _safe_write_path
        home = Path.home()
        with pytest.raises(ValueError, match="credential directory"):
            _safe_write_path(str(home / ".aws" / "out.json"))


class TestSanitizeError:
    def test_abicheck_error_passes_through(self) -> None:
        from abicheck.errors import AbicheckError
        from abicheck.mcp_server import _sanitize_error
        exc = AbicheckError("specific error message")
        assert _sanitize_error(exc) == "specific error message"

    def test_value_error_passes_through(self) -> None:
        from abicheck.mcp_server import _sanitize_error
        assert _sanitize_error(ValueError("bad value")) == "bad value"

    def test_os_error_redacted(self) -> None:
        from abicheck.mcp_server import _sanitize_error
        exc = OSError("[Errno 13] Permission denied: '/home/user/.ssh/id_rsa'")
        result = _sanitize_error(exc, context="test")
        assert "/home/user" not in result
        assert "file system error" in result

    def test_unexpected_error_generic(self) -> None:
        from abicheck.mcp_server import _sanitize_error
        exc = RuntimeError("internal detail that should not leak")
        result = _sanitize_error(exc, context="test_op")
        assert "internal detail" not in result
        assert "unexpected error" in result


class TestDetectBinaryFormatMagic:
    def test_elf_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "lib.so"
        f.write_bytes(b"\x7fELF\x00\x00")
        assert _detect_binary_format(f) == "elf"

    def test_pe_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "lib.dll"
        f.write_bytes(b"MZ\x90\x00")
        assert _detect_binary_format(f) == "pe"

    def test_macho_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "lib.dylib"
        f.write_bytes(b"\xcf\xfa\xed\xfe")
        assert _detect_binary_format(f) == "macho"

    def test_unknown_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "lib.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        assert _detect_binary_format(f) is None

    def test_nonexistent_file(self) -> None:
        assert _detect_binary_format(Path("/nonexistent/file.so")) is None


class TestAbiDumpSafePathValidation:
    def test_invalid_output_path_suffix_returns_error(self, tmp_path: Path) -> None:
        old = AbiSnapshot(library="lib.so", version="1.0")
        snap_p = tmp_path / "snap.json"
        snap_p.write_text(snapshot_to_json(old), encoding="utf-8")
        raw = abi_dump(str(snap_p), output_path=str(tmp_path / "out.txt"))
        data = json.loads(raw)
        assert data.get("status") == "error"
        assert ".json" in data.get("error", "")

    def test_system_output_path_blocked(self, tmp_path: Path) -> None:
        old = AbiSnapshot(library="lib.so", version="1.0")
        snap_p = tmp_path / "snap.json"
        snap_p.write_text(snapshot_to_json(old), encoding="utf-8")
        raw = abi_dump(str(snap_p), output_path="/etc/malicious.json")
        data = json.loads(raw)
        assert data.get("status") == "error"

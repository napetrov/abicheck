"""Tests for abi_check.reporter — JSON and Markdown output."""
import json

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.reporter import to_json, to_markdown


def _result(verdict: Verdict, changes=None) -> DiffResult:
    return DiffResult(
        old_version="1.0", new_version="2.0",
        library="libtest.so.1",
        changes=changes or [],
        verdict=verdict,
    )


class TestJsonReporter:
    def test_no_change_json(self):
        r = _result(Verdict.NO_CHANGE)
        d = json.loads(to_json(r))
        assert d["verdict"] == "NO_CHANGE"
        assert d["summary"]["total_changes"] == 0

    def test_breaking_json_has_changes(self):
        c = Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "Public function removed: foo")
        r = _result(Verdict.BREAKING, changes=[c])
        d = json.loads(to_json(r))
        assert d["verdict"] == "BREAKING"
        assert d["summary"]["breaking"] == 1
        assert d["changes"][0]["kind"] == "func_removed"


class TestMarkdownReporter:
    def test_no_change_contains_no_change(self):
        md = to_markdown(_result(Verdict.NO_CHANGE))
        assert "NO_CHANGE" in md
        assert "No ABI changes" in md

    def test_breaking_contains_section(self):
        c = Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "Public function removed: foo",
                   old_value="foo")
        md = to_markdown(_result(Verdict.BREAKING, [c]))
        assert "❌ Breaking Changes" in md
        assert "func_removed" in md

    def test_compatible_section(self):
        c = Change(ChangeKind.FUNC_ADDED, "_Z6newapiv", "New public function: new_api",
                   new_value="new_api")
        md = to_markdown(_result(Verdict.COMPATIBLE, [c]))
        assert "COMPATIBLE" in md
        assert "Additions" in md

    def test_noexcept_added_in_quality_section(self):
        c = Change(ChangeKind.FUNC_NOEXCEPT_ADDED, "_Z4swapv",
                   "noexcept specifier added: swap")
        md = to_markdown(_result(Verdict.COMPATIBLE, [c]))
        assert "COMPATIBLE" in md
        assert "Quality Issues" in md

    def test_legend_always_present(self):
        md = to_markdown(_result(Verdict.NO_CHANGE))
        assert "Legend" in md

    def test_risk_changes_in_json(self):
        """JSON summary must include risk_changes field with correct count."""
        c = Change(ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED, "libc.so.6",
                   "New GLIBC_2.34 version requirement added")
        r = _result(Verdict.COMPATIBLE_WITH_RISK, changes=[c])
        d = json.loads(to_json(r))
        assert d["verdict"] == "COMPATIBLE_WITH_RISK"
        assert "risk_changes" in d["summary"], "JSON summary must contain 'risk_changes' key"
        assert d["summary"]["risk_changes"] == 1
        assert d["summary"]["breaking"] == 0

    def test_risk_section_in_markdown(self):
        """Markdown must include Deployment Risk Changes section when risk > 0."""
        c = Change(ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED, "libc.so.6",
                   "New GLIBC_2.34 version requirement added")
        md = to_markdown(_result(Verdict.COMPATIBLE_WITH_RISK, [c]))
        assert "COMPATIBLE_WITH_RISK" in md
        assert "⚠️ Deployment Risk Changes" in md
        assert "binary-compatible" in md
        assert "symbol_version_required_added" in md

    def test_compatible_with_risk_emoji_in_markdown(self):
        """COMPATIBLE_WITH_RISK verdict uses ⚠️ emoji in header table."""
        c = Change(ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED, "libc.so.6",
                   "New GLIBC_2.34 version requirement added")
        md = to_markdown(_result(Verdict.COMPATIBLE_WITH_RISK, [c]))
        assert "⚠️ `COMPATIBLE_WITH_RISK`" in md


# ---------------------------------------------------------------------------
# Severity-aware reporter output
# ---------------------------------------------------------------------------

class TestSeverityMarkdown:
    """Tests for to_markdown with severity_config parameter."""

    def test_severity_badges_shown_when_config_provided(self):
        """Section headers include severity badges when severity_config is set."""
        from abicheck.severity import PRESET_DEFAULT
        c = Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "Public function removed: foo",
                   old_value="foo")
        md = to_markdown(_result(Verdict.BREAKING, [c]), severity_config=PRESET_DEFAULT)
        assert "`ERROR`" in md

    def test_severity_badges_absent_without_config(self):
        """Section headers do NOT include severity badges without severity_config."""
        c = Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "Public function removed: foo",
                   old_value="foo")
        md = to_markdown(_result(Verdict.BREAKING, [c]))
        assert "`ERROR`" not in md
        assert "`WARNING`" not in md
        assert "`INFO`" not in md

    def test_severity_summary_table_in_markdown(self):
        """Markdown includes a severity configuration table when config is provided."""
        from abicheck.severity import PRESET_STRICT
        c = Change(ChangeKind.FUNC_ADDED, "_Z6newapiv", "New public function: new_api")
        md = to_markdown(_result(Verdict.COMPATIBLE, [c]), severity_config=PRESET_STRICT)
        assert "Severity Configuration" in md
        assert "ABI/API Incompatibilities" in md
        assert "Additions" in md

    def test_severity_summary_absent_without_config(self):
        """Markdown does NOT include severity table without config."""
        c = Change(ChangeKind.FUNC_ADDED, "_Z6newapiv", "New public function: new_api")
        md = to_markdown(_result(Verdict.COMPATIBLE, [c]))
        assert "Severity Configuration" not in md

    def test_quality_section_with_severity_label(self):
        """Quality section shows severity badge when config is provided."""
        from abicheck.severity import PRESET_DEFAULT
        c = Change(ChangeKind.FUNC_NOEXCEPT_ADDED, "_Z4swapv",
                   "noexcept specifier added: swap")
        md = to_markdown(_result(Verdict.COMPATIBLE, [c]), severity_config=PRESET_DEFAULT)
        assert "Quality Issues" in md
        assert "`WARNING`" in md

    def test_additions_section_with_severity_label(self):
        """Additions section shows severity badge when config is provided."""
        from abicheck.severity import PRESET_DEFAULT
        c = Change(ChangeKind.FUNC_ADDED, "_Z6newapiv", "New public function: new_api")
        md = to_markdown(_result(Verdict.COMPATIBLE, [c]), severity_config=PRESET_DEFAULT)
        assert "Additions" in md
        assert "`INFO`" in md


class TestSeverityJson:
    """Tests for to_json with severity_config parameter."""

    def test_severity_section_in_json(self):
        """JSON output includes severity section when config is provided."""
        from abicheck.severity import PRESET_DEFAULT
        c = Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "Public function removed: foo")
        r = _result(Verdict.BREAKING, changes=[c])
        d = json.loads(to_json(r, severity_config=PRESET_DEFAULT))
        assert "severity" in d
        sev = d["severity"]
        assert "config" in sev
        assert sev["config"]["abi_breaking"] == "error"
        assert sev["config"]["addition"] == "info"
        assert "categories" in sev
        assert sev["categories"]["abi_breaking"]["count"] == 1

    def test_severity_absent_in_json_without_config(self):
        """JSON output does NOT include severity section without config."""
        c = Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "Public function removed: foo")
        r = _result(Verdict.BREAKING, changes=[c])
        d = json.loads(to_json(r))
        assert "severity" not in d

    def test_severity_exit_code_in_json(self):
        """JSON severity section includes computed exit_code."""
        from abicheck.severity import PRESET_STRICT
        c = Change(ChangeKind.FUNC_ADDED, "_Z6newapiv", "New public function: new_api")
        r = _result(Verdict.COMPATIBLE, changes=[c])
        d = json.loads(to_json(r, severity_config=PRESET_STRICT))
        assert d["severity"]["exit_code"] == 1

    def test_severity_category_counts(self):
        """JSON severity categories have correct counts for mixed changes."""
        from abicheck.severity import PRESET_DEFAULT
        changes = [
            Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "removed: foo"),
            Change(ChangeKind.FUNC_ADDED, "_Z3barv", "added: bar"),
            Change(ChangeKind.VISIBILITY_LEAK, "std::string", "std symbol exposed"),
        ]
        r = _result(Verdict.BREAKING, changes=changes)
        d = json.loads(to_json(r, severity_config=PRESET_DEFAULT))
        cats = d["severity"]["categories"]
        assert cats["abi_breaking"]["count"] == 1
        assert cats["addition"]["count"] == 1
        assert cats["quality_issues"]["count"] == 1
        assert cats["potential_breaking"]["count"] == 0

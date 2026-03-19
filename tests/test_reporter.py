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

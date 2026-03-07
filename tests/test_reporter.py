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
        assert "Compatible Additions" in md

    def test_noexcept_added_in_breaking_section(self):
        c = Change(ChangeKind.FUNC_NOEXCEPT_ADDED, "_Z4swapv",
                   "noexcept specifier added: swap")
        md = to_markdown(_result(Verdict.BREAKING, [c]))
        assert "BREAKING" in md
        assert "Breaking Changes" in md

    def test_legend_always_present(self):
        md = to_markdown(_result(Verdict.NO_CHANGE))
        assert "Legend" in md

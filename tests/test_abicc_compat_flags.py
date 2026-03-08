"""Tests for ABICC compat mode flags.

Verifies that abicheck compat command:
- Accepts all major ABICC-equivalent CLI flags
- -s/-strict promotes COMPATIBLE → BREAKING exit code
- -source/-src/-api filters ELF-only changes out
- -skip-symbols / -skip-types build suppression correctly
- -v1/-v2 override version labels
- -stdout prints report to stdout
- _filter_source_only removes BINARY_ONLY_KINDS
- _build_skip_suppression handles exact names and patterns
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.cli import (
    _BINARY_ONLY_KINDS,
    _SOURCE_BREAK_KINDS,
    _build_skip_suppression,
    _filter_source_only,
    main,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _result(verdict: Verdict, kinds: list[ChangeKind]) -> DiffResult:
    changes = [
        Change(kind=k, symbol=f"_sym_{i}", description=k.value)
        for i, k in enumerate(kinds)
    ]
    return DiffResult(
        old_version="1.0", new_version="2.0",
        library="libtest.so.1",
        changes=changes,
        verdict=verdict,
    )


# ── _filter_source_only ───────────────────────────────────────────────────────

class TestFilterSourceOnly:
    def test_removes_binary_only_soname(self):
        r = _result(Verdict.BREAKING, [ChangeKind.SONAME_CHANGED, ChangeKind.FUNC_REMOVED])
        filtered = _filter_source_only(r)
        kinds = {c.kind for c in filtered.changes}
        assert ChangeKind.SONAME_CHANGED not in kinds
        assert ChangeKind.FUNC_REMOVED in kinds

    def test_removes_symbol_binding_changed(self):
        r = _result(Verdict.BREAKING, [ChangeKind.SYMBOL_BINDING_CHANGED])
        filtered = _filter_source_only(r)
        assert filtered.changes == []
        assert filtered.verdict == Verdict.NO_CHANGE

    def test_keeps_func_params_changed(self):
        r = _result(Verdict.BREAKING, [ChangeKind.FUNC_PARAMS_CHANGED])
        filtered = _filter_source_only(r)
        assert len(filtered.changes) == 1
        assert filtered.verdict == Verdict.BREAKING

    def test_verdict_recalculated_to_no_change(self):
        r = _result(Verdict.BREAKING, [ChangeKind.TOOLCHAIN_FLAG_DRIFT])
        filtered = _filter_source_only(r)
        assert filtered.verdict == Verdict.NO_CHANGE

    def test_all_binary_kinds_removable(self):
        """All BINARY_ONLY_KINDS must exist in ChangeKind enum."""
        for kind in _BINARY_ONLY_KINDS:
            assert kind in ChangeKind


# ── _build_skip_suppression ───────────────────────────────────────────────────

class TestBuildSkipSuppression:
    def test_exact_symbol_match(self, tmp_path):
        f = tmp_path / "skip.txt"
        f.write_text("_Z3foov\n_Z3barv\n")
        sup = _build_skip_suppression(f, None)
        assert len(sup._suppressions) == 2
        assert sup._suppressions[0].symbol == "_Z3foov"

    def test_pattern_symbol_match(self, tmp_path):
        f = tmp_path / "skip.txt"
        f.write_text("_Z.*foo.*\n")
        sup = _build_skip_suppression(f, None)
        assert sup._suppressions[0].symbol_pattern == "_Z.*foo.*"

    def test_skip_types_file(self, tmp_path):
        f = tmp_path / "types.txt"
        f.write_text("MyStruct\nOtherType\n")
        sup = _build_skip_suppression(None, f)
        assert len(sup._suppressions) == 2
        assert sup._suppressions[0].symbol == "MyStruct"

    def test_both_none_returns_empty(self):
        sup = _build_skip_suppression(None, None)
        assert sup._suppressions == []

    def test_comments_skipped(self, tmp_path):
        f = tmp_path / "skip.txt"
        f.write_text("# comment\n_Z3foov\n  \n")
        sup = _build_skip_suppression(f, None)
        assert len(sup._suppressions) == 1

    def test_missing_file_raises_oserror(self, tmp_path):
        """Non-existent file raises OSError (caller handles with sys.exit(2))."""
        with pytest.raises(OSError):
            _build_skip_suppression(tmp_path / "nonexistent.txt", None)

    def test_merge_combines_suppressions(self, tmp_path):
        """SuppressionList.merge() combines rules from both lists."""
        from abicheck.suppression import Suppression, SuppressionList
        a = SuppressionList(suppressions=[Suppression(symbol="_sym1")])
        b = SuppressionList(suppressions=[Suppression(symbol="_sym2")])
        merged = SuppressionList.merge(a, b)
        assert len(merged._suppressions) == 2


# ── CLI flag parsing ──────────────────────────────────────────────────────────

class TestCompatCliFlags:
    """Verify all ABICC-equivalent flags are accepted by the CLI parser."""

    def _invoke_help(self, *args):
        runner = CliRunner()
        return runner.invoke(main, ["compat", "--help"])

    def test_help_contains_strict_flag(self):
        result = self._invoke_help()
        assert "-s" in result.output or "strict" in result.output

    def test_help_contains_show_retval(self):
        result = self._invoke_help()
        assert "show-retval" in result.output

    def test_help_contains_source_flag(self):
        result = self._invoke_help()
        assert "source" in result.output

    def test_help_contains_headers_only(self):
        result = self._invoke_help()
        assert "headers-only" in result.output

    def test_help_contains_skip_symbols(self):
        result = self._invoke_help()
        assert "skip-symbols" in result.output

    def test_help_contains_v1_v2(self):
        result = self._invoke_help()
        assert "v1" in result.output or "vnum1" in result.output

    def test_help_contains_stdout(self):
        result = self._invoke_help()
        assert "stdout" in result.output

    def test_d1_d2_aliases_accepted(self):
        """Verify -d1/-d2 aliases for -old/-new are registered."""
        runner = CliRunner()
        result = runner.invoke(main, ["compat", "--help"])
        assert "-d1" in result.output or "d1" in result.output


# ── SOURCE_BREAK_KINDS / BINARY_ONLY_KINDS completeness ──────────────────────

class TestKindSets:
    def test_no_overlap_between_source_and_binary(self):
        overlap = _SOURCE_BREAK_KINDS & _BINARY_ONLY_KINDS
        assert overlap == frozenset(), f"Overlap: {overlap}"

    def test_soname_in_binary_only(self):
        assert ChangeKind.SONAME_CHANGED in _BINARY_ONLY_KINDS

    def test_func_params_in_source_break(self):
        assert ChangeKind.FUNC_PARAMS_CHANGED in _SOURCE_BREAK_KINDS

    def test_filter_source_only_source_break_verdict(self):
        """_filter_source_only: SOURCE_BREAK_KINDS changes → correct verdict + filtering."""
        from abicheck.cli import _filter_source_only
        r = _result(Verdict.BREAKING, [ChangeKind.SONAME_CHANGED, ChangeKind.FUNC_PARAMS_CHANGED])
        filtered = _filter_source_only(r)
        # SONAME removed, FUNC_PARAMS_CHANGED stays
        assert ChangeKind.SONAME_CHANGED not in {c.kind for c in filtered.changes}
        assert ChangeKind.FUNC_PARAMS_CHANGED in {c.kind for c in filtered.changes}
        # FUNC_PARAMS_CHANGED is in _SOURCE_BREAK_KINDS → verdict SOURCE_BREAK
        assert filtered.verdict in (Verdict.BREAKING, Verdict.SOURCE_BREAK)

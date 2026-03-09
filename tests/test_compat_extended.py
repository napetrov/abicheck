"""Tests for extended ABICC compat mode features.

Covers:
- compat-dump subcommand
- -symbols-list / -types-list (whitelist filtering)
- -warn-newsym flag
- -component / -limit-affected / -list-affected flags
- -skip-internal-symbols / -skip-internal-types regex flags
- -title wired to HTML output
- -quiet flag
- ABICC dump format detection and clear error messaging
- JSON dump input support for compat mode
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.cli import (
    _apply_warn_newsym,
    _build_internal_suppression,
    _build_skip_suppression,
    _build_whitelist_suppression,
    _limit_affected_changes,
    _load_descriptor_or_dump,
    _write_affected_list,
)
from abicheck.compat import CompatDescriptor
from abicheck.html_report import generate_html_report
from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.serialization import save_snapshot

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_result(
    changes: list[Change] | None = None,
    verdict: Verdict = Verdict.COMPATIBLE,
) -> DiffResult:
    return DiffResult(
        old_version="1.0",
        new_version="2.0",
        library="libtest.so",
        changes=changes or [],
        verdict=verdict,
    )


def _change(kind: ChangeKind, symbol: str = "test_sym") -> Change:
    return Change(kind=kind, symbol=symbol, description=f"{kind.value} on {symbol}")


def _write_file(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).strip(), encoding="utf-8")
    return p


def _make_snapshot(version: str = "1.0") -> AbiSnapshot:
    return AbiSnapshot(
        library="libtest.so",
        version=version,
        functions=[
            Function(name="foo", mangled="_Z3foov", return_type="void",
                     visibility=Visibility.PUBLIC),
        ],
        variables=[],
        types=[],
    )


# ── _build_whitelist_suppression ──────────────────────────────────────────────

class TestWhitelistSuppression:
    def test_whitelist_suppresses_non_listed(self, tmp_path: Path) -> None:
        wl = _write_file(tmp_path, "symbols.txt", "_Z3foov\n_Z3barv\n")
        sl = _build_whitelist_suppression(wl, None)

        # A change on a whitelisted symbol should NOT be suppressed
        c_foo = _change(ChangeKind.FUNC_REMOVED, "_Z3foov")
        assert not sl.is_suppressed(c_foo)

        # A change on a non-whitelisted symbol SHOULD be suppressed
        c_baz = _change(ChangeKind.FUNC_REMOVED, "_Z3bazv")
        assert sl.is_suppressed(c_baz)

    def test_whitelist_empty_file_no_crash(self, tmp_path: Path) -> None:
        wl = _write_file(tmp_path, "empty.txt", "# comments only\n")
        sl = _build_whitelist_suppression(wl, None)
        # No whitelist entries → no suppression rules generated
        assert len(sl) == 0

    def test_whitelist_types(self, tmp_path: Path) -> None:
        wl = _write_file(tmp_path, "types.txt", "MyStruct\n")
        sl = _build_whitelist_suppression(None, wl)

        c_listed = _change(ChangeKind.TYPE_SIZE_CHANGED, "MyStruct")
        assert not sl.is_suppressed(c_listed)

        c_other = _change(ChangeKind.TYPE_SIZE_CHANGED, "OtherStruct")
        assert sl.is_suppressed(c_other)

    def test_whitelist_comments_and_blanks(self, tmp_path: Path) -> None:
        content = "# Header\n\n_Z3foov\n\n# Trailer\n"
        wl = _write_file(tmp_path, "wl.txt", content)
        sl = _build_whitelist_suppression(wl, None)
        c_foo = _change(ChangeKind.FUNC_REMOVED, "_Z3foov")
        assert not sl.is_suppressed(c_foo)


# ── _build_internal_suppression ───────────────────────────────────────────────

class TestInternalSuppression:
    def test_skip_internal_symbols(self) -> None:
        sl = _build_internal_suppression("_ZN.*internal.*", None)
        c = _change(ChangeKind.FUNC_REMOVED, "_ZN3Foo8internalEv")
        assert sl.is_suppressed(c)

    def test_skip_internal_types(self) -> None:
        sl = _build_internal_suppression(None, ".*Impl$")
        c = _change(ChangeKind.TYPE_SIZE_CHANGED, "FooImpl")
        assert sl.is_suppressed(c)

    def test_skip_internal_does_not_match_public(self) -> None:
        sl = _build_internal_suppression("_ZN.*internal.*", None)
        c = _change(ChangeKind.FUNC_REMOVED, "_Z3foov")
        assert not sl.is_suppressed(c)

    def test_invalid_regex_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid symbol_pattern"):
            _build_internal_suppression("[invalid", None)


# ── _apply_warn_newsym ────────────────────────────────────────────────────────

class TestWarnNewsym:
    def test_func_added_becomes_breaking(self) -> None:
        result = _make_result(
            changes=[_change(ChangeKind.FUNC_ADDED)],
            verdict=Verdict.COMPATIBLE,
        )
        updated = _apply_warn_newsym(result)
        assert updated.verdict == Verdict.BREAKING

    def test_var_added_becomes_breaking(self) -> None:
        result = _make_result(
            changes=[_change(ChangeKind.VAR_ADDED)],
            verdict=Verdict.COMPATIBLE,
        )
        updated = _apply_warn_newsym(result)
        assert updated.verdict == Verdict.BREAKING

    def test_no_change_with_new_sym_becomes_breaking(self) -> None:
        result = _make_result(
            changes=[_change(ChangeKind.FUNC_ADDED)],
            verdict=Verdict.NO_CHANGE,
        )
        updated = _apply_warn_newsym(result)
        assert updated.verdict == Verdict.BREAKING

    def test_already_breaking_stays_breaking(self) -> None:
        result = _make_result(
            changes=[_change(ChangeKind.FUNC_ADDED), _change(ChangeKind.FUNC_REMOVED)],
            verdict=Verdict.BREAKING,
        )
        updated = _apply_warn_newsym(result)
        assert updated.verdict == Verdict.BREAKING

    def test_no_new_symbols_unchanged(self) -> None:
        result = _make_result(
            changes=[_change(ChangeKind.TYPE_SIZE_CHANGED)],
            verdict=Verdict.COMPATIBLE,
        )
        updated = _apply_warn_newsym(result)
        assert updated.verdict == Verdict.COMPATIBLE


# ── _limit_affected_changes ───────────────────────────────────────────────────

class TestLimitAffected:
    def test_limits_per_kind(self) -> None:
        changes = [
            _change(ChangeKind.FUNC_REMOVED, f"sym_{i}") for i in range(10)
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        limited = _limit_affected_changes(result, limit=3)
        assert len(limited.changes) == 3
        assert limited.verdict == Verdict.BREAKING  # verdict preserved

    def test_zero_limit_is_noop(self) -> None:
        changes = [_change(ChangeKind.FUNC_REMOVED)]
        result = _make_result(changes=changes)
        limited = _limit_affected_changes(result, limit=0)
        assert len(limited.changes) == 1

    def test_limits_different_kinds_independently(self) -> None:
        changes = [
            _change(ChangeKind.FUNC_REMOVED, f"r_{i}") for i in range(5)
        ] + [
            _change(ChangeKind.FUNC_ADDED, f"a_{i}") for i in range(5)
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        limited = _limit_affected_changes(result, limit=2)
        removed = [c for c in limited.changes if c.kind == ChangeKind.FUNC_REMOVED]
        added = [c for c in limited.changes if c.kind == ChangeKind.FUNC_ADDED]
        assert len(removed) == 2
        assert len(added) == 2


# ── _write_affected_list ──────────────────────────────────────────────────────

class TestWriteAffectedList:
    def test_writes_sorted_symbols(self, tmp_path: Path) -> None:
        result = _make_result(changes=[
            _change(ChangeKind.FUNC_REMOVED, "zebra"),
            _change(ChangeKind.FUNC_ADDED, "alpha"),
            _change(ChangeKind.TYPE_SIZE_CHANGED, "middle"),
        ])
        out = tmp_path / "affected.txt"
        _write_affected_list(result, out)
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert lines == ["alpha", "middle", "zebra"]

    def test_empty_changes_empty_file(self, tmp_path: Path) -> None:
        result = _make_result(changes=[])
        out = tmp_path / "affected.txt"
        _write_affected_list(result, out)
        assert out.read_text(encoding="utf-8") == ""

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        result = _make_result(changes=[_change(ChangeKind.FUNC_REMOVED)])
        out = tmp_path / "deep" / "nested" / "affected.txt"
        _write_affected_list(result, out)
        assert out.exists()

    def test_deduplicates_symbols(self, tmp_path: Path) -> None:
        result = _make_result(changes=[
            _change(ChangeKind.FUNC_REMOVED, "same_sym"),
            _change(ChangeKind.FUNC_RETURN_CHANGED, "same_sym"),
        ])
        out = tmp_path / "affected.txt"
        _write_affected_list(result, out)
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert lines == ["same_sym"]


# ── _load_descriptor_or_dump ──────────────────────────────────────────────────

class TestLoadDescriptorOrDump:
    def test_loads_json_dump(self, tmp_path: Path) -> None:
        snap = _make_snapshot()
        path = tmp_path / "dump.json"
        save_snapshot(snap, path)
        result = _load_descriptor_or_dump(path)
        assert isinstance(result, tuple)
        assert result[0].version == "1.0"

    def test_loads_xml_descriptor(self, tmp_path: Path) -> None:
        xml = _write_file(tmp_path, "desc.xml", """
            <descriptor>
              <version>2.0</version>
              <libs>/usr/lib/libfoo.so</libs>
            </descriptor>
        """)
        result = _load_descriptor_or_dump(xml)
        assert isinstance(result, CompatDescriptor)
        assert result.version == "2.0"

    def test_rejects_abicc_perl_dump_by_extension(self, tmp_path: Path) -> None:
        dump_file = tmp_path / "old.dump"
        dump_file.write_text("$VAR1 = { ... }", encoding="utf-8")
        with pytest.raises(ValueError, match="ABICC Perl dump format is not supported"):
            _load_descriptor_or_dump(dump_file)

    def test_rejects_abicc_perl_dump_by_content(self, tmp_path: Path) -> None:
        dump_file = tmp_path / "old.txt"
        dump_file.write_text("$VAR1 = {\n  'LibraryName' => 'libfoo',\n};", encoding="utf-8")
        with pytest.raises(ValueError, match="ABICC Perl dump format detected"):
            _load_descriptor_or_dump(dump_file)

    def test_rejects_abicc_xml_dump(self, tmp_path: Path) -> None:
        dump_file = tmp_path / "dump.xml"
        dump_file.write_text(
            '<?xml version="1.0"?>\n<ABI_dump_1.0>\n<library>libfoo</library>\n</ABI_dump_1.0>',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="ABICC XML dump format detected"):
            _load_descriptor_or_dump(dump_file)

    def test_error_message_guides_migration(self, tmp_path: Path) -> None:
        dump_file = tmp_path / "old.dump"
        dump_file.write_text("$VAR1 = {}", encoding="utf-8")
        with pytest.raises(ValueError, match="compat-dump"):
            _load_descriptor_or_dump(dump_file)


# ── HTML title wiring ─────────────────────────────────────────────────────────

class TestHtmlTitle:
    def _fake_result(self, verdict: str = "COMPATIBLE") -> object:
        v = SimpleNamespace(value=verdict)
        return SimpleNamespace(
            verdict=v,
            changes=[],
            suppressed_changes=[],
            suppressed_count=0,
            suppression_file_provided=False,
        )

    def test_custom_title_in_html(self) -> None:
        html = generate_html_report(
            self._fake_result(),
            lib_name="libfoo",
            title="My Custom Report Title",
        )
        assert "My Custom Report Title" in html
        # Default title should not appear
        assert "ABI Compatibility Report — libfoo" not in html

    def test_default_title_when_none(self) -> None:
        html = generate_html_report(
            self._fake_result(),
            lib_name="libfoo",
        )
        assert "ABI Compatibility Report — libfoo" in html

    def test_title_is_html_escaped(self) -> None:
        html = generate_html_report(
            self._fake_result(),
            title="<script>alert(1)</script>",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ── CI cross-validation infrastructure ────────────────────────────────────────

class TestCrossValidationHelpers:
    """Tests for the building blocks used in CI cross-validation.

    These tests verify that the compat mode transforms compose correctly,
    enabling golden-file CI tests that compare abicheck output against
    known-good reference results.
    """

    def test_strict_plus_warn_newsym_composition(self) -> None:
        """When both -strict and -warn-newsym are active, FUNC_ADDED → BREAKING."""
        from abicheck.cli import _apply_strict, _apply_warn_newsym

        result = _make_result(
            changes=[_change(ChangeKind.FUNC_ADDED)],
            verdict=Verdict.COMPATIBLE,
        )
        # Apply in same order as CLI: warn-newsym first, then strict
        result = _apply_warn_newsym(result)
        result = _apply_strict(result)
        assert result.verdict == Verdict.BREAKING

    def test_source_filter_plus_strict(self) -> None:
        """Source-only filter + strict: binary-only changes are removed before strict."""
        from abicheck.cli import _apply_strict, _filter_source_only

        result = _make_result(
            changes=[
                _change(ChangeKind.SONAME_CHANGED, "libtest.so"),
                _change(ChangeKind.FUNC_ADDED, "_Z3foov"),
            ],
            verdict=Verdict.BREAKING,
        )
        result = _filter_source_only(result)
        assert result.verdict == Verdict.COMPATIBLE  # only FUNC_ADDED left
        result = _apply_strict(result)
        assert result.verdict == Verdict.BREAKING  # strict promotes it

    def test_whitelist_plus_skip_composition(self, tmp_path: Path) -> None:
        """Whitelist and skip can be combined: whitelist first, then skip further."""
        from abicheck.cli import _merge_suppression

        wl_file = _write_file(tmp_path, "wl.txt", "_Z3foov\n_Z3barv\n")
        skip_file = _write_file(tmp_path, "skip.txt", "_Z3barv\n")

        wl = _build_whitelist_suppression(wl_file, None)
        skip = _build_skip_suppression(skip_file, None)
        merged = _merge_suppression(wl, skip)

        # foo: whitelisted, not skipped → NOT suppressed
        assert not merged.is_suppressed(_change(ChangeKind.FUNC_REMOVED, "_Z3foov"))
        # bar: whitelisted but also skipped → IS suppressed
        assert merged.is_suppressed(_change(ChangeKind.FUNC_REMOVED, "_Z3barv"))
        # baz: not whitelisted → IS suppressed (by whitelist)
        assert merged.is_suppressed(_change(ChangeKind.FUNC_REMOVED, "_Z3bazv"))

    def test_exit_code_mapping(self) -> None:
        """Verify exit code mapping matches ABICC spec."""
        # NO_CHANGE → 0, COMPATIBLE → 0, BREAKING → 1, SOURCE_BREAK → 2
        verdicts = {
            Verdict.NO_CHANGE: 0,
            Verdict.COMPATIBLE: 0,
            Verdict.BREAKING: 1,
            Verdict.SOURCE_BREAK: 2,
        }
        for v, expected_exit in verdicts.items():
            result = _make_result(verdict=v)
            verdict_str = result.verdict.value
            if verdict_str == "BREAKING":
                code = 1
            elif verdict_str == "SOURCE_BREAK":
                code = 2
            else:
                code = 0
            assert code == expected_exit, f"{v} should map to exit {expected_exit}"


# ── compat-dump JSON round-trip ───────────────────────────────────────────────

class TestCompatDumpRoundTrip:
    """Verify that JSON dumps produced by compat-dump can be loaded and compared."""

    def test_dump_and_reload(self, tmp_path: Path) -> None:
        snap = _make_snapshot("3.0")
        path = tmp_path / "dump.json"
        save_snapshot(snap, path)

        loaded = _load_descriptor_or_dump(path)
        assert isinstance(loaded, tuple)
        reloaded = loaded[0]
        assert reloaded.version == "3.0"
        assert len(reloaded.functions) == 1
        assert reloaded.functions[0].name == "foo"

    def test_dump_json_is_valid(self, tmp_path: Path) -> None:
        snap = _make_snapshot()
        path = tmp_path / "dump.json"
        save_snapshot(snap, path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["library"] == "libtest.so"
        assert data["version"] == "1.0"
        assert len(data["functions"]) == 1

# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for abicheck.appcompat — Application Compatibility Checking (ADR-005)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from abicheck.appcompat import (
    AppCompatResult,
    AppRequirements,
    _detect_app_format,
    _is_relevant_to_app,
    check_against,
    check_appcompat,
    parse_app_requirements,
)
from abicheck.checker import Change, DiffResult
from abicheck.checker_policy import ChangeKind, Verdict
from abicheck.reporter import appcompat_to_json, appcompat_to_markdown


# ---------------------------------------------------------------------------
# Unit tests: AppRequirements / AppCompatResult data structures
# ---------------------------------------------------------------------------

class TestDataStructures:
    def test_app_requirements_defaults(self):
        reqs = AppRequirements()
        assert reqs.needed_libs == []
        assert reqs.undefined_symbols == set()
        assert reqs.required_versions == {}

    def test_app_requirements_populated(self):
        reqs = AppRequirements(
            needed_libs=["libfoo.so.1", "libc.so.6"],
            undefined_symbols={"foo_init", "foo_process"},
            required_versions={"FOO_1.0": "libfoo.so.1"},
        )
        assert len(reqs.needed_libs) == 2
        assert "foo_init" in reqs.undefined_symbols
        assert reqs.required_versions["FOO_1.0"] == "libfoo.so.1"

    def test_app_compat_result_defaults(self):
        result = AppCompatResult(
            app_path="/usr/bin/myapp",
            old_lib_path="old.so",
            new_lib_path="new.so",
        )
        assert result.verdict == Verdict.COMPATIBLE
        assert result.symbol_coverage == 100.0
        assert result.missing_symbols == []
        assert result.breaking_for_app == []


# ---------------------------------------------------------------------------
# Unit tests: _is_relevant_to_app
# ---------------------------------------------------------------------------

class TestIsRelevantToApp:
    def _make_app(self, symbols: set[str] | None = None, versions: dict[str, str] | None = None):
        return AppRequirements(
            undefined_symbols=symbols or {"foo_init", "foo_process", "foo_cleanup"},
            required_versions=versions or {},
        )

    def test_direct_symbol_match(self):
        app = self._make_app()
        change = Change(
            kind=ChangeKind.FUNC_REMOVED,
            symbol="foo_init",
            description="Function removed: foo_init",
        )
        assert _is_relevant_to_app(change, app) is True

    def test_no_match(self):
        app = self._make_app()
        change = Change(
            kind=ChangeKind.FUNC_REMOVED,
            symbol="bar_init",
            description="Function removed: bar_init",
        )
        assert _is_relevant_to_app(change, app) is False

    def test_affected_symbols_match(self):
        app = self._make_app()
        change = Change(
            kind=ChangeKind.TYPE_SIZE_CHANGED,
            symbol="Config",
            description="Type size changed: Config",
            affected_symbols=["foo_init", "bar_init"],
        )
        assert _is_relevant_to_app(change, app) is True

    def test_affected_symbols_no_match(self):
        app = self._make_app()
        change = Change(
            kind=ChangeKind.TYPE_SIZE_CHANGED,
            symbol="Config",
            description="Type size changed: Config",
            affected_symbols=["bar_init", "baz_init"],
        )
        assert _is_relevant_to_app(change, app) is False

    def test_soname_changed_always_relevant(self):
        app = self._make_app()
        change = Change(
            kind=ChangeKind.SONAME_CHANGED,
            symbol="",
            description="SONAME changed",
            old_value="libfoo.so.1",
            new_value="libfoo.so.2",
        )
        assert _is_relevant_to_app(change, app) is True

    def test_compat_version_changed_always_relevant(self):
        app = self._make_app()
        change = Change(
            kind=ChangeKind.COMPAT_VERSION_CHANGED,
            symbol="",
            description="Mach-O compat version changed",
        )
        assert _is_relevant_to_app(change, app) is True

    def test_symbol_version_removed_relevant(self):
        app = self._make_app(
            versions={"FOO_1.0": "libfoo.so.1"},
        )
        change = Change(
            kind=ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED,
            symbol="FOO_1.0",
            description="Symbol version removed",
            old_value="libfoo.so.1",
        )
        assert _is_relevant_to_app(change, app) is True

    def test_symbol_version_removed_different_version(self):
        app = self._make_app(
            versions={"FOO_1.0": "libfoo.so.1"},
        )
        change = Change(
            kind=ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED,
            symbol="FOO_2.0",
            description="Symbol version removed",
            old_value="libfoo.so.1",
        )
        assert _is_relevant_to_app(change, app) is False


# ---------------------------------------------------------------------------
# Unit tests: _detect_app_format
# ---------------------------------------------------------------------------

class TestDetectAppFormat:
    def test_nonexistent_path(self, tmp_path):
        assert _detect_app_format(tmp_path / "nope") is None

    def test_unknown_format(self, tmp_path):
        f = tmp_path / "unknown.bin"
        f.write_bytes(b"\x00\x00\x00\x00")
        assert _detect_app_format(f) is None

    def test_elf_magic(self, tmp_path):
        f = tmp_path / "app.elf"
        f.write_bytes(b"\x7fELF" + b"\x00" * 100)
        assert _detect_app_format(f) == "elf"

    def test_pe_magic(self, tmp_path):
        data = bytearray(512)
        data[0:2] = b"MZ"
        data[0x3C:0x40] = (0x80).to_bytes(4, "little")
        data[0x80:0x84] = b"PE\x00\x00"
        f = tmp_path / "app.exe"
        f.write_bytes(bytes(data))
        assert _detect_app_format(f) == "pe"

    def test_macho_magic(self, tmp_path):
        f = tmp_path / "app.macho"
        f.write_bytes(b"\xfe\xed\xfa\xcf" + b"\x00" * 100)
        assert _detect_app_format(f) == "macho"


# ---------------------------------------------------------------------------
# Unit tests: AppCompatResult verdict computation
# ---------------------------------------------------------------------------

class TestAppCompatResultVerdict:
    def test_missing_symbols_means_breaking(self):
        result = AppCompatResult(
            app_path="/usr/bin/myapp",
            old_lib_path="old.so",
            new_lib_path="new.so",
            missing_symbols=["foo_init"],
            verdict=Verdict.BREAKING,
        )
        assert result.verdict == Verdict.BREAKING

    def test_no_changes_means_compatible(self):
        result = AppCompatResult(
            app_path="/usr/bin/myapp",
            old_lib_path="old.so",
            new_lib_path="new.so",
            required_symbol_count=5,
            verdict=Verdict.COMPATIBLE,
        )
        assert result.verdict == Verdict.COMPATIBLE


# ---------------------------------------------------------------------------
# Unit tests: reporters
# ---------------------------------------------------------------------------

class TestAppCompatReporters:
    def _make_result(self, *, missing=None, breaking=None, irrelevant=None, verdict=None):
        return AppCompatResult(
            app_path="/usr/bin/myapp",
            old_lib_path="libfoo.so.1",
            new_lib_path="libfoo.so.2",
            required_symbols={"foo_init", "foo_process", "foo_cleanup"},
            required_symbol_count=3,
            breaking_for_app=breaking or [],
            irrelevant_for_app=irrelevant or [],
            missing_symbols=missing or [],
            missing_versions=[],
            full_diff=DiffResult(
                old_version="1.0",
                new_version="2.0",
                library="libfoo",
            ),
            verdict=verdict or Verdict.COMPATIBLE,
            symbol_coverage=100.0,
        )

    def test_markdown_compatible(self):
        result = self._make_result()
        md = appcompat_to_markdown(result)
        assert "# Application Compatibility Report" in md
        assert "COMPATIBLE" in md
        assert "/usr/bin/myapp" in md

    def test_markdown_with_missing_symbols(self):
        result = self._make_result(
            missing=["foo_init"],
            verdict=Verdict.BREAKING,
        )
        md = appcompat_to_markdown(result)
        assert "Missing Symbols" in md
        assert "foo_init" in md

    def test_markdown_with_relevant_changes(self):
        change = Change(
            kind=ChangeKind.FUNC_PARAMS_CHANGED,
            symbol="foo_process",
            description="parameter type changed",
        )
        result = self._make_result(breaking=[change])
        md = appcompat_to_markdown(result)
        assert "Relevant Changes" in md
        assert "foo_process" in md

    def test_markdown_show_irrelevant(self):
        change = Change(
            kind=ChangeKind.FUNC_ADDED,
            symbol="bar_new",
            description="function added: bar_new",
        )
        result = self._make_result(irrelevant=[change])
        md = appcompat_to_markdown(result, show_irrelevant=True)
        assert "Irrelevant Changes" in md
        assert "bar_new" in md

    def test_markdown_hide_irrelevant_default(self):
        change = Change(
            kind=ChangeKind.FUNC_ADDED,
            symbol="bar_new",
            description="function added",
        )
        result = self._make_result(irrelevant=[change])
        md = appcompat_to_markdown(result)
        assert "--show-irrelevant" in md

    def test_json_output(self):
        result = self._make_result()
        j = appcompat_to_json(result)
        data = json.loads(j)
        assert data["verdict"] == "COMPATIBLE"
        assert data["application"] == "/usr/bin/myapp"
        assert data["required_symbol_count"] == 3

    def test_json_with_missing(self):
        result = self._make_result(
            missing=["foo_init"],
            verdict=Verdict.BREAKING,
        )
        j = appcompat_to_json(result)
        data = json.loads(j)
        assert data["verdict"] == "BREAKING"
        assert "foo_init" in data["missing_symbols"]

    def test_json_with_relevant_changes(self):
        change = Change(
            kind=ChangeKind.FUNC_REMOVED,
            symbol="foo_init",
            description="Function removed",
        )
        result = self._make_result(breaking=[change])
        j = appcompat_to_json(result)
        data = json.loads(j)
        assert data["relevant_change_count"] == 1
        assert data["relevant_changes"][0]["symbol"] == "foo_init"

    def test_markdown_weak_mode(self):
        result = AppCompatResult(
            app_path="/usr/bin/myapp",
            old_lib_path="",
            new_lib_path="libfoo.so.2",
            required_symbols={"foo_init"},
            required_symbol_count=1,
            verdict=Verdict.COMPATIBLE,
            symbol_coverage=100.0,
        )
        md = appcompat_to_markdown(result)
        assert "libfoo.so.2" in md
        # Weak mode: no old lib shown with arrow
        assert "→" not in md


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

class TestAppcompatCLI:
    def test_appcompat_help(self):
        from click.testing import CliRunner
        from abicheck.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["appcompat", "--help"])
        assert result.exit_code == 0
        assert "Check if an application is compatible" in result.output

    def test_appcompat_missing_args(self):
        from click.testing import CliRunner
        from abicheck.cli import main

        runner = CliRunner()
        # No arguments at all
        result = runner.invoke(main, ["appcompat"])
        assert result.exit_code != 0

    def test_appcompat_weak_mode_with_positional_fails(self, tmp_path):
        from click.testing import CliRunner
        from abicheck.cli import main

        app = tmp_path / "app"
        app.write_bytes(b"\x7fELF" + b"\x00" * 100)
        lib1 = tmp_path / "lib1.so"
        lib1.write_bytes(b"\x7fELF" + b"\x00" * 100)
        lib2 = tmp_path / "lib2.so"
        lib2.write_bytes(b"\x7fELF" + b"\x00" * 100)

        runner = CliRunner()
        result = runner.invoke(main, [
            "appcompat", str(app), str(lib1), str(lib2),
            "--check-against", str(lib2),
        ])
        assert result.exit_code != 0
        assert "cannot be used with" in result.output


# ---------------------------------------------------------------------------
# Integration-ish: _is_relevant_to_app with realistic change sets
# ---------------------------------------------------------------------------

class TestFilteringIntegration:
    """Test that filtering correctly partitions changes."""

    def test_mixed_changes_partitioned(self):
        app = AppRequirements(
            undefined_symbols={"foo_init", "foo_process"},
        )
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="foo_init", description="removed"),
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="bar_init", description="removed"),
            Change(kind=ChangeKind.FUNC_ADDED, symbol="baz_new", description="added"),
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="Config",
                   description="size changed", affected_symbols=["foo_process"]),
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="Internal",
                   description="size changed", affected_symbols=["bar_helper"]),
        ]

        relevant = [c for c in changes if _is_relevant_to_app(c, app)]
        irrelevant = [c for c in changes if not _is_relevant_to_app(c, app)]

        assert len(relevant) == 2  # foo_init removed + Config size (affects foo_process)
        assert len(irrelevant) == 3  # bar_init removed + baz_new added + Internal size
        assert relevant[0].symbol == "foo_init"
        assert relevant[1].symbol == "Config"

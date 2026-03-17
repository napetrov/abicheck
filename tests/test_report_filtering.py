# Copyright 2026 Nikolay Petrov
# SPDX-License-Identifier: Apache-2.0

"""Tests for ADR-004: Report Filtering, Deduplication, and Leaf-Change Mode."""

from __future__ import annotations

import json

import pytest

from abicheck.checker import (
    Change,
    ChangeKind,
    DiffResult,
    Verdict,
    _filter_redundant,
    _match_root_type,
)
from abicheck.reporter import (
    ShowOnlyFilter,
    apply_show_only,
    to_json,
    to_markdown,
    to_stat,
    to_stat_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    changes: list[Change] | None = None,
    redundant_changes: list[Change] | None = None,
    verdict: Verdict = Verdict.BREAKING,
    policy: str = "strict_abi",
) -> DiffResult:
    return DiffResult(
        old_version="1.0",
        new_version="2.0",
        library="libtest.so",
        changes=changes or [],
        verdict=verdict,
        policy=policy,
        redundant_changes=redundant_changes or [],
        redundant_count=len(redundant_changes) if redundant_changes else 0,
    )


# ---------------------------------------------------------------------------
# _filter_redundant tests
# ---------------------------------------------------------------------------

class TestFilterRedundant:
    def test_no_root_types_returns_all(self):
        """When no root type changes exist, all changes are kept."""
        changes = [
            Change(ChangeKind.FUNC_REMOVED, "foo", "removed"),
            Change(ChangeKind.FUNC_ADDED, "bar", "added"),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 2
        assert len(redundant) == 0

    def test_type_change_causes_func_params_redundancy(self):
        """FUNC_PARAMS_CHANGED referencing a root type is redundant."""
        changes = [
            Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed from 64 to 72 bytes"),
            Change(
                ChangeKind.FUNC_PARAMS_CHANGED, "config_init",
                "parameter type changed in config_init(Config*)",
                old_value="Config (64 bytes)",
                new_value="Config (72 bytes)",
            ),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 1
        assert kept[0].kind == ChangeKind.TYPE_SIZE_CHANGED
        assert len(redundant) == 1
        assert redundant[0].kind == ChangeKind.FUNC_PARAMS_CHANGED
        assert redundant[0].caused_by_type == "Config"

    def test_root_annotated_with_caused_count(self):
        """Root change gets caused_count and derived symbols."""
        changes = [
            Change(ChangeKind.TYPE_SIZE_CHANGED, "Point", "size changed"),
            Change(
                ChangeKind.FUNC_PARAMS_CHANGED, "draw",
                "parameter type changed: Point",
                old_value="Point (8 bytes)",
            ),
            Change(
                ChangeKind.FUNC_RETURN_CHANGED, "get_point",
                "return type changed: Point",
                new_value="Point (16 bytes)",
            ),
        ]
        kept, redundant = _filter_redundant(changes)
        root = kept[0]
        assert root.kind == ChangeKind.TYPE_SIZE_CHANGED
        assert root.caused_count == 2
        assert len(redundant) == 2

    def test_func_removed_always_independent(self):
        """FUNC_REMOVED is never redundant even if type changed."""
        changes = [
            Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed"),
            Change(ChangeKind.FUNC_REMOVED, "config_init", "removed", old_value="Config*"),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 2
        assert len(redundant) == 0

    def test_unrelated_func_params_not_redundant(self):
        """FUNC_PARAMS_CHANGED not referencing root type is kept."""
        changes = [
            Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed"),
            Change(
                ChangeKind.FUNC_PARAMS_CHANGED, "process",
                "parameter count changed",
                old_value="int",
                new_value="int, int",
            ),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 2
        assert len(redundant) == 0

    def test_nested_type_field_type_changed_redundancy(self):
        """TYPE_FIELD_TYPE_CHANGED referencing a root type is redundant."""
        changes = [
            Change(ChangeKind.TYPE_SIZE_CHANGED, "Point", "size changed"),
            Change(
                ChangeKind.TYPE_FIELD_TYPE_CHANGED, "Container::pos",
                "field type changed: Point",
                old_value="Point (8 bytes)",
                new_value="Point (16 bytes)",
            ),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 1
        assert len(redundant) == 1

    def test_elf_changes_always_independent(self):
        """ELF-level changes are never redundant."""
        changes = [
            Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed"),
            Change(ChangeKind.SONAME_CHANGED, "libfoo.so", "SONAME changed"),
            Change(ChangeKind.NEEDED_ADDED, "libbar.so", "new dep added"),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 3
        assert len(redundant) == 0

    def test_var_type_changed_redundancy(self):
        """VAR_TYPE_CHANGED referencing a root type is redundant."""
        changes = [
            Change(ChangeKind.ENUM_MEMBER_REMOVED, "Status", "member removed"),
            Change(
                ChangeKind.VAR_TYPE_CHANGED, "current_status",
                "variable type changed: Status",
                old_value="Status",
                new_value="Status",
            ),
        ]
        kept, redundant = _filter_redundant(changes)
        assert len(kept) == 1
        assert len(redundant) == 1

    def test_qualified_symbol_matches_root(self):
        """Root type with :: qualifier matches base type name."""
        changes = [
            Change(ChangeKind.TYPE_FIELD_REMOVED, "Container::flags", "field removed"),
            Change(
                ChangeKind.FUNC_PARAMS_CHANGED, "process",
                "param type changed: Container",
                old_value="Container (64)",
            ),
        ]
        kept, redundant = _filter_redundant(changes)
        # Container::flags root type name is "Container"
        assert len(kept) == 1
        assert len(redundant) == 1


class TestMatchRootType:
    def test_matches_in_old_value(self):
        c = Change(ChangeKind.FUNC_PARAMS_CHANGED, "foo", "desc", old_value="Config*")
        assert _match_root_type(c, {"Config": Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "")}) == "Config"

    def test_matches_in_description(self):
        c = Change(ChangeKind.FUNC_RETURN_CHANGED, "bar", "return type changed: Config")
        assert _match_root_type(c, {"Config": Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "")}) == "Config"

    def test_no_match_returns_none(self):
        c = Change(ChangeKind.FUNC_PARAMS_CHANGED, "foo", "param count changed", old_value="int")
        assert _match_root_type(c, {"Config": Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "")}) is None


# ---------------------------------------------------------------------------
# ShowOnlyFilter tests
# ---------------------------------------------------------------------------

class TestShowOnlyFilter:
    def test_parse_severity_tokens(self):
        f = ShowOnlyFilter.parse("breaking,api-break")
        assert f.severities == frozenset({"breaking", "api-break"})
        assert not f.elements
        assert not f.actions

    def test_parse_mixed_tokens(self):
        f = ShowOnlyFilter.parse("breaking,functions,removed")
        assert f.severities == frozenset({"breaking"})
        assert f.elements == frozenset({"functions"})
        assert f.actions == frozenset({"removed"})

    def test_parse_unknown_token_raises(self):
        with pytest.raises(ValueError, match="Unknown --show-only token"):
            ShowOnlyFilter.parse("bogus")

    def test_severity_filter_breaking(self):
        f = ShowOnlyFilter.parse("breaking")
        c_break = Change(ChangeKind.FUNC_REMOVED, "foo", "removed")
        c_compat = Change(ChangeKind.FUNC_ADDED, "bar", "added")
        assert f.matches(c_break)
        assert not f.matches(c_compat)

    def test_element_filter_functions(self):
        f = ShowOnlyFilter.parse("functions")
        c_func = Change(ChangeKind.FUNC_REMOVED, "foo", "removed")
        c_type = Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size changed")
        assert f.matches(c_func)
        assert not f.matches(c_type)

    def test_action_filter_removed(self):
        f = ShowOnlyFilter.parse("removed")
        c_removed = Change(ChangeKind.FUNC_REMOVED, "foo", "removed")
        c_added = Change(ChangeKind.FUNC_ADDED, "bar", "added")
        c_changed = Change(ChangeKind.FUNC_PARAMS_CHANGED, "baz", "changed")
        assert f.matches(c_removed)
        assert not f.matches(c_added)
        assert not f.matches(c_changed)

    def test_cross_dimension_and(self):
        """breaking AND functions → only breaking function changes."""
        f = ShowOnlyFilter.parse("breaking,functions")
        c_func_removed = Change(ChangeKind.FUNC_REMOVED, "foo", "removed")
        c_type_changed = Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size changed")
        c_func_added = Change(ChangeKind.FUNC_ADDED, "bar", "added")  # not breaking
        assert f.matches(c_func_removed)
        assert not f.matches(c_type_changed)
        assert not f.matches(c_func_added)

    def test_within_dimension_or(self):
        """types,enums → types OR enums."""
        f = ShowOnlyFilter.parse("types,enums")
        c_type = Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size")
        c_enum = Change(ChangeKind.ENUM_MEMBER_REMOVED, "E", "member")
        c_func = Change(ChangeKind.FUNC_REMOVED, "f", "removed")
        assert f.matches(c_type)
        assert f.matches(c_enum)
        assert not f.matches(c_func)


class TestApplyShowOnly:
    def test_filters_changes(self):
        changes = [
            Change(ChangeKind.FUNC_REMOVED, "foo", "removed"),
            Change(ChangeKind.FUNC_ADDED, "bar", "added"),
            Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size changed"),
        ]
        result = apply_show_only(changes, "functions")
        assert len(result) == 2
        assert all(c.kind.value.startswith("func_") for c in result)


# ---------------------------------------------------------------------------
# Stat mode tests
# ---------------------------------------------------------------------------

class TestStatMode:
    def test_stat_text_output(self):
        result = _make_result(
            changes=[
                Change(ChangeKind.FUNC_REMOVED, "foo", "removed"),
                Change(ChangeKind.FUNC_ADDED, "bar", "added"),
            ],
        )
        text = to_stat(result)
        assert "BREAKING" in text
        assert "1 breaking" in text
        assert "1 compatible" in text
        assert "2 total" in text

    def test_stat_json_output(self):
        result = _make_result(
            changes=[
                Change(ChangeKind.FUNC_REMOVED, "foo", "removed"),
            ],
        )
        text = to_stat_json(result)
        d = json.loads(text)
        assert d["verdict"] == "BREAKING"
        assert "summary" in d
        assert "changes" not in d  # stat mode: no changes array

    def test_stat_with_redundant_count(self):
        result = _make_result(
            changes=[Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size")],
            redundant_changes=[Change(ChangeKind.FUNC_PARAMS_CHANGED, "f", "changed")],
        )
        text = to_stat(result)
        assert "1 redundant hidden" in text

    def test_stat_via_to_markdown(self):
        result = _make_result(
            changes=[Change(ChangeKind.FUNC_REMOVED, "foo", "removed")],
        )
        text = to_markdown(result, stat=True)
        assert "BREAKING" in text
        assert "total" in text

    def test_stat_via_to_json(self):
        result = _make_result(
            changes=[Change(ChangeKind.FUNC_REMOVED, "foo", "removed")],
        )
        text = to_json(result, stat=True)
        d = json.loads(text)
        assert "changes" not in d


# ---------------------------------------------------------------------------
# Leaf mode tests
# ---------------------------------------------------------------------------

class TestLeafMode:
    def test_leaf_markdown(self):
        result = _make_result(
            changes=[
                Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed from 64 to 72 bytes",
                       affected_symbols=["config_init", "config_load"]),
                Change(ChangeKind.FUNC_REMOVED, "old_api", "function removed: old_api"),
            ],
        )
        text = to_markdown(result, report_mode="leaf")
        assert "leaf-change view" in text
        assert "Config" in text
        assert "config_init" in text
        assert "Non-Type Changes" in text
        assert "old_api" in text

    def test_leaf_json(self):
        result = _make_result(
            changes=[
                Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed",
                       affected_symbols=["f1", "f2"]),
                Change(ChangeKind.FUNC_REMOVED, "old_api", "removed"),
            ],
        )
        text = to_json(result, report_mode="leaf")
        d = json.loads(text)
        assert "leaf_changes" in d
        assert "non_type_changes" in d
        assert len(d["leaf_changes"]) == 1
        assert d["leaf_changes"][0]["symbol"] == "Config"
        assert d["leaf_changes"][0]["affected_count"] == 2
        assert len(d["non_type_changes"]) == 1


# ---------------------------------------------------------------------------
# Show-impact tests
# ---------------------------------------------------------------------------

class TestShowImpact:
    def test_impact_in_markdown(self):
        root = Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed",
                      affected_symbols=["f1", "f2", "f3"])
        root.caused_count = 3
        result = _make_result(changes=[root])
        text = to_markdown(result, show_impact=True)
        assert "Impact Summary" in text
        assert "Config" in text

    def test_impact_in_json(self):
        result = _make_result(
            changes=[Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed",
                           affected_symbols=["f1"])],
        )
        text = to_json(result, show_impact=True)
        d = json.loads(text)
        assert "show_only_applied" in d  # impact-related key


# ---------------------------------------------------------------------------
# Show-only in markdown/json
# ---------------------------------------------------------------------------

class TestShowOnlyInReporters:
    def test_show_only_in_markdown(self):
        result = _make_result(
            changes=[
                Change(ChangeKind.FUNC_REMOVED, "foo", "removed"),
                Change(ChangeKind.FUNC_ADDED, "bar", "added"),
                Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size"),
            ],
        )
        text = to_markdown(result, show_only="functions")
        assert "Filtered by" in text
        assert "2 of 3 changes shown" in text

    def test_show_only_in_json(self):
        result = _make_result(
            changes=[
                Change(ChangeKind.FUNC_REMOVED, "foo", "removed"),
                Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size"),
            ],
        )
        text = to_json(result, show_only="breaking")
        d = json.loads(text)
        # Both FUNC_REMOVED and TYPE_SIZE_CHANGED are breaking
        assert len(d["changes"]) == 2


# ---------------------------------------------------------------------------
# Redundancy note in markdown
# ---------------------------------------------------------------------------

class TestRedundancyNote:
    def test_redundancy_note_shown(self):
        result = _make_result(
            changes=[Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size")],
            redundant_changes=[Change(ChangeKind.FUNC_PARAMS_CHANGED, "f", "changed")],
        )
        text = to_markdown(result)
        assert "1 redundant change(s) hidden" in text
        assert "--show-redundant" in text

    def test_no_redundancy_note_when_zero(self):
        result = _make_result(
            changes=[Change(ChangeKind.FUNC_REMOVED, "foo", "removed")],
        )
        text = to_markdown(result)
        assert "redundant" not in text


# ---------------------------------------------------------------------------
# Change model new fields
# ---------------------------------------------------------------------------

class TestChangeModelFields:
    def test_caused_by_type_default_none(self):
        c = Change(ChangeKind.FUNC_REMOVED, "foo", "removed")
        assert c.caused_by_type is None
        assert c.caused_count == 0

    def test_caused_count_in_json(self):
        c = Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size")
        c.caused_count = 5
        result = _make_result(changes=[c])
        text = to_json(result)
        d = json.loads(text)
        assert d["changes"][0]["caused_count"] == 5


# ---------------------------------------------------------------------------
# DiffResult new fields
# ---------------------------------------------------------------------------

class TestDiffResultFields:
    def test_redundant_changes_default_empty(self):
        result = DiffResult(
            old_version="1", new_version="2", library="lib.so",
        )
        assert result.redundant_changes == []
        assert result.redundant_count == 0

    def test_redundant_count_in_json(self):
        result = _make_result(
            changes=[Change(ChangeKind.TYPE_SIZE_CHANGED, "T", "size")],
            redundant_changes=[Change(ChangeKind.FUNC_PARAMS_CHANGED, "f", "changed")],
        )
        text = to_json(result)
        d = json.loads(text)
        assert d["redundant_count"] == 1


# ---------------------------------------------------------------------------
# Caused-count in markdown format
# ---------------------------------------------------------------------------

class TestCausedCountInMarkdown:
    def test_caused_count_shown(self):
        c = Change(ChangeKind.TYPE_SIZE_CHANGED, "Config", "size changed 64 -> 72")
        c.caused_count = 12
        c.affected_symbols = ["f1", "f2"]
        result = _make_result(changes=[c])
        text = to_markdown(result)
        assert "12 derived change(s) collapsed" in text

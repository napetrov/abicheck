"""Tests for SARIF 2.1.0 output (Sprint 7)."""
from __future__ import annotations

import json

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.sarif import to_sarif, to_sarif_str


def _make_result(
    changes: list[Change],
    verdict: Verdict = Verdict.BREAKING,
    library: str = "libfoo.so.1",
    old: str = "1.0",
    new: str = "2.0",
) -> DiffResult:
    return DiffResult(
        old_version=old,
        new_version=new,
        library=library,
        changes=changes,
        verdict=verdict,
    )


def _breaking_change() -> Change:
    return Change(
        kind=ChangeKind.FUNC_REMOVED,
        symbol="_Z3foov",
        description="Function foo() removed",
    )


def _compatible_change() -> Change:
    return Change(
        kind=ChangeKind.FUNC_ADDED,
        symbol="_Z3barv",
        description="Function bar() added",
    )


def _valued_change() -> Change:
    return Change(
        kind=ChangeKind.FUNC_RETURN_CHANGED,
        symbol="_Z7get_valv",
        description="Return type changed",
        old_value="int",
        new_value="long",
    )


# ---------------------------------------------------------------------------
# Schema structure tests
# ---------------------------------------------------------------------------

class TestSarifSchema:
    def test_top_level_keys(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        assert doc["version"] == "2.1.0"
        assert "$schema" in doc
        assert "runs" in doc
        assert len(doc["runs"]) == 1

    def test_tool_driver(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        driver = doc["runs"][0]["tool"]["driver"]
        assert driver["name"] == "abicheck"
        assert "version" in driver
        assert "informationUri" in driver

    def test_rules_populated(self) -> None:
        doc = to_sarif(_make_result([_breaking_change(), _compatible_change()]))
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = {r["id"] for r in rules}
        assert "func_removed" in rule_ids
        assert "func_added" in rule_ids

    def test_rules_deduplicated(self) -> None:
        """Two changes of same kind → one rule."""
        c1 = Change(kind=ChangeKind.FUNC_REMOVED, symbol="foo", description="foo removed")
        c2 = Change(kind=ChangeKind.FUNC_REMOVED, symbol="bar", description="bar removed")
        doc = to_sarif(_make_result([c1, c2]))
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        func_removed_rules = [r for r in rules if r["id"] == "func_removed"]
        assert len(func_removed_rules) == 1

    def test_results_count(self) -> None:
        doc = to_sarif(_make_result([_breaking_change(), _compatible_change()]))
        assert len(doc["runs"][0]["results"]) == 2

    def test_empty_changes(self) -> None:
        doc = to_sarif(_make_result([], verdict=Verdict.NO_CHANGE))
        assert doc["runs"][0]["results"] == []
        assert doc["runs"][0]["tool"]["driver"]["rules"] == []


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

class TestSeverityMapping:
    def test_func_removed_is_error(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        result = doc["runs"][0]["results"][0]
        assert result["level"] == "error"

    def test_func_added_is_warning(self) -> None:
        doc = to_sarif(_make_result([_compatible_change()], verdict=Verdict.COMPATIBLE))
        result = doc["runs"][0]["results"][0]
        assert result["level"] == "warning"

    def test_rule_default_level_breaking(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["defaultConfiguration"]["level"] == "error"

    def test_rule_default_level_compatible(self) -> None:
        doc = to_sarif(_make_result([_compatible_change()], verdict=Verdict.COMPATIBLE))
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["defaultConfiguration"]["level"] == "warning"

    def test_rule_help_uri_uses_policy_doc_slug(self) -> None:
        doc = to_sarif(_make_result([_compatible_change()], verdict=Verdict.COMPATIBLE))
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["helpUri"].endswith("#func_added")


# ---------------------------------------------------------------------------
# Result content
# ---------------------------------------------------------------------------

class TestResultContent:
    def test_result_message_plain(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        msg = doc["runs"][0]["results"][0]["message"]["text"]
        assert "Function foo() removed" in msg

    def test_result_message_with_values(self) -> None:
        doc = to_sarif(_make_result([_valued_change()]))
        msg = doc["runs"][0]["results"][0]["message"]["text"]
        assert "int" in msg
        assert "long" in msg
        assert "→" in msg

    def test_result_rule_id(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        result = doc["runs"][0]["results"][0]
        assert result["ruleId"] == "func_removed"

    def test_result_location_symbol(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        locs = doc["runs"][0]["results"][0]["locations"]
        assert locs[0]["logicalLocations"][0]["name"] == "_Z3foov"

    def test_result_location_library(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()], library="libbar.so.2"))
        locs = doc["runs"][0]["results"][0]["locations"]
        assert locs[0]["physicalLocation"]["artifactLocation"]["uri"] == "libbar.so.2"

    def test_result_properties(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        props = doc["runs"][0]["results"][0]["properties"]
        assert props["symbol"] == "_Z3foov"
        assert props["oldVersion"] == "1.0"
        assert props["newVersion"] == "2.0"


# ---------------------------------------------------------------------------
# Invocation / automation details
# ---------------------------------------------------------------------------

class TestInvocation:
    def test_invocation_breaking_not_successful(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()], verdict=Verdict.BREAKING))
        assert doc["runs"][0]["invocations"][0]["executionSuccessful"] is False

    def test_invocation_no_change_successful(self) -> None:
        doc = to_sarif(_make_result([], verdict=Verdict.NO_CHANGE))
        assert doc["runs"][0]["invocations"][0]["executionSuccessful"] is True

    def test_automation_details_id(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()], library="libfoo.so.1", old="1.0", new="2.0"))
        aid = doc["runs"][0]["automationDetails"]["id"]
        assert "abicheck/libfoo.so.1/1.0_to_2.0" == aid

    def test_run_properties(self) -> None:
        doc = to_sarif(_make_result([_breaking_change()]))
        props = doc["runs"][0]["properties"]
        assert props["abiVerdict"] == "BREAKING"
        assert props["changeCount"] == 1


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_sarif_str_is_valid_json(self) -> None:
        s = to_sarif_str(_make_result([_breaking_change()]))
        parsed = json.loads(s)
        assert parsed["version"] == "2.1.0"

    def test_to_sarif_str_indented(self) -> None:
        s = to_sarif_str(_make_result([]), indent=4)
        assert "    " in s  # 4-space indent present

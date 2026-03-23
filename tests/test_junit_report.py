"""Tests for JUnit XML output."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from abicheck.checker_types import Change, DiffResult
from abicheck.checker_policy import ChangeKind, Verdict
from abicheck.junit_report import to_junit_xml, to_junit_xml_multi
from abicheck.model import AbiSnapshot, Function, RecordType, Variable, EnumType, EnumMember


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_snapshot(
    library: str = "libfoo.so.1",
    version: str = "1.0",
    functions: list[Function] | None = None,
    types: list[RecordType] | None = None,
    variables: list[Variable] | None = None,
    enums: list[EnumType] | None = None,
) -> AbiSnapshot:
    s = AbiSnapshot(library=library, version=version)
    if functions:
        s.functions = functions
    if types:
        s.types = types
    if variables:
        s.variables = variables
    if enums:
        s.enums = enums
    return s


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


# ---------------------------------------------------------------------------
# Schema structure tests
# ---------------------------------------------------------------------------

class TestJUnitSchema:
    def test_top_level_element(self) -> None:
        xml = to_junit_xml(_make_result([]))
        root = _parse(xml)
        assert root.tag == "testsuites"
        assert root.get("name") == "abicheck"

    def test_single_testsuite(self) -> None:
        xml = to_junit_xml(_make_result([]))
        root = _parse(xml)
        suites = root.findall("testsuite")
        assert len(suites) == 1
        assert suites[0].get("name") == "libfoo.so.1"

    def test_errors_always_zero(self) -> None:
        xml = to_junit_xml(_make_result([]))
        root = _parse(xml)
        assert root.get("errors") == "0"
        assert root.find("testsuite").get("errors") == "0"

    def test_xml_declaration(self) -> None:
        xml = to_junit_xml(_make_result([]))
        assert xml.startswith("<?xml version='1.0' encoding='UTF-8'?>")


# ---------------------------------------------------------------------------
# No changes → all pass
# ---------------------------------------------------------------------------

class TestNoChanges:
    def test_no_changes_no_snapshot(self) -> None:
        xml = to_junit_xml(
            _make_result([], verdict=Verdict.NO_CHANGE),
        )
        root = _parse(xml)
        assert root.get("tests") == "0"
        assert root.get("failures") == "0"

    def test_no_changes_with_snapshot(self) -> None:
        snap = _make_snapshot(functions=[
            Function(name="foo::bar", mangled="_ZN3foo3barEv", return_type="void"),
            Function(name="foo::baz", mangled="_ZN3foo3bazEi", return_type="int"),
        ])
        result = _make_result([], verdict=Verdict.NO_CHANGE)
        xml = to_junit_xml(result, snap)
        root = _parse(xml)
        ts = root.find("testsuite")
        assert ts.get("tests") == "2"
        assert ts.get("failures") == "0"
        # All testcases pass (no <failure> children)
        for tc in ts.findall("testcase"):
            assert tc.find("failure") is None


# ---------------------------------------------------------------------------
# Breaking changes → failures
# ---------------------------------------------------------------------------

class TestBreakingChanges:
    def test_func_removed_is_failure(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.FUNC_REMOVED,
                symbol="_ZN3foo6legacyEv",
                description="Function foo::legacy() was removed",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        ts = root.find("testsuite")
        assert ts.get("failures") == "1"
        tc = ts.find("testcase")
        assert tc.get("name") == "_ZN3foo6legacyEv"
        assert tc.get("classname") == "functions"
        fail = tc.find("failure")
        assert fail is not None
        assert "BREAKING" in fail.get("type")
        assert "func_removed" in fail.get("message")

    def test_type_size_changed_is_failure(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.TYPE_SIZE_CHANGED,
                symbol="struct foo::Config",
                description="size changed from 16 to 24 bytes",
                old_value="16",
                new_value="24",
                source_location="include/foo.h:42",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        tc = root.find(".//testcase[@name='struct foo::Config']")
        assert tc is not None
        assert tc.get("classname") == "types"
        fail = tc.find("failure")
        assert fail is not None
        assert "Source: include/foo.h:42" in fail.text

    def test_func_added_passes(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.FUNC_ADDED,
                symbol="_ZN3foo9new_thingEv",
                description="Function foo::new_thing() was added",
            ),
        ]
        xml = to_junit_xml(_make_result(changes, verdict=Verdict.COMPATIBLE))
        root = _parse(xml)
        ts = root.find("testsuite")
        assert ts.get("failures") == "0"
        tc = ts.find("testcase")
        assert tc.find("failure") is None

    def test_mixed_changes(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.FUNC_REMOVED,
                symbol="_ZN3foo6legacyEv",
                description="Function removed",
            ),
            Change(
                kind=ChangeKind.FUNC_ADDED,
                symbol="_ZN3foo9new_thingEv",
                description="Function added",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        ts = root.find("testsuite")
        assert ts.get("tests") == "2"
        assert ts.get("failures") == "1"


# ---------------------------------------------------------------------------
# Suppressed changes → pass
# ---------------------------------------------------------------------------

class TestSuppressedChanges:
    def test_suppressed_symbols_appear_as_passing(self) -> None:
        """Symbols that were suppressed (not in changes list) should still
        appear as passing test cases when the old snapshot is provided."""
        snap = _make_snapshot(functions=[
            Function(name="foo::bar", mangled="_ZN3foo3barEv", return_type="void"),
            Function(name="foo::suppressed", mangled="_ZN3foo10suppressedEv", return_type="void"),
        ])
        # Only one change — the suppressed one is not in the changes list
        changes = [
            Change(
                kind=ChangeKind.FUNC_REMOVED,
                symbol="_ZN3foo3barEv",
                description="Function removed",
            ),
        ]
        result = _make_result(changes)
        xml = to_junit_xml(result, snap)
        root = _parse(xml)
        ts = root.find("testsuite")
        assert ts.get("tests") == "2"
        assert ts.get("failures") == "1"
        # The suppressed symbol passes
        suppressed_tc = ts.find(".//testcase[@name='_ZN3foo10suppressedEv']")
        assert suppressed_tc is not None
        assert suppressed_tc.find("failure") is None


# ---------------------------------------------------------------------------
# XML escaping of C++ mangled names with templates
# ---------------------------------------------------------------------------

class TestXmlEscaping:
    def test_template_symbol_escaping(self) -> None:
        """C++ mangled names with angle brackets must be properly escaped."""
        changes = [
            Change(
                kind=ChangeKind.FUNC_REMOVED,
                symbol="_ZN3foo3barINS_3BazIiEEEEvT_",
                description="Function foo::bar<foo::Baz<int>>() removed",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        # This should parse without error — if escaping is wrong, ET.fromstring fails
        root = _parse(xml)
        tc = root.find(".//testcase")
        assert tc.get("name") == "_ZN3foo3barINS_3BazIiEEEEvT_"

    def test_description_with_angle_brackets(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.FUNC_RETURN_CHANGED,
                symbol="_ZN3foo3barEv",
                description="Return type changed from std::vector<int> to std::vector<long>",
                old_value="std::vector<int>",
                new_value="std::vector<long>",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        fail = root.find(".//failure")
        assert "std::vector<int>" in fail.text or "std::vector&lt;int&gt;" in ET.tostring(fail, encoding="unicode")


# ---------------------------------------------------------------------------
# Failure attributes
# ---------------------------------------------------------------------------

class TestFailureAttributes:
    def test_failure_message_format(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.FUNC_RETURN_CHANGED,
                symbol="_ZN3foo3bazEv",
                description="Return type changed from int to long",
                old_value="int",
                new_value="long",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        fail = root.find(".//failure")
        msg = fail.get("message")
        assert msg == "func_return_changed: Return type changed from int to long"

    def test_failure_body_includes_values(self) -> None:
        changes = [
            Change(
                kind=ChangeKind.TYPE_SIZE_CHANGED,
                symbol="MyStruct",
                description="size changed",
                old_value="16",
                new_value="24",
            ),
        ]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        fail = root.find(".//failure")
        assert "(16 → 24)" in fail.text


# ---------------------------------------------------------------------------
# Classname grouping
# ---------------------------------------------------------------------------

class TestClassnameGrouping:
    def test_function_classname(self) -> None:
        changes = [Change(kind=ChangeKind.FUNC_REMOVED, symbol="f", description="")]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        assert root.find(".//testcase").get("classname") == "functions"

    def test_variable_classname(self) -> None:
        changes = [Change(kind=ChangeKind.VAR_REMOVED, symbol="v", description="")]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        assert root.find(".//testcase").get("classname") == "variables"

    def test_type_classname(self) -> None:
        changes = [Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="T", description="")]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        assert root.find(".//testcase").get("classname") == "types"

    def test_enum_classname(self) -> None:
        changes = [Change(kind=ChangeKind.ENUM_MEMBER_REMOVED, symbol="E", description="")]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        assert root.find(".//testcase").get("classname") == "enums"

    def test_elf_metadata_classname(self) -> None:
        changes = [Change(kind=ChangeKind.SONAME_CHANGED, symbol="soname", description="")]
        xml = to_junit_xml(_make_result(changes))
        root = _parse(xml)
        assert root.find(".//testcase").get("classname") == "metadata"


# ---------------------------------------------------------------------------
# Multi-suite (compare-release)
# ---------------------------------------------------------------------------

class TestMultiSuite:
    def test_multiple_testsuites(self) -> None:
        r1 = _make_result(
            [Change(kind=ChangeKind.FUNC_REMOVED, symbol="f1", description="removed")],
            library="libfoo.so.1",
        )
        r2 = _make_result(
            [],
            library="libbar.so.2",
            verdict=Verdict.NO_CHANGE,
        )
        xml = to_junit_xml_multi([(r1, None), (r2, None)])
        root = _parse(xml)
        suites = root.findall("testsuite")
        assert len(suites) == 2
        assert suites[0].get("name") == "libfoo.so.1"
        assert suites[1].get("name") == "libbar.so.2"

    def test_rollup_counts(self) -> None:
        r1 = _make_result(
            [Change(kind=ChangeKind.FUNC_REMOVED, symbol="f1", description="removed")],
            library="libfoo.so.1",
        )
        r2 = _make_result(
            [Change(kind=ChangeKind.FUNC_ADDED, symbol="f2", description="added")],
            library="libbar.so.2",
            verdict=Verdict.COMPATIBLE,
        )
        xml = to_junit_xml_multi([(r1, None), (r2, None)])
        root = _parse(xml)
        assert root.get("tests") == "2"
        assert root.get("failures") == "1"

    def test_empty_multi(self) -> None:
        xml = to_junit_xml_multi([])
        root = _parse(xml)
        assert root.get("tests") == "0"
        assert root.get("failures") == "0"
        assert root.findall("testsuite") == []


# ---------------------------------------------------------------------------
# With full snapshot — pass rate
# ---------------------------------------------------------------------------

class TestWithSnapshot:
    def test_pass_rate_includes_all_symbols(self) -> None:
        """Total test count includes unchanged symbols from old snapshot."""
        snap = _make_snapshot(
            functions=[
                Function(name="f1", mangled="f1", return_type="void"),
                Function(name="f2", mangled="f2", return_type="void"),
                Function(name="f3", mangled="f3", return_type="void"),
            ],
            types=[
                RecordType(name="MyStruct", kind="struct"),
            ],
        )
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="f1", description="removed"),
        ]
        result = _make_result(changes)
        xml = to_junit_xml(result, snap)
        root = _parse(xml)
        ts = root.find("testsuite")
        # 3 functions + 1 type = 4 total
        assert ts.get("tests") == "4"
        assert ts.get("failures") == "1"

    def test_additions_included_in_count(self) -> None:
        """New symbols (not in old snapshot) should also be counted."""
        snap = _make_snapshot(
            functions=[
                Function(name="f1", mangled="f1", return_type="void"),
            ],
        )
        changes = [
            Change(kind=ChangeKind.FUNC_ADDED, symbol="f2", description="added"),
        ]
        result = _make_result(changes, verdict=Verdict.COMPATIBLE)
        xml = to_junit_xml(result, snap)
        root = _parse(xml)
        ts = root.find("testsuite")
        # f1 (from snapshot) + f2 (addition) = 2
        assert ts.get("tests") == "2"
        assert ts.get("failures") == "0"


# ---------------------------------------------------------------------------
# Valid XML output
# ---------------------------------------------------------------------------

class TestValidXml:
    def test_output_is_valid_xml(self) -> None:
        """Output must be parseable XML."""
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="sym1", description="desc"),
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="T1", description="size",
                   old_value="8", new_value="16"),
            Change(kind=ChangeKind.FUNC_ADDED, symbol="sym2", description="added"),
        ]
        xml = to_junit_xml(_make_result(changes))
        # Should not raise
        root = ET.fromstring(xml)
        assert root.tag == "testsuites"

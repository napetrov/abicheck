"""Tests for ABICC-compatible XML report generation.

Validates that our XML output matches the real ABICC XML schema so that
abi-tracker, lvc-monitor, and distro infrastructure can parse it.

Real ABICC XML structure:
    <reports>
      <report kind="binary" version="1.2">
        <test_info><library>...</library>...</test_info>
        <test_results><verdict>...</verdict>...</test_results>
        <problem_summary>...</problem_summary>
        <added_symbols>...</added_symbols>
        <removed_symbols>...</removed_symbols>
        <problems_with_types severity="High">...</problems_with_types>
        ...
      </report>
      <report kind="source" version="1.2">...</report>
    </reports>
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.xml_report import generate_xml_report, write_xml_report


def _make_result(
    changes: list[Change] | None = None,
    verdict: Verdict = Verdict.NO_CHANGE,
) -> DiffResult:
    return DiffResult(
        old_version="1.0",
        new_version="2.0",
        library="libtest",
        changes=changes or [],
        verdict=verdict,
    )


class TestXmlReportStructure:
    """Verify the XML report matches the real ABICC schema."""

    def test_root_element_is_reports(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        assert root.tag == "reports"

    def test_has_binary_and_source_report_elements(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        reports = root.findall("report")
        assert len(reports) == 2
        kinds = {r.get("kind") for r in reports}
        assert kinds == {"binary", "source"}

    def test_report_version_attribute(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        for report in root.findall("report"):
            assert report.get("version") == "1.2"

    def test_test_info_section(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo",
                                  old_version="1.0", new_version="2.0")
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        test_info = binary.find("test_info")
        assert test_info is not None
        assert test_info.find("library").text == "libfoo"
        assert test_info.find("version1/number").text == "1.0"
        assert test_info.find("version2/number").text == "2.0"

    def test_test_results_section(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        test_results = binary.find("test_results")
        assert test_results is not None
        assert test_results.find("verdict") is not None
        assert test_results.find("affected") is not None
        assert test_results.find("symbols") is not None

    def test_problem_summary_section(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        summary = binary.find("problem_summary")
        assert summary is not None
        assert summary.find("added_symbols") is not None
        assert summary.find("removed_symbols") is not None
        assert summary.find("problems_with_types") is not None
        assert summary.find("problems_with_symbols") is not None

    def test_problem_summary_severity_tiers(self):
        """ABICC classifies problems into High/Medium/Low/Safe tiers."""
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        summary = root.find("report[@kind='binary']/problem_summary")
        types = summary.find("problems_with_types")
        for sev in ("high", "medium", "low", "safe"):
            el = types.find(sev)
            assert el is not None, f"Missing <problems_with_types>/<{sev}>"
            assert el.text == "0"

    def test_xml_declaration_present(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        assert xml.startswith("<?xml ")


class TestXmlReportCounts:
    """Verify counts and verdicts in the XML report."""

    def test_no_changes_compatible_verdict(self):
        result = _make_result(verdict=Verdict.NO_CHANGE)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        assert binary.find("test_results/verdict").text == "compatible"
        summary = binary.find("problem_summary")
        assert summary.find("added_symbols").text == "0"
        assert summary.find("removed_symbols").text == "0"

    def test_func_removed_counts_as_removed(self):
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        assert binary.find("test_results/verdict").text == "incompatible"
        assert binary.find("problem_summary/removed_symbols").text == "1"

    def test_func_added_counts_as_added(self):
        changes = [
            Change(kind=ChangeKind.FUNC_ADDED, symbol="_Z3barv",
                   description="bar() added"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.COMPATIBLE)
        xml = generate_xml_report(result)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        assert binary.find("test_results/verdict").text == "compatible"
        assert binary.find("problem_summary/added_symbols").text == "1"

    def test_type_problem_classified_by_severity(self):
        changes = [
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="MyStruct",
                   description="size changed", old_value="8", new_value="16"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=5)
        root = ET.fromstring(xml)
        summary = root.find("report[@kind='binary']/problem_summary")
        types = summary.find("problems_with_types")
        # TYPE_SIZE_CHANGED is High severity
        assert types.find("high").text == "1"
        assert types.find("medium").text == "0"

    def test_func_return_changed_is_medium_severity(self):
        changes = [
            Change(kind=ChangeKind.FUNC_RETURN_CHANGED, symbol="_Z3foov",
                   description="return type changed", old_value="int", new_value="long"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        summary = root.find("report[@kind='binary']/problem_summary")
        syms = summary.find("problems_with_symbols")
        assert syms.find("medium").text == "1"

    def test_source_section_excludes_binary_only_kinds(self):
        changes = [
            Change(kind=ChangeKind.SONAME_CHANGED, symbol="libfoo.so",
                   description="soname changed"),
            Change(kind=ChangeKind.FUNC_RETURN_CHANGED, symbol="_Z3foov",
                   description="return type changed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        # Source section excludes SONAME_CHANGED (binary-only)
        source = root.find("report[@kind='source']")
        source_summary = source.find("problem_summary")
        # Only func_return_changed should be present (medium severity symbol problem)
        syms = source_summary.find("problems_with_symbols")
        assert syms.find("medium").text == "1"


class TestXmlReportDetailSections:
    """Verify detail sections contain per-change data."""

    def test_added_symbols_detail(self):
        changes = [
            Change(kind=ChangeKind.FUNC_ADDED, symbol="_Z3barv",
                   description="bar() added"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.COMPATIBLE)
        xml = generate_xml_report(result)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        added = binary.find("added_symbols")
        assert added is not None
        names = [n.text for n in added.findall("name")]
        assert "_Z3barv" in names

    def test_removed_symbols_detail(self):
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        removed = binary.find("removed_symbols")
        assert removed is not None
        names = [n.text for n in removed.findall("name")]
        assert "_Z3foov" in names

    def test_type_problem_detail_section(self):
        changes = [
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="MyStruct",
                   description="size changed from 8 to 16",
                   old_value="8", new_value="16"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=5)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        # Should have <problems_with_types severity="High"> detail section
        type_probs = binary.findall("problems_with_types[@severity='High']")
        assert len(type_probs) == 1
        type_el = type_probs[0].find("type")
        assert type_el is not None
        assert type_el.get("name") == "MyStruct"
        prob = type_el.find("problem")
        assert prob.get("id") == "type_size_changed"
        change_el = prob.find("change")
        assert change_el.get("old_value") == "8"
        assert change_el.get("new_value") == "16"

    def test_symbol_problem_detail_section(self):
        changes = [
            Change(kind=ChangeKind.FUNC_RETURN_CHANGED, symbol="_Z3foov",
                   description="return type changed",
                   old_value="int", new_value="long"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        sym_probs = binary.findall("problems_with_symbols[@severity='Medium']")
        assert len(sym_probs) == 1
        sym_el = sym_probs[0].find("symbol")
        assert sym_el.get("name") == "_Z3foov"

    def test_no_detail_sections_when_no_changes(self):
        result = _make_result()
        xml = generate_xml_report(result)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        # No detail sections should be present
        assert binary.find("added_symbols") is None
        assert binary.find("removed_symbols") is None
        assert binary.find("problems_with_types[@severity]") is None


class TestXmlReportParsability:
    """Simulate how abi-tracker / lvc-monitor would parse the XML report."""

    def test_abi_tracker_bc_percentage_extraction(self):
        """abi-tracker computes BC from affected/symbols counts."""
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, lib_name="libfoo", old_symbol_count=10)
        root = ET.fromstring(xml)
        # Navigate like abi-tracker: report[@kind='binary']/test_results/verdict
        binary = root.find("report[@kind='binary']")
        verdict = binary.find("test_results/verdict").text
        assert verdict == "incompatible"

    def test_abi_tracker_problem_summary_extraction(self):
        """abi-tracker reads problem_summary/removed_symbols and severity counts."""
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="MyStruct",
                   description="size changed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        summary = root.find("report[@kind='binary']/problem_summary")
        removed = int(summary.find("removed_symbols").text)
        assert removed == 1
        high_types = int(summary.find("problems_with_types/high").text)
        assert high_types == 1

    def test_mixed_changes_full_extraction(self):
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
            Change(kind=ChangeKind.FUNC_ADDED, symbol="_Z3barv",
                   description="bar() added"),
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="MyStruct",
                   description="size changed"),
            Change(kind=ChangeKind.FUNC_RETURN_CHANGED, symbol="_Z3bazv",
                   description="return type changed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, lib_name="libfoo", old_symbol_count=20)
        root = ET.fromstring(xml)
        binary = root.find("report[@kind='binary']")
        summary = binary.find("problem_summary")

        assert summary.find("removed_symbols").text == "1"
        assert summary.find("added_symbols").text == "1"
        # type_size_changed → High type problem
        assert summary.find("problems_with_types/high").text == "1"
        # func_return_changed → Medium symbol problem
        assert summary.find("problems_with_symbols/medium").text == "1"


class TestWriteXmlReport:
    def test_writes_valid_xml_file(self, tmp_path: Path):
        result = _make_result()
        out = tmp_path / "sub" / "report.xml"
        write_xml_report(result, out, lib_name="libfoo")
        assert out.exists()
        content = out.read_text()
        root = ET.fromstring(content)
        assert root.tag == "reports"

    def test_creates_parent_dirs(self, tmp_path: Path):
        result = _make_result()
        out = tmp_path / "a" / "b" / "c" / "report.xml"
        write_xml_report(result, out, lib_name="libfoo")
        assert out.exists()

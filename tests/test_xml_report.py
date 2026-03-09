"""Tests for ABICC-compatible XML report generation."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

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
    """Verify the XML report matches ABICC's expected schema."""

    def test_root_element_and_attributes(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo", old_version="1.0", new_version="2.0")
        root = ET.fromstring(xml)
        assert root.tag == "report"
        assert root.get("version") == "1.2"
        assert root.get("library") == "libfoo"
        assert root.get("version1") == "1.0"
        assert root.get("version2") == "2.0"

    def test_has_binary_and_source_sections(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        binary = root.find("binary")
        source = root.find("source")
        assert binary is not None, "Missing <binary> section"
        assert source is not None, "Missing <source> section"

    def test_binary_section_elements(self):
        """All expected child elements must be present in <binary>."""
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        binary = root.find("binary")
        expected_children = [
            "compatible", "problems_with_types", "problems_with_symbols",
            "problems_total", "removed", "added", "warnings", "affected",
        ]
        for tag in expected_children:
            el = binary.find(tag)
            assert el is not None, f"Missing <binary>/<{tag}>"
            assert el.text is not None, f"<binary>/<{tag}> has no text"

    def test_source_section_elements(self):
        """All expected child elements must be present in <source>."""
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        root = ET.fromstring(xml)
        source = root.find("source")
        expected_children = [
            "compatible", "problems_with_types", "problems_with_symbols",
            "problems_total", "removed", "added", "warnings", "affected",
        ]
        for tag in expected_children:
            el = source.find(tag)
            assert el is not None, f"Missing <source>/<{tag}>"

    def test_xml_declaration_present(self):
        result = _make_result()
        xml = generate_xml_report(result, lib_name="libfoo")
        assert xml.startswith("<?xml ")


class TestXmlReportCounts:
    """Verify that counts in the XML report are correct."""

    def test_no_changes_all_zeros(self):
        result = _make_result(verdict=Verdict.NO_CHANGE)
        xml = generate_xml_report(result)
        root = ET.fromstring(xml)
        binary = root.find("binary")
        assert binary.find("compatible").text == "100.0"
        assert binary.find("problems_total").text == "0"
        assert binary.find("removed").text == "0"
        assert binary.find("added").text == "0"

    def test_func_removed_counts_as_removed(self):
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        binary = root.find("binary")
        assert binary.find("removed").text == "1"
        assert binary.find("compatible").text == "90.0"

    def test_func_added_counts_as_added(self):
        changes = [
            Change(kind=ChangeKind.FUNC_ADDED, symbol="_Z3barv",
                   description="bar() added"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.COMPATIBLE)
        xml = generate_xml_report(result)
        root = ET.fromstring(xml)
        binary = root.find("binary")
        assert binary.find("added").text == "1"
        assert binary.find("compatible").text == "100.0"

    def test_type_problem_counted_correctly(self):
        changes = [
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="MyStruct",
                   description="size changed", old_value="8", new_value="16"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=5)
        root = ET.fromstring(xml)
        binary = root.find("binary")
        assert binary.find("problems_with_types").text == "1"
        assert binary.find("problems_with_symbols").text == "0"
        assert binary.find("problems_total").text == "1"

    def test_symbol_problem_counted_correctly(self):
        changes = [
            Change(kind=ChangeKind.FUNC_RETURN_CHANGED, symbol="_Z3foov",
                   description="return type changed", old_value="int", new_value="long"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        binary = root.find("binary")
        assert binary.find("problems_with_symbols").text == "1"
        assert binary.find("problems_with_types").text == "0"

    def test_source_section_excludes_binary_only_kinds(self):
        changes = [
            Change(kind=ChangeKind.SONAME_CHANGED, symbol="libfoo.so",
                   description="soname changed", old_value="libfoo.so.1", new_value="libfoo.so.2"),
            Change(kind=ChangeKind.FUNC_RETURN_CHANGED, symbol="_Z3foov",
                   description="return type changed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=10)
        root = ET.fromstring(xml)
        # Binary section has both
        binary = root.find("binary")
        assert binary.find("affected").text == "2"
        # Source section excludes SONAME_CHANGED (binary-only)
        source = root.find("source")
        assert source.find("affected").text == "1"

    def test_mixed_changes(self):
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
        xml = generate_xml_report(result, old_symbol_count=20)
        root = ET.fromstring(xml)
        binary = root.find("binary")
        assert binary.find("removed").text == "1"
        assert binary.find("added").text == "1"
        # problems: type_size_changed (type) + func_return_changed (symbol)
        # func_removed is a removal, not counted as a "problem"
        assert binary.find("problems_with_types").text == "1"
        assert binary.find("problems_with_symbols").text == "1"
        assert binary.find("problems_total").text == "2"


class TestXmlReportParsability:
    """Simulate how abi-tracker would parse the XML report."""

    def test_abi_tracker_bc_percentage_extraction(self):
        """abi-tracker extracts BC% from <binary><compatible>."""
        changes = [
            Change(kind=ChangeKind.FUNC_REMOVED, symbol="_Z3foov",
                   description="foo() removed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, lib_name="libfoo", old_symbol_count=10)
        root = ET.fromstring(xml)
        # abi-tracker does: root.find("binary/compatible").text
        bc_text = root.find("binary/compatible").text
        bc_pct = float(bc_text)
        assert bc_pct == 90.0

    def test_abi_tracker_problems_total_extraction(self):
        """abi-tracker extracts problem count from <binary><problems_total>."""
        changes = [
            Change(kind=ChangeKind.TYPE_SIZE_CHANGED, symbol="S",
                   description="size changed"),
        ]
        result = _make_result(changes=changes, verdict=Verdict.BREAKING)
        xml = generate_xml_report(result, old_symbol_count=5)
        root = ET.fromstring(xml)
        problems = int(root.find("binary/problems_total").text)
        assert problems == 1


class TestWriteXmlReport:
    def test_writes_file(self, tmp_path: Path):
        result = _make_result()
        out = tmp_path / "sub" / "report.xml"
        write_xml_report(result, out, lib_name="libfoo")
        assert out.exists()
        content = out.read_text()
        root = ET.fromstring(content)
        assert root.tag == "report"

    def test_creates_parent_dirs(self, tmp_path: Path):
        result = _make_result()
        out = tmp_path / "a" / "b" / "c" / "report.xml"
        write_xml_report(result, out, lib_name="libfoo")
        assert out.exists()

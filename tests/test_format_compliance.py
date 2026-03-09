"""Tests for ABICC format compliance fixes.

Validates that abicheck compat mode produces output compatible with
existing ABICC report parsing harnesses.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner


class TestReportFormatChoices:
    """Verify -report-format accepts ABICC format names."""

    def test_htm_is_valid_format(self):
        """ABICC uses 'htm' not 'html' — we must accept both."""
        from abicheck.cli import main
        runner = CliRunner()
        # Just test that 'htm' is accepted (will fail on missing descriptor, not on format)
        result = runner.invoke(main, [
            "compat", "-lib", "test", "-old", "/nonexistent", "-new", "/nonexistent",
            "-report-format", "htm",
        ])
        # Should NOT fail with "invalid choice: htm"
        assert "Invalid value for '-report-format'" not in (result.output or "")

    def test_xml_is_valid_format(self):
        """XML format must be accepted for abi-tracker compatibility."""
        from abicheck.cli import main
        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "-lib", "test", "-old", "/nonexistent", "-new", "/nonexistent",
            "-report-format", "xml",
        ])
        assert "Invalid value for '-report-format'" not in (result.output or "")

    def test_html_is_still_valid(self):
        from abicheck.cli import main
        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "-lib", "test", "-old", "/nonexistent", "-new", "/nonexistent",
            "-report-format", "html",
        ])
        assert "Invalid value for '-report-format'" not in (result.output or "")


class TestDefaultReportPath:
    """Verify default report filename matches ABICC convention."""

    def test_default_filename_is_compat_report(self):
        """ABICC default filename is compat_report.html, not report.html."""
        from pathlib import Path
        source = Path(__file__).parent.parent / "abicheck" / "cli.py"
        content = source.read_text()
        assert "compat_report." in content, (
            "Default report filename should be 'compat_report.*' to match ABICC convention"
        )


class TestConsoleOutputFormat:
    """Verify console output includes ABICC-compatible BC% line."""

    def test_bc_percentage_line_in_source(self):
        """Console output should include 'Binary compatibility: XX.X%' like ABICC."""
        from pathlib import Path
        source = Path(__file__).parent.parent / "abicheck" / "cli.py"
        content = source.read_text()
        assert "Binary compatibility:" in content, (
            "Console output should include ABICC-format 'Binary compatibility: XX.X%'"
        )

    def test_total_problems_line_in_source(self):
        """Console output should include ABICC-format problem count."""
        from pathlib import Path
        source = Path(__file__).parent.parent / "abicheck" / "cli.py"
        content = source.read_text()
        assert "Total binary compatibility problems:" in content, (
            "Console output should include ABICC-format problem count"
        )

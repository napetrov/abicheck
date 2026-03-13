"""Backward-compatible shim. Implementation moved to abicheck.compat.xml_report.

New code should import from there directly:
    from abicheck.compat.xml_report import generate_xml_report, write_xml_report
"""
# Deprecated location — import from abicheck.compat.xml_report directly.
from .compat.xml_report import *  # noqa: F403

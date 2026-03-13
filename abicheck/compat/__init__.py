"""abicheck.compat — ABICC compatibility layer.

Submodules:
- descriptor: ABICC XML descriptor parsing (CompatDescriptor, parse_descriptor)
- xml_report: ABICC-format XML report generation
- abicc_dump_import: ABICC Perl dump importer
- cli: compat/compat-dump CLI subcommands and helpers
"""
from .descriptor import CompatDescriptor, parse_descriptor

__all__ = ["CompatDescriptor", "parse_descriptor"]

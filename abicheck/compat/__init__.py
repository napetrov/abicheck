"""abicheck.compat — ABICC compatibility layer.

This subpackage contains all code specific to ABICC (abi-compliance-checker)
compatibility mode:

- ``descriptor``: ABICC XML descriptor parsing (CompatDescriptor, parse_descriptor)
- ``xml_report``: ABICC-format XML report generation
- ``cli``: ``compat`` and ``compat-dump`` CLI subcommands + all ABICC helpers

Public re-exports for backward compatibility (existing code can still import
directly from ``abicheck.compat``):
"""
from .descriptor import CompatDescriptor, parse_descriptor

__all__ = ["CompatDescriptor", "parse_descriptor"]

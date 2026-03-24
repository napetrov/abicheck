"""Confidence tier and evidence assertion tests.

Verifies that the scanner correctly computes confidence levels and evidence
tiers based on available data sources (header, ELF, DWARF, PE, Mach-O).
"""
from __future__ import annotations

import copy

import pytest

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.checker_policy import Confidence
from abicheck.dwarf_advanced import AdvancedDwarfMetadata, ToolchainInfo
from abicheck.dwarf_metadata import DwarfMetadata, StructLayout
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType
from abicheck.model import (
    AbiSnapshot,
    EnumMember,
    EnumType,
    Function,
    Param,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)


def _snap(version="1.0", functions=None, variables=None, types=None,
          enums=None, typedefs=None, elf=None, dwarf=None,
          dwarf_advanced=None):
    return AbiSnapshot(
        library="libtest.so.1", version=version,
        functions=functions or [], variables=variables or [],
        types=types or [], enums=enums or [],
        typedefs=typedefs or {}, elf=elf, dwarf=dwarf,
        dwarf_advanced=dwarf_advanced,
    )


def _pub_func(name, mangled, ret="void", params=None, **kwargs):
    return Function(name=name, mangled=mangled, return_type=ret,
                    params=params or [], visibility=Visibility.PUBLIC, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# Evidence Tier Detection
# ═══════════════════════════════════════════════════════════════════════════

class TestEvidenceTiers:
    """Verify evidence_tiers list reflects available data sources."""

    def test_header_only_evidence(self):
        """Snapshot with header data but no binary metadata → 'header' tier."""
        f = _pub_func("api", "_Z3apiv")
        r = compare(_snap(functions=[f]), _snap(functions=[f]))
        assert "header" in r.evidence_tiers

    def test_elf_evidence_included(self):
        """Snapshot with ELF metadata → 'elf' tier."""
        elf = ElfMetadata(
            soname="libtest.so.1",
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )
        f = _pub_func("api", "_Z3apiv")
        r = compare(_snap(functions=[f], elf=elf),
                     _snap(functions=[f], elf=elf))
        assert "elf" in r.evidence_tiers

    def test_dwarf_evidence_included(self):
        """Snapshot with DWARF metadata → 'dwarf' tier."""
        dwarf = DwarfMetadata(
            structs={"Foo": StructLayout(name="Foo", byte_size=4)},
            has_dwarf=True,
        )
        r = compare(_snap(dwarf=dwarf), _snap(dwarf=dwarf))
        assert "dwarf" in r.evidence_tiers

    def test_multiple_evidence_tiers(self):
        """Snapshot with header + ELF + DWARF → all three tiers."""
        f = _pub_func("api", "_Z3apiv")
        elf = ElfMetadata(
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )
        dwarf = DwarfMetadata(
            structs={"Cfg": StructLayout(name="Cfg", byte_size=4)},
            has_dwarf=True,
        )
        r = compare(
            _snap(functions=[f], elf=elf, dwarf=dwarf),
            _snap(functions=[f], elf=elf, dwarf=dwarf),
        )
        assert "header" in r.evidence_tiers
        assert "elf" in r.evidence_tiers
        assert "dwarf" in r.evidence_tiers

    def test_empty_snapshot_minimal_evidence(self):
        """Empty snapshots have minimal evidence."""
        r = compare(_snap(), _snap())
        assert r.evidence_tiers == [] or r.evidence_tiers == ["header"]


# ═══════════════════════════════════════════════════════════════════════════
# Confidence Levels
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceLevels:
    """Verify confidence correlates with evidence sources."""

    def test_empty_snapshot_low_confidence(self):
        """Empty snapshots → LOW confidence."""
        r = compare(_snap(), _snap())
        assert r.confidence == Confidence.LOW

    def test_header_only_not_high_confidence(self):
        """Header-only analysis (no binary data) → MEDIUM or LOW."""
        f = _pub_func("api", "_Z3apiv")
        t = RecordType(name="Cfg", kind="struct", size_bits=32)
        r = compare(
            _snap(functions=[f], types=[t]),
            copy.deepcopy(_snap(functions=[f], types=[t])),
        )
        assert r.confidence in (Confidence.MEDIUM, Confidence.LOW)

    def test_elf_increases_confidence(self):
        """Adding ELF metadata should not decrease confidence vs header-only."""
        f = _pub_func("api", "_Z3apiv")
        elf = ElfMetadata(
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )

        header_only = compare(
            _snap(functions=[f]),
            copy.deepcopy(_snap(functions=[f])),
        )
        with_elf = compare(
            _snap(functions=[f], elf=elf),
            _snap(functions=[f], elf=elf),
        )

        confidence_order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
        assert confidence_order[with_elf.confidence] >= confidence_order[header_only.confidence]

    def test_elf_plus_dwarf_high_confidence(self):
        """ELF + DWARF + headers → should be HIGH or MEDIUM."""
        f = _pub_func("api", "_Z3apiv")
        elf = ElfMetadata(
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )
        dwarf = DwarfMetadata(
            structs={"Cfg": StructLayout(name="Cfg", byte_size=4)},
            has_dwarf=True,
        )

        r = compare(
            _snap(functions=[f], elf=elf, dwarf=dwarf),
            _snap(functions=[f], elf=elf, dwarf=dwarf),
        )
        assert r.confidence in (Confidence.HIGH, Confidence.MEDIUM)


# ═══════════════════════════════════════════════════════════════════════════
# Coverage Warnings
# ═══════════════════════════════════════════════════════════════════════════

class TestCoverageWarnings:
    """Verify coverage_warnings flag missing detectors."""

    def test_fewer_warnings_with_complete_data(self):
        """Full metadata → fewer warnings than header-only."""
        f = _pub_func("api", "_Z3apiv")
        elf = ElfMetadata(
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )
        dwarf = DwarfMetadata(has_dwarf=True)

        full = compare(
            _snap(functions=[f], elf=elf, dwarf=dwarf),
            _snap(functions=[f], elf=elf, dwarf=dwarf),
        )
        header_only = compare(_snap(functions=[f]), _snap(functions=[f]))
        assert len(full.coverage_warnings) <= len(header_only.coverage_warnings)

    def test_warnings_when_dwarf_missing(self):
        """Missing DWARF → at least one coverage warning."""
        f = _pub_func("api", "_Z3apiv")
        elf = ElfMetadata(
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )

        r = compare(
            _snap(functions=[f], elf=elf),
            _snap(functions=[f], elf=elf),
        )
        assert len(r.coverage_warnings) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Confidence with Breaking Changes
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceWithBreakingChanges:
    """Confidence should be reported even when changes are detected."""

    def test_breaking_change_with_high_confidence(self):
        """Breaking change detected with full metadata → still reports confidence."""
        f_old = _pub_func("api", "_Z3apiv", ret="int")
        f_new = _pub_func("api", "_Z3apiv", ret="long")
        elf = ElfMetadata(
            symbols=[ElfSymbol(name="_Z3apiv", binding=SymbolBinding.GLOBAL,
                               sym_type=SymbolType.FUNC)],
        )
        dwarf = DwarfMetadata(has_dwarf=True)

        r = compare(
            _snap(functions=[f_old], elf=elf, dwarf=dwarf),
            _snap(functions=[f_new], elf=elf, dwarf=dwarf),
        )
        assert r.verdict == Verdict.BREAKING
        assert r.confidence is not None
        assert isinstance(r.evidence_tiers, list)

    def test_breaking_change_header_only_lower_confidence(self):
        """Breaking change with header-only data → lower confidence."""
        f_old = _pub_func("api", "_Z3apiv", ret="int")
        f_new = _pub_func("api", "_Z3apiv", ret="long")

        r = compare(
            _snap(functions=[f_old]),
            _snap(functions=[f_new]),
        )
        assert r.verdict == Verdict.BREAKING
        assert r.confidence in (Confidence.MEDIUM, Confidence.LOW)


# ═══════════════════════════════════════════════════════════════════════════
# Detector Results
# ═══════════════════════════════════════════════════════════════════════════

class TestDetectorResults:
    """Verify detector_results are populated for introspection."""

    def test_detector_results_populated(self):
        """At least some detectors should report results."""
        f = _pub_func("api", "_Z3apiv")
        r = compare(_snap(functions=[f]), _snap(functions=[f]))
        assert isinstance(r.detector_results, list)
        assert len(r.detector_results) > 0

    def test_each_detector_has_name(self):
        """Every detector result should have a name."""
        f = _pub_func("api", "_Z3apiv")
        r = compare(_snap(functions=[f]), _snap(functions=[f]))
        for dr in r.detector_results:
            assert hasattr(dr, "name")
            assert dr.name  # non-empty

    def test_disabled_detectors_report_reason(self):
        """Detectors disabled due to missing metadata should explain why."""
        f = _pub_func("api", "_Z3apiv")
        r = compare(_snap(functions=[f]), _snap(functions=[f]))
        # Check that at least some detectors report disabled status
        # (DWARF, advanced_dwarf should be disabled without binary data)
        disabled = [dr for dr in r.detector_results if not dr.enabled]
        # There should be some disabled detectors when no binary data
        assert len(disabled) > 0
        for dr in disabled:
            assert dr.coverage_gap  # should explain why it was disabled

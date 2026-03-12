"""Unit tests for abicheck/core/model — Phase 1a v0.2 data model."""
from __future__ import annotations

import pytest

from abicheck.core.model import (
    AnnotatedChange,
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    EntityType,
    Origin,
    PolicyResult,
    PolicySummary,
    PolicyVerdict,
    SourceLocation,
)

# ---------------------------------------------------------------------------
# Origin
# ---------------------------------------------------------------------------

class TestOrigin:
    def test_int_enum_values(self) -> None:
        # IntEnum — no heap string per value
        assert Origin.CASTXML == 0
        assert Origin.DWARF == 1
        assert Origin.ELF == 2

    def test_confidence_ordering(self) -> None:
        assert Origin.CASTXML.confidence > Origin.DWARF.confidence
        assert Origin.DWARF.confidence > Origin.PDB.confidence
        assert Origin.PDB.confidence > Origin.ELF.confidence
        assert Origin.ELF.confidence == Origin.MACHO.confidence == Origin.COFF.confidence

    def test_confidence_values_exact(self) -> None:
        assert Origin.CASTXML.confidence == 1.0
        assert Origin.DWARF.confidence == 0.9
        assert Origin.PDB.confidence == 0.8    # PDB > ELF (type info available)
        assert Origin.ELF.confidence == 0.7
        assert Origin.MACHO.confidence == 0.7
        assert Origin.COFF.confidence == 0.7
        assert Origin.BTF.confidence == 0.6
        assert Origin.CTF.confidence == 0.6

    def test_confidence_monotone_by_priority(self) -> None:
        """Confidence ordering must be consistent — no inversions."""
        priority_order = [
            Origin.CASTXML, Origin.DWARF, Origin.PDB,
            Origin.ELF, Origin.MACHO, Origin.COFF, Origin.BTF, Origin.CTF,
        ]
        for a, b in zip(priority_order, priority_order[1:]):
            assert a.confidence >= b.confidence, (
                f"{a.name}.confidence ({a.confidence}) < {b.name}.confidence ({b.confidence})"
            )

    def test_confidence_is_stable(self) -> None:
        # Property returns the same value on repeated calls (no dict rebuild per call)
        assert Origin.ELF.confidence == Origin.ELF.confidence
        assert Origin.CASTXML.confidence == 1.0  # spot-check module constant

    def test_highest_returns_best(self) -> None:
        assert Origin.highest((Origin.ELF, Origin.DWARF, Origin.CASTXML)) == Origin.CASTXML
        assert Origin.highest((Origin.ELF,)) == Origin.ELF

    def test_highest_pdb_beats_elf(self) -> None:
        """PDB has higher confidence than ELF — highest() must reflect this."""
        assert Origin.highest((Origin.ELF, Origin.PDB)) == Origin.PDB

    def test_highest_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            Origin.highest(())


# ---------------------------------------------------------------------------
# SourceLocation
# ---------------------------------------------------------------------------

class TestSourceLocation:
    def test_str_with_line(self) -> None:
        loc = SourceLocation(file="foo.h", line=42)
        assert str(loc) == "foo.h:42"

    def test_str_without_line(self) -> None:
        loc = SourceLocation(file="bar.h")
        assert str(loc) == "bar.h"

    def test_str_includes_column(self) -> None:
        """column is included in __str__ when present alongside line."""
        loc = SourceLocation(file="foo.h", line=42, column=10)
        assert str(loc) == "foo.h:42:10"
        assert loc.column == 10  # accessible on instance

    def test_str_line_only_no_column(self) -> None:
        """column is omitted from __str__ when not set."""
        loc = SourceLocation(file="foo.h", line=42)
        assert str(loc) == "foo.h:42"

    def test_line_none_no_colon(self) -> None:
        loc = SourceLocation(file="foo.h", line=None, column=5)
        assert ":" not in str(loc)


# ---------------------------------------------------------------------------
# Change
# ---------------------------------------------------------------------------

def _make_change(**kwargs) -> Change:
    defaults = dict(
        change_kind=ChangeKind.SYMBOL,
        entity_type=EntityType.FUNCTION,
        entity_name="foo",
        before=EntitySnapshot("int foo()"),
        after=EntitySnapshot("void foo()"),
        severity=ChangeSeverity.BREAK,
        origin=Origin.ELF,
    )
    defaults.update(kwargs)
    return Change(**defaults)


class TestChange:
    def test_basic_construction(self) -> None:
        c = _make_change()
        assert c.change_kind == ChangeKind.SYMBOL
        assert c.severity == ChangeSeverity.BREAK
        assert c.origin == Origin.ELF
        assert c.corroborating == ()
        assert c.confidence == 1.0
        assert c.location is None

    def test_corroborating_tuple(self) -> None:
        c = _make_change(
            origin=Origin.DWARF,
            corroborating=(Origin.ELF,),  # primary must have highest confidence
        )
        assert isinstance(c.corroborating, tuple)
        assert Origin.ELF in c.corroborating

    def test_corroborating_primary_not_in_corroborating(self) -> None:
        """Primary origin must not appear in corroborating."""
        with pytest.raises(ValueError, match="must not appear in corroborating"):
            _make_change(origin=Origin.ELF, corroborating=(Origin.ELF, Origin.DWARF))

    def test_corroborating_duplicates_rejected(self) -> None:
        """Corroborating sources must be unique."""
        with pytest.raises(ValueError, match="must be unique"):
            _make_change(origin=Origin.ELF, corroborating=(Origin.DWARF, Origin.DWARF))

    def test_primary_must_be_highest_confidence(self) -> None:
        """Lower-confidence primary with higher-confidence corroborating must be rejected."""
        with pytest.raises(ValueError, match="highest-confidence"):
            _make_change(origin=Origin.ELF, corroborating=(Origin.CASTXML,))

    def test_primary_highest_with_three_origins_rejected(self) -> None:
        """DWARF primary but CASTXML corroborating — CASTXML is highest, so DWARF is rejected."""
        with pytest.raises(ValueError, match="highest-confidence"):
            _make_change(origin=Origin.DWARF, corroborating=(Origin.CASTXML,))

    def test_equal_confidence_primary_is_accepted(self) -> None:
        """Equal-confidence origins: ELF+MACHO both 0.7 — first-provided wins, no error."""
        c = _make_change(origin=Origin.ELF, corroborating=(Origin.MACHO,))
        assert c.origin == Origin.ELF  # tie: first provided stays primary

    def test_confidence_boundary_valid(self) -> None:
        _make_change(confidence=0.0)   # should not raise
        _make_change(confidence=1.0)   # should not raise

    def test_confidence_validation_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            _make_change(confidence=1.5)
        with pytest.raises(ValueError):
            _make_change(confidence=-0.1)

    def test_requires_review_shim(self) -> None:
        review = _make_change(severity=ChangeSeverity.REVIEW_NEEDED)
        assert review.requires_review is True
        breaking = _make_change(severity=ChangeSeverity.BREAK)
        assert breaking.requires_review is False

    def test_with_location(self) -> None:
        loc = SourceLocation("include/foo.h", 99)
        c = _make_change(location=loc)
        assert c.location is not None
        assert str(c.location) == "include/foo.h:99"

    def test_change_kinds_coverage(self) -> None:
        kinds = {k.value for k in ChangeKind}
        assert "symbol" in kinds
        assert "size_change" in kinds           # distinct from type_layout
        assert "calling_convention" in kinds    # only with DWARF/castxml evidence
        assert "type_layout" in kinds
        assert "vtable_inheritance" in kinds

    def test_calling_convention_requires_dwarf_or_castxml(self) -> None:
        """CALLING_CONVENTION must not be emitted with binary-only evidence."""
        with pytest.raises(ValueError, match="CALLING_CONVENTION requires DWARF or CASTXML"):
            _make_change(
                change_kind=ChangeKind.CALLING_CONVENTION,
                origin=Origin.ELF,
                corroborating=(),
            )

    def test_calling_convention_ok_with_dwarf(self) -> None:
        c = _make_change(
            change_kind=ChangeKind.CALLING_CONVENTION,
            origin=Origin.DWARF,
        )
        assert c.change_kind == ChangeKind.CALLING_CONVENTION

    def test_calling_convention_ok_with_castxml(self) -> None:
        c = _make_change(
            change_kind=ChangeKind.CALLING_CONVENTION,
            origin=Origin.CASTXML,
        )
        assert c.change_kind == ChangeKind.CALLING_CONVENTION


# ---------------------------------------------------------------------------
# PolicyResult
# ---------------------------------------------------------------------------

class TestPolicyResult:
    def _annotated(self, verdict: PolicyVerdict, severity: ChangeSeverity) -> AnnotatedChange:
        return AnnotatedChange(
            change=_make_change(severity=severity),
            verdict=verdict,
        )

    def test_empty_is_pass(self) -> None:
        result = PolicyResult.from_annotated([])
        assert result.summary.verdict == PolicyVerdict.PASS
        assert result.summary.incompatible_count == 0
        assert result.summary.review_needed_count == 0

    def test_block_on_breaking_change(self) -> None:
        changes = [self._annotated(PolicyVerdict.BLOCK, ChangeSeverity.BREAK)]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.BLOCK
        assert result.summary.incompatible_count == 1

    def test_warn_on_review_needed(self) -> None:
        changes = [self._annotated(PolicyVerdict.WARN, ChangeSeverity.REVIEW_NEEDED)]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.WARN
        assert result.summary.review_needed_count == 1

    def test_block_takes_priority_over_warn(self) -> None:
        changes = [
            self._annotated(PolicyVerdict.WARN, ChangeSeverity.REVIEW_NEEDED),
            self._annotated(PolicyVerdict.BLOCK, ChangeSeverity.BREAK),
        ]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.BLOCK

    def test_compatible_extension_only_is_pass(self) -> None:
        changes = [self._annotated(PolicyVerdict.PASS, ChangeSeverity.COMPATIBLE_EXTENSION)]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.PASS
        assert result.summary.incompatible_count == 0
        assert result.summary.review_needed_count == 0
        assert result.summary.compatible_extension_count == 1

    def test_suppressed_count(self) -> None:
        changes = [
            self._annotated(PolicyVerdict.PASS, ChangeSeverity.SUPPRESSED),
            self._annotated(PolicyVerdict.PASS, ChangeSeverity.SUPPRESSED),
        ]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.suppressed_count == 2
        assert result.summary.verdict == PolicyVerdict.PASS

    def test_suppressed_does_not_mask_block(self) -> None:
        changes = [
            self._annotated(PolicyVerdict.PASS, ChangeSeverity.SUPPRESSED),
            self._annotated(PolicyVerdict.BLOCK, ChangeSeverity.BREAK),
        ]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.BLOCK
        assert result.summary.suppressed_count == 1
        assert result.summary.incompatible_count == 1

    def test_per_change_traceability(self) -> None:
        block_change = _make_change(entity_name="removed_func", severity=ChangeSeverity.BREAK)
        compat_change = _make_change(entity_name="added_func",
                                     severity=ChangeSeverity.COMPATIBLE_EXTENSION)
        changes = [
            AnnotatedChange(change=block_change, verdict=PolicyVerdict.BLOCK),
            AnnotatedChange(change=compat_change, verdict=PolicyVerdict.PASS),
        ]
        result = PolicyResult.from_annotated(changes)
        blocking = [ac for ac in result.annotated_changes if ac.verdict == PolicyVerdict.BLOCK]
        assert len(blocking) == 1
        assert blocking[0].change.entity_name == "removed_func"

    def test_error_verdict_manual_construction(self) -> None:
        """ERROR verdict is not producible via from_annotated — must be constructed manually."""
        result = PolicyResult(
            annotated_changes=[],
            summary=PolicySummary(verdict=PolicyVerdict.ERROR, error_count=1),
        )
        assert result.summary.verdict == PolicyVerdict.ERROR
        assert result.summary.error_count == 1

    def test_error_verdict_from_annotated(self) -> None:
        """from_annotated: ERROR verdict when any annotated change has verdict ERROR."""
        changes = [self._annotated(PolicyVerdict.ERROR, ChangeSeverity.REVIEW_NEEDED)]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.ERROR
        assert result.summary.error_count == 1

    def test_error_takes_precedence_over_block(self) -> None:
        """ERROR > BLOCK: pipeline failure supersedes breaking changes."""
        changes = [
            self._annotated(PolicyVerdict.BLOCK, ChangeSeverity.BREAK),
            self._annotated(PolicyVerdict.ERROR, ChangeSeverity.REVIEW_NEEDED),
        ]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.ERROR
        assert result.summary.incompatible_count == 1
        assert result.summary.error_count == 1

    def test_warn_verdict_derives_from_annotated_verdict(self) -> None:
        """from_annotated: WARN is counted by AnnotatedChange.verdict, not change.severity."""
        changes = [self._annotated(PolicyVerdict.WARN, ChangeSeverity.BREAK)]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.verdict == PolicyVerdict.WARN
        assert result.summary.review_needed_count == 1

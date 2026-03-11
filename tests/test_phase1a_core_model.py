"""Unit tests for abicheck/core/model — Phase 1a v0.2 data model."""
from __future__ import annotations

import pytest

from abicheck.core.model import (
    AnnotatedChange,
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
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
        assert Origin.DWARF.confidence > Origin.ELF.confidence
        assert Origin.ELF.confidence == Origin.MACHO.confidence

    def test_highest_returns_best(self) -> None:
        assert Origin.highest((Origin.ELF, Origin.DWARF, Origin.CASTXML)) == Origin.CASTXML
        assert Origin.highest((Origin.ELF,)) == Origin.ELF

    def test_highest_empty_raises(self) -> None:
        with pytest.raises(ValueError):
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


# ---------------------------------------------------------------------------
# Change
# ---------------------------------------------------------------------------

def _make_change(**kwargs) -> Change:
    defaults = dict(
        change_kind=ChangeKind.SYMBOL,
        entity_type="function",
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
            corroborating=(Origin.DWARF, Origin.CASTXML),
        )
        assert isinstance(c.corroborating, tuple)
        assert Origin.CASTXML in c.corroborating

    def test_confidence_validation(self) -> None:
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
        # Verify all ChangeKind values exist
        kinds = {k.value for k in ChangeKind}
        assert "symbol" in kinds
        assert "size_change" in kinds         # distinct from type_layout
        assert "calling_convention" in kinds  # only with DWARF/castxml evidence


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

    def test_suppressed_count(self) -> None:
        changes = [
            self._annotated(PolicyVerdict.PASS, ChangeSeverity.SUPPRESSED),
            self._annotated(PolicyVerdict.PASS, ChangeSeverity.SUPPRESSED),
        ]
        result = PolicyResult.from_annotated(changes)
        assert result.summary.suppressed_count == 2
        assert result.summary.verdict == PolicyVerdict.PASS

    def test_per_change_traceability(self) -> None:
        # Can trace exactly which change caused the verdict
        block_change = _make_change(entity_name="removed_func", severity=ChangeSeverity.BREAK)
        compat_change = _make_change(entity_name="added_func", severity=ChangeSeverity.COMPATIBLE_EXTENSION)
        changes = [
            AnnotatedChange(change=block_change, verdict=PolicyVerdict.BLOCK),
            AnnotatedChange(change=compat_change, verdict=PolicyVerdict.PASS),
        ]
        result = PolicyResult.from_annotated(changes)
        blocking = [ac for ac in result.annotated_changes if ac.verdict == PolicyVerdict.BLOCK]
        assert len(blocking) == 1
        assert blocking[0].change.entity_name == "removed_func"

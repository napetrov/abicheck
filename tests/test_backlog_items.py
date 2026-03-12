"""Tests for backlog items:
- EntityType enum (Task 1)
- Phase 2b version_range matching (Task 2)
- Security boundary hardening (Task 3)
"""
from __future__ import annotations

import pytest

from abicheck.core.errors import (
    AbicheckError,
    SnapshotError,
    SuppressionError,
    ValidationError,
)
from abicheck.core.model import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    EntityType,
    Origin,
)
from abicheck.core.pipeline import analyse
from abicheck.core.suppressions import SuppressionEngine, SuppressionRule
from abicheck.core.suppressions.rule import SuppressionScope, VersionRange
from abicheck.model import AbiSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_change(
    *,
    name: str = "foo",
    kind: ChangeKind = ChangeKind.SYMBOL,
    entity_type: EntityType = EntityType.FUNCTION,
    severity: ChangeSeverity = ChangeSeverity.BREAK,
) -> Change:
    return Change(
        change_kind=kind,
        entity_type=entity_type,
        entity_name=name,
        before=EntitySnapshot("int foo()"),
        after=EntitySnapshot("void foo()"),
        severity=severity,
        origin=Origin.CASTXML,
        confidence=0.9,
    )


def _empty_snap(version: str = "v1") -> AbiSnapshot:
    return AbiSnapshot(library="libfoo.so", version=version,
                       functions=[], variables=[], types=[])


# ---------------------------------------------------------------------------
# Task 1: EntityType enum
# ---------------------------------------------------------------------------

class TestEntityTypeEnum:
    def test_enum_values(self) -> None:
        assert EntityType.FUNCTION.value == "function"
        assert EntityType.VARIABLE.value == "variable"
        assert EntityType.TYPE.value == "type"
        assert EntityType.FIELD.value == "field"

    def test_is_str_enum(self) -> None:
        """EntityType is a str enum — works in string contexts."""
        assert isinstance(EntityType.FUNCTION, str)
        assert EntityType.FUNCTION == "function"

    def test_change_accepts_entity_type_enum(self) -> None:
        c = _make_change(entity_type=EntityType.FUNCTION)
        assert c.entity_type == EntityType.FUNCTION
        assert c.entity_type.value == "function"

    def test_change_all_entity_types(self) -> None:
        for et in EntityType:
            c = _make_change(entity_type=et)
            assert c.entity_type == et

    def test_entity_type_str_enum_sorts_by_value(self) -> None:
        """str enum values work in sorted() — used in pipeline sort key."""
        types = [EntityType.TYPE, EntityType.FUNCTION, EntityType.FIELD, EntityType.VARIABLE]
        sorted_types = sorted(types)
        # sorted by str value: field, function, type, variable
        assert sorted_types == [
            EntityType.FIELD,
            EntityType.FUNCTION,
            EntityType.TYPE,
            EntityType.VARIABLE,
        ]

    def test_match_map_key_uses_value(self) -> None:
        """SuppressionEngine match_map key uses entity_type.value (str)."""
        engine = SuppressionEngine([SuppressionRule(entity_glob="foo*", reason="test")])
        result = engine.apply([_make_change(name="foobar")])
        assert len(result.suppressed) == 1
        key = (
            result.suppressed[0].entity_type.value,
            result.suppressed[0].entity_name,
            result.suppressed[0].change_kind.value,
        )
        assert key in result.match_map

    def test_entity_type_exported_from_core_model(self) -> None:
        from abicheck.core.model import EntityType as ET  # noqa: PLC0415
        assert ET is EntityType


# ---------------------------------------------------------------------------
# Task 2: Phase 2b — version_range matching
# ---------------------------------------------------------------------------

class TestVersionRangeMatching:
    """Tests for version_range matching in SuppressionEngine."""

    def _engine_with_range(
        self,
        from_version: str | None = None,
        to_version: str | None = None,
        inclusive: bool = True,
        scheme: str = "semver",
    ) -> SuppressionEngine:
        vr = VersionRange(
            from_version=from_version,
            to_version=to_version,
            inclusive=inclusive,
            scheme=scheme,
        )
        rule = SuppressionRule(
            entity_glob="*",
            scope=SuppressionScope(version_range=vr),
            reason="test version range",
        )
        return SuppressionEngine([rule])

    # ── semver ────────────────────────────────────────────────────────────

    def test_semver_in_range_inclusive(self) -> None:
        engine = self._engine_with_range("1.0.0", "2.0.0", inclusive=True)
        result = engine.apply([_make_change()], version_context="1.5.0")
        assert len(result.suppressed) == 1

    def test_semver_at_lower_bound_inclusive(self) -> None:
        engine = self._engine_with_range("1.0.0", "2.0.0", inclusive=True)
        result = engine.apply([_make_change()], version_context="1.0.0")
        assert len(result.suppressed) == 1

    def test_semver_at_upper_bound_inclusive(self) -> None:
        engine = self._engine_with_range("1.0.0", "2.0.0", inclusive=True)
        result = engine.apply([_make_change()], version_context="2.0.0")
        assert len(result.suppressed) == 1

    def test_semver_below_range_not_suppressed(self) -> None:
        engine = self._engine_with_range("1.0.0", "2.0.0", inclusive=True)
        result = engine.apply([_make_change()], version_context="0.9.0")
        assert len(result.active) == 1
        assert len(result.suppressed) == 0

    def test_semver_above_range_not_suppressed(self) -> None:
        engine = self._engine_with_range("1.0.0", "2.0.0", inclusive=True)
        result = engine.apply([_make_change()], version_context="2.1.0")
        assert len(result.active) == 1

    def test_semver_none_from_version_matches_below(self) -> None:
        """from_version=None → -∞, matches anything ≤ to_version."""
        engine = self._engine_with_range(None, "2.0.0", inclusive=True)
        result = engine.apply([_make_change()], version_context="1.0.0")
        assert len(result.suppressed) == 1

    def test_semver_none_to_version_matches_above(self) -> None:
        """to_version=None → +∞, matches anything ≥ from_version."""
        engine = self._engine_with_range("1.0.0", None, inclusive=True)
        result = engine.apply([_make_change()], version_context="99.0.0")
        assert len(result.suppressed) == 1

    def test_semver_both_none_matches_all(self) -> None:
        """Both bounds None → matches any version."""
        engine = self._engine_with_range(None, None, inclusive=True)
        result = engine.apply([_make_change()], version_context="0.1.0")
        assert len(result.suppressed) == 1

    # ── intel_quarterly ───────────────────────────────────────────────────

    def test_intel_quarterly_in_range(self) -> None:
        engine = self._engine_with_range("2024.1", "2024.3", scheme="intel_quarterly")
        result = engine.apply([_make_change()], version_context="2024.2")
        assert len(result.suppressed) == 1

    def test_intel_quarterly_below_range(self) -> None:
        engine = self._engine_with_range("2024.1", "2024.3", scheme="intel_quarterly")
        result = engine.apply([_make_change()], version_context="2023.4")
        assert len(result.active) == 1

    def test_intel_quarterly_above_range(self) -> None:
        engine = self._engine_with_range("2024.1", "2024.3", scheme="intel_quarterly")
        result = engine.apply([_make_change()], version_context="2025.1")
        assert len(result.active) == 1

    def test_intel_quarterly_at_boundary(self) -> None:
        engine = self._engine_with_range("2024.1", "2024.1", inclusive=True, scheme="intel_quarterly")
        result = engine.apply([_make_change()], version_context="2024.1")
        assert len(result.suppressed) == 1

    def test_intel_quarterly_none_bounds(self) -> None:
        engine = self._engine_with_range(None, "2024.4", scheme="intel_quarterly")
        result = engine.apply([_make_change()], version_context="2020.1")
        assert len(result.suppressed) == 1

    # ── linear ────────────────────────────────────────────────────────────

    def test_linear_int_in_range(self) -> None:
        engine = self._engine_with_range("10", "20", scheme="linear")
        result = engine.apply([_make_change()], version_context="15")
        assert len(result.suppressed) == 1

    def test_linear_string_comparison(self) -> None:
        engine = self._engine_with_range("alpha", "gamma", scheme="linear")
        result = engine.apply([_make_change()], version_context="beta")
        assert len(result.suppressed) == 1

    def test_linear_int_below_range(self) -> None:
        engine = self._engine_with_range("10", "20", scheme="linear")
        result = engine.apply([_make_change()], version_context="5")
        assert len(result.active) == 1

    # ── version_context=None skips filter ────────────────────────────────

    def test_version_context_none_skips_filter_suppresses(self) -> None:
        """When version_context=None (no version info), range filter is skipped.
        Conservative: if other fields match, suppress anyway."""
        engine = self._engine_with_range("1.0.0", "2.0.0")
        # No version_context → filter skipped → match succeeds
        result = engine.apply([_make_change()])
        assert len(result.suppressed) == 1

    def test_version_context_none_in_init_skips_filter(self) -> None:
        """version_context=None in __init__ also skips filter."""
        engine = SuppressionEngine(
            [SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(from_version="1.0.0", to_version="2.0.0")
                ),
            )],
            version_context=None,
        )
        result = engine.apply([_make_change()])
        assert len(result.suppressed) == 1

    def test_version_context_in_init_applies_filter(self) -> None:
        """version_context in __init__ applies range filter."""
        engine = SuppressionEngine(
            [SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(from_version="1.0.0", to_version="2.0.0")
                ),
            )],
            version_context="3.0.0",
        )
        result = engine.apply([_make_change()])
        # 3.0.0 is outside [1.0.0, 2.0.0] → not suppressed
        assert len(result.active) == 1

    def test_version_context_apply_overrides_init(self) -> None:
        """version_context in apply() overrides the init-time value."""
        engine = SuppressionEngine(
            [SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(from_version="1.0.0", to_version="2.0.0")
                ),
            )],
            version_context="3.0.0",  # outside range
        )
        # Override with a version inside the range
        result = engine.apply([_make_change()], version_context="1.5.0")
        assert len(result.suppressed) == 1

    # ── invalid version_range at load time ──────────────────────────────

    def test_invalid_semver_at_load_raises(self) -> None:
        with pytest.raises((ValueError, SuppressionError), match="Invalid"):
            SuppressionEngine([SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(from_version="not-a-semver")
                ),
            )])

    def test_invalid_intel_quarterly_at_load_raises(self) -> None:
        with pytest.raises((ValueError, SuppressionError)):
            SuppressionEngine([SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(
                        from_version="2024",  # missing quarter
                        scheme="intel_quarterly",
                    )
                ),
            )])

    def test_invalid_intel_quarterly_quarter_out_of_range_raises(self) -> None:
        with pytest.raises((ValueError, SuppressionError), match="quarter must be 1..4"):
            SuppressionEngine([SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(
                        from_version="2024.0",
                        scheme="intel_quarterly",
                    )
                ),
            )])

    def test_invalid_linear_mixed_bound_types_raises(self) -> None:
        with pytest.raises((ValueError, SuppressionError), match="both int or both str"):
            SuppressionEngine([SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    version_range=VersionRange(
                        from_version="10",
                        to_version="zzz",
                        scheme="linear",
                    )
                ),
            )])


# ---------------------------------------------------------------------------
# Task 3: Security boundary hardening
# ---------------------------------------------------------------------------

class TestSecurityLimits:
    """Tests for input length limits in SuppressionEngine."""

    def test_entity_glob_too_long_raises(self) -> None:
        long_glob = "a" * 501
        with pytest.raises((ValueError, SuppressionError), match="entity_glob too long"):
            SuppressionEngine([SuppressionRule(entity_glob=long_glob)])

    def test_entity_glob_at_limit_ok(self) -> None:
        ok_glob = "a" * 500
        engine = SuppressionEngine([SuppressionRule(entity_glob=ok_glob)])
        assert engine is not None

    def test_entity_regex_too_long_raises(self) -> None:
        long_regex = "a" * 501
        with pytest.raises((ValueError, SuppressionError), match="entity_regex too long"):
            SuppressionEngine([SuppressionRule(entity_regex=long_regex)])

    def test_entity_regex_at_limit_ok(self) -> None:
        ok_regex = "a" * 500
        engine = SuppressionEngine([SuppressionRule(entity_regex=ok_regex)])
        assert engine is not None

    def test_reason_too_long_raises(self) -> None:
        long_reason = "x" * 1001
        with pytest.raises((ValueError, SuppressionError), match="reason too long"):
            SuppressionEngine([SuppressionRule(reason=long_reason)])

    def test_reason_at_limit_ok(self) -> None:
        ok_reason = "x" * 1000
        engine = SuppressionEngine([SuppressionRule(reason=ok_reason)])
        assert engine is not None

    def test_reason_empty_ok(self) -> None:
        engine = SuppressionEngine([SuppressionRule(reason="")])
        assert engine is not None


class TestPipelineNullGuard:
    """Tests for null-input guards in pipeline.analyse()."""

    def test_analyse_none_old_raises_type_error(self) -> None:
        snap = _empty_snap()
        with pytest.raises(TypeError, match="old AbiSnapshot is None"):
            analyse(None, snap)  # type: ignore[arg-type]

    def test_analyse_none_new_raises_type_error(self) -> None:
        snap = _empty_snap()
        with pytest.raises(TypeError, match="new AbiSnapshot is None"):
            analyse(snap, None)  # type: ignore[arg-type]

    def test_analyse_both_none_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="old AbiSnapshot is None"):
            analyse(None, None)  # type: ignore[arg-type]


class TestErrorHierarchy:
    """Tests for structured AbicheckError hierarchy."""

    def test_abicheckerror_is_exception(self) -> None:
        assert issubclass(AbicheckError, Exception)

    def test_validation_error_is_abicheckerror(self) -> None:
        assert issubclass(ValidationError, AbicheckError)

    def test_snapshot_error_is_abicheckerror(self) -> None:
        assert issubclass(SnapshotError, AbicheckError)

    def test_suppression_error_is_abicheckerror(self) -> None:
        assert issubclass(SuppressionError, AbicheckError)

    def test_suppression_error_is_value_error(self) -> None:
        """SuppressionError inherits ValueError for backward compatibility."""
        assert issubclass(SuppressionError, ValueError)

    def test_suppression_error_caught_as_value_error(self) -> None:
        """Existing code catching ValueError continues to work."""
        with pytest.raises(ValueError):
            raise SuppressionError("test error")

    def test_suppression_error_caught_as_abicheckerror(self) -> None:
        with pytest.raises(AbicheckError):
            raise SuppressionError("test error")

    def test_suppression_engine_raises_suppression_error(self) -> None:
        """SuppressionEngine raises SuppressionError for invalid patterns."""
        with pytest.raises(SuppressionError):
            SuppressionEngine([SuppressionRule(entity_regex="(", reason="broken")])

    def test_suppression_engine_raises_for_glob_too_long(self) -> None:
        """Length limit raises SuppressionError (not bare ValueError)."""
        with pytest.raises(SuppressionError):
            SuppressionEngine([SuppressionRule(entity_glob="a" * 501)])

    def test_can_instantiate_all_error_types(self) -> None:
        """All error types can be instantiated and carry messages."""
        for cls in [AbicheckError, ValidationError, SnapshotError, SuppressionError]:
            e = cls("test message")
            assert str(e) == "test message"

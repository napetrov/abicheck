"""Tests for Phase 3: scope.platform filtering in SuppressionEngine + detect_platform()."""
from __future__ import annotations

import pytest

from abicheck.core.errors import SuppressionError
from abicheck.core.model import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    EntityType,
    Origin,
)
from abicheck.core.pipeline import KNOWN_PLATFORMS, detect_platform
from abicheck.core.suppressions import SuppressionEngine, SuppressionRule
from abicheck.core.suppressions.rule import SuppressionScope
from abicheck.model import AbiSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_change(name: str = "foo") -> Change:
    return Change(
        change_kind=ChangeKind.SYMBOL,
        entity_type=EntityType.FUNCTION,
        entity_name=name,
        before=EntitySnapshot("int foo()"),
        after=EntitySnapshot("void foo()"),
        severity=ChangeSeverity.BREAK,
        origin=Origin.CASTXML,
        confidence=0.9,
    )


def _engine_with_platform(platform: str) -> SuppressionEngine:
    return SuppressionEngine([
        SuppressionRule(
            entity_glob="*",
            scope=SuppressionScope(platform=platform),
            reason=f"platform={platform}",
        )
    ])


def _snap(platform: str | None = None, has_elf: bool = False) -> AbiSnapshot:
    from abicheck.elf_metadata import ElfMetadata  # noqa: PLC0415
    elf = ElfMetadata(soname="", needed=[], rpath="", runpath="",
                      versions_defined=[], versions_required={}, symbols=[]) if has_elf else None
    return AbiSnapshot(library="libfoo.so", version="1.0", platform=platform, elf=elf)


# ---------------------------------------------------------------------------
# detect_platform()
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    def test_explicit_elf_platform(self) -> None:
        snap = _snap(platform="elf")
        assert detect_platform(snap) == "elf"

    def test_explicit_pe_platform(self) -> None:
        snap = _snap(platform="pe")
        assert detect_platform(snap) == "pe"

    def test_explicit_macho_platform(self) -> None:
        snap = _snap(platform="macho")
        assert detect_platform(snap) == "macho"

    def test_inferred_from_elf_metadata(self) -> None:
        """When platform is None but elf metadata present → infer 'elf'."""
        snap = _snap(platform=None, has_elf=True)
        assert detect_platform(snap) == "elf"

    def test_none_when_no_platform_and_no_elf(self) -> None:
        snap = _snap(platform=None, has_elf=False)
        assert detect_platform(snap) is None

    def test_unknown_explicit_platform_returns_none(self) -> None:
        """Unknown platform string → returns None (not a known platform)."""
        snap = _snap(platform="wasm")
        assert detect_platform(snap) is None

    def test_explicit_platform_takes_priority_over_elf_infer(self) -> None:
        """Explicit platform wins even when elf metadata present."""
        snap = _snap(platform="macho", has_elf=True)
        assert detect_platform(snap) == "macho"

    def test_known_platforms_constant(self) -> None:
        assert "elf" in KNOWN_PLATFORMS
        assert "pe" in KNOWN_PLATFORMS
        assert "macho" in KNOWN_PLATFORMS


# ---------------------------------------------------------------------------
# scope.platform validation at load time
# ---------------------------------------------------------------------------

class TestPlatformValidationAtLoad:
    def test_valid_elf_platform_ok(self) -> None:
        engine = _engine_with_platform("elf")
        assert engine is not None

    def test_valid_pe_platform_ok(self) -> None:
        engine = _engine_with_platform("pe")
        assert engine is not None

    def test_valid_macho_platform_ok(self) -> None:
        engine = _engine_with_platform("macho")
        assert engine is not None

    def test_unknown_platform_raises(self) -> None:
        with pytest.raises(SuppressionError, match="Unknown platform"):
            _engine_with_platform("wasm")

    def test_unknown_platform_error_lists_valid_values(self) -> None:
        with pytest.raises(SuppressionError, match="elf"):
            _engine_with_platform("foobar")

    def test_invalid_platform_context_in_apply_raises(self) -> None:
        engine = _engine_with_platform("elf")
        with pytest.raises(SuppressionError, match="Unknown platform_context"):
            engine.apply([_make_change()], platform_context="wasm")


# ---------------------------------------------------------------------------
# platform_context filtering semantics
# ---------------------------------------------------------------------------

class TestPlatformContextFiltering:
    def test_matching_platform_suppresses(self) -> None:
        engine = _engine_with_platform("elf")
        result = engine.apply([_make_change()], platform_context="elf")
        assert len(result.suppressed) == 1

    def test_non_matching_platform_not_suppressed(self) -> None:
        engine = _engine_with_platform("elf")
        result = engine.apply([_make_change()], platform_context="pe")
        assert len(result.active) == 1
        assert len(result.suppressed) == 0

    def test_platform_context_none_skips_filter_conservative(self) -> None:
        """When platform_context=None, filter is skipped → rule still applies."""
        engine = _engine_with_platform("elf")
        result = engine.apply([_make_change()])  # no platform_context
        assert len(result.suppressed) == 1

    def test_platform_context_in_init_applies(self) -> None:
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(platform="elf"))],
            platform_context="elf",
        )
        result = engine.apply([_make_change()])
        assert len(result.suppressed) == 1

    def test_platform_context_in_init_non_match(self) -> None:
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(platform="elf"))],
            platform_context="macho",
        )
        result = engine.apply([_make_change()])
        assert len(result.active) == 1

    def test_apply_platform_context_overrides_init(self) -> None:
        """platform_context in apply() overrides init."""
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(platform="elf"))],
            platform_context="pe",  # no match at init
        )
        # Override with matching platform
        result = engine.apply([_make_change()], platform_context="elf")
        assert len(result.suppressed) == 1

    def test_apply_platform_context_none_falls_back_to_init(self) -> None:
        """apply(platform_context=None) falls back to init value."""
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(platform="elf"))],
            platform_context="pe",  # no match
        )
        result = engine.apply([_make_change()], platform_context=None)
        assert len(result.active) == 1  # uses init "pe" → no match

    def test_rule_without_platform_matches_any_context(self) -> None:
        """Rule with no platform scope → matches regardless of platform_context."""
        engine = SuppressionEngine([SuppressionRule(entity_glob="*", reason="any")])
        for p in ["elf", "pe", "macho"]:
            result = engine.apply([_make_change()], platform_context=p)
            assert len(result.suppressed) == 1, f"Expected suppressed for platform={p}"

    def test_multiple_rules_platform_filters_independently(self) -> None:
        """Different rules for different platforms — each applies only to its platform."""
        engine = SuppressionEngine([
            SuppressionRule(entity_glob="elf_*",
                            scope=SuppressionScope(platform="elf"), reason="elf-only"),
            SuppressionRule(entity_glob="pe_*",
                            scope=SuppressionScope(platform="pe"), reason="pe-only"),
        ])
        elf_result = engine.apply([_make_change("elf_func"), _make_change("pe_func")],
                                   platform_context="elf")
        assert len(elf_result.suppressed) == 1
        assert elf_result.suppressed[0].entity_name == "elf_func"
        assert len(elf_result.active) == 1
        assert elf_result.active[0].entity_name == "pe_func"

    def test_macho_platform_not_suppressed_on_elf(self) -> None:
        engine = _engine_with_platform("macho")
        result = engine.apply([_make_change()], platform_context="elf")
        assert len(result.active) == 1

    def test_platform_combined_with_version_range(self) -> None:
        """platform + version_range: BOTH must match."""
        from abicheck.core.suppressions.rule import VersionRange  # noqa: PLC0415
        engine = SuppressionEngine([
            SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(
                    platform="elf",
                    version_range=VersionRange(from_version="1.0.0", to_version="2.0.0"),
                ),
                reason="elf + semver range",
            )
        ])
        # Both match
        r1 = engine.apply([_make_change()], platform_context="elf", version_context="1.5.0")
        assert len(r1.suppressed) == 1

        # Platform matches, version doesn't
        r2 = engine.apply([_make_change()], platform_context="elf", version_context="3.0.0")
        assert len(r2.active) == 1

        # Version matches, platform doesn't
        r3 = engine.apply([_make_change()], platform_context="pe", version_context="1.5.0")
        assert len(r3.active) == 1


# ---------------------------------------------------------------------------
# detect_platform integration with analyse_full()
# ---------------------------------------------------------------------------

class TestDetectPlatformIntegration:
    def test_analyse_full_auto_detects_elf_platform(self) -> None:
        """analyse_full auto-detects 'elf' from snapshot and passes to engine."""
        from abicheck.core.pipeline import analyse_full  # noqa: PLC0415
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        snap_v1 = _snap(platform="elf")
        snap_v1.functions = [Function(name="foo", mangled="_Z3foov",
                                       return_type="int", visibility=Visibility.PUBLIC)]

        snap_v2 = _snap(platform="elf")
        snap_v2.functions = []  # foo removed → BREAKING

        # Rule only suppresses on elf — should apply
        engine = SuppressionEngine([
            SuppressionRule(entity_glob="foo", scope=SuppressionScope(platform="elf"))
        ])
        result = analyse_full(snap_v1, snap_v2, engine=engine)
        # foo removed and suppressed → verdict PASS
        assert result.summary.verdict.value in ("pass",), f"Expected PASS, got {result.summary.verdict}"

    def test_analyse_full_no_suppression_on_wrong_platform(self) -> None:
        """analyse_full with pe snapshot: elf-only rule should not suppress."""
        from abicheck.core.pipeline import analyse_full  # noqa: PLC0415
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        snap_v1 = _snap(platform="pe")
        snap_v1.functions = [Function(name="foo", mangled="_Z3foov",
                                       return_type="int", visibility=Visibility.PUBLIC)]
        snap_v2 = _snap(platform="pe")
        snap_v2.functions = []  # foo removed → BREAKING, not suppressed

        engine = SuppressionEngine([
            SuppressionRule(entity_glob="foo", scope=SuppressionScope(platform="elf"))
        ])
        result = analyse_full(snap_v1, snap_v2, engine=engine)
        # foo removed, elf rule doesn't apply to pe → BLOCK
        assert result.summary.verdict.value in ("block",), f"Expected BLOCK, got {result.summary.verdict}"

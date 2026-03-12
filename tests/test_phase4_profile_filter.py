"""Tests for Phase 4: scope.profile filtering in SuppressionEngine + detect_profile()."""
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
from abicheck.core.pipeline import KNOWN_PROFILES, detect_profile
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


def _engine_with_profile(profile: str) -> SuppressionEngine:
    return SuppressionEngine([
        SuppressionRule(
            entity_glob="*",
            scope=SuppressionScope(profile=profile),
            reason=f"profile={profile}",
        )
    ])


def _snap(profile: str | None = None) -> AbiSnapshot:
    return AbiSnapshot(library="libfoo.so", version="1.0", language_profile=profile)


# ---------------------------------------------------------------------------
# detect_profile()
# ---------------------------------------------------------------------------

class TestDetectProfile:
    def test_explicit_c_profile(self) -> None:
        snap = _snap(profile="c")
        assert detect_profile(snap) == "c"

    def test_explicit_cpp_profile(self) -> None:
        snap = _snap(profile="cpp")
        assert detect_profile(snap) == "cpp"

    def test_explicit_sycl_profile(self) -> None:
        snap = _snap(profile="sycl")
        assert detect_profile(snap) == "sycl"

    def test_unknown_explicit_profile_returns_none(self) -> None:
        snap = _snap(profile="fortran")
        assert detect_profile(snap) is None

    def test_none_when_no_profile_and_no_functions(self) -> None:
        snap = _snap(profile=None)
        assert detect_profile(snap) is None

    def test_infer_cpp_from_mangled_symbol(self) -> None:
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        snap = _snap(profile=None)
        snap.functions = [
            Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC),
        ]
        assert detect_profile(snap) == "cpp"

    def test_infer_c_from_extern_c_only(self) -> None:
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        snap = _snap(profile=None)
        snap.functions = [
            Function(
                name="foo",
                mangled="foo",
                return_type="int",
                visibility=Visibility.PUBLIC,
                is_extern_c=True,
            ),
            Function(
                name="bar",
                mangled="bar",
                return_type="int",
                visibility=Visibility.PUBLIC,
                is_extern_c=True,
            ),
        ]
        assert detect_profile(snap) == "c"

    def test_mixed_symbols_unknown(self) -> None:
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        snap = _snap(profile=None)
        snap.functions = [
            Function(name="foo", mangled="foo", return_type="int", visibility=Visibility.PUBLIC, is_extern_c=False),
            Function(name="bar", mangled="bar", return_type="int", visibility=Visibility.PUBLIC, is_extern_c=True),
        ]
        assert detect_profile(snap) is None

    def test_known_profiles_constant(self) -> None:
        assert "c" in KNOWN_PROFILES
        assert "cpp" in KNOWN_PROFILES
        assert "sycl" in KNOWN_PROFILES


# ---------------------------------------------------------------------------
# scope.profile validation at load time
# ---------------------------------------------------------------------------

class TestProfileValidationAtLoad:
    def test_valid_c_profile_ok(self) -> None:
        engine = _engine_with_profile("c")
        assert engine is not None

    def test_valid_cpp_profile_ok(self) -> None:
        engine = _engine_with_profile("cpp")
        assert engine is not None

    def test_valid_sycl_profile_ok(self) -> None:
        engine = _engine_with_profile("sycl")
        assert engine is not None

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(SuppressionError, match="Unknown profile"):
            _engine_with_profile("fortran")

    def test_invalid_profile_context_in_apply_raises(self) -> None:
        engine = _engine_with_profile("cpp")
        with pytest.raises(SuppressionError, match="Unknown profile_context"):
            engine.apply([_make_change()], profile_context="fortran")


# ---------------------------------------------------------------------------
# profile_context filtering semantics
# ---------------------------------------------------------------------------

class TestProfileContextFiltering:
    def test_matching_profile_suppresses(self) -> None:
        engine = _engine_with_profile("cpp")
        result = engine.apply([_make_change()], profile_context="cpp")
        assert len(result.suppressed) == 1

    def test_non_matching_profile_not_suppressed(self) -> None:
        engine = _engine_with_profile("cpp")
        result = engine.apply([_make_change()], profile_context="c")
        assert len(result.active) == 1
        assert len(result.suppressed) == 0

    def test_profile_context_none_skips_filter_conservative(self) -> None:
        engine = _engine_with_profile("cpp")
        result = engine.apply([_make_change()])
        assert len(result.suppressed) == 1

    def test_profile_context_in_init_applies(self) -> None:
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(profile="cpp"))],
            profile_context="cpp",
        )
        result = engine.apply([_make_change()])
        assert len(result.suppressed) == 1

    def test_apply_profile_context_overrides_init(self) -> None:
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(profile="cpp"))],
            profile_context="c",
        )
        result = engine.apply([_make_change()], profile_context="cpp")
        assert len(result.suppressed) == 1

    def test_apply_profile_context_none_falls_back_to_init(self) -> None:
        engine = SuppressionEngine(
            [SuppressionRule(entity_glob="*", scope=SuppressionScope(profile="cpp"))],
            profile_context="c",
        )
        result = engine.apply([_make_change()], profile_context=None)
        assert len(result.active) == 1

    def test_profile_combined_with_platform_both_must_match(self) -> None:
        engine = SuppressionEngine([
            SuppressionRule(
                entity_glob="*",
                scope=SuppressionScope(platform="elf", profile="cpp"),
                reason="elf+cpp",
            )
        ])
        # both match
        r1 = engine.apply([_make_change()], platform_context="elf", profile_context="cpp")
        assert len(r1.suppressed) == 1
        # profile mismatch
        r2 = engine.apply([_make_change()], platform_context="elf", profile_context="c")
        assert len(r2.active) == 1
        # platform mismatch
        r3 = engine.apply([_make_change()], platform_context="pe", profile_context="cpp")
        assert len(r3.active) == 1


class TestDetectProfileIntegration:
    def test_analyse_full_auto_detects_cpp_profile(self) -> None:
        from abicheck.core.pipeline import analyse_full  # noqa: PLC0415
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        old = AbiSnapshot(
            library="libfoo.so",
            version="1",
            platform="elf",
            functions=[Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC)],
        )
        new = AbiSnapshot(
            library="libfoo.so",
            version="2",
            platform="elf",
            functions=[],
        )

        engine = SuppressionEngine([
            SuppressionRule(entity_glob="foo", scope=SuppressionScope(platform="elf", profile="cpp"))
        ])
        out = analyse_full(old, new, engine=engine)
        assert out.summary.verdict.value == "pass"

    def test_analyse_full_profile_mismatch_not_suppressed(self) -> None:
        from abicheck.core.pipeline import analyse_full  # noqa: PLC0415
        from abicheck.model import Function, Visibility  # noqa: PLC0415

        old = AbiSnapshot(
            library="libfoo.so",
            version="1",
            platform="elf",
            language_profile="c",
            functions=[Function(name="foo", mangled="foo", return_type="int", visibility=Visibility.PUBLIC, is_extern_c=True)],
        )
        new = AbiSnapshot(
            library="libfoo.so",
            version="2",
            platform="elf",
            language_profile="c",
            functions=[],
        )

        engine = SuppressionEngine([
            SuppressionRule(entity_glob="foo", scope=SuppressionScope(platform="elf", profile="cpp"))
        ])
        out = analyse_full(old, new, engine=engine)
        assert out.summary.verdict.value == "block"

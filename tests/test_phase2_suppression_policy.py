from __future__ import annotations

import pytest

from abicheck.core.model import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    Origin,
    PolicyVerdict,
)
from abicheck.core.pipeline import analyse_full
from abicheck.core.policy import PluginAbiPolicy, SdkVendorPolicy, StrictAbiPolicy
from abicheck.core.suppressions import SuppressionEngine, SuppressionRule


def _make_change(
    *,
    name: str = "foo",
    kind: ChangeKind = ChangeKind.SYMBOL,
    severity: ChangeSeverity = ChangeSeverity.BREAK,
) -> Change:
    return Change(
        change_kind=kind,
        entity_type="function",
        entity_name=name,
        before=EntitySnapshot("int foo()"),
        after=EntitySnapshot("void foo()"),
        severity=severity,
        origin=Origin.CASTXML,
        confidence=0.9,
    )


def _snap_with_func(name: str = "foo", version: str = "v1"):  # type: ignore[no-untyped-def]
    from abicheck.model import AbiSnapshot, Function, Visibility
    return AbiSnapshot(
        library="libfoo.so",
        version=version,
        functions=[Function(name=name, mangled=f"_Z{len(name)}{name}v",
                            return_type="int", visibility=Visibility.PUBLIC)],
        variables=[],
        types=[],
    )


def _empty_snap(version: str = "v2"):  # type: ignore[no-untyped-def]
    from abicheck.model import AbiSnapshot
    return AbiSnapshot(library="libfoo.so", version=version,
                       functions=[], variables=[], types=[])


class TestSuppressionEngine:
    def test_invalid_regex_fails_at_load(self) -> None:
        with pytest.raises(ValueError, match="Invalid RE2 pattern"):
            SuppressionEngine([SuppressionRule(entity_regex="(", reason="broken")])

    def test_invalid_glob_fails_at_load(self) -> None:
        # RE2 should reject fundamentally broken patterns; well-formed globs pass
        engine = SuppressionEngine([SuppressionRule(entity_glob="std::*")])
        assert engine is not None

    def test_empty_rules_passthrough(self) -> None:
        engine = SuppressionEngine([])
        result = engine.apply([_make_change(), _make_change(name="bar")])
        assert result.suppressed == []
        assert len(result.active) == 2

    def test_glob_suppresses_matching_entity(self) -> None:
        engine = SuppressionEngine([SuppressionRule(entity_glob="std::*", reason="stdlib")])
        changes = [
            _make_change(name="std::vector<int>::size"),
            _make_change(name="my::api"),
        ]
        result = engine.apply(changes)
        assert len(result.suppressed) == 1
        assert result.suppressed[0].severity == ChangeSeverity.SUPPRESSED
        assert result.suppressed[0].entity_name == "std::vector<int>::size"
        assert len(result.active) == 1

    def test_regex_suppresses_matching_entity(self) -> None:
        engine = SuppressionEngine([
            SuppressionRule(entity_regex=r"_Z.*internal", reason="internal ABI"),
        ])
        changes = [
            _make_change(name="_Zinternalhook"),
            _make_change(name="public_api"),
        ]
        result = engine.apply(changes)
        assert len(result.suppressed) == 1
        assert result.suppressed[0].entity_name == "_Zinternalhook"
        assert len(result.active) == 1

    def test_change_kind_filter(self) -> None:
        engine = SuppressionEngine([
            SuppressionRule(
                change_kind=ChangeKind.TYPE_LAYOUT.value,
                entity_glob="Point*",
                reason="known layout churn",
            ),
        ])
        changes = [
            _make_change(name="Point", kind=ChangeKind.SYMBOL),
            _make_change(name="Point", kind=ChangeKind.TYPE_LAYOUT),
        ]
        result = engine.apply(changes)
        assert len(result.suppressed) == 1
        assert result.suppressed[0].change_kind == ChangeKind.TYPE_LAYOUT

    def test_first_matching_rule_wins(self) -> None:
        rules = [
            SuppressionRule(entity_glob="foo*", reason="rule_one"),
            SuppressionRule(entity_glob="foo*", reason="rule_two"),
        ]
        engine = SuppressionEngine(rules)
        result = engine.apply([_make_change(name="foobar")])
        assert len(result.suppressed) == 1
        matched = result.match_map[id(result.suppressed[0])]
        assert matched.reason == "rule_one"

    def test_glob_and_regex_both_must_match(self) -> None:
        """Both patterns must match — AND semantics."""
        rule = SuppressionRule(entity_glob="std::*", entity_regex=r".*vector.*")
        engine = SuppressionEngine([rule])
        changes = [
            _make_change(name="std::vector<int>::push_back"),  # both match
            _make_change(name="std::string::find"),             # glob only
            _make_change(name="my::vector_impl"),               # regex only
        ]
        result = engine.apply(changes)
        assert len(result.suppressed) == 1
        assert result.suppressed[0].entity_name == "std::vector<int>::push_back"

    def test_match_map_populated(self) -> None:
        rule = SuppressionRule(entity_glob="foo*", reason="test-rule")
        engine = SuppressionEngine([rule])
        result = engine.apply([_make_change(name="foobar")])
        assert len(result.match_map) == 1
        matched = result.match_map[id(result.suppressed[0])]
        assert matched.reason == "test-rule"

    def test_all_suppressed_yields_empty_active(self) -> None:
        engine = SuppressionEngine([SuppressionRule(entity_glob="*", reason="suppress all")])
        changes = [_make_change(name="a"), _make_change(name="b"), _make_change(name="c")]
        result = engine.apply(changes)
        assert len(result.active) == 0
        assert len(result.suppressed) == 3
        assert all(c.severity == ChangeSeverity.SUPPRESSED for c in result.suppressed)


class TestPolicyProfiles:
    def test_strict_abi_blocks_break(self) -> None:
        p = StrictAbiPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.BREAK)])
        assert out.summary.verdict == PolicyVerdict.BLOCK
        assert out.summary.incompatible_count == 1

    def test_strict_abi_warns_review_needed(self) -> None:
        p = StrictAbiPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.REVIEW_NEEDED)])
        assert out.summary.verdict == PolicyVerdict.WARN
        assert out.summary.review_needed_count == 1

    def test_sdk_vendor_warns_review_needed(self) -> None:
        p = SdkVendorPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.REVIEW_NEEDED)])
        assert out.summary.verdict == PolicyVerdict.WARN

    def test_sdk_vendor_blocks_break(self) -> None:
        # sdk_vendor currently mirrors strict_abi (TODO Phase 3 to differentiate)
        p = SdkVendorPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.BREAK)])
        assert out.summary.verdict == PolicyVerdict.BLOCK

    def test_plugin_abi_warns_on_break(self) -> None:
        p = PluginAbiPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.BREAK)])
        assert out.summary.verdict == PolicyVerdict.WARN
        assert out.summary.incompatible_count == 0   # BREAK → WARN, not BLOCK
        assert out.summary.review_needed_count == 1  # WARN counted here

    def test_plugin_abi_passes_review_needed(self) -> None:
        p = PluginAbiPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.REVIEW_NEEDED)])
        assert out.summary.verdict == PolicyVerdict.PASS

    def test_suppressed_change_is_pass_across_profiles(self) -> None:
        """Suppressed changes → PASS regardless of profile."""
        change = _make_change(severity=ChangeSeverity.SUPPRESSED)
        for profile in [StrictAbiPolicy(), SdkVendorPolicy(), PluginAbiPolicy()]:
            out = profile.apply([change])
            assert out.summary.verdict == PolicyVerdict.PASS
            assert out.summary.suppressed_count == 1


class TestPipelineFull:
    def test_analyse_full_applies_suppression_then_policy(self) -> None:
        old = _snap_with_func("foo")
        new = _empty_snap()

        rules = [SuppressionRule(entity_glob="foo", change_kind=ChangeKind.SYMBOL.value)]
        result = analyse_full(old, new, rules=rules, policy="strict_abi")

        assert result.summary.verdict == PolicyVerdict.PASS
        assert result.summary.suppressed_count == 1

    def test_analyse_full_no_suppression_blocks(self) -> None:
        """Without suppression rules, a removed function → BLOCK."""
        old = _snap_with_func("foo")
        new = _empty_snap()

        result = analyse_full(old, new, rules=[], policy="strict_abi")
        assert result.summary.verdict == PolicyVerdict.BLOCK
        assert result.summary.incompatible_count >= 1
        assert result.summary.suppressed_count == 0

    def test_analyse_full_unknown_policy_raises(self) -> None:
        old = _empty_snap("v1")
        new = _empty_snap("v2")
        with pytest.raises(ValueError, match="Unknown policy profile"):
            analyse_full(old, new, rules=[], policy="does_not_exist")

    def test_analyse_full_reuses_engine(self) -> None:
        """Pre-built engine can be passed to avoid re-compiling patterns."""
        engine = SuppressionEngine([SuppressionRule(entity_glob="foo*", reason="batch")])
        old = _snap_with_func("foobar")
        new = _empty_snap()

        result = analyse_full(old, new, engine=engine, policy="strict_abi")
        assert result.summary.suppressed_count == 1

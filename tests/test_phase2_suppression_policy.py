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
from abicheck.model import AbiSnapshot, Function, Visibility


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


def _snap(*, funcs: list[Function] | None = None, version: str = "v1") -> AbiSnapshot:
    return AbiSnapshot(
        library="libfoo.so",
        version=version,
        functions=funcs or [],
        variables=[],
        types=[],
    )


class TestSuppressionEngine:
    def test_invalid_regex_fails_at_load(self) -> None:
        with pytest.raises(ValueError, match="Invalid RE2 pattern"):
            SuppressionEngine([
                SuppressionRule(entity_regex="(", reason="broken regex"),
            ])

    def test_glob_suppresses_matching_entity(self) -> None:
        engine = SuppressionEngine([
            SuppressionRule(entity_glob="std::*", reason="stdlib noise"),
        ])
        changes = [
            _make_change(name="std::vector<int>::size"),
            _make_change(name="my::api"),
        ]
        result = engine.apply(changes)
        assert len(result.suppressed) == 1
        assert result.suppressed[0].severity == ChangeSeverity.SUPPRESSED
        assert result.suppressed[0].entity_name == "std::vector<int>::size"
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


class TestPolicyProfiles:
    def test_strict_abi_blocks_break(self) -> None:
        p = StrictAbiPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.BREAK)])
        assert out.summary.verdict == PolicyVerdict.BLOCK

    def test_sdk_vendor_warns_review_needed(self) -> None:
        p = SdkVendorPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.REVIEW_NEEDED)])
        assert out.summary.verdict == PolicyVerdict.WARN

    def test_plugin_abi_warns_on_break(self) -> None:
        p = PluginAbiPolicy()
        out = p.apply([_make_change(severity=ChangeSeverity.BREAK)])
        assert out.summary.verdict == PolicyVerdict.WARN
        assert out.summary.incompatible_count == 0  # WARN not BLOCK in plugin policy


class TestPipelineFull:
    def test_analyse_full_applies_suppression_then_policy(self) -> None:
        old = _snap(funcs=[
            Function(name="foo", mangled="_Z3foov", return_type="int", visibility=Visibility.PUBLIC),
        ])
        new = _snap(version="v2")

        rules = [SuppressionRule(entity_glob="foo", change_kind=ChangeKind.SYMBOL.value)]
        result = analyse_full(old, new, rules=rules, policy="strict_abi")

        # Removed function would've been BREAK, but suppression turns it into PASS
        assert result.summary.verdict == PolicyVerdict.PASS
        assert result.summary.suppressed_count == 1

    def test_analyse_full_unknown_policy_raises(self) -> None:
        old = _snap()
        new = _snap(version="v2")
        with pytest.raises(ValueError, match="Unknown policy profile"):
            analyse_full(old, new, rules=[], policy="does_not_exist")

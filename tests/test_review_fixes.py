"""Tests for fixes identified during the scan-accuracy review.

Covers:
- canonicalize_type_name edge cases (C3: const-reorder, multi-word, templates)
- Parameter type canonicalization in function signature checks (C1)
- Confidence computation with both snapshots and variables (C2)
- SuppressionList.audit() (H1)
- PolicyFile.validate_overrides() (H1)
- Confidence enum (H2)
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

from abicheck.checker import Change, ChangeKind, compare
from abicheck.checker_policy import Confidence, Verdict
from abicheck.model import (
    AbiSnapshot,
    Function,
    Param,
    ParamKind,
    RecordType,
    TypeField,
    Variable,
    Visibility,
    canonicalize_type_name,
)
from abicheck.policy_file import PolicyFile

# ─── canonicalize_type_name ──────────────────────────────────────────────────


class TestCanonicalizeTypeName:
    """Direct unit tests for canonicalize_type_name."""

    def test_strip_struct_prefix(self):
        assert canonicalize_type_name("struct Foo") == "Foo"

    def test_strip_class_prefix(self):
        assert canonicalize_type_name("class Bar") == "Bar"

    def test_strip_union_prefix(self):
        assert canonicalize_type_name("union Baz") == "Baz"

    def test_strip_enum_prefix(self):
        assert canonicalize_type_name("enum Color") == "Color"

    def test_east_const_simple(self):
        assert canonicalize_type_name("const int") == "int const"

    def test_east_const_pointer(self):
        assert canonicalize_type_name("const int *") == "int const *"

    def test_east_const_multi_word(self):
        """const unsigned long long should move const after full base type."""
        assert canonicalize_type_name("const unsigned long long") == "unsigned long long const"

    def test_east_const_volatile(self):
        """const volatile int should move const after the full base."""
        assert canonicalize_type_name("const volatile int") == "volatile int const"

    def test_east_const_multi_word_pointer(self):
        assert canonicalize_type_name("const unsigned int *") == "unsigned int const *"

    def test_template_type_preserved(self):
        """Template types with angle brackets should not be reordered."""
        assert canonicalize_type_name("const std::vector<int>") == "const std::vector<int>"

    def test_already_east_const(self):
        assert canonicalize_type_name("int const") == "int const"

    def test_pointer_to_const(self):
        """int const * should be left alone (const is already east)."""
        assert canonicalize_type_name("int const *") == "int const *"

    def test_whitespace_collapse(self):
        # Leading whitespace prevents struct-prefix regex from matching (anchored at ^)
        assert canonicalize_type_name("class   Bar") == "Bar"
        assert canonicalize_type_name("int    *") == "int *"

    def test_identity(self):
        assert canonicalize_type_name("int") == "int"

    def test_empty_string(self):
        assert canonicalize_type_name("") == ""


# ─── Parameter type canonicalization (C1) ────────────────────────────────────


class TestParamTypeCanonicalization:
    """Verify that struct/class prefix differences in param types don't cause false positives."""

    def test_struct_prefix_in_param_no_false_positive(self):
        """'struct stat *' vs 'stat *' should NOT trigger FUNC_PARAMS_CHANGED."""
        old = AbiSnapshot(
            library="libtest.so", version="1.0",
            functions=[Function(
                name="do_stat", mangled="_Z7do_statP4stat",
                return_type="int",
                params=[Param(name="s", type="struct stat *", kind=ParamKind.POINTER)],
                visibility=Visibility.PUBLIC,
            )],
        )
        new = AbiSnapshot(
            library="libtest.so", version="2.0",
            functions=[Function(
                name="do_stat", mangled="_Z7do_statP4stat",
                return_type="int",
                params=[Param(name="s", type="stat *", kind=ParamKind.POINTER)],
                visibility=Visibility.PUBLIC,
            )],
        )
        result = compare(old, new)
        param_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_PARAMS_CHANGED]
        assert len(param_changes) == 0, "struct prefix difference should not be a param change"

    def test_const_reorder_in_param_no_false_positive(self):
        """'const int' vs 'int const' in params should NOT trigger FUNC_PARAMS_CHANGED."""
        old = AbiSnapshot(
            library="libtest.so", version="1.0",
            functions=[Function(
                name="get", mangled="_Z3geti",
                return_type="void",
                params=[Param(name="x", type="const int", kind=ParamKind.VALUE)],
                visibility=Visibility.PUBLIC,
            )],
        )
        new = AbiSnapshot(
            library="libtest.so", version="2.0",
            functions=[Function(
                name="get", mangled="_Z3geti",
                return_type="void",
                params=[Param(name="x", type="int const", kind=ParamKind.VALUE)],
                visibility=Visibility.PUBLIC,
            )],
        )
        result = compare(old, new)
        param_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_PARAMS_CHANGED]
        assert len(param_changes) == 0


# ─── Confidence computation (C2) ────────────────────────────────────────────


class TestConfidenceComputation:
    """Verify confidence checks both snapshots and includes variables."""

    def test_confidence_is_enum(self):
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        result = compare(old, new)
        assert isinstance(result.confidence, Confidence)

    def test_confidence_str_comparison_still_works(self):
        """Confidence enum is str-based so string comparisons keep working."""
        assert Confidence.HIGH == "high"
        assert Confidence.MEDIUM == "medium"
        assert Confidence.LOW == "low"

    def test_empty_old_populated_new_has_headers(self):
        """When old is empty but new has functions, has_headers should be True."""
        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(
            library="lib.so", version="2.0",
            functions=[Function(
                name="foo", mangled="_Z3foov",
                return_type="void", visibility=Visibility.PUBLIC,
            )],
        )
        result = compare(old, new)
        assert "header" in result.evidence_tiers

    def test_variables_only_detected_as_headers(self):
        """Snapshots with only variables should still be detected as having header data."""
        old = AbiSnapshot(
            library="lib.so", version="1.0",
            variables=[Variable(
                name="ver", mangled="_Z3verv", type="int",
                visibility=Visibility.PUBLIC,
            )],
        )
        new = copy.deepcopy(old)
        new.version = "2.0"
        result = compare(old, new)
        assert "header" in result.evidence_tiers


# ─── SuppressionList.audit() ────────────────────────────────────────────────


class TestSuppressionAudit:
    """Tests for SuppressionList.audit()."""

    def test_audit_stale_rules(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
        ])
        # No changes match the suppression
        audit = slist.audit([])
        assert len(audit.stale_rules) == 1
        assert audit.has_issues

    def test_audit_matching_rule_not_stale(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
        ])
        change = Change(
            kind=ChangeKind.FUNC_REMOVED,
            symbol="_Z3foov",
            description="removed",
        )
        audit = slist.audit([change])
        assert len(audit.stale_rules) == 0
        # FUNC_REMOVED is BREAKING so should appear in high_risk
        assert len(audit.high_risk_matches) == 1

    def test_audit_expired_rules(self):
        from abicheck.suppression import Suppression, SuppressionList

        past = date.today() - timedelta(days=10)
        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="expired", expires=past),
        ])
        audit = slist.audit([])
        assert len(audit.expired_rules) == 1
        assert audit.has_issues

    def test_audit_near_expiry(self):
        from abicheck.suppression import Suppression, SuppressionList

        soon = date.today() + timedelta(days=5)
        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="expiring", expires=soon),
        ])
        audit = slist.audit([], near_expiry_days=30)
        assert len(audit.near_expiry_rules) == 1

    def test_audit_no_issues(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
        ])
        change = Change(
            kind=ChangeKind.FUNC_ADDED,
            symbol="_Z3foov",
            description="added",
        )
        audit = slist.audit([change])
        # FUNC_ADDED is not BREAKING, rule matched, no expiry
        assert len(audit.stale_rules) == 0
        assert len(audit.high_risk_matches) == 0
        assert not audit.has_issues

    def test_audit_summary_output(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
        ])
        audit = slist.audit([])
        summary = audit.summary()
        assert "stale" in summary.lower() or "matched nothing" in summary.lower()

    def test_audit_summary_no_issues(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
        ])
        change = Change(
            kind=ChangeKind.FUNC_ADDED,
            symbol="_Z3foov",
            description="added",
        )
        audit = slist.audit([change])
        summary = audit.summary()
        assert "No issues found" in summary

    def test_audit_summary_high_risk(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
        ])
        change = Change(
            kind=ChangeKind.FUNC_REMOVED,
            symbol="_Z3foov",
            description="removed",
        )
        audit = slist.audit([change])
        summary = audit.summary()
        assert "BREAKING" in summary

    def test_audit_summary_expired(self):
        from abicheck.suppression import Suppression, SuppressionList

        past = date.today() - timedelta(days=10)
        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="old", expires=past),
        ])
        audit = slist.audit([])
        summary = audit.summary()
        assert "expired" in summary.lower()

    def test_audit_summary_near_expiry(self):
        from abicheck.suppression import Suppression, SuppressionList

        soon = date.today() + timedelta(days=5)
        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="soon", expires=soon),
        ])
        audit = slist.audit([], near_expiry_days=30)
        summary = audit.summary()
        assert "expiring soon" in summary.lower()

    def test_audit_match_counts(self):
        from abicheck.suppression import Suppression, SuppressionList

        slist = SuppressionList([
            Suppression(symbol="_Z3foov", reason="test"),
            Suppression(symbol="_Z3barv", reason="test2"),
        ])
        c1 = Change(kind=ChangeKind.FUNC_ADDED, symbol="_Z3foov", description="added")
        c2 = Change(kind=ChangeKind.FUNC_ADDED, symbol="_Z3foov", description="added2")
        audit = slist.audit([c1, c2])
        assert audit.match_counts[0] == 2  # first rule matched twice
        assert audit.match_counts[1] == 0  # second rule matched nothing
        assert audit.total_rules == 2


# ─── PolicyFile.validate_overrides() ─────────────────────────────────────────


class TestPolicyFileValidateOverrides:
    """Tests for PolicyFile.validate_overrides()."""

    def test_no_overrides_no_warnings(self):
        pf = PolicyFile()
        assert pf.validate_overrides() == []

    def test_critical_kind_to_ignore_warns(self):
        pf = PolicyFile(overrides={ChangeKind.FUNC_REMOVED: Verdict.COMPATIBLE})
        warnings = pf.validate_overrides()
        assert len(warnings) == 1
        assert "HIGH RISK" in warnings[0]

    def test_critical_kind_to_risk_warns(self):
        pf = PolicyFile(overrides={ChangeKind.TYPE_SIZE_CHANGED: Verdict.COMPATIBLE_WITH_RISK})
        warnings = pf.validate_overrides()
        assert len(warnings) == 1
        assert "RISK" in warnings[0]

    def test_breaking_kind_to_ignore_warns(self):
        pf = PolicyFile(overrides={ChangeKind.FUNC_VIRTUAL_ADDED: Verdict.COMPATIBLE})
        warnings = pf.validate_overrides()
        assert len(warnings) == 1
        assert "BREAKING" in warnings[0]

    def test_safe_override_no_warning(self):
        pf = PolicyFile(overrides={ChangeKind.ENUM_MEMBER_RENAMED: Verdict.COMPATIBLE})
        warnings = pf.validate_overrides()
        assert len(warnings) == 0

    def test_critical_kind_to_warn_no_warning(self):
        """Downgrading critical BREAKING to API_BREAK (warn) should not warn."""
        pf = PolicyFile(overrides={ChangeKind.FUNC_REMOVED: Verdict.API_BREAK})
        warnings = pf.validate_overrides()
        assert len(warnings) == 0

    def test_multiple_overrides_multiple_warnings(self):
        pf = PolicyFile(overrides={
            ChangeKind.FUNC_REMOVED: Verdict.COMPATIBLE,
            ChangeKind.VAR_REMOVED: Verdict.COMPATIBLE,
            ChangeKind.SONAME_CHANGED: Verdict.COMPATIBLE_WITH_RISK,
        })
        warnings = pf.validate_overrides()
        assert len(warnings) == 3

    def test_validate_uses_base_policy_breaking_kinds(self):
        """validate_overrides should use the base policy's breaking set."""
        # Under plugin_abi, CALLING_CONVENTION_CHANGED is downgraded to COMPATIBLE.
        # Under strict_abi, it's BREAKING. So overriding it to 'ignore' under
        # strict_abi should warn, but the kind itself is still in BREAKING_KINDS
        # for strict_abi.
        pf = PolicyFile(
            base_policy="strict_abi",
            overrides={ChangeKind.CALLING_CONVENTION_CHANGED: Verdict.COMPATIBLE},
        )
        warnings = pf.validate_overrides()
        assert len(warnings) == 1
        assert "BREAKING" in warnings[0]


# ─── Namespace-qualified canonicalization ─────────────────────────────────────


class TestCanonicalizeNamespaceTypes:
    """Verify canonicalize_type_name handles scoped/qualified identifiers."""

    def test_const_namespace_type_pointer(self):
        assert canonicalize_type_name("const ns::Type *") == "ns::Type const *"

    def test_const_namespace_type_reference(self):
        assert canonicalize_type_name("const ns::Type &") == "ns::Type const &"

    def test_const_nested_namespace(self):
        assert canonicalize_type_name("const a::b::C") == "a::b::C const"

    def test_leading_whitespace_struct(self):
        """Leading whitespace should not prevent struct-prefix stripping."""
        assert canonicalize_type_name("  struct Foo") == "Foo"

    def test_const_struct_combined(self):
        """const struct Foo * should canonicalize to Foo const *."""
        assert canonicalize_type_name("const struct Foo *") == "Foo const *"


# ─── Union field type canonicalization ────────────────────────────────────────


class TestUnionFieldCanonicalization:
    """Verify union field type comparison uses canonicalize_type_name."""

    def test_union_field_struct_prefix_no_false_positive(self):
        """'struct X' vs 'X' in union field types should NOT trigger UNION_FIELD_TYPE_CHANGED."""
        old = AbiSnapshot(
            library="libtest.so", version="1.0",
            types=[RecordType(
                name="MyUnion", kind="union", is_union=True,
                fields=[TypeField(name="data", type="struct Inner")],
            )],
        )
        new = AbiSnapshot(
            library="libtest.so", version="2.0",
            types=[RecordType(
                name="MyUnion", kind="union", is_union=True,
                fields=[TypeField(name="data", type="Inner")],
            )],
        )
        result = compare(old, new)
        union_changes = [c for c in result.changes if c.kind == ChangeKind.UNION_FIELD_TYPE_CHANGED]
        assert len(union_changes) == 0, "struct prefix difference should not be a union field type change"

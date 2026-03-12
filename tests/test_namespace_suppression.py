"""B8: Namespace suppression (abicc #4, abicc #43).

SuppressionEngine should support namespace-level pattern matching so that
all changes under a given namespace (e.g. `internal::`) can be suppressed
with a single rule.

Implementation:
- SuppressionRule gains `namespace_pattern` field (RE2 pattern)
- SuppressionEngine._rule_matches() extracts the namespace prefix from
  entity_name (text before last '::') and fullmatches against namespace_re
- entity_name "internal::Foo" → namespace prefix "internal"
- entity_name "a::b::Foo::bar" → namespace prefix "a::b::Foo"
- entity_name "global_func" → namespace prefix "" (empty)
"""
from __future__ import annotations

import pytest

from abicheck.core.model import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    EntityType,
    Origin,
)
from abicheck.core.suppressions import SuppressionEngine
from abicheck.core.suppressions.rule import SuppressionRule


def _change(entity_name: str, kind: ChangeKind = ChangeKind.SYMBOL) -> Change:
    return Change(
        change_kind=kind,
        entity_type=EntityType.FUNCTION,
        entity_name=entity_name,
        before=EntitySnapshot(entity_repr="old"),
        after=EntitySnapshot(entity_repr="<removed>"),
        severity=ChangeSeverity.BREAK,
        origin=Origin.ELF,
    )


class TestNamespaceSuppressionField:
    """Verify SuppressionRule has namespace_pattern field."""

    def test_namespace_pattern_field_exists(self) -> None:
        """SuppressionRule must have namespace_pattern field."""
        rule = SuppressionRule(reason="test")
        assert hasattr(rule, "namespace_pattern")
        assert rule.namespace_pattern is None  # default

    def test_namespace_pattern_can_be_set(self) -> None:
        """SuppressionRule.namespace_pattern can be set to a string."""
        rule = SuppressionRule(namespace_pattern="internal", reason="suppress internal ns")
        assert rule.namespace_pattern == "internal"


class TestNamespaceSuppressionMatching:
    """Verify SuppressionEngine matches namespace_pattern correctly."""

    def test_suppress_internal_namespace(self) -> None:
        """Changes under 'internal' namespace must be suppressed.

        namespace prefix extraction: rfind('::') gives last separator.
        - "internal::Foo" → namespace = "internal" → matches "internal"
        - "internal::Bar::baz" → namespace = "internal::Bar" → does NOT match "internal"
          (use pattern r"internal(::.*)?" to match all depths)
        """
        rule = SuppressionRule(namespace_pattern="internal", reason="internal namespace")
        engine = SuppressionEngine([rule])

        changes = [
            _change("internal::Foo"),   # namespace = "internal" → suppressed
            _change("public::Bar"),     # namespace = "public" → active
        ]
        result = engine.apply(changes)
        assert len(result.suppressed) == 1
        assert result.suppressed[0].entity_name == "internal::Foo"
        assert len(result.active) == 1
        assert result.active[0].entity_name == "public::Bar"

    def test_do_not_suppress_public_namespace(self) -> None:
        """Changes outside the namespace must NOT be suppressed."""
        rule = SuppressionRule(namespace_pattern="internal", reason="internal namespace")
        engine = SuppressionEngine([rule])

        changes = [
            _change("internal::Foo"),  # suppressed
            _change("public_api"),     # NOT suppressed (no namespace)
            _change("MyLib::PublicFoo"),  # NOT suppressed (different namespace)
        ]
        result = engine.apply(changes)
        suppressed_names = {c.entity_name for c in result.suppressed}
        active_names = {c.entity_name for c in result.active}
        assert "internal::Foo" in suppressed_names
        assert "public_api" in active_names
        assert "MyLib::PublicFoo" in active_names

    def test_namespace_pattern_with_nested_namespace(self) -> None:
        """Pattern 'internal' matches 'internal::detail::Foo' (namespace prefix = 'internal::detail')."""
        # 'internal' fullmatches only the immediate namespace 'internal', not 'internal::detail'
        rule = SuppressionRule(namespace_pattern="internal", reason="internal ns only")
        engine = SuppressionEngine([rule])

        changes = [
            _change("internal::Foo"),          # namespace = "internal" → suppressed
            _change("internal::detail::Bar"),   # namespace = "internal::detail" → NOT suppressed
        ]
        result = engine.apply(changes)
        suppressed_names = {c.entity_name for c in result.suppressed}
        active_names = {c.entity_name for c in result.active}
        assert "internal::Foo" in suppressed_names
        assert "internal::detail::Bar" in active_names

    def test_namespace_pattern_regex_nested(self) -> None:
        """Regex pattern 'internal(::.*)?$' matches all depths of 'internal::*'."""
        rule = SuppressionRule(namespace_pattern=r"internal(::.*)?" , reason="all internal")
        engine = SuppressionEngine([rule])

        changes = [
            _change("internal::Foo"),
            _change("internal::detail::Bar"),
            _change("internal::detail::impl::Baz"),
            _change("public_api"),
        ]
        result = engine.apply(changes)
        suppressed_names = {c.entity_name for c in result.suppressed}
        active_names = {c.entity_name for c in result.active}
        assert "internal::Foo" in suppressed_names
        assert "internal::detail::Bar" in suppressed_names
        assert "internal::detail::impl::Baz" in suppressed_names
        assert "public_api" in active_names

    def test_namespace_pattern_global_scope(self) -> None:
        """Empty namespace pattern matches symbols in global scope (no ::)."""
        rule = SuppressionRule(namespace_pattern="", reason="suppress global scope")
        engine = SuppressionEngine([rule])

        changes = [
            _change("global_func"),    # no namespace → namespace prefix = ""
            _change("MyLib::method"),  # has namespace → not matched
        ]
        result = engine.apply(changes)
        suppressed_names = {c.entity_name for c in result.suppressed}
        assert "global_func" in suppressed_names
        assert "MyLib::method" not in suppressed_names

    def test_namespace_and_entity_glob_combined(self) -> None:
        """namespace_pattern + entity_glob: BOTH must match."""
        rule = SuppressionRule(
            namespace_pattern="internal",
            entity_glob="internal::*Impl",
            reason="suppress internal Impl classes",
        )
        engine = SuppressionEngine([rule])

        changes = [
            _change("internal::FooImpl"),   # namespace=internal AND glob=*Impl → suppressed
            _change("internal::Foo"),        # namespace=internal but NOT *Impl → active
            _change("public::FooImpl"),      # *Impl but NOT internal namespace → active
        ]
        result = engine.apply(changes)
        suppressed_names = {c.entity_name for c in result.suppressed}
        active_names = {c.entity_name for c in result.active}
        assert "internal::FooImpl" in suppressed_names
        assert "internal::Foo" in active_names
        assert "public::FooImpl" in active_names

    def test_namespace_suppression_with_compare(self) -> None:
        """End-to-end: namespace suppression via core pipeline."""
        from abicheck.core.pipeline import analyse_full
        from abicheck.model import AbiSnapshot, Function, Visibility

        def _func(name: str, mangled: str) -> Function:
            return Function(
                name=name, mangled=mangled,
                return_type="void", visibility=Visibility.PUBLIC,
            )

        old = AbiSnapshot(library="lib.so", version="1.0", functions=[
            _func("internal::impl_foo", "_ZN8internal8impl_fooEv"),
            _func("public_api", "_Zpub"),
        ])
        new = AbiSnapshot(library="lib.so", version="2.0", functions=[
            # internal::impl_foo removed — suppressed by namespace rule
            _func("public_api", "_Zpub"),
        ])

        rule = SuppressionRule(namespace_pattern="internal", reason="internal namespace")
        result = analyse_full(old, new, rules=[rule])
        # The internal function change should be suppressed
        all_changes = result.annotated_changes
        suppressed = [ac for ac in all_changes if ac.change.severity.value == "suppressed"]
        suppressed_names = {ac.change.entity_name for ac in suppressed}
        assert any("internal" in n for n in suppressed_names), (
            "internal::impl_foo removal must be suppressed by namespace rule"
        )

    def test_invalid_namespace_pattern_raises(self) -> None:
        """Invalid RE2 pattern in namespace_pattern must raise SuppressionError."""
        from abicheck.core.errors import SuppressionError
        rule = SuppressionRule(namespace_pattern="[invalid regex", reason="bad")
        with pytest.raises(SuppressionError, match="namespace_pattern"):
            SuppressionEngine([rule])

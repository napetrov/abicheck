"""Unit tests for _is_nontrivial_aggregate — full Itanium ABI triviality check."""
from __future__ import annotations

from abicheck.dwarf_advanced import _is_nontrivial_aggregate

# ---------------------------------------------------------------------------
# Minimal DWARF DIE stubs (mirrors _Die / _Attr in test_phase3_dwarf_helpers)
# ---------------------------------------------------------------------------

class _Attr:
    def __init__(self, value: object, form: str = "DW_FORM_ref4") -> None:
        self.value = value
        self.form = form


class _Die:
    def __init__(
        self,
        tag: str,
        attrs: dict[str, object] | None = None,
        children: list[_Die] | None = None,
        offset: int = 0,
    ) -> None:
        self.tag = tag
        self.attributes = attrs or {}
        self._children = list(children or [])
        self.offset = offset

    def iter_children(self):  # noqa: ANN201
        return iter(self._children)


class _CU:
    """Minimal CU stub with a get_DIE_from_refaddr lookup table."""

    def __init__(self, die_map: dict[int, _Die] | None = None, cu_offset: int = 0) -> None:
        self._die_map: dict[int, _Die] = die_map or {}
        self.cu_offset = cu_offset

    def get_DIE_from_refaddr(self, offset: int) -> _Die | None:
        return self._die_map.get(offset)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestNontrivialAggregate:
    """Unit tests covering all edge cases of _is_nontrivial_aggregate."""

    # 1. Simple struct with no dtor → False (trivial)
    def test_simple_struct_no_dtor(self) -> None:
        struct_die = _Die("DW_TAG_structure_type", {"DW_AT_name": _Attr("Point")}, offset=1)
        assert _is_nontrivial_aggregate(struct_die) is False

    # 2. User-defined dtor → True (non-trivial)
    def test_user_defined_dtor(self) -> None:
        dtor = _Die(
            "DW_TAG_subprogram",
            {"DW_AT_name": _Attr("~Foo"), "DW_AT_linkage_name": _Attr("_ZN3FooD1Ev")},
            offset=10,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Foo")},
            children=[dtor],
            offset=1,
        )
        assert _is_nontrivial_aggregate(struct_die) is True

    # 3. DW_AT_defaulted=1 dtor → False (trivially defaulted)
    def test_defaulted_dtor_is_trivial(self) -> None:
        dtor = _Die(
            "DW_TAG_subprogram",
            {
                "DW_AT_name": _Attr("~Bar"),
                "DW_AT_linkage_name": _Attr("_ZN3BarD1Ev"),
                "DW_AT_defaulted": _Attr(1),
            },
            offset=10,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Bar")},
            children=[dtor],
            offset=2,
        )
        assert _is_nontrivial_aggregate(struct_die) is False

    # 4. DW_AT_artificial=1 dtor → False (compiler-generated, not user-declared)
    def test_artificial_dtor_is_trivial(self) -> None:
        dtor = _Die(
            "DW_TAG_subprogram",
            {
                "DW_AT_name": _Attr("~Baz"),
                "DW_AT_linkage_name": _Attr("_ZN3BazD1Ev"),
                "DW_AT_artificial": _Attr(1),
            },
            offset=10,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Baz")},
            children=[dtor],
            offset=3,
        )
        assert _is_nontrivial_aggregate(struct_die) is False

    # 5. DW_TAG_inheritance child → True (has base class, conservative)
    def test_inheritance_child_is_nontrivial(self) -> None:
        base_ref = _Die("DW_TAG_inheritance", {"DW_AT_type": _Attr(99)}, offset=20)
        struct_die = _Die(
            "DW_TAG_class_type",
            {"DW_AT_name": _Attr("Derived")},
            children=[base_ref],
            offset=4,
        )
        assert _is_nontrivial_aggregate(struct_die) is True

    # 6. Copy ctor pattern in linkage (C1E) without DW_AT_defaulted → True
    def test_user_copy_ctor_is_nontrivial(self) -> None:
        copy_ctor = _Die(
            "DW_TAG_subprogram",
            {
                "DW_AT_name": _Attr("Widget"),
                "DW_AT_linkage_name": _Attr("_ZN6WidgetC1ERKS_"),
            },
            offset=10,
        )
        struct_die = _Die(
            "DW_TAG_class_type",
            {"DW_AT_name": _Attr("Widget")},
            children=[copy_ctor],
            offset=5,
        )
        assert _is_nontrivial_aggregate(struct_die) is True

    # 7. Non-struct tag → always False
    def test_non_struct_tag_always_false(self) -> None:
        die = _Die("DW_TAG_base_type", {"DW_AT_name": _Attr("int")}, offset=6)
        assert _is_nontrivial_aggregate(die) is False

    # 8. Cache is populated and reused
    def test_cache_is_populated(self) -> None:
        struct_die = _Die("DW_TAG_structure_type", {"DW_AT_name": _Attr("Cached")}, offset=100)
        cache: dict[int, bool] = {}
        result1 = _is_nontrivial_aggregate(struct_die, cache=cache)
        assert 100 in cache
        assert result1 is False
        assert cache[100] is False

    # 9. Cache sentinel prevents infinite recursion on cyclic member types
    def test_cache_prevents_cycle(self) -> None:
        """Cyclic type reference (self-referential struct) must not infinite-loop."""
        # struct Node { Node* next; } — DW_TAG_member pointing back to struct_die
        # We set up the member's DW_AT_type to point to the struct itself (offset 200)
        member = _Die(
            "DW_TAG_member",
            {"DW_AT_name": _Attr("next"), "DW_AT_type": _Attr(200, "DW_FORM_ref_addr")},
            offset=201,
        )
        # struct_die at offset=200 has the member child pointing back to itself
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Node"), "DW_AT_byte_size": _Attr(8)},
            children=[member],
            offset=200,
        )
        cu = _CU(die_map={200: struct_die})
        cache: dict[int, bool] = {}
        # Should not raise RecursionError
        result = _is_nontrivial_aggregate(struct_die, cache=cache, CU=cu)
        assert result is False  # Node has no dtor → trivial

    # 10. Move ctor pattern (C2E) → True
    def test_user_move_ctor_is_nontrivial(self) -> None:
        move_ctor = _Die(
            "DW_TAG_subprogram",
            {
                "DW_AT_name": _Attr("Node"),
                "DW_AT_linkage_name": _Attr("_ZN4NodeC2EOS_"),
            },
            offset=10,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Node")},
            children=[move_ctor],
            offset=7,
        )
        assert _is_nontrivial_aggregate(struct_die) is True

    # 11. defaulted copy ctor (DW_AT_defaulted set) → still trivial
    def test_defaulted_copy_ctor_is_trivial(self) -> None:
        copy_ctor = _Die(
            "DW_TAG_subprogram",
            {
                "DW_AT_name": _Attr("Trivial"),
                "DW_AT_linkage_name": _Attr("_ZN7TrivialC1ERKS_"),
                "DW_AT_defaulted": _Attr(1),
            },
            offset=10,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Trivial")},
            children=[copy_ctor],
            offset=8,
        )
        assert _is_nontrivial_aggregate(struct_die) is False

    # 12. Non-trivial member type (e.g. struct Outer { NonTrivialMember s; })
    def test_nontrivial_member_type_propagates(self) -> None:
        """struct Outer { NonTrivial s; } — no explicit dtor but non-trivial via member.

        This is the CodeRabbit issue: struct with a std::string-like member must be
        detected as non-trivial even without an explicit dtor.
        """
        # NonTrivialMember has a user-defined dtor → non-trivial
        inner_dtor = _Die(
            "DW_TAG_subprogram",
            {
                "DW_AT_name": _Attr("~NonTrivial"),
                "DW_AT_linkage_name": _Attr("_ZN10NonTrivialD1Ev"),
            },
            offset=300,
        )
        inner_struct = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("NonTrivial"), "DW_AT_byte_size": _Attr(8)},
            children=[inner_dtor],
            offset=301,
        )
        # Outer has a member whose type is NonTrivial (at offset 301)
        member = _Die(
            "DW_TAG_member",
            {"DW_AT_name": _Attr("s"), "DW_AT_type": _Attr(301, "DW_FORM_ref_addr")},
            offset=310,
        )
        outer_struct = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Outer"), "DW_AT_byte_size": _Attr(8)},
            children=[member],
            offset=311,
        )
        cu = _CU(die_map={301: inner_struct})
        # No explicit dtor on Outer, but member type is non-trivial → Outer is non-trivial
        assert _is_nontrivial_aggregate(outer_struct, CU=cu) is True

    # 13. Member type is a primitive → trivial (no false positive)
    def test_primitive_member_does_not_cause_false_positive(self) -> None:
        """struct Data { int x; } — int member should not trigger non-triviality."""
        int_type = _Die("DW_TAG_base_type", {"DW_AT_name": _Attr("int"), "DW_AT_byte_size": _Attr(4)}, offset=400)
        member = _Die(
            "DW_TAG_member",
            {"DW_AT_name": _Attr("x"), "DW_AT_type": _Attr(400, "DW_FORM_ref_addr")},
            offset=401,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("Data"), "DW_AT_byte_size": _Attr(4)},
            children=[member],
            offset=402,
        )
        cu = _CU(die_map={400: int_type})
        assert _is_nontrivial_aggregate(struct_die, CU=cu) is False

    # 14. Without CU, member types are not resolved (safe degradation)
    def test_no_cu_member_type_not_checked(self) -> None:
        """When CU=None, member type check is skipped — no false positives."""
        member = _Die(
            "DW_TAG_member",
            {"DW_AT_name": _Attr("s"), "DW_AT_type": _Attr(999, "DW_FORM_ref_addr")},
            offset=500,
        )
        struct_die = _Die(
            "DW_TAG_structure_type",
            {"DW_AT_name": _Attr("SafeOuter")},
            children=[member],
            offset=501,
        )
        # CU=None → member type is skipped, struct is still trivial
        assert _is_nontrivial_aggregate(struct_die, CU=None) is False

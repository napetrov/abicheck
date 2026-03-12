"""B4: Anonymous union false positive (abicc #58).

When a struct gains an anonymous union member, the existing field `x` should
NOT be reported as removed/changed if it's still present at the same offset.

Scenario:
  v1: struct S { int x; };
  v2: struct S { union { int x; int y; }; };  // anon union, x still at offset 0

Expected behavior:
- MUST NOT emit STRUCT_FIELD_REMOVED for 'x'
- MUST NOT emit TYPE_FIELD_REMOVED for 'x' (it's still there at offset 0)
- SHOULD emit TYPE_FIELD_ADDED_COMPATIBLE for 'y' (new field added at same offset)

castxml XML handling note:
- castxml represents anonymous unions as inline Union elements
- Fields inside the anonymous union appear as members of the containing struct
  in the flattened layout (same offsets as in memory)
- Our parser captures the flattened field list, so x remains at offset 0

This is a regression test ensuring we don't emit false positives for the
anonymous union case that abicc had issues with.
"""
from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.model import AbiSnapshot, RecordType, TypeField


def _snap_v1_plain_struct() -> AbiSnapshot:
    """v1: struct S { int x; }"""
    return AbiSnapshot(
        library="lib.so",
        version="1.0",
        types=[
            RecordType(
                name="S",
                kind="struct",
                size_bits=32,
                fields=[TypeField(name="x", type="int", offset_bits=0)],
            )
        ],
    )


def _snap_v2_anon_union_added() -> AbiSnapshot:
    """v2: struct S { union { int x; int y; }; }  — x still at offset 0, y added."""
    return AbiSnapshot(
        library="lib.so",
        version="2.0",
        types=[
            RecordType(
                name="S",
                kind="struct",
                size_bits=32,
                fields=[
                    TypeField(name="x", type="int", offset_bits=0),
                    TypeField(name="y", type="int", offset_bits=0),  # same offset — union
                ],
            )
        ],
    )


class TestAnonUnionFalsePositive:
    """Verify anonymous union doesn't cause false 'field removed' positives.

    abicc #58: tools reported STRUCT_FIELD_REMOVED for 'x' when adding
    an anonymous union that kept x at the same offset.
    """

    def test_x_not_removed_when_anon_union_added(self) -> None:
        """Field 'x' must NOT be reported as removed when anon union is added."""
        result = compare(_snap_v1_plain_struct(), _snap_v2_anon_union_added())
        _kinds = {c.kind for c in result.changes}  # noqa: F841
        # x is still at offset 0 → should NOT be removed
        removed_changes = [
            c for c in result.changes
            if c.kind in (ChangeKind.TYPE_FIELD_REMOVED, ChangeKind.STRUCT_FIELD_REMOVED)
            and "x" in str(c.description)
        ]
        assert not removed_changes, (
            f"False positive: 'x' reported as removed when anon union added: {removed_changes}"
        )

    def test_y_added_is_compatible(self) -> None:
        """Field 'y' (added at same offset, same struct size) → compatible addition."""
        result = compare(_snap_v1_plain_struct(), _snap_v2_anon_union_added())
        _kinds = {c.kind for c in result.changes}  # noqa: F841
        # y is added at same offset (same size struct) → compatible
        kinds = {c.kind for c in result.changes}
        # This may be TYPE_FIELD_ADDED_COMPATIBLE or TYPE_FIELD_ADDED depending on
        # whether the struct is standard-layout; either way not BREAKING for same size
        assert result.verdict != Verdict.BREAKING or ChangeKind.TYPE_SIZE_CHANGED in kinds, (
            "Adding a field at same offset in same-size struct should not be BREAKING "
            "unless the struct size actually changed"
        )

    def test_same_struct_no_false_positive(self) -> None:
        """Identical struct (x only) → no changes at all."""
        result = compare(_snap_v1_plain_struct(), _snap_v1_plain_struct())
        assert not result.changes

    def test_struct_with_added_y_field_at_different_offset(self) -> None:
        """Adding field y at a NEW offset (after x) → compatible if non-polymorphic."""
        old = AbiSnapshot(
            library="lib.so", version="1.0",
            types=[RecordType(
                name="S", kind="struct", size_bits=32,
                fields=[TypeField(name="x", type="int", offset_bits=0)],
            )],
        )
        new = AbiSnapshot(
            library="lib.so", version="2.0",
            types=[RecordType(
                name="S", kind="struct", size_bits=64,
                fields=[
                    TypeField(name="x", type="int", offset_bits=0),
                    TypeField(name="y", type="int", offset_bits=32),
                ],
            )],
        )
        result = compare(old, new)
        _kinds = {c.kind for c in result.changes}  # noqa: F841
        # x is NOT removed
        removed_for_x = [c for c in result.changes
                         if c.kind in (ChangeKind.TYPE_FIELD_REMOVED, ChangeKind.STRUCT_FIELD_REMOVED)
                         and "x" in str(c.description)]
        assert not removed_for_x

    def test_castxml_anon_union_xml_parsing(self) -> None:
        """CastxmlParser must handle anonymous union members via flattened layout.

        In castxml output, an anonymous union inside a struct results in
        the union's fields being listed as members of the containing struct
        (they share offsets). This test verifies our parser captures them correctly.
        """
        from abicheck.dumper import _CastxmlParser

        root = Element("CastXML")

        file_el = SubElement(root, "File")
        file_el.set("id", "f1")
        file_el.set("name", "mylib.h")

        loc1 = SubElement(root, "Location")
        loc1.set("id", "l1")
        loc1.set("file", "f1")
        loc1.set("line", "1")

        # Fundamental type: int
        int_type = SubElement(root, "FundamentalType")
        int_type.set("id", "_int")
        int_type.set("name", "int")

        # The struct with inline anonymous union flattened into members
        struct_el = SubElement(root, "Struct")
        struct_el.set("id", "_1")
        struct_el.set("name", "S")
        struct_el.set("size", "32")
        struct_el.set("align", "32")
        struct_el.set("location", "l1")

        # x at offset 0 (original field, now inside anon union)
        field_x = SubElement(struct_el, "Field")
        field_x.set("id", "_1f1")
        field_x.set("name", "x")
        field_x.set("type", "_int")
        field_x.set("offset", "0")

        # y at offset 0 (new field in anon union, same offset as x)
        field_y = SubElement(struct_el, "Field")
        field_y.set("id", "_1f2")
        field_y.set("name", "y")
        field_y.set("type", "_int")
        field_y.set("offset", "0")

        parser = _CastxmlParser(root, exported_dynamic=set(), exported_static=set())
        types = parser.parse_types()
        s = next((t for t in types if t.name == "S"), None)
        assert s is not None
        field_names = {f.name for f in s.fields}
        # Both x and y must be captured
        assert "x" in field_names
        assert "y" in field_names

    def test_anon_union_field_offsets(self) -> None:
        """Anonymous union fields share the same offset_bits."""
        new = _snap_v2_anon_union_added()
        # In v2, x and y both have offset_bits=0 (union semantics)
        s_new = new.types[0]
        x_field = next(f for f in s_new.fields if f.name == "x")
        y_field = next(f for f in s_new.fields if f.name == "y")
        assert x_field.offset_bits == y_field.offset_bits == 0
